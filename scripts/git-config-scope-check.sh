#!/usr/bin/env bash
# git-config-scope-check.sh — which scope does git report for a value that reaches a
# repo's config by each route?
#
# The claim under test, from the-purloined-config-proposal.md: a rule keyed on config
# scope ("protected configuration" is system, global and command) sees these routes as
#   include.path from local config, file in the worktree   -> local
#   git config --worktree (extensions.worktreeConfig)      -> worktree
#   git -c key=value                                        -> command
#   git clone -c key=value (the clone option)               -> local, in .git/config
#   GIT_CONFIG_COUNT/KEY_n/VALUE_n environment variables    -> command
# The clone row is the one that matters: a value the user passes to protect a clone
# looks identical to one a repo's script wrote.
#
# Uses a throwaway directory, an empty global config and no system config, so the
# result does not depend on the machine's own git configuration. Linux only (it uses
# /dev/null as the global config). Needs git. Exits 0 if every route reports the
# expected scope, 1 otherwise. The scope names are git's; they have been stable since
# `--show-scope` was added, but re-run it when git ships a major version.

set -uo pipefail

command -v git >/dev/null || { echo "git not on PATH"; exit 1; }
[ "$(uname -s)" = Linux ] || { echo "Linux only"; exit 1; }

W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

echo "git $(git --version | awk '{print $3}') on $(uname -s)"
echo

failures=0
check() { # check <route> <expected-scope> <got-scope>
    if [ "$2" = "$3" ]; then printf '  PASS  %-52s %s\n' "$1" "$3"
    else printf '  FAIL  %-52s expected %s, got %s\n' "$1" "$2" "${3:-<none>}"; failures=$((failures + 1)); fi
}
scope() { git "$@" 2>/dev/null | cut -f1; }   # first field of --show-scope output

cd "$W" && git init -q repo && cd repo

printf '[core]\n\thooksPath = .husky/_\n' > .gitincluded
git config --local include.path ../.gitincluded
check "include.path in local config (file in worktree)" local \
      "$(scope config --show-scope --get core.hooksPath)"

git config extensions.worktreeConfig true
git config --worktree core.editor evil-editor
check "git config --worktree" worktree "$(scope config --show-scope --get core.editor)"

check "git -c key=value" command "$(scope -c core.pager=less config --show-scope --get core.pager)"

cd "$W" && git init -q --bare src.git && git clone -q -c core.hooksPath=/dev/null src.git dst 2>/dev/null
check "git clone -c key=value" local "$(scope -C dst config --show-scope --get core.hooksPath)"
printf '        value written to dst/.git/config: %s\n' "$(git -C dst config --local --get core.hooksPath)"

check "GIT_CONFIG_COUNT environment variables" command \
      "$(GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.sshCommand GIT_CONFIG_VALUE_0=ssh-wrapper \
         scope -C repo config --show-scope --get core.sshCommand)"

echo
if [ "$failures" -eq 0 ]; then echo "every route reported the expected scope"; else echo "$failures route(s) did not"; fi
exit $((failures > 0))
