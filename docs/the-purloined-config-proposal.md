# A Smaller Ask of `git`: Repo-Local Capabilities Should Need Your Say-So

*A companion to [The Purloined Config](the-purloined-config.md). Written by Brad Merrill,
assisted by Claude. The proposal and opinions are the author's; the verification section at
the end is Claude's, in its voice.*

## The ask

A script the repo told my package manager to run wrote `core.hooksPath` into my local
`.git/config`, and my global "no hooks in forks" rule lost to it, because a repo-local value
beats a global one.

My first instinct was that `.git/` should be off limits: only `git` writes there, nothing
else gets direct access. That was wrong, and it took me a minute to see why. Nothing wrote to
the file directly. The script ran `git config core.hooksPath ...`, which is `git` writing its
own config through its own front door. A rule saying "only `git` may write `.git/`" allows
this exactly as it happened. Locking the folder doesn't work anyway: file permissions are per
user, not per program, and `git` runs as me, so anything else running as me has the same
rights. Tools that read and write `.git/` without the `git` binary would break too.

So the line isn't about who writes the file. It's about who gets to change what `git` is
allowed to do. Some config keys are settings. Others are capabilities:

`core.hooksPath`, `credential.helper`, `core.sshCommand`, `core.pager`, `core.editor`,
`core.fsmonitor`, any `alias.*` starting with `!`, `filter.*.clean` and `smudge`,
`diff.*.textconv`, `url.*.insteadOf`.

Those aren't preferences. Every one of them names a command `git` will run, or a place `git`
will send things.

What I want: a repo-local value for a capability key does nothing until I allowlist that
repo. The same shape as `safe.directory`, which already refuses to operate on a repo owned by
someone else until you say so.

Look at what that does to my Tuesday. `husky` still runs. The config write still succeeds.
The file still changes. And the hooks still don't run, because a repo-local `core.hooksPath`
means nothing until I say it does. My global rule wins, which is what I set it up to do.

A smaller version would also help: have `git config` print a warning when it sets a
capability key in local scope. Just say it out loud. Most of my nine hours went because
nothing announced anything.

## This isn't a new kind of rule

`git` already treats some repo-supplied config differently, for security reasons:

- **`safe.directory`** refuses to operate on a repo owned by someone else until you
  allowlist it. It came from the CVE-2022-24765 fix.
- **`.gitmodules` cannot set an executable update command.** `git` reads `.gitmodules` as
  config, but `submodule.<name>.update` is limited to checkout, rebase, merge or none, "but
  not '!command' (for security reasons)".
- **`protocol.allow`** gives `ext::` a default policy of `never` and anything unknown a
  policy of `user`, so a transport that shells out can't be reached by a recursive
  submodule clone.

## And `git` tried something close to it on hooks

Version 2.45.1 added two protections around hooks during a clone. Version 2.45.2 reverted
both. One of them refused any active `core.hooksPath` in the repository's local config during
a clone. A value passed with `-c` lands there too, so it also blocked
`clone -c core.hooksPath=/dev/null`, which people pass deliberately to make a clone safer. The
other protection stopped hooks running during a clone, and broke Git LFS, which installs its
own hooks then. The release notes call these "overly aggressive 'defense in depth' changes"
that "broke legitimate use cases like 'git lfs' and 'git annex'".

So this isn't an idea nobody considered. The lesson I take from it is that the protection has
to be scoped by where a value came from, and that it has to be an allowlist you can set, not
a blanket refusal.

---

## Verification

Written by Claude, at the author's request, from `git`'s own documentation and source history
in a working session on 2026-09-24. Read from a blobless clone of `git/git`.

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
- **Nothing under `.git/` can be tracked**: `git ls-files --error-unmatch .git/config` →
  `error: pathspec '.git/config' did not match any file(s) known to git`.

### Corrections to earlier drafts

- An earlier draft said `git` does not honour `.gitmodules` as config at all. That is false:
  it reads it and refuses only the form that runs a command.
- `git`'s three controls were first described as each following a security *problem*. Only
  `safe.directory` is tied to a CVE, so the wording is now "for security reasons".
- The hooks revert was first described as being about `-c core.hooksPath=/dev/null` alone.
  That was one of two protections reverted, and the other broke Git LFS.

### Where Claude is going on its own word

- That libgit2, JGit, go-git and isomorphic-git read and write `.git/` without calling the
  `git` binary. This is from training, not from reading each one's source.
- That the list of capability keys above is complete and that each key on it can run a
  command or send data elsewhere. This is the author's proposal; Claude did not check each
  key against `git`'s documentation.
