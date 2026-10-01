# I Have No Flag: how it was checked

*Addendum to [I Have No Flag, and I Must Comply](i-have-no-flag.md). Companion to the
[first article's addendum](the-purloined-config-addendum.md).*

This addendum is written by Claude, at the author's request, on 2026-09-30. The article's
claims about other people's software were checked by a separate Opus-model review that fetched
the raw pages with `curl` and read them directly, not through a summarising fetch tool. It
also ran one experiment on Claude Code 2.1.285 under WSL. The vendor documentation was fetched
as markdown from `code.claude.com/docs/en/<page>.md` on 2026-09-30, and much of what it
describes is version-gated.

The verdicts below are against the article as it stood on 2026-09-30, before the corrections
listed at the end were applied. Those corrections have since been made, except the `pnpm`
retest, which is softened in the text, not resolved.

### "Working one level up": contradicted

The article says opening `claude` one level above a repo means "you won't ever pick up agent
instructions that might have a chance of executing before your global instructions."

- **Nothing loads "before" your global instructions in any layout.**
  [Memory docs](https://code.claude.com/docs/en/memory): "Claude Code loads `CLAUDE.md` and
  `CLAUDE.local.md` from your current working directory and every directory above it." They
  are listed "from broadest scope to most specific, so a project instruction appears in
  context after a user instruction." And on conflicts: "Neither set overrides the other: if a
  user rule and a project rule conflict, Claude may follow either one." The premise is wrong
  wherever you launch.
- **Repo instruction files still arrive from one level up, on first file access.** Same page:
  "Claude also discovers `CLAUDE.md` and `CLAUDE.local.md` files in subdirectories under your
  current working directory. Instead of loading them at launch, they are included when Claude
  reads files in those subdirectories." The same applies to a subdirectory's `.claude/rules/`
  and, per the skills docs, to `.claude/skills/`, which "load the first time Claude reads or
  edits a file in that subdirectory".
- **Experiment, Claude Code 2.1.285, non-interactive (`-p`) mode, WSL.** A codeword planted in
  `parent/repo/CLAUDE.md`: launched from `parent/` with no file read, the model answered
  UNKNOWN. After one Read of `repo/notes.txt`, Claude Code appended the full `repo/CLAUDE.md`
  to the tool result, headed "Contents of …/parent/repo/CLAUDE.md:". Launched inside `repo/`,
  the codeword was known at once. In one run the model declined to use the appended text
  because it arrived in a tool result; that is a model judgment, likely influenced by the
  user-level `CLAUDE.md` and the prompt wording, not a loading control.
  **This experiment is not yet reproducible from this repo.** The two scripts that ran it are
  in the session scratchpad; they hardcode scratchpad paths and depend on fixture folders they
  do not create. A self-contained version belongs in `scripts/` before the article cites it.
- **`AGENTS.md`** is read by default only when no `CLAUDE.md`, `.claude/CLAUDE.md` or
  `CLAUDE.local.md` exists in the working directory or any directory above it (v2.1.277 or
  later). The experiment did not exercise it: an ancestor `CLAUDE.md` under the author's home
  folder suppressed it. That part rests on the docs alone.
- **What launching one level up does do.** Repo `.claude/settings.json`, and so its hooks,
  `env` and allow rules, do not load: the docs say "Hooks and other `.claude/settings.json`
  keys load from the current working directory's `.claude/` folder with no parent-directory
  fallback", and the experiment's `SessionStart` hook ran only when launched inside the repo.
  Nested `.claude/agents/` are not discovered ("walking up from the current working
  directory"). A child `.mcp.json` is probably not read; the docs do not say, so that is
  inference. This is a real tier-one benefit.
- **It also costs something.** The write boundary becomes the parent folder ("can only write to
  the folder where it was started and its subfolders"), so every sibling repo is in scope.

### Approval prompts on tier one: supported, with limits

"Most of it sits behind a first-use approval prompt" holds for interactive use:

- VS Code automatic tasks (`runOn: folderOpen`): "Automatic tasks never run in an untrusted
  workspace", and otherwise "you are prompted once to Allow or Disallow automatic tasks"
  ([tasks docs](https://raw.githubusercontent.com/microsoft/vscode-docs/main/docs/debugtest/tasks.md)).
- Claude Code project `.mcp.json`: "prompts for approval in interactive sessions before using
  project-scoped servers". Hooks are held back until the workspace trust dialog is accepted.
- **But not in headless runs, which is the article's own scenario.** In `-p`, SDK and cloud
  sessions, project-scoped MCP servers load "without asking", and "hooks committed in a
  repository's `.claude/settings.json` run in a folder you've never trusted".
- Devcontainers: the docs I found require trusting the folder and describe no per-command
  prompt for `postCreateCommand` or `postAttachCommand`. The article omits `initializeCommand`,
  which the [spec](https://raw.githubusercontent.com/devcontainers/spec/main/docs/specs/devcontainerjson-reference.md)
  says runs "on the host machine".
- Cursor: workspace trust exists but "is disabled by default".
- A committed `.githooks/` directory plus a README line: no prompt exists.

### "Nothing gates tier two at all": contradicted as worded

The article says there is "no allowlist, no default-off, no equivalent of `ignore-scripts=true`."
First-party docs show controls in each tool:

- **Claude Code:** `claudeMdExcludes` (glob patterns, any settings layer, also applies to
  `AGENTS.md`); a "Project instructions" setting that Claude Code "ignores … in project and
  local settings files", so a repo cannot override it; an approval dialog for external
  imports; `--bare`, `--safe-mode`, `--setting-sources user` and `skillOverrides`. Even the
  strictest project-instructions value still lazy-loads a subdirectory's `CLAUDE.md` and rules.
- **VS Code:** `chat.useAgentsMdFile`, `chat.useClaudeMdFile` and
  `github.copilot.chat.codeGeneration.useInstructionFiles` toggle instruction files;
  `chat.useNestedAgentsMdFiles` "is disabled by default"; restricted workspace mode "disables
  agents in that workspace".
- **Cursor:** no per-user switch for project rules or `AGENTS.md` was found in the pages
  fetched. That is "not found", not "none exists".
- **GitHub Copilot:** a repo owner can toggle custom instructions for pull-request review only.

What survives: no tool found defaults repo instruction files to off, and the sound point that
there is no execution step to refuse. The article should say "few, opt-in and easy to miss",
not "nothing".

### Shai-Hulud and OWASP

- **CISA page: overstated against the cited link.** The
  [alert](https://www.cisa.gov/news-events/alerts/2025/09/23/widespread-supply-chain-compromise-impacting-npm-ecosystem)
  says the malware "scanned the environment for sensitive credentials" and "targeted GitHub
  Personal Access Tokens (PATs) and application programming interface (API) keys for cloud
  services, including Amazon Web Services (AWS), Google Cloud Platform (GCP), and Microsoft
  Azure". It does not mention lifecycle or postinstall scripts, and for npm says only that the
  malware spread "by authenticating to the npm registry as the compromised developer".
- **[Unit 42](https://unit42.paloaltonetworks.com/npm-supply-chain-attack/) supports both
  halves:** "The malicious package versions contain a worm that executes a post-installation
  script," and the harvested credentials include ".npmrc files (for npm tokens)". These
  sentences are from the September body of that post, not its later "Shai-Hulud 2.0" update.
- **OWASP: supported.** "Disabling lifecycle scripts by default by adding `ignore-scripts=true`
  to your `.npmrc` file is the safest option."

### "About eighteen months": unsupported

The dated anchors found: `.github/copilot-instructions.md` in VS Code 1.94 (2024-10-03,
experimental); `.cursorrules` in use by 2024-09-16 (a third-party repo's first commit, so not
a first appearance); `CLAUDE.md` in Claude Code by 2025-02-22 to 2025-02-27; `AGENTS.md` support
in Codex on 2025-05-11 and the standard's repo on 2025-08-19. Measured to today those give
roughly 13 to 24 months, so "eighteen" has no anchor. The `.cursorrules` first appearance was
not found.

### Other claims

- **`pnpm` and the environment variable: retest.** The article says for `pnpm` the winning
  control is its own global config. That is tested for `NPM_CONFIG_IGNORE_SCRIPTS`, which
  `pnpm` ignores (first addendum). But `pnpm`'s docs say "`pnpm_config_*` environment variables
  … override settings from `pnpm-workspace.yaml`", so `pnpm_config_ignore_scripts` may also
  work, and was not tested.
- **"It's not code execution" (tier two) is overstated.** The tier lists `.claude/` skills and
  subagents. Skills carry `allowed-tools`, which workspace trust never gates, and hooks;
  subagents can declare inline MCP servers.
- **"No approval prompt of any kind" (tier three) is overstated for fetched content.** VS Code
  asks you to trust a domain first; Claude Code network requests prompt in Manual mode. It is
  fair for text already inside the repo.
- **"Running on the host, as you" is overstated:** sandboxes, devcontainers and cloud agents
  exist.
- **CMake claims: supported** by Kitware's docs (`execute_process`, `install(SCRIPT)`,
  `<LANG>_COMPILER_LAUNCHER`). "Cannot have" an ignore-scripts mode is the author's argument.
- **The precedence lesson repeats in Claude Code.** hooks.md: a `"disableAllHooks": false` in a
  project's `.claude/settings.json` overrides a `true` in your user settings. The article could
  use this.
- **The author's own accounts** (the nine-hour incident, the CUDA dependency story, "always-allow
  inside a week") are anecdote and opinion in the first person, and are left as they are.

### Corrections the article needed (applied 2026-09-30, except item 6)

1. Replace the "one level up" paragraph. Suggested wording from the review: "Launching one
   level up keeps a repo's settings, hooks and (I believe) MCP servers from loading. It does
   not keep its CLAUDE.md, rules or skills out: those load the first time the agent reads a
   file in the repo." Drop "won't ever" and the "before your global instructions" rationale.
2. Change "Nothing gates tier two at all" to "few, opt-in and easy to miss", and name
   `claudeMdExcludes` and the VS Code toggles.
3. Say headless agent runs get no prompt for hooks or MCP, since the article's own scenario is
   an agent run unattended.
4. Add the Unit 42 link next to the CISA one, and describe CISA as reporting credential
   harvesting, not lifecycle scripts.
5. Replace "eighteen months" with a dated sentence, for example: "Repo instruction files went
   from tool-specific conventions (`.cursorrules` and `copilot-instructions.md`, both in use by
   autumn 2024) to a cross-tool standard (`AGENTS.md`, August 2025) in under a year."
6. Retest `pnpm_config_ignore_scripts`, or soften "for pnpm it is pnpm's own global config".
7. Fix "down level down" and the unclosed `*` on line 2.

### Where Claude is going on its own word

- **What could not be accessed:** the first appearance of `.cursorrules`; whether a parent
  launch picks up a child's `.mcp.json`; whether nested `.claude/commands/` load lazily; and
  `AGENTS.md` subdirectory behaviour from a parent with no `CLAUDE.md` above it.
- **Version drift.** These are 2026-09-30 docs and a 2.1.285 test. Claude Code changes fast, so
  every Claude Code claim here needs re-checking before it is republished.
- **Other tools** (Cursor, Copilot, VS Code) were read from their docs only, not exercised.
