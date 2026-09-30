#!/usr/bin/env bash
# verify-trigger-table.sh — reproduce the trigger table in the-purloined-config.md.
#
# The claim under test: a `prepare` lifecycle script in a project's own
# package.json runs during `pnpm install` and can write into that repo's local
# .git/config — but only on an install that actually has work to do.
#
# Builds a throwaway fixture rather than using a real project, so the result does
# not depend on any particular checkout. The fixture's prepare script does what
# husky's does (`git config core.hooksPath ...`) instead of installing husky, to
# keep one variable in play; husky is not the mechanism, `prepare` is.
#
# Needs pnpm and network access. Touches nothing outside its own temp directory.
# Exits 0 if all three rows reproduce, 1 otherwise.
#
# Set PNPM to test a different version, e.g.
#   PNPM="npx --yes pnpm@12" ./verify-trigger-table.sh
# The claim is about pnpm's behaviour, so it is worth re-running whenever pnpm
# ships a major.

set -uo pipefail

PNPM="${PNPM:-pnpm}"
$PNPM --version >/dev/null 2>&1 || { echo "cannot run: $PNPM"; exit 1; }
command -v git >/dev/null || { echo "git not on PATH"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

echo "pnpm $($PNPM --version), git $(git --version | awk '{print $3}')"
echo "fixture: $WORK"
echo

git init -q .
mkdir -p .husky/_

# One tiny dependency with no deps and no install scripts of its own, so a fresh
# install has real work to do without introducing another lifecycle script.
cat > package.json <<'JSON'
{
  "name": "trigger-table-fixture",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "prepare": "node -e \"require('fs').appendFileSync('prepare.log','ran\\n')\" && git config core.hooksPath .husky/_"
  },
  "dependencies": { "ms": "2.1.3" }
}
JSON

failures=0

# hooks_path: the repo-LOCAL value only. A global core.hooksPath (quite common)
# would otherwise be reported as if the fixture had set it.
hooks_path() { git config --local --get core.hooksPath || echo "<unset>"; }
prepare_runs() { [ -f prepare.log ] && wc -l < prepare.log | tr -d ' ' || echo 0; }

check() { # check <row> <expected-prepare-ran> <expected-hooks-path>
    local row="$1" want_ran="$2" want_path="$3" got_ran got_path
    got_ran="$( [ "$(prepare_runs)" -gt "${BASELINE_RUNS}" ] && echo yes || echo no )"
    got_path="$(hooks_path)"
    if [ "$got_ran" = "$want_ran" ] && [ "$got_path" = "$want_path" ]; then
        printf '  PASS  %s\n        prepare ran: %-3s   core.hooksPath: %s\n' \
               "$row" "$got_ran" "$got_path"
    else
        printf '  FAIL  %s\n        expected prepare=%s hooksPath=%s\n        got      prepare=%s hooksPath=%s\n' \
               "$row" "$want_ran" "$want_path" "$got_ran" "$got_path"
        failures=$((failures + 1))
    fi
    BASELINE_RUNS="$(prepare_runs)"
}

BASELINE_RUNS=0

echo "row 2: install with node_modules absent"
$PNPM install --silent >/dev/null 2>&1
check "install after deleting node_modules" yes ".husky/_"

echo
echo "row 1: install again, node_modules present, lockfile unchanged"
git config --local --unset core.hooksPath 2>/dev/null
$PNPM install --silent >/dev/null 2>&1
check "install, node_modules present, lockfile unchanged" no "<unset>"

echo
echo "row 3: install with --ignore-scripts, node_modules absent"
rm -rf "$WORK/node_modules"
$PNPM install --ignore-scripts --silent >/dev/null 2>&1
check "install with --ignore-scripts, node_modules deleted" no "<unset>"

echo
if [ "$failures" -eq 0 ]; then
    echo "all three rows reproduced"
else
    echo "$failures row(s) did not reproduce"
fi
exit $((failures > 0))
