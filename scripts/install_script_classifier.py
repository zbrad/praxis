#!/usr/bin/env python3
"""install_script_classifier.py — what do declared install scripts actually do?

Second half of the measurement started by install_script_sampler.py. Takes the
TSV that sampler wrote, re-reads each declaring repo's root package.json by its
recorded blob sha (so the file is exactly the one sampled), and labels every
install-lifecycle script in two passes:

1. Text pass. Patterns over the command string itself (see _TEXT_RULES).
2. File pass. When a command runs a script file (`node scripts/x.mjs`,
   `sh setup.sh`, ...), that file is read from the repo's default branch and
   labelled by patterns over its contents (see _CONTENT_RULES). The file is only
   used if the repo's package.json still has the sampled blob sha; otherwise the
   repo is marked `drifted` and its files are not read, so a file is never
   attributed to a manifest it did not come with.

Both passes are patterns over text. They say what a script mentions, not what it
does at runtime, and a script can be built to evade them. Labels were fixed
before the numbers were seen; a script that matches none is `other`.

It only reads. Nothing from a sampled repository is cloned, installed or run.

Usage:
    install_script_classifier.py SAMPLE.tsv [--out FILE.tsv]

Needs the `gh` CLI, authenticated.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Largest referenced file that will be read; bigger ones are recorded, not read.
MAX_FILE_BYTES = 256 * 1024

_TEXT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "hook_installer",
        re.compile(
            r"husky|simple-git-hooks|lefthook|git[- ]hooks|core\.hooksPath|"
            r"pre-commit install|install[-_]hooks|git config",
            re.I,
        ),
    ),
    (
        "patcher",
        re.compile(r"patch-package|apply[:_-]?patches|\bpatch\b", re.I),
    ),
    (
        "native_or_fetch",
        re.compile(
            r"node-gyp|prebuild|node-pre-gyp|electron-rebuild|install-app-deps|"
            r"playwright install|puppeteer|cypress install|curl |wget |download",
            re.I,
        ),
    ),
    (
        "codegen",
        re.compile(
            r"prisma generate|svelte-kit sync|\bgen:|codegen|graphql-codegen", re.I
        ),
    ),
    (
        "build_step",
        re.compile(
            r"\btsc\b|\bbuild\b|rollup|webpack|\bvite\b|esbuild|tsup|unbuild|"
            r"\bturbo\b|\bnx\b|\bbob\b|\bgulp\b|\bgrunt\b|\bbabel\b|"
            r"\bcompile\b|\bpack\b|\bnpm run\b|\bpnpm run\b|\byarn run\b",
            re.I,
        ),
    ),
    (
        "policy_check",
        re.compile(r"only-allow|check-node-version|engines|is-ci", re.I),
    ),
)

_CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "hook_installer",
        re.compile(
            r"core\.hooksPath|\.git/hooks|husky|simple-git-hooks|lefthook|git config"
        ),
    ),
    (
        "network",
        re.compile(
            r"\bfetch\(|https?\.(get|request)\(|\bcurl\b|\bwget\b|download|axios|\bgot\("
        ),
    ),
    (
        "spawns_process",
        re.compile(r"child_process|execSync|spawnSync|\bspawn\(|\bexec\(|\bexeca\b"),
    ),
    (
        "writes_files",
        re.compile(
            r"writeFile|copyFile|rmSync|unlink|mkdirSync|symlink|cpSync|\bcp \b|\brm \b"
        ),
    ),
    (
        "env_or_runtime_check",
        re.compile(
            r"process\.version|npm_config_user_agent|process\.platform|process\.exit"
        ),
    ),
)

_FILE_REF = re.compile(
    r"(?:node|bun run|bun|sh|bash|tsx|jiti|deno run)\s+(?:-\S+\s+)*"
    r"(\.{0,2}/?[\w@./-]+\.(?:mjs|cjs|js|ts|sh|py))"
)


class InstallScriptClassifier:
    """Label install-lifecycle scripts of already-sampled repositories."""

    def __init__(self, sample: Path) -> None:
        """Create a classifier.

        Args:
            sample: TSV written by install_script_sampler.py.
        """
        if not sample.is_file():
            raise ValueError(f"no such sample file: {sample}")
        self._sample = sample

    @staticmethod
    def text_labels(command: str) -> list[str]:
        """Return every text-pass label matching this command, else ['other']."""
        found = [name for name, rx in _TEXT_RULES if rx.search(command)]
        return found or ["other"]

    @staticmethod
    def content_labels(text: str) -> list[str]:
        """Return every content-pass label matching this file, else ['other']."""
        found = [name for name, rx in _CONTENT_RULES if rx.search(text)]
        return found or ["other"]

    @staticmethod
    def file_refs(command: str) -> list[str]:
        """Return script-file paths a command runs, normalised to repo-relative."""
        return [m.lstrip("./") for m in _FILE_REF.findall(command)]

    def _api(self, path: str) -> Optional[dict[str, object]]:
        """GET a GitHub API path and parse the JSON, or None on any failure."""
        result = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            logger.debug("api %s failed: %s", path, result.stderr.strip())
            return None
        try:
            parsed = json.loads(result.stdout)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _decode(meta: dict[str, object]) -> Optional[str]:
        """Decode the base64 `content` of a GitHub contents/blob response."""
        try:
            return base64.b64decode(str(meta["content"])).decode("utf-8", "replace")
        except (KeyError, ValueError):
            return None

    def _manifest(self, repo: str, sha: str) -> Optional[dict[str, object]]:
        """Fetch the sampled package.json by blob sha and parse it."""
        meta = self._api(f"repos/{repo}/git/blobs/{sha}")
        text = self._decode(meta) if meta else None
        if text is None:
            return None
        try:
            parsed = json.loads(text)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _still_current(self, repo: str, sha: str) -> bool:
        """True if the default branch's package.json is still the sampled blob."""
        meta = self._api(f"repos/{repo}/contents/package.json")
        return bool(meta) and meta is not None and meta.get("sha") == sha

    def _read_file(self, repo: str, path: str) -> Optional[str]:
        """Read a repo file from the default branch, or None if missing/too big."""
        meta = self._api(f"repos/{repo}/contents/{path}")
        if not meta or meta.get("type") != "file":
            return None
        if int(str(meta.get("size", 0))) > MAX_FILE_BYTES:
            return None
        return self._decode(meta)

    def run(self) -> list[dict[str, str]]:
        """Return one row per (repo, lifecycle script) among declaring repos."""
        rows: list[dict[str, str]] = []
        with self._sample.open() as handle:
            for rec in csv.DictReader(handle, delimiter="\t"):
                if not rec["lifecycle"]:
                    continue
                repo, sha = rec["repo"], rec["blob_sha"]
                manifest = self._manifest(repo, sha)
                scripts = manifest.get("scripts", {}) if manifest else {}
                if not isinstance(scripts, dict):
                    continue
                current = self._still_current(repo, sha)
                for key in rec["lifecycle"].split(","):
                    command = str(scripts.get(key, ""))
                    text = self.text_labels(command)
                    refs = self.file_refs(command)
                    content: list[str] = []
                    state = "no_file"
                    if refs and not current:
                        state = "drifted"
                    elif refs:
                        state = "unreadable"
                        for ref in refs:
                            body = self._read_file(repo, ref)
                            if body is not None:
                                state = "read"
                                content.extend(self.content_labels(body))
                    rows.append(
                        {
                            "stratum": rec["stratum"],
                            "repo": repo,
                            "key": key,
                            "text_labels": ",".join(text),
                            "file_state": state,
                            "content_labels": ",".join(sorted(set(content))),
                            "command": command.replace("\t", " ").replace("\n", " "),
                        }
                    )
        return rows

    @staticmethod
    def write_rows(rows: list[dict[str, str]], path: Path) -> None:
        """Write one TSV row per classified script."""
        cols = (
            "stratum",
            "repo",
            "key",
            "text_labels",
            "file_state",
            "content_labels",
            "command",
        )
        lines = ["\t".join(cols)] + ["\t".join(r[c] for c in cols) for r in rows]
        path.write_text("\n".join(lines) + "\n")

    @staticmethod
    def summarise(rows: list[dict[str, str]]) -> str:
        """Return counts: text pass, then what reading the referenced files added."""
        repos = sorted({r["repo"] for r in rows})
        out = [f"repos: {len(repos)}  scripts: {len(rows)}", ""]
        labels = [n for n, _ in _TEXT_RULES] + ["other"]
        by_repo: dict[str, list[set[str]]] = {name: [] for name in repos}
        for r in rows:
            by_repo[r["repo"]].append(set(r["text_labels"].split(",")))
        out.append("TEXT PASS\nlabel\tscripts\trepos_with_any\trepos_where_only_this")
        for name in labels:
            scripts = sum(name in r["text_labels"].split(",") for r in rows)
            any_ = sum(any(name in s for s in sets) for sets in by_repo.values())
            only = sum(all(s == {name} for s in sets) for sets in by_repo.values())
            out.append(f"{name}\t{scripts}\t{any_}\t{only}")
        opaque = [r for r in rows if r["file_state"] != "no_file"]
        out.append("")
        out.append(f"FILE PASS: {len(opaque)} scripts run a referenced file")
        states: dict[str, int] = {}
        for r in opaque:
            states[r["file_state"]] = states.get(r["file_state"], 0) + 1
        out.append(
            "file_state: " + ", ".join(f"{k}={v}" for k, v in sorted(states.items()))
        )
        out.append("label\tscripts_whose_file_has_it")
        for name in [n for n, _ in _CONTENT_RULES] + ["other"]:
            count = sum(name in r["content_labels"].split(",") for r in opaque)
            out.append(f"{name}\t{count}")
        return "\n".join(out)

    @classmethod
    def main(cls, argv: Optional[list[str]] = None) -> int:
        """CLI entry point."""
        parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        parser.add_argument("sample", type=Path)
        parser.add_argument("--out", type=Path, default=None)
        args = parser.parse_args(argv)
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
        rows = cls(args.sample).run()
        if args.out is not None:
            cls.write_rows(rows, args.out)
        print(cls.summarise(rows))
        return 0


if __name__ == "__main__":
    sys.exit(InstallScriptClassifier.main())
