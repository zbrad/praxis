#!/usr/bin/env bash
# repro-husky-hookspath.sh — reproduce the incident in the-purloined-config.md on the
# real project, in a throwaway directory.
#
# The claim under test: installing a project whose root package.json has
#   "prepare": "pnpm exec husky || true && git config blame.ignoreRevsFile ..."
# writes core.hooksPath into the clone's local .git/config, and that repo-local value
# beats a global core.hooksPath the user set on purpose. With pnpm's global
# `ignoreScripts: true` set, the same install writes nothing.
#
# Run A: pnpm's config isolated and empty (the incident's conditions).
#   Expect: local core.hooksPath = .husky/_ and the effective value is .husky/_
# Run B: pnpm's config isolated, containing only `ignoreScripts: true`.
#   Expect: no local core.hooksPath and the effective value is the global one.
#
# The user's "global rule" is emulated with a throwaway GIT_CONFIG_GLOBAL, so the
# result does not depend on the machine's own git config. Needs pnpm, git and
# network access. Runs the project's own `prepare` script and husky (downloaded
# from the npm registry) in run A, which is the point; other dependencies' install
# scripts stay blocked by pnpm's default. Touches nothing outside its own temp dir.
# Linux only: pnpm's config is isolated through XDG_CONFIG_HOME.
#
# REPO and REF can be overridden. Exits 0 if both runs behave as expected, else 1.

set -uo pipefail

PNPM="${PNPM:-pnpm}"
REPO="${REPO:-https://github.com/zbrad/ComfyUI_frontend.git}"
REF="${REF:-a981a927db}"

$PNPM --version >/dev/null 2>&1 || { echo "cannot run: $PNPM"; exit 1; }
command -v git >/dev/null || { echo "git not on PATH"; exit 1; }
[ "$(uname -s)" = Linux ] || { echo "Linux only (XDG_CONFIG_HOME isolation)"; exit 1; }

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT

mkdir -p "$W/global-hooks" "$W/xdg-empty" "$W/xdg-protected/pnpm"
printf '[core]\n\thooksPath = %s/global-hooks\n' "$W" > "$W/gitconfig-global"
printf 'ignoreScripts: true\n' > "$W/xdg-protected/pnpm/config.yaml"
export GIT_CONFIG_GLOBAL="$W/gitconfig-global"

echo "pnpm $($PNPM --version), git $(git --version | awk '{print $3}')"
echo "project: $REPO @ $REF"
echo "global core.hooksPath (emulated): $W/global-hooks"
echo

failures=0

run() { # run <name> <xdg-dir> <expected-local> <expected-effective>
    local name="$1" xdg="$2" want_local="$3" want_eff="$4" got_local got_eff
    git clone -q "$REPO" "$W/$name" && git -C "$W/$name" checkout -q "$REF" \
        || { echo "  FAIL  $name: clone or checkout failed"; failures=$((failures + 1)); return; }
    (cd "$W/$name" && XDG_CONFIG_HOME="$xdg" $PNPM install --frozen-lockfile >/dev/null 2>&1)
    got_local="$(git -C "$W/$name" config --local --get core.hooksPath || echo '<unset>')"
    got_eff="$(git -C "$W/$name" config --get core.hooksPath || echo '<unset>')"
    [ "$want_eff" = GLOBAL ] && want_eff="$W/global-hooks"
    if [ "$got_local" = "$want_local" ] && [ "$got_eff" = "$want_eff" ]; then
        printf '  PASS  %s\n        local: %s   effective: %s\n' "$name" "$got_local" "$got_eff"
    else
        printf '  FAIL  %s\n        expected local=%s effective=%s\n        got      local=%s effective=%s\n' \
               "$name" "$want_local" "$want_eff" "$got_local" "$got_eff"
        failures=$((failures + 1))
    fi
}

echo "run A: pnpm config empty (the incident's conditions)"
run a-unprotected "$W/xdg-empty" ".husky/_" ".husky/_"
echo
echo "run B: pnpm config has ignoreScripts: true"
run b-protected "$W/xdg-protected" "<unset>" GLOBAL
echo
if [ "$failures" -eq 0 ]; then echo "both runs behaved as expected"; else echo "$failures run(s) did not"; fi
exit $((failures > 0))
