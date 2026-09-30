#!/usr/bin/env python3
"""install_script_sampler.py — how many JS/TS repos declare install scripts?

Tests one claim: "nearly every JavaScript or TypeScript repository declares
install scripts". It samples repositories from GitHub search, reads each one's
root package.json through the GitHub API, and counts how many declare any of
the lifecycle scripts a package manager runs as part of installing.

It only reads. Nothing from a sampled repository is cloned, installed or run.

Sampling is stratified by language and star band, because a top-by-stars list
alone would answer a different question (how do famous projects behave). Each
result records the blob sha of the package.json it read, so any row can be
re-checked against the exact file. The strata, sample sizes and search sort
order are the parameters of the measurement; change them and it is a new one.

Usage:
    install_script_sampler.py [--per-stratum N] [--out FILE.tsv]

Needs the `gh` CLI, authenticated. Search API allows 30 requests per minute.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Lifecycle scripts a package manager may run as part of installing, as opposed
# to scripts a human invokes. Same list as scripts/repo_scan.py.
INSTALL_LIFECYCLE = ("preinstall", "install", "postinstall", "prepare")

LANGUAGES = ("JavaScript", "TypeScript")

# Star bands, high to low. Search qualifiers, verbatim.
STAR_BANDS = ("stars:>=20000", "stars:1000..2000", "stars:100..200")


@dataclass
class SampleRow:
    """One sampled repository and what its root package.json declared."""

    stratum: str
    full_name: str
    pushed_at: str
    has_package_json: bool
    blob_sha: str = ""
    lifecycle: list[str] = field(default_factory=list)


class InstallScriptSampler:
    """Sample repositories and count root-level install-lifecycle scripts."""

    def __init__(self, per_stratum: int) -> None:
        """Create a sampler.

        Args:
            per_stratum: Repositories to request per language and star band.
        """
        if per_stratum < 1 or per_stratum > 100:
            raise ValueError("per_stratum must be between 1 and 100")
        self._per_stratum = per_stratum

    def run(self) -> list[SampleRow]:
        """Sample every stratum and return one row per repository."""
        rows: list[SampleRow] = []
        for language in LANGUAGES:
            for band in STAR_BANDS:
                stratum = f"{language} {band}"
                for name, pushed_at in self._search(language, band):
                    rows.append(self._read_repo(stratum, name, pushed_at))
                logger.info("done %s", stratum)
        return rows

    def _gh(self, args: list[str]) -> Optional[str]:
        """Run `gh` and return stdout, or None if the API answered 404."""
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            return result.stdout
        if "404" in result.stderr:
            return None
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")

    def _search(self, language: str, band: str) -> list[tuple[str, str]]:
        """Return (full_name, pushed_at) pairs for one stratum."""
        query = f"language:{language} {band} fork:false archived:false"
        out = self._gh(
            [
                "api",
                "-X",
                "GET",
                "search/repositories",
                "-f",
                f"q={query}",
                "-f",
                "sort=updated",
                "-f",
                f"per_page={self._per_stratum}",
            ]
        )
        if out is None:
            raise RuntimeError(f"search returned 404 for {query!r}")
        return [(i["full_name"], i["pushed_at"]) for i in json.loads(out)["items"]]

    def _read_repo(self, stratum: str, name: str, pushed_at: str) -> SampleRow:
        """Read one repo's root package.json and record its lifecycle scripts."""
        out = self._gh(["api", f"repos/{name}/contents/package.json"])
        if out is None:
            return SampleRow(stratum, name, pushed_at, has_package_json=False)
        meta = json.loads(out)
        try:
            manifest = json.loads(base64.b64decode(meta["content"]))
        except (KeyError, ValueError):
            logger.warning("unreadable package.json in %s", name)
            return SampleRow(stratum, name, pushed_at, has_package_json=False)
        scripts = manifest.get("scripts", {}) if isinstance(manifest, dict) else {}
        found = [
            k for k in INSTALL_LIFECYCLE if isinstance(scripts, dict) and k in scripts
        ]
        return SampleRow(
            stratum, name, pushed_at, True, blob_sha=meta["sha"], lifecycle=found
        )

    @staticmethod
    def summarise(rows: list[SampleRow]) -> str:
        """Return a per-stratum table of counts. Counts, not scores."""
        lines = [
            "group\trepos\twith_package_json\tany_lifecycle\tany_pct\t"
            "prepare_only\tprepare_only_pct\tnon_prepare\tnon_prepare_pct\t"
            + "\t".join(INSTALL_LIFECYCLE)
        ]
        strata = list(dict.fromkeys(r.stratum for r in rows))
        groups: list[tuple[str, list[SampleRow]]] = [
            (s, [r for r in rows if r.stratum == s]) for s in strata
        ]
        for language in LANGUAGES:
            groups.append(
                (
                    f"{language} (all bands)",
                    [r for r in rows if r.stratum.startswith(language)],
                )
            )
        groups.append(("ALL", rows))
        for label, group in groups:
            with_pkg = [r for r in group if r.has_package_json]
            any_lc = [r for r in with_pkg if r.lifecycle]
            prepare_only = [r for r in any_lc if r.lifecycle == ["prepare"]]
            non_prepare = [r for r in any_lc if set(r.lifecycle) - {"prepare"}]
            per_key = [
                str(sum(k in r.lifecycle for r in with_pkg)) for k in INSTALL_LIFECYCLE
            ]
            total = len(with_pkg) or 1
            lines.append(
                "\t".join(
                    [
                        label,
                        str(len(group)),
                        str(len(with_pkg)),
                        str(len(any_lc)),
                        f"{100 * len(any_lc) / total:.0f}%",
                        str(len(prepare_only)),
                        f"{100 * len(prepare_only) / total:.0f}%",
                        str(len(non_prepare)),
                        f"{100 * len(non_prepare) / total:.0f}%",
                    ]
                    + per_key
                )
            )
        return "\n".join(lines)

    @staticmethod
    def write_rows(rows: list[SampleRow], path: Path) -> None:
        """Write one TSV row per sampled repo, with the date it was taken."""
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [
            "date\tstratum\trepo\tpushed_at\thas_package_json\tblob_sha\tlifecycle"
        ]
        for r in rows:
            lines.append(
                "\t".join(
                    [
                        stamp,
                        r.stratum,
                        r.full_name,
                        r.pushed_at,
                        str(r.has_package_json),
                        r.blob_sha,
                        ",".join(r.lifecycle),
                    ]
                )
            )
        path.write_text("\n".join(lines) + "\n")

    @classmethod
    def main(cls, argv: Optional[list[str]] = None) -> int:
        """CLI entry point."""
        parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
        parser.add_argument("--per-stratum", type=int, default=50)
        parser.add_argument("--out", type=Path, default=None)
        args = parser.parse_args(argv)
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
        rows = cls(args.per_stratum).run()
        if args.out is not None:
            cls.write_rows(rows, args.out)
        print(cls.summarise(rows))
        return 0


if __name__ == "__main__":
    sys.exit(InstallScriptSampler.main())
