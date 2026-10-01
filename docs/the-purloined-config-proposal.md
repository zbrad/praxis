# RFC: Repo-local capability config should need a per-repo trust decision

*A companion to [The Purloined Config](the-purloined-config.md). Written by Brad Merrill,
assisted by Claude. The proposal and opinions are the author's; the verification section at
the end is Claude's, in its voice. This is a design sketch, not a patch.*

## Summary

A `git` config value in a repository's own `.git/config` should not be able to make `git` run
a command or send data somewhere until the user has said they trust that repository. Until
then, such a value should have no effect and `git` should say so.

## Problem

A build script the repo shipped ran `git config core.hooksPath ...`. That wrote a repo-local
value, which beats a global one, and it re-enabled hooks that my global "no hooks in forks"
setting had turned off. `git` did nothing wrong: the script used `git`'s own front door, as
me, with my permissions. Nothing announced the change, and finding it cost me much of a
nine-hour day.

Restricting who may write `.git/` does not fix this. The script called `git config`, so
"only `git` writes there" allows it exactly as it happened, and file permissions are per
user, not per program. The line has to be drawn by what the value can make `git` do, not by
who wrote it.

## Background: reproducing it

The behaviour reproduces on demand, with scripts in this repo, so the case does not rest on
my account.

- [`scripts/repro-husky-hookspath.sh`](../scripts/repro-husky-hookspath.sh) clones the real
  project at a pinned commit, sets a global `core.hooksPath`, and runs `pnpm install`.
  - **Run A, pnpm's config empty:** the project's own `prepare` script runs `husky`, and a
    second value, `.husky/_` in scope `local`, appears in `.git/config`. The effective value
    is now `.husky/_`: the repo-local value beat the global one.
  - **Run B, pnpm's global config has `ignoreScripts: true`:** nothing is written and the
    global value stays in force.
- [`scripts/verify-trigger-table.sh`](../scripts/verify-trigger-table.sh) does the same with a
  throwaway fixture instead of a real project, and shows the write happens only on an install
  that has work to do.

What `git` showed throughout: `git config --show-scope --get-all core.hooksPath` lists both
values with their scopes, so `git` knows where each value came from. But at no point did it
say anything when the local value was written. The install output showed only
`prepare: Done`. That silence, and a global setting losing to a value a script supplied, is
what I am asking about.

## Proposal

1. **Capability keys.** Treat these as capabilities, not preferences, because each names
   something `git` will execute or somewhere it will send data: `core.hooksPath`,
   `credential.helper`, `core.sshCommand`, `core.pager`, `core.editor`, `core.fsmonitor`,
   `alias.*` values starting with `!`, `filter.*.clean` and `smudge`, `diff.*.textconv`,
   `url.*.insteadOf`. This is a candidate list. It needs review key by key, and I have not
   checked each one against `git`'s documentation.
2. **Trust list.** A capability key set in a repo's local config is ignored, and the next
   scope (global, then system) applies, until the user allowlists that repo. The shape is
   `safe.directory`, which already refuses to operate on a repo owned by someone else until
   you say so.
3. **Say so.** When a capability key is ignored for lack of trust, or is being set in local
   scope by `git config`, print a warning. This smaller step is worth having even if 1 and
   2 are not adopted: it would have cost me seconds, not hours.

Applied to my case: `husky` still runs and the config write still succeeds, but the repo's
`core.hooksPath` has no effect and `git` tells me why. My global rule stays in force.

## Precedent

`git` already treats some repo-supplied config differently for security reasons:

- **`safe.directory`** refuses to operate on a repo owned by someone else until you
  allowlist it. It came from the CVE-2022-24765 fix.
- **`.gitmodules` cannot set an executable update command.** `submodule.<name>.update` is
  limited to checkout, rebase, merge or none, "but not '!command' (for security reasons)".
- **`protocol.allow`** defaults `ext::` to `never` and unknown protocols to `user`, so a
  transport that shells out cannot be reached by a recursive submodule clone.

## Prior attempt, and what it teaches

Version 2.45.1 added two protections around hooks during a clone, and 2.45.2 reverted both.
One refused any active `core.hooksPath` in the local config during a clone. A value passed
with `-c` lands there too, so it also blocked `clone -c core.hooksPath=/dev/null`, which
people pass deliberately to make a clone safer. The other stopped hooks running during a
clone and broke Git LFS. The release notes call the changes "overly aggressive 'defense in
depth' changes" that "broke legitimate use cases like 'git lfs' and 'git annex'".

This proposal must avoid both failures. It is a per-repo allowlist, not a blanket refusal,
and it does not change when hooks run. But it does not yet solve the first one, below.

## Open questions

- **Protective values.** `clone -c core.hooksPath=/dev/null` writes a repo-local value.
  Ignoring it for lack of trust would undo the protection the user asked for. The rule
  probably has to depend on where a value came from (the command line versus a file), or
  exempt values that only reduce capability. I do not know the right answer.
- **The user's own values.** `git` cannot tell a repo-local value the user set from one a
  script set. A user who sets `core.hooksPath` in a repo on purpose must also allowlist the
  repo. That may be acceptable, since it is one step, but it is a behavior change.
- **Existing workflows.** `husky` legitimately writes a repo-local `core.hooksPath`, so every
  `husky` user would need to allowlist their repos. The upgrade path, and how the allowlist is
  set per repo, needs design. (Git LFS mattered to the reverted clone-time protection because
  it installs hook files then; I have not checked whether it writes any config.)
- **Other entry points.** `include` and `includeIf` files and worktree config can also
  supply these keys.

---

## Verification

Written by Claude, at the author's request, from `git`'s own documentation and source history
in a working session on 2026-09-24. Read from a blobless clone of `git/git`. The proposal text
was rewritten on 2026-09-30 and the citations below were not re-read then; they are as they
were checked.

- **`safe.directory` came from the CVE-2022-24765 fix.** Earliest commit touching
  `Documentation/config/safe.txt` is `8959555c`, "setup_git_directory(): add an owner check
  for the top-level directory", 2022-03-02. RelNotes 2.35.2 states it merges the 2.30.3
  through 2.34.2 fixes for that CVE. The fix shipped in those maintenance releases as well
  as 2.35.2. MITRE's record describes the CVE as the Windows `C:\.git` search-path problem and
  lists `GIT_CEILING_DIRECTORIES` as the mitigation. That is the pre-patch workaround, not the
  fix, and reading only the CVE record makes `safe.directory` look unrelated. The
  `safe.directory=*` opt-out came later, in `0f85c4a30`, 2022-04-13.
- **`.gitmodules` cannot set an executable update command.** `Documentation/gitmodules.adoc`
  limits `submodule.<name>.update` to checkout, rebase, merge or none, "but not '!command'
  (for security reasons)". The commit that introduced the restriction, `ac1fbbda2`
  (2013-12-02), gives portability and blind copying as its reason, not an incident.
- **`protocol.allow`**: per `Documentation/config/protocol.adoc`, `ext` defaults to `never`
  and unknown protocols to `user`. The `user` policy exists so that commands running
  clone/fetch/push without user input, such as recursive submodule initialization, cannot use
  such protocols. The commits that added the mechanism (`a5adaced2`, 2015-09-16;
  `f1762d772`, 2016-12-14) describe sandboxing untrusted clones and cite no incident.
- **The hooks protections that shipped and were reverted.** RelNotes 2.45.2 lists
  *Revert "core.hooksPath: add some protection while cloning"*, *tests: verify that
  `clone -c core.hooksPath=/dev/null` works again*, and *clone: drop the protections where
  hooks aren't run*. The first was added in `20f3588ef` (2024-03-30) and errors out on an
  active repo-local `core.hooksPath` during a clone. The revert commit `75631a3cd` says the
  protection breaks `git clone --config core.hooksPath=/dev/null`. The second was reverted in
  `873a466ea`, whose message says it broke Git LFS. Discussed in Junio C Hamano's "Fix various
  overly aggressive protections in 2.45.1 and friends" series, May 2024.

- **Reproduction, 2026-09-30.** Both scripts above were run on Linux with `pnpm` 11.13.1,
  `git` 2.43.0 and Node v26.8.2. Both exited 0: `verify-trigger-table.sh` reproduced all three
  rows, and `repro-husky-hookspath.sh` showed run A writing the local value and run B not.
  The scripts isolate `pnpm`'s global config through `XDG_CONFIG_HOME`, which works on Linux
  only. An earlier version of `verify-trigger-table.sh` did not isolate it, so on a machine that
  already had `ignoreScripts: true` set, row 2 failed, which tested the machine and not the
  claim. The result depends on local state in two ways: the network (the registry and GitHub)
  and the pinned commit of the project. The global `core.hooksPath` in run A and B is emulated
  with a throwaway `GIT_CONFIG_GLOBAL`, not the author's real setting.

- **Which scope `git` reports for each route into config, 2026-10-01.**
  [`scripts/git-config-scope-check.sh`](../scripts/git-config-scope-check.sh) uses a throwaway
  repo, an empty global config and no system config. Run on Linux with `git` 2.43.0, it exited
  0. An earlier ad-hoc run of the same checks on Windows with `git` 2.44.0 gave the same
  scopes for the first four rows; the environment-variable row was added after.

  | Route into config | Scope reported |
  | --- | --- |
  | `include.path` in local config, file inside the worktree | `local` |
  | `git config --worktree` (with `extensions.worktreeConfig`) | `worktree` |
  | `git -c key=value` | `command` |
  | `git clone -c key=value` | `local`, written to `.git/config` |
  | `GIT_CONFIG_COUNT` / `GIT_CONFIG_KEY_n` / `GIT_CONFIG_VALUE_n` | `command` |

  Two consequences for the open questions. A rule keyed on scope covers includes without extra
  work, because an included file reports the scope of the file that includes it, but it must
  decide whether `worktree` counts as protected. And the `clone -c` row is the problem case
  from the first open question: a value the user passes to make a clone safer is stored as
  `local`, indistinguishable from one a repo's script wrote. `git`'s documentation defines
  protected configuration as the `system`, `global` and `command` scopes
  (`Documentation/git-config.adoc`, read from `git/git` master on 2026-09-30). Include files
  were tested only where the file sits inside the worktree; an include pointing outside it was
  not tested.

### Corrections to earlier drafts

- An earlier draft said `git` does not honour `.gitmodules` as config at all. That is false:
  it reads it and refuses only the form that runs a command.
- `git`'s three controls were first described as each following a security *problem*. Only
  `safe.directory` is tied to a CVE, so the wording is now "for security reasons".
- The hooks revert was first described as being about `-c core.hooksPath=/dev/null` alone.
  That was one of two protections reverted, and the other broke Git LFS.
- The 2026-09-30 rewrite removed a sentence saying libgit2, JGit, go-git and isomorphic-git
  read and write `.git/` without the `git` binary. That was from Claude's training, never
  checked, and it sat in the author's voice. It also removed a claim that every key on the
  capability list runs a command or sends data, and now calls the list a candidate list. The
  earlier draft and the author's own verification note contradicted each other on this.
- The 2026-09-30 rewrite also dropped the `git ls-files --error-unmatch .git/config` check.
  It supported a point about `.git/` that the proposal no longer makes.

### Where Claude is going on its own word

- That `husky` legitimately writes a repo-local `core.hooksPath`. That is from the first
  addendum's reading of `husky`'s source, not re-read here. An earlier version of this
  proposal also said Git LFS writes repo-local hook *configuration*. That was wrong: the 2.45.2
  revert says only that the clone-time protection broke LFS, which installs hook files.
- That `include`, `includeIf` and worktree config can supply these keys. This is from
  Claude's training, not checked, and is listed as an open question for that reason.
