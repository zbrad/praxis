#!/usr/bin/env python3
"""repo_scan.py — count what a repository can do to your machine when you build it.

Counts detections. It does not score them, because a count is a measurement
anyone can reproduce and a severity rating is a claim about someone's project.
Install scripts are common, so a nonzero count here is normal and is not an
accusation.

Hard constraint: this never executes anything from the repository. It reads files
and, when asked, reads a lockfile the repository already contains. A scanner that
builds a project to learn what the build does has become the thing it scans for.

Usage:
    repo_scan.py PATH [PATH ...] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Lifecycle scripts a package manager may run as part of installing, as opposed
# to scripts a human invokes. `prepare` is the one that caused the incident this
# repo's first article is about.
_INSTALL_LIFECYCLE = ("preinstall", "install", "postinstall", "prepare")

# Files that carry instructions to a coding agent. Read automatically by the
# tool, because reading them is the feature.
_AGENT_INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".windsurfrules",
    ".github/copilot-instructions.md",
)
_AGENT_INSTRUCTION_DIRS = (".claude", ".cursor")

# Files that declare something to launch or run, rather than something to read.
_LAUNCH_DECLARATIONS = (
    ".mcp.json",
    ".vscode/tasks.json",
    ".devcontainer/devcontainer.json",
    ".devcontainer.json",
)

# npm/pnpm settings a repo can ship that weaken a default, or that override
# whatever the user configured. npm config precedence is
# CLI > env > project > user > global, so ANY setting in a repo .npmrc silently
# beats ~/.npmrc.
_WEAKENING_SETTINGS = (
    "ignore-scripts",
    "engine-strict",
    "unsafe-perm",
    "node-linker",
    "enable-pre-post-scripts",
    "dangerously-allow-all-builds",
    "only-built-dependencies",
    "never-built-dependencies",
    "pm-on-fail",
    "package-manager-strict",
    "verify-store-integrity",
    "strict-peer-dependencies",
)

# pnpm-workspace.yaml / package.json keys that change what may be built or which
# package manager runs.
_WORKSPACE_OVERRIDE_KEYS = (
    "onlyBuiltDependencies",
    "neverBuiltDependencies",
    "ignoredBuiltDependencies",
    "dangerouslyAllowAllBuilds",
    "pmOnFail",
    "enablePrePostScripts",
    "nodeLinker",
    "onlyBuiltDependenciesFile",
)

# A `git config` invocation that WRITES rather than reads. Matches "git config"
# not immediately followed by a read flag/subcommand. Deliberately broad: the
# user's rationale (2026-09-24) is that a build or install step has no
# legitimate reason to touch git configuration AT ALL, so any write is flagged
# regardless of which key it targets -- this is not limited to the capability
# keys (core.hooksPath, credential.helper, core.sshCommand, core.pager,
# core.editor -- see the-purloined-config.md's "capability" list) even though
# those are the ones that can go on to execute something themselves.
#
# Static-analysis limit: this only sees `git config` spelled out as literal
# text. The article's own incident (`"prepare": "pnpm exec husky || true &&
# git config ... || true"`) matches directly. A bare `"prepare": "husky"`
# does NOT match on its own -- see _KNOWN_GIT_CONFIG_WRITERS below for how
# that case is covered instead. Committed hook-installer scripts (.husky/,
# .githooks/, hooks/) are grepped for the same literal pattern for the same
# reason: whatever text is actually there to read, is read.
_GIT_CONFIG_WRITE = re.compile(
    r"\bgit\s+config\b(?!\s+(?:--get\b|--get-all\b|--get-regexp\b|"
    r"--get-urlmatch\b|-l\b|--list\b|-e\b|--edit\b|-h\b|--help\b))"
)

# Packages VERIFIED (not assumed) to call `git config` themselves during
# install, keyed to the exact evidence for each so a claim about someone
# else's software stays checked, not recalled (the-purloined-config.md's own
# stated research standard: "checked against that project's own
# documentation or release notes at the time of writing, not recalled").
#
# husky: confirmed 2026-09-24 directly in typicode/husky's index.js --
#   `c.spawnSync('git', ['config', 'core.hooksPath', `${d}/_`])` -- a WRITE,
#   and husky's own docs list "Uses new Git feature (core.hooksPath)" as a
#   headline feature, not a hidden side effect. Matches the invocation as a
#   command word (husky/husky install/husky init/npx husky/pnpm exec husky/
#   yarn husky), since the package.json convention is `"prepare": "husky"`
#   with no `git config` text of its own to match against _GIT_CONFIG_WRITE.
#
# simple-git-hooks was checked and excluded: its own source
#   (simple-git-hooks.js) only does `execSync('git config --local
#   core.hooksPath', ...)` to READ and respect an existing value; it never
#   writes one. Vite's `postinstall: simple-git-hooks` (see the worked
#   example below) is legitimately a different, lesser case than husky's.
_KNOWN_GIT_CONFIG_WRITERS = {
    "husky": re.compile(r"(?:^|[\s;&|])(?:npx\s+|pnpm\s+(?:exec|dlx)\s+|yarn\s+(?:dlx\s+)?)?husky\b"),
}

# Build systems whose configuration is itself a program.
_EXECUTABLE_BUILD_FILES = (
    "CMakeLists.txt",
    "setup.py",
    "build.rs",
    "binding.gyp",
    "Makefile",
    "configure",
)


class RepoScanner:
    """Count the ways a checkout can act on the machine that builds it."""

    def __init__(self, root: Path) -> None:
        """Set the checkout to inspect."""
        self._root = root
        self._findings: dict[str, list[str]] = {}
        self._notes: list[str] = []
        self._values: dict[str, str] = {}
        self._packages: list[str] = []

    def scan(self) -> dict[str, object]:
        """Run every check and return the counts plus what produced them."""
        self._check_root_lifecycle_scripts()
        self._check_git_config_writes()
        self._check_package_manager_pin()
        self._check_committed_hooks()
        self._check_agent_instructions()
        self._check_launch_declarations()
        self._check_git_surface()
        self._check_executable_builds()
        self._check_workflows()
        self._check_config_overrides()
        self._check_dependency_install_scripts()
        return {
            "repo": str(self._root),
            "identity": self._git_identity(),
            "total_detections": sum(len(v) for v in self._findings.values()),
            "counts": {k: len(v) for k, v in sorted(self._findings.items())},
            "detections": {k: sorted(v) for k, v in sorted(self._findings.items())},
            "values": self._values,
            "packages": self._packages,
            "notes": self._notes,
        }

    def _git_identity(self) -> dict[str, str]:
        """Read remote, branch and commit, so a measurement can be re-run later.

        Reads git's own metadata rather than repo content. Safe on a fresh clone:
        a clone has no repo-local git config, so there is no `core.fsmonitor` or
        alias for these commands to pick up.
        """
        identity = {"remote": "", "branch": "", "commit": "", "committed": ""}
        queries = {
            "remote": ["config", "--get", "remote.origin.url"],
            "branch": ["rev-parse", "--abbrev-ref", "HEAD"],
            "commit": ["rev-parse", "HEAD"],
            "committed": ["log", "-1", "--format=%cI"],
        }
        for key, arguments in queries.items():
            result = subprocess.run(
                ["git", "-C", str(self._root), *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                identity[key] = result.stdout.strip()
        return identity

    def _add(self, category: str, detail: str) -> None:
        """Record one detection under a category."""
        self._findings.setdefault(category, []).append(detail)

    def _read_json(self, relative: str) -> Optional[dict]:
        """Read a JSON file, or None when it is absent or unparseable."""
        path = self._root / relative
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except ValueError:
            self._notes.append(f"{relative}: present but not valid JSON")
            return None

    def _check_root_lifecycle_scripts(self) -> None:
        """Count install-time scripts the project declares for itself.

        These are the ones a lockfile's hasInstallScript flag does not cover: it
        describes dependencies, not the project you cloned.
        """
        manifest = self._read_json("package.json")
        if manifest is None:
            return
        scripts = manifest.get("scripts")
        if not isinstance(scripts, dict):
            return
        for name in _INSTALL_LIFECYCLE:
            if name in scripts:
                self._add("root_install_scripts", f"{name}: {scripts[name]}")

    def _check_git_config_writes(self) -> None:
        """Flag a literal `git config` WRITE reachable from install/build.

        SECURITY ALERT category, not a neutral count: a build or install step
        has no legitimate reason to modify git configuration at all -- that is
        beyond its scope regardless of which key it touches (2026-09-24
        decision; see mitigations.md). Two ways in: a literal `git config`
        write (_GIT_CONFIG_WRITE) in a root lifecycle script or committed
        hook-installer script, or a lifecycle script invoking a package
        VERIFIED to write git config itself (_KNOWN_GIT_CONFIG_WRITERS) even
        though its own text says nothing about git.
        """
        manifest = self._read_json("package.json")
        if isinstance(manifest, dict):
            scripts = manifest.get("scripts")
            if isinstance(scripts, dict):
                for name in _INSTALL_LIFECYCLE:
                    command = scripts.get(name)
                    if not isinstance(command, str):
                        continue
                    if _GIT_CONFIG_WRITE.search(command):
                        self._add("git_config_writes", f"package.json scripts.{name}: {command}")
                        continue
                    for pkg, pattern in _KNOWN_GIT_CONFIG_WRITERS.items():
                        if pattern.search(command):
                            self._add(
                                "git_config_writes",
                                f"package.json scripts.{name}: {command}  "
                                f"(known git-config-writer: {pkg})",
                            )
                            break

        for directory in (".husky", ".githooks", "hooks"):
            base = self._root / directory
            if not base.is_dir():
                continue
            for entry in sorted(base.rglob("*")):
                if not entry.is_file() or entry.name.startswith("."):
                    continue
                body = entry.read_text(encoding="utf-8", errors="replace")
                match = _GIT_CONFIG_WRITE.search(body)
                if match:
                    line_no = body[: match.start()].count("\n") + 1
                    self._add(
                        "git_config_writes",
                        f"{entry.relative_to(self._root)}:{line_no}: {match.group(0)}",
                    )

    def _check_package_manager_pin(self) -> None:
        """Count declarations that decide which package manager binary runs."""
        manifest = self._read_json("package.json")
        if manifest is None:
            return
        pinned = manifest.get("packageManager")
        if isinstance(pinned, str):
            self._add("package_manager_pin", f"packageManager: {pinned}")
            self._values["pm_pin"] = pinned
        dev_engines = manifest.get("devEngines")
        if isinstance(dev_engines, dict) and "packageManager" in dev_engines:
            self._add(
                "package_manager_pin",
                f"devEngines.packageManager: {json.dumps(dev_engines['packageManager'])}",
            )
            self._values.setdefault(
                "pm_pin", f"devEngines:{json.dumps(dev_engines['packageManager'])}"
            )

    def _check_committed_hooks(self) -> None:
        """Count git hook scripts shipped in the tree.

        Git never installs these itself. Something has to point core.hooksPath at
        them, which is the step worth knowing about.
        """
        for directory in (".husky", ".githooks", "hooks"):
            base = self._root / directory
            if not base.is_dir():
                continue
            for entry in sorted(base.rglob("*")):
                if entry.is_file() and not entry.name.startswith("."):
                    self._add("committed_hooks", str(entry.relative_to(self._root)))

    def _check_agent_instructions(self) -> None:
        """Count files that instruct a coding agent."""
        for name in _AGENT_INSTRUCTION_FILES:
            if (self._root / name).is_file():
                self._add("agent_instructions", name)
        for directory in _AGENT_INSTRUCTION_DIRS:
            base = self._root / directory
            if not base.is_dir():
                continue
            for entry in sorted(base.rglob("*")):
                if entry.is_file():
                    self._add("agent_instructions", str(entry.relative_to(self._root)))

    def _check_launch_declarations(self) -> None:
        """Count files declaring a process to spawn or a command to run on open."""
        for name in _LAUNCH_DECLARATIONS:
            path = self._root / name
            if not path.is_file():
                continue
            self._add("launch_declarations", name)
            body = path.read_text(encoding="utf-8", errors="replace")
            for marker in (
                "postCreateCommand",
                "postAttachCommand",
                "postStartCommand",
                "initializeCommand",
                "onCreateCommand",
                "folderOpen",
            ):
                if marker in body:
                    self._add("run_on_open", f"{name}: {marker}")

    def _check_git_surface(self) -> None:
        """Count committed git configuration that needs a local write to arm."""
        attributes = self._root / ".gitattributes"
        if attributes.is_file():
            body = attributes.read_text(encoding="utf-8", errors="replace")
            for match in sorted(set(re.findall(r"\bfilter=([\w.-]+)", body))):
                self._add("gitattributes_filters", f"filter={match}")
            for match in sorted(set(re.findall(r"\bdiff=([\w.-]+)", body))):
                self._add("gitattributes_filters", f"diff={match}")
        if (self._root / ".gitmodules").is_file():
            self._add("submodules", ".gitmodules")

    def _check_executable_builds(self) -> None:
        """Count build files that are programs rather than data."""
        for name in _EXECUTABLE_BUILD_FILES:
            if (self._root / name).is_file():
                self._add("executable_build_files", name)

    def _check_workflows(self) -> None:
        """Count CI workflow definitions, which run with repository credentials."""
        base = self._root / ".github" / "workflows"
        if not base.is_dir():
            return
        for entry in sorted(base.glob("*.y*ml")):
            self._add("ci_workflows", str(entry.relative_to(self._root)))

    def _check_config_overrides(self) -> None:
        """Count repo-shipped settings that override the user's configuration.

        npm's config precedence is CLI > env > project > user > global, so any
        setting in a repo `.npmrc` silently beats `~/.npmrc`. Verified: a repo
        shipping `ignore-scripts=false` re-enables install scripts for a user who
        had set `ignore-scripts=true` in their own config.
        """
        npmrc = self._root / ".npmrc"
        if npmrc.is_file():
            for raw in npmrc.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.split("#", 1)[0].split(";", 1)[0].strip()
                if not line or "=" not in line:
                    continue
                key = line.split("=", 1)[0].strip().lower()
                self._add("repo_npmrc", line)
                if key in _WEAKENING_SETTINGS:
                    self._add("config_overrides", f".npmrc {line}")

        workspace = self._root / "pnpm-workspace.yaml"
        if workspace.is_file():
            body = workspace.read_text(encoding="utf-8", errors="replace")
            for key in _WORKSPACE_OVERRIDE_KEYS:
                if re.search(rf"^\s*{re.escape(key)}\s*:", body, re.MULTILINE):
                    self._add("config_overrides", f"pnpm-workspace.yaml {key}")

        manifest = self._read_json("package.json")
        if isinstance(manifest, dict):
            section = manifest.get("pnpm")
            if isinstance(section, dict):
                for key in _WORKSPACE_OVERRIDE_KEYS:
                    if key in section:
                        self._add("config_overrides", f"package.json pnpm.{key}")

        for other in (".yarnrc.yml", ".yarnrc", ".bunfig.toml"):
            if (self._root / other).is_file():
                self._add("repo_npmrc", other)

    def _check_dependency_install_scripts(self) -> None:
        """Count the resolved dependency tree and its install scripts.

        npm writes `hasInstallScript` into package-lock.json, so a full
        transitive count is a JSON read at any depth. pnpm's v9 lockfile carries
        no equivalent flag, so for a pnpm project the package list and versions
        are recorded but install scripts are reported as not counted rather than
        as zero.
        """
        lock = self._read_json("package-lock.json")
        if lock is not None and isinstance(lock.get("packages"), dict):
            packages = lock["packages"]
            for name, meta in sorted(packages.items()):
                if not name:
                    continue
                short = name.rsplit("node_modules/", 1)[-1]
                version = meta.get("version", "") if isinstance(meta, dict) else ""
                self._packages.append(f"{short}@{version}" if version else short)
                if isinstance(meta, dict) and meta.get("hasInstallScript"):
                    self._add("dependency_install_scripts", f"{short}@{version}")
            self._values["dependencies"] = str(len(self._packages))
            self._values["dep_source"] = "package-lock.json"
            return

        pnpm_lock = self._root / "pnpm-lock.yaml"
        if pnpm_lock.is_file():
            in_packages = False
            for raw in pnpm_lock.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if re.match(r"^[A-Za-z]", raw):
                    in_packages = raw.startswith("packages:")
                    continue
                if not in_packages:
                    continue
                entry = re.match(r"^  '?([^' ][^']*?)'?:\s*$", raw)
                if entry:
                    self._packages.append(entry.group(1))
            self._values["dependencies"] = str(len(self._packages))
            self._values["dep_source"] = "pnpm-lock.yaml"
            self._notes.append(
                f"pnpm-lock.yaml: {len(self._packages)} packages listed; no "
                "hasInstallScript equivalent, so dependency install scripts are "
                "NOT counted"
            )
            return

        for alternative in ("yarn.lock", "bun.lock", "bun.lockb"):
            if (self._root / alternative).is_file():
                self._values["dep_source"] = alternative
                self._notes.append(
                    f"{alternative} present; not parsed, dependency tree NOT counted"
                )
                return
        self._values["dep_source"] = "none"
        self._notes.append("no lockfile found; dependency tree not counted")

    @classmethod
    def _log_columns(cls) -> tuple[str, ...]:
        """Fixed TSV schema for the measurement log.

        Fixed on purpose: the category list is closed, so the log stays loadable
        by anything that reads TSV rather than needing a parser that follows
        whichever categories happened to fire.
        """
        return (
            "measured_at",
            "project",
            "remote",
            "branch",
            "commit",
            "committed_at",
            "total",
            "pm_pin",
            "dependencies",
            "dep_source",
            "root_install_scripts",
            "dependency_install_scripts",
            "repo_npmrc",
            "config_overrides",
            "committed_hooks",
            "agent_instructions",
            "launch_declarations",
            "run_on_open",
            "gitattributes_filters",
            "submodules",
            "executable_build_files",
            "ci_workflows",
            # Appended at the end (2026-09-24), not inserted among the
            # existing columns, so older rows in an existing measurements.tsv
            # stay readable by position -- they're simply one column short
            # (empty string), rather than every later value shifting left.
            "git_config_writes",
        )

    @classmethod
    def _append_log(cls, path: Path, result: dict[str, object], stamp: str) -> None:
        """Append one TSV row, writing the header if the file is new.

        Also writes the resolved package list beside the log, so two scans of the
        same project can be diffed rather than only compared by count.
        """
        identity = result["identity"]
        counts = result["counts"]
        values = result["values"]
        row: dict[str, object] = {
            "measured_at": stamp,
            "project": Path(str(result["repo"])).resolve().name,
            "remote": identity.get("remote", ""),
            "branch": identity.get("branch", ""),
            "commit": identity.get("commit", "")[:12],
            "committed_at": identity.get("committed", ""),
            "total": result["total_detections"],
            "pm_pin": values.get("pm_pin", ""),
            "dependencies": values.get("dependencies", ""),
            "dep_source": values.get("dep_source", ""),
        }
        for column in cls._log_columns():
            row.setdefault(column, counts.get(column, 0))

        new_file = not path.exists()
        with path.open("a", encoding="utf-8") as handle:
            if new_file:
                handle.write("\t".join(cls._log_columns()) + "\n")
            handle.write(
                "\t".join(str(row[column]) for column in cls._log_columns()) + "\n"
            )

        packages = result["packages"]
        if packages:
            out = path.parent / "packages"
            out.mkdir(exist_ok=True)
            name = f"{row['project']}-{row['commit']}.txt"
            (out / name).write_text("\n".join(sorted(packages)) + "\n", encoding="utf-8")

    @classmethod
    def main(cls, argv: Optional[list[str]] = None) -> int:
        """Entry point."""
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("paths", nargs="+", type=Path, help="checkouts to scan")
        parser.add_argument(
            "--json", action="store_true", help="emit JSON instead of a summary"
        )
        parser.add_argument(
            "--log",
            type=Path,
            default=None,
            help="append one TSV row per scan to this measurement log",
        )
        args = parser.parse_args(argv)

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        results = []
        for path in args.paths:
            if not path.is_dir():
                print(f"not a directory: {path}", file=sys.stderr)
                return 2
            result = cls(path).scan()
            results.append(result)
            if args.log is not None:
                cls._append_log(args.log, result, stamp)

        if args.json:
            print(json.dumps(results, indent=2))
            return 0

        for result in results:
            identity = result["identity"]
            print(f"\n{result['repo']}  {identity.get('commit', '')[:12]} ({identity.get('branch', '')})")
            print(f"  {result['total_detections']} detections")
            counts = result["counts"]
            width = max((len(k) for k in counts), default=0)
            for category, count in counts.items():
                if category == "git_config_writes" and count:
                    print(f"    {'!! SECURITY ALERT':<{width}}  {category} = {count}")
                    for detail in result["detections"][category]:
                        print(f"         {detail}")
                else:
                    print(f"    {category:<{width}}  {count}")
            for note in result["notes"]:
                print(f"  note: {note}")
        return 0


if __name__ == "__main__":
    sys.exit(RepoScanner.main())
