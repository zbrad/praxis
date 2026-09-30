# praxis

Notes from practice. Things that cost me time, written down so they cost you less.

## Supply chain, trust, and what builds are allowed to do

A two-part series about a git config file that changed without my asking, why that
turned out to be normal, and what it implies now that coding agents run our builds.

**1. [The Purloined Config; or, There Ain't No Such Thing as a Free Build](docs/the-purloined-config.md)**

A commit failed because it ran a linter I never installed. Nine hours later I understood
why: a lifecycle script in the project's `package.json`, run automatically by an ordinary
install, pointed git at a hook directory that shipped with the repo. Nobody attacked me.
Every participant behaved correctly. That's the problem.

Covers what git deliberately got right, why the trigger fires rarely enough to be hard to
catch, what the package managers have and haven't fixed, why no registry or host will tell
you a repo runs code when you build it — and a short proposal for `git`, with the reasoning and
verification in a companion addendum.

**2. [I Have No Flag, and I Must Comply; or, Do Agents Dream of Trusted Repos?](docs/i-have-no-flag.md)**

The same shape one level up. A repo can get your package manager to rewrite your git
config, and there's a flag for that. A repo can also reconfigure your coding agent, and
there is no flag, because there is no `--ignore-scripts` for a paragraph.

Splits repo-resident configuration into three tiers — things that execute, instruction
files, and whatever the agent reads while working — argues that the middle tier is harder
to defend than the npm problem rather than easier, and lands on precedence rather than
prohibition, with rule text you can paste into your own setup.

## If you only want the fix

For npm, put this in your shell profile — **not** in `~/.npmrc`, which a repository can
override:

```
export NPM_CONFIG_IGNORE_SCRIPTS=true
```

For pnpm, put this in `~/.config/pnpm/config.yaml`, which is the only place that both
survives a repo `.npmrc` and covers a project's own install scripts:

```
ignoreScripts: true
```

It isn't free. Packages that compile native addons or download binaries at install time
genuinely need their scripts, so some builds will break and you'll run those deliberately.
The articles explain the trade-offs and what to check afterwards.

Then, in any repository you haven't built before:

```
git config --get core.hooksPath      # should be empty, or yours
```

## Checking it yourself

[`scripts/verify-trigger-table.sh`](scripts/verify-trigger-table.sh) reproduces the central empirical claim
of the first article — that a project's own `prepare` script runs during an install and can
write into your repo's local git config, but only on an install that has real work to do.
It builds its own throwaway fixture, needs pnpm and network, touches nothing outside a temp
directory, and exits non-zero if any of the three cases stops holding.

## The scanner

[`scripts/repo_scan.py`](scripts/repo_scan.py) counts what a repository can do to your machine when you
build it. It **counts, it does not score** — a count is a measurement anyone can
reproduce, a severity rating is a claim about someone's project. A nonzero count is
normal and is not an accusation.

It never executes anything from the repository. It reads files, and reads a lockfile the
repository already contains. Cloning is safe because git does not execute repo content;
nothing between clone and report may build, install or run anything.

One category is the exception to "count, don't score": `git_config_writes` is printed as a
**security alert**, not a neutral count. A build or install step has no legitimate reason to
touch git configuration at all — that's beyond its scope regardless of which key it targets,
so any `git config` write reachable from a root lifecycle script (`preinstall`/`install`/
`postinstall`/`prepare`) or a committed hook-installer script (`.husky/`, `.githooks/`,
`hooks/`) is flagged, whether or not the key looks dangerous on its own. This is a static text
match, so it has the same limit as everything else here: it sees `git config` spelled out as
literal text (the-purloined-config.md's own incident, `"prepare": "... && git config ... ||
true"`, matches directly) — with one verified exception: `husky` is checked into a
`_KNOWN_GIT_CONFIG_WRITERS` table, confirmed 2026-09-24 directly against `typicode/husky`'s
own `index.js` (`spawnSync('git', ['config', 'core.hooksPath', ...])`) rather than assumed, so
`"prepare": "husky"` alone — no `git config` text of its own — is flagged too. Other hook
managers are not assumed guilty by association: `simple-git-hooks` was checked the same way
and excluded, because its source only *reads* `core.hooksPath` to respect an existing value,
never writes one.

```
./scripts/repo_scan.py path/to/checkout [more...] [--json] [--log path/to/measurements.tsv]
```

`--log` appends one TSV row per scan — date, project, remote, branch, commit, and every
count — so any measurement can be re-run later against the exact same tree. It also writes
the resolved package list and versions alongside it (in a `packages/` directory next to the
log file), so two scans of the same project can be diffed rather than only compared by count.
Where that log lives is up to you; ours is operational data, not published research, so it's
kept outside this repo (`~/.claude/measurements/`, gitignored here) rather than committed.

What three widely used, well-run frontend projects looked like on 2026-09-23:

| project | pm pin | deps | total | root install scripts | repo .npmrc | agent instr. | CI |
|---|---|---|---|---|---|---|---|
| vuejs/core | pnpm@12.4.2 | 642 | 11 | 2 | 0 | 0 | 8 |
| vitejs/vite | pnpm@12.4.2 | 1415 | 17 | 2 | 0 | 1 | 13 |
| sveltejs/svelte | pnpm@10.33.4 | 493 | 7 | 0 | 1 | 1 | 4 |

None of these projects is doing anything wrong, and that is the point. Vite's two root
install scripts are `postinstall: simple-git-hooks` — a hooks installer, the same class of
thing as husky — and `preinstall: npx only-allow pnpm`, which fetches and runs a package
from the registry before installing, in order to enforce which package manager you use.
Enforcing a policy with the mechanism the policy is worried about is a fair summary of
where the ecosystem currently is.

### Why a repo `.npmrc` is counted

npm's configuration precedence is CLI flags > environment > **project `.npmrc`** > user
`~/.npmrc` > global. So any setting a repository ships beats the one you set for yourself.
Measured on npm 11.19.1 and pnpm 11.13.1, against a root-project `postinstall`:

| | no repo `.npmrc` | repo ships `ignore-scripts=false` |
|---|---|---|
| npm, `~/.npmrc` only | blocked | **runs** |
| npm, `NPM_CONFIG_IGNORE_SCRIPTS=true` | — | blocked |
| pnpm, `~/.npmrc` only | **runs** | **runs** |
| pnpm, `NPM_CONFIG_IGNORE_SCRIPTS=true` | — | **runs** |
| pnpm, `--ignore-scripts` on the command line | blocked | blocked |

Two things follow. A repo can switch off the protection you configured for yourself, which
is why the scanner counts any repo `.npmrc` whether or not its contents look alarming —
svelte's is `playwright_skip_browser_download=1`, entirely reasonable, and it still
demonstrates the channel. And `ignore-scripts=true` in `~/.npmrc` **does not cover pnpm's
root-project scripts at all**, with or without a repo `.npmrc`; only the command-line flag
does.

## Notes

Everything here is written from a specific incident, with the commands and output that
produced it. Where a claim is about someone else's software, it was checked against that
project's own documentation or release notes at the time of writing, not recalled.

Corrections are welcome as issues.

## Using any of this

Quote it freely — that needs no permission from me. The prose is © Brad Merrill, all rights
reserved; ask if you want to republish a whole piece somewhere.

The configuration snippets, rule text and commands are meant to be copied. Take them, adapt
them, ship them in your own setup or your team's, no attribution needed.
