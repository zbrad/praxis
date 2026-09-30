
# The Purloined Config: how it was checked

*Addendum to [The Purloined Config](the-purloined-config.md). The `git` proposal is checked in
[its own addendum](the-purloined-config-proposal.md).*

This addendum is written by Claude, which did the verification for this piece at the
author's request, across several working sessions from 2026-09-22 to 2026-09-24. Every claim
below about someone else's software was read out of that project's own documentation,
release notes or source history in those sessions. Several of Claude's first attempts at
these citations were wrong, which is why the corrections are itemised rather than
summarised.

### `npm` and the package managers

- **Lifecycle scripts run automatically as part of installing** —
  [`npm`'s own documentation](https://docs.npmjs.com/cli/v11/using-npm/scripts). Turning them
  off is longstanding advice, not new here: the
  [OWASP `npm` Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/NPM_Security_Cheat_Sheet.html)
  recommends `--ignore-scripts` and `ignore-scripts=true` in `.npmrc`.
- **`npm view esbuild scripts`** returned `{ postinstall: 'node install.js' }` on `npm`
  11.19.1. Run it yourself; that is the point of including it.
- **`pnpm` blocks dependency lifecycle scripts by default from 10.0** —
  [`pnpm`'s v10.0.0 release](https://github.com/pnpm/pnpm/releases/tag/v10.0.0), with
  `pnpm.onlyBuiltDependencies` as the allowlist.
- **That protection was itself bypassable.**
  [GHSA-379q-355j-w6rj](https://github.com/pnpm/pnpm/security/advisories/GHSA-379q-355j-w6rj),
  "pnpm v10+ Bypass 'Dependency lifecycle scripts execution disabled by default'", high
  severity, published 2026-01-07, not patched until `pnpm` 10.26.0. Worth knowing before
  treating default-off as settled.
- **`npm` v12 does the same, for dependencies only** —
  [GitHub's changelog](https://github.blog/changelog/2026-06-09-upcoming-breaking-changes-for-npm-v12/):
  "`npm install` will no longer execute `preinstall`, `install`, or `postinstall` scripts
  from dependencies unless they are explicitly allowed." It also blocks `prepare` from `git`,
  file and link dependencies, and says nothing about the root project's own scripts.
- **`husky` writes `core.hooksPath` by default, as a feature.** Read from the installed
  package, `husky` 9.1.7, `index.js`, on 2026-09-24: unless `HUSKY=0` is set, the path
  contains `..`, or there is no `.git`, it runs
  `spawnSync('git', ['config', 'core.hooksPath', '<dir>/_'])`, with `<dir>` defaulting to
  `.husky`. There is no prompt and no opt-in beyond running it. So `pnpm exec husky` in a
  `prepare` script is the write; nothing else in the story is needed. `HUSKY=0` is an
  off-switch in the source (Claude did not check whether the docs mention it), and it is set per process, so it
  does not protect anything you forget to set it on. To re-check: `cat node_modules/husky/index.js` in any project that
  depends on it.
  This was also read independently, in an earlier session on 2026-09-24 on another of the
  author's machines, directly from `typicode/husky`'s own `index.js` on GitHub: the same
  `spawnSync('git', ['config', 'core.hooksPath', ...])` call. That reading is recorded in the
  comments of [`scripts/repo_scan.py`](../scripts/repo_scan.py), which also notes that `husky`'s
  own docs list `core.hooksPath` as a headline feature, and that `simple-git-hooks` was
  checked and only *reads* the setting, never writes it. The two readings agree; the second
  is of upstream's repository rather than the author's installed copy.
- **The root-project gap is not theoretical.** The affected machine was on `pnpm` 11.13.1, with
  `packageManager` pinned to it and `onlyBuiltDependencies` absent from both `package.json`
  and `pnpm-workspace.yaml`. The project's own `prepare` ran anyway.
- **The trigger table** is three actual runs, not reasoning about what should happen. The
  first conclusion — that every install rewrites the setting — was wrong, and testing it is
  what corrected it.
  [`scripts/verify-trigger-table.sh`](../scripts/verify-trigger-table.sh) in this repo reproduces all three
  rows and exits non-zero if any of them stops holding. It builds a throwaway fixture
  rather than using a real project, so the result doesn't depend on the author's checkout, and the
  fixture's `prepare` does what `husky`'s does rather than installing `husky` — `prepare` is the
  trigger; `husky` is only what it invokes. Needs `pnpm` and network access, and touches nothing outside its
  own temp directory.
  **Confirmed reproducing on `pnpm` 11.13.1 and on `pnpm` 12.5.1**, the current release at time
  of writing — so the root-project gap is still open in the latest major, not a leftover of
  an old version. Set `PNPM` to re-check a future one:
  `PNPM="npx --yes pnpm@13" scripts/verify-trigger-table.sh` (from the repo root).

### The mitigation, and why the usual advice is not enough

All measured, on `npm` 11.19.1 and `pnpm` 11.13.1, against a root-project `postinstall` and a
`file:` dependency's `postinstall`:

|     | no repo `.npmrc` | repo ships `ignore-scripts=false` |
| --- | --- | --- |
| `npm`, `ignore-scripts=true` in `~/.npmrc` | blocked | **runs** |
| `npm`, `NPM_CONFIG_IGNORE_SCRIPTS=true` | blocked | blocked |
| `pnpm`, `ignore-scripts=true` in `~/.npmrc` | **runs** | **runs** |
| `pnpm`, `NPM_CONFIG_IGNORE_SCRIPTS=true` | **runs** | **runs** |
| `pnpm`, `ignoreScripts: true` in `~/.config/pnpm/config.yaml` | blocked | blocked |
| either, `--ignore-scripts` on the command line | blocked | blocked |

Both the working settings cover the project's own scripts and its dependencies', and
neither interferes with `npm run` / `pnpm run`, which still execute along with their pre and
post hooks — checked separately, because a mitigation that breaks every build is not one.

Two corrections to what was first written, both found by testing rather than reading:

- **`ignore-scripts=true` in `~/.npmrc` is defeatable by the repository.** `npm`'s precedence
  is CLI, then environment, then the project's `.npmrc`, then the user's. A repo shipping
  `ignore-scripts=false` wins.
- **It never covered `pnpm`'s root-project scripts at all**, with or without a repo `.npmrc`,
  and `NPM_CONFIG_IGNORE_SCRIPTS` does not help there either. `pnpm` only honours its own
  global config or the flag.

Also unresolved, and worth knowing: `pmOnFail`, which governs whether a repo's
`packageManager` field can make `pnpm` download and run a package manager version that
repository chose, **cannot be set in global config at all** — `pnpm` ignores it there with a
warning and proceeds with the download. Its default is `download`. So that particular door
has no machine-level lock yet.

### Corrections to earlier drafts of this piece

- The cost was first written as ten hours. The timestamps given, 10:29 to 19:31, make it
  nine.

### Scale

Retrieved 2026-09-22. Both numbers move, so treat them as a snapshot.

- The upstream repository behind this story: 709 forks, 2,030 stars, via the GitHub API.
- Fork counts include forks nobody ever cloned, so this is a measure of reach, not of how
  many people ran the build.

### What the hosts scan for

Checked 2026-09-30, after the author asked where hosts document scanning. This was done twice.
The first pass fetched pages through a small-model summariser. A second pass, by a separate
Opus-model review, re-fetched the raw pages with `curl` and read them directly; the quotes
below are from that second reading. It could not read the logged-in owner view, JS-rendered
content or the code-scanning and Dependabot alert APIs (they require authentication).

- **`npm` scans new packages at publish time.** [GitHub's changelog, 2026-07-28](https://github.blog/changelog/2026-07-28-npm-publish-time-malware-scanning-and-dual-use-metadata/):
  "Newly published packages will be automatically scanned before they become available for
  install. Depending on the results, a package may be published as normal, held for manual
  review, or blocked." The page says nothing about install scripts or how the scan works.
- **Dependabot can alert on known-malicious dependencies, for the owner only.**
  [GitHub's changelog, 2026-07-28](https://github.blog/changelog/2026-07-28-dependabot-alerts-on-malicious-packages-across-more-ecosystems/):
  "If you have malware alerting enabled, Dependabot will now match your dependencies against
  this expanded set of malware advisories and alert you when a match is found." It is enabled
  per repository, or across an organization or enterprise. Notifications go to people with
  write, maintain or admin permissions. GitHub's
  [docs](https://docs.github.com/en/code-security/concepts/supply-chain-security/malware-alerts)
  say: "GitHub never publicly discloses malicious dependencies for any repository." It covers
  packages a project depends on, not a repository a stranger clones and builds. (GitHub's own
  docs disagree on ecosystem coverage: one page says npm only, another lists eight.)
- **Scanning of repository contents: no first-party page says it happens.** The nearest
  statements are the
  [Community Guidelines](https://docs.github.com/en/site-policy/github-terms/github-community-guidelines)
  ("We rely on reports from the community, as well as proactive detection", unspecified);
  automatic secret scanning on public repos (credentials, not malware); and, since
  2026-07-28, [Actions holding "potentially malicious" workflow runs](https://github.blog/changelog/2026-07-28-github-actions-holds-potentially-malicious-workflows-for-approval/)
  in public repos for approval, which protects the repo's own CI, not someone who clones it.
  The claim that GitHub runs YARA, entropy or behavioural checks on repos comes only from
  [a community discussion](https://github.com/orgs/community/discussions/200792), which is
  non-authoritative and is not cited in the article.
- **The repository page shows no scan indicator.** Logged out, the upstream repository's tab
  is labelled "Security and quality" with a count of 3. The 3 are published advisories, all
  high severity (two stored DOM-XSS, one same-origin XSS), not scan results. The Security page
  says "This project has not set up a SECURITY.md file yet", and neither page mentions malware
  or setup scripts. **The fork shows a count of 0**, so the article's earlier "the fork I built
  showed three" was wrong and now says upstream. The owner's logged-in view may differ and was
  not checked. A dated screenshot should back this before publication.
- **The fork owner's Advanced Security settings, as pasted by the author on 2026-09-30, are
  all opt-in.** Dependency graph, Dependabot alerts, Dependabot version updates and AI Scan for
  pull requests (Preview) were Off. Code scanning was "not available" because Actions is
  disabled on the fork. Copilot Autofix was On but depends on CodeQL. Secret alerts to partners
  for public repositories are always on. All analyse the owner's own code and dependencies.
  No malware-alerts option appeared in the paste, which may mean it is hidden while Dependabot
  alerts is Off, not rolled out, or omitted from the paste. Claude has not seen the page.
- **The other version claims hold.** `pnpm` 10.0.0 (2025-01-07): "Lifecycle scripts of
  dependencies are not executed during installation by default!" The `npm` v12 changelog says
  `preinstall`, `install` and `postinstall` from dependencies are blocked unless allowed, and
  is silent on the root project's own scripts. `npm` 12 has since shipped (registry `latest`
  was 12.1.0). Whether its root scripts still run is inferred from that silence, not tested;
  only `npm` 11.19.1 was measured.

Corrections to earlier drafts of the article:

- It said "Nothing points outward." That was too strong; it now says "Almost nothing" and
  credits `npm` publish-time scanning.
- It described Dependabot malware alerts as pointing at strangers. They serve the repository's
  maintainers and are not publicly disclosed, so the article now says so.
- It said "the fork I built showed" a count of three. That was upstream's count.
- It said `npm` v12 "is doing the same". v12 has since shipped, and `pnpm`'s blocking is
  specifically of dependencies' scripts.

What survives is narrower: the features that exist look for malicious code, and none describes
what a legitimate project's own setup script will do to the person who builds it.

### Inherited fork workflows

The author's account, backed by six notification emails the author supplied as PDFs, which are
held privately and not in this repo because they carry a notification address. All come from
`notifications@github.com` under the author's name, "Run failed" or "No jobs were run":

- 2026-06-16, `zbrad/llama.cpp`, `build-cann.yml`: no jobs were run
- 2026-08-14, `zbrad/pytorch`, `inductor-rocm-mi200.yml`: no jobs were run
- 2026-09-11, `zbrad/flashinfer`, Issue Claim: a job failed in 4 seconds
- 2026-09-20, `zbrad/raft`, `build`: 34 jobs, with CUDA devcontainer builds for amd64 and arm64
- 2026-09-23, `zbrad/sqlite`, Tuned Release: one job failed, one was cancelled

A sixth, 2026-07-03, was a `pre-commit` run on a pull request the author submitted to
`vllm-project/vllm`, which the author identifies as an auto-review, so it is not counted. The emails
do not say what triggered each run. The author recalls that "Copilot stuff" sent some of the
emails; none of the six mentions Copilot, so the article does not claim it. The author disabled
Actions on public forks on 2026-09-24; the last run above is the day before, which is consistent
with, but does not prove, that being the cause.

### Where Claude is going on its own word

- That no host offers a repo-level score or notice for build-time behaviour. Absence claims
  are the easiest kind to be wrong about. Claude checked GitHub's documented npm,
  Dependabot and Actions protections and one upstream repository page, and found nothing of
  that kind. It did not audit
  GitLab, Bitbucket or any other host. If one ships this, the author would like to know.
