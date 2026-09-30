# The Purloined Config; or, There Ain't No Such Thing as a Free Build

*Written by Brad Merrill, assisted by Claude with grammar, spelling, fact checking, and the
verification and validation work. Claude's account of what it checked is in the
[addendum](the-purloined-config-addendum.md), written in its voice. The incident, the opinions
and the conclusions are the author's.*

Yesterday, I was scared that I had found a severe security issue.  Today, I'm a bit more humbled about gaps in my own knowledge, but actually no less concerned that this, and similar behaviors, could be subverted by bad actors.  

I was actually concerned enough to not want to discuss it publicly first, but to ask the coding engine to help validate whether there was a real problem.  It declined to even discuss potential exploits.  (Wow, hiding facts with info gates is not going to help us, only hinder, but that's a whole other discussion.)

What it could help with, though, was the diagnosis, the replicability, and the reference history of the technical issue.   What is still outside its purview is the software engineer social contracts that we have built up in our thinking and our trust that can allow this to happen.  The promise and appeal of open source software is deeply rooted in this trust.  Hopefully this is just a reminder that we, as a group, have to raise awareness about applying some new software safety ratings to well known publicly hosted software repositories.  We know what some of these should be, there will be more.  It would benefit us all to prepare. 

## The Incident that prompted all this

At 10:29 on a Tuesday morning, my local `git` commit failed, trying to run a linter I never provisioned.

WTF, that should not have been possible. This is a well known open source project fork, and I have a standing rule in my agents that `git` hooks (and agent rules) do not run in forks — enforced properly, not by remembering: set in my global `git` config.

Set once, applies everywhere, no per-repo discipline required. That is how you are supposed to do it.

So the mechanism designed to prevent exactly this had been bypassed, in a repo I'd been working in for days.

## The diagnosis

So what do most engineers do when they want to rebuild an open source project, maybe tweak it for local details? They fork the project, and do an initial local build. That build is where it got me, and I'd bet it has gotten most everyone else as well.

`git` does not clone hooks. That is a deliberate design decision and it is the right one:
cloning a repository must never be able to execute code on your machine. Everything under .git/ is local, created fresh at clone time, and nothing on the remote side can write into it.

So the boundary is clear and clean: repository contents are data; local config is capability, and I would assert implicit permission.

A build script, on the other hand, is creating folders, invoking compilers, and building
required packages. This is where I found out about a known weakness in `pnpm` installs.

A `package.json` can declare lifecycle scripts [`preinstall`, `install`, `postinstall`, `prepare`], and the package manager runs them automatically, without notice or explicit permission. Hey, it's just part of installing, right!?

This project just had one line, sitting in package.json where I'd never known to look:

```json
"prepare": "pnpm exec husky || true && git config blame.ignoreRevsFile .git-blame-ignore-revs || true"
```

That's the whole thing. It runs `husky`, and `husky`'s job, by design, is to write core.hooksPath into my local .git/config, so from then on the hook scripts that shipped in the repo run on every commit. (The second command, `blame.ignoreRevsFile`, is a "harmless" second write to the same file, but it is still a write.)

And here's what it took me a while to see. I did run an install — but it did more than fulfill missing dependencies. The project (a web frontend in this case) requires a `pnpm` install, so of course I'd typed it. But in my head I was building a project, not changing behaviors or permissions of existing apps. My bad.

In this case, the misbehavior doesn't fire every time, which is why the timeline made no sense at first:

| What I ran | prepare ran? | core.hooksPath after |
| --- | --- | --- |
| install, node_modules present, lockfile unchanged | no  | unchanged |
| install after deleting node_modules | **yes** | **written back** |
| install with --ignore-scripts, node_modules deleted | no  | unset |

`pnpm` skips lifecycle scripts when there's nothing to install. So it fires on a fresh clone, a deleted node_modules, or a lockfile change. Rare, and at the tail end of a twenty minute run I'd started for a completely different reason.

Which is worse than firing every time. Something that happens on every build gets noticed.

## Why this felt like a betrayal

There was no obvious evil villain here, the project was trying to do common useful things, but for me it broke trust by reaching into a file that is none of its business.

But not because it lacked permission. It ran as me, so it had every permission I have. That is the actual problem. There is no way to say "fetch my dependencies, but don't touch my config," because nothing in this model distinguishes those two things.

It's not really an exploit, it's best practice. And that's disappointing.

Open source was never the same thing as trusted source. I knew that and yet I blithely rebuilt an open source project (that has 700+ forks), thinking it had some limited trust.

The cost was about nine hours. The commit failed at 10:29 and I had a verified fix at 19:31. No, not all nine hours were rat holed on this, other sessions were getting some attention as well, but just having to switch mental context to issues that were not germane to what I wanted to be working on, is its own overhead cost.

The final time cost: a full rebuild of node_modules, a typecheck, a unit test run, and a 111MB production build, twice — once to reproduce and once to verify the fix. Plus the reading, the wrong hypothesis, and the near-miss with poor solutions.

Net change: one line in one config file.

## Where are the guardians? The warnings?

The usual caution in open source is to only use "well known" repos, but that is quickly becoming moot.
- How "known" is "well known", how do you measure it?
- Fast moving AI tech repos are almost all unknown, so how could you measure their trustworthiness?
- How could you publish your own repo, and quantify it as trustworthy?

So whose job should this be?

Not the `npm` registry, which is the part you can check yourself. `npm` knows at publish time exactly which packages declare preinstall, install, postinstall or prepare, and it will tell you if you ask:

```
$ npm view esbuild scripts
{ postinstall: 'node install.js' }
```

One command, verifiable answer. No account, no tooling, no scanning infrastructure. And `esbuild` isn't doing anything wrong — that postinstall fetches the right platform binary, which is a completely legitimate reason to need a script, and it is the same reason turning scripts off isn't free.

The data is sitting in the registry and has been the whole time — it is simply not on the package page. No badge, no filter, no warning, nothing in the install output. So effectively nobody asks.

Not the code-hosting companies — which is odd, because they scan constantly. Static analysis, dependency alerting, secrets scanning, push protection, advisory databases, etc.  These are firms that invest heavily in being seen as security companies, and none of it answers the question I actually had.

To be fair, one of them does point at strangers. As of July 2026, `npm` scans newly published packages for malware before they can be installed
([GitHub changelog](https://github.blog/changelog/2026-07-28-npm-publish-time-malware-scanning-and-dual-use-metadata/)).
Dependabot can now also alert a repository's maintainers when a dependency matches a known-malicious package
([changelog](https://github.blog/changelog/2026-07-28-dependabot-alerts-on-malicious-packages-across-more-ecosystems/)),
but that serves the owner, and GitHub's docs say it
["never publicly discloses malicious dependencies for any repository"](https://docs.github.com/en/code-security/concepts/supply-chain-security/malware-alerts).
Both look for malicious code. Neither says what a legitimate project's own setup script will do to you, which is my case.
And nothing on the repository page tells you whether it was scanned, or for what. The upstream repository shows a "Security and quality" tab with a count of three, which is three published XSS advisories, not scan results, and no security policy. My fork shows none.

Look at what all those tools have in common: they point inward. Secret scanning protects you from your own leak. Dependency alerting protects you from stale CVEs in dependencies you already chose. Static analysis finds bugs in code you own. Every one of them serves the
repository's owner.

Almost nothing points outward. Nothing tells a stranger arriving at a repo what it will do to their machine when they build it. There is no score for "declares install scripts," for "ships `git` hooks," for "has a post-create command," or — newest and least examined — for
"carries instruction files aimed at a coding agent." ([more on that in the next piece](i-have-no-flag.md))

The package managers, partly — and credit where it's due. `pnpm` has blocked *dependencies'* lifecycle scripts by default since 10.0, and [`npm` v12, since released, does the same](https://github.blog/changelog/2026-06-09-upcoming-breaking-changes-for-npm-v12/). That's a real fix and it will save a lot of people a lot of grief.

But read the scope. Both of them block scripts from *dependencies*. On `pnpm`, I tested that the project's own scripts still run. On `npm` 12 I haven't: its changelog is silent on them, so I'm inferring.

So the case that just got closed is "a package buried two hundred deep in my tree does something." The case still wide open is "the repository I just cloned, from someone I've never met, runs its own script." I was on `pnpm` 11, with no allowlist configured anywhere, and my prepare script ran just fine.

I got caught by the part nobody fixed, and it's the part you hit first, because it's the first build of anything new.

## Are we repo rating the wrong things?

My, admittedly poor, assumption was that a platform would build this defensively. Automated detection is how you demonstrate you took reasonable care.

I think, unfortunately, the incentive runs the other way, and that's the part that gnaws at me.

Today's repos are scored on forks, stars, and watchers.  They don't really represent quality, acceptance, or trustworthiness.

A trust score is a claim. The moment a host rates repositories, it owns the ratings it got wrong — every repo marked clean that turns out hostile becomes something it asserted rather than something it merely hosted. Staying blind is cheaper than looking, and it is cheaper precisely because looking would create the obligation. Detection doesn't cover your exposure here. Detection manufactures it.

And there's no buyer. Secret scanning and security tools are sold to enterprises protecting their own code. "Warn me about the unfamiliar repo I'm about to build" protects an individual doing something casual, and nobody gets invoiced for that.

None of which is particularly helpful for individual developers, which really bothers me as it feels like a dereliction of duty. The information exists, the capability exists, the disclosure doesn't — and the reason it doesn't is that disclosure would cost the discloser something and save them nothing.  (Disclose the disclosure, there's a tongue twister in there somewhere)

But ultimately, I think that `git` got the boundary right. Everything built on top of it should stop stepping over.

## Mitigations and Remediations

But now I have to add several new barriers:

#### Change global settings

Both package managers need a different setting, and neither of them is the one everybody recommends. I hit this on `pnpm`, so it goes first, but `npm` does not get a pass.

- `pnpm`
  This is the one that got me. Put this in `~/.config/pnpm/config.yaml`:

  ```yaml
  ignoreScripts: true
  ```

  It covers a case `~/.npmrc` never did: `pnpm` runs a project's *own* install scripts regardless of what your `.npmrc` says, which is exactly the script that got me. `pnpm` also ignores `NPM_CONFIG_IGNORE_SCRIPTS`, so the environment is no help here.
  Global config is, and it survives a repo `.npmrc`.

  Neither this nor the `npm` setting below breaks `npm run` or `pnpm run` — an explicitly invoked script still runs, including its pre and post hooks. What stops is code running as a side effect of installing.

- `npm` 
  I did not hit this one, but I'd still not treat it as fixed. Put this in your
  shell profile, not in `~/.npmrc`:

  ```bash
  export NPM_CONFIG_IGNORE_SCRIPTS=true
  ```

  `ignore-scripts=true` in `~/.npmrc` is the usual advice and it is not enough. `npm`'s config precedence is CLI flags, then environment, then the **project's** `.npmrc`, then yours. A repository that ships an `.npmrc` containing `ignore-scripts=false` silently switches your protection back off. The environment beats it; your own config file does not.
  And `npm` v12's default blocks scripts from *dependencies*; its changelog is silent on a project's own scripts, and we measured `npm` 11, not 12. Until someone checks, assume the same gap.

Not free, in the usual way: packages that compile native addons or download binaries genuinely need their scripts, so some builds will fail and you run those deliberately instead of reopening the door for everything.

#### Custom post build check scripts

Automating `git config --get core.hooksPath`, and an actual read of `.git/config`, after any build/install in a repo I haven't built before, a layer I never thought of previous to this.

Of course, now I have to run this level of audit on all current and future forks.

#### Turn off Actions on your forks

A fork inherits upstream's workflows, and they run under your account. Between June and September 2026, five of my forks ran theirs on their own and emailed me the results.[^runs] I now disable Actions on public forks.

There is a cost: GitHub's code scanning needs Actions, and the other scanning options are opt-in and only look at the fork owner's own code.[^settings]

[^runs]: All from `notifications@github.com`, dated 2026-06-16 to 2026-09-23. The emails do not say what triggered each run.
    - `zbrad/llama.cpp`, `build-cann.yml`: no jobs were run
    - `zbrad/pytorch`, `inductor-rocm-mi200.yml`: no jobs were run
    - `zbrad/flashinfer`, Issue Claim: a job failed in 4 seconds
    - `zbrad/raft`, `build`: 34 jobs, including CUDA devcontainer builds for amd64 and arm64
    - `zbrad/sqlite`, Tuned Release: one job failed, one was cancelled

[^settings]: My fork's Advanced Security page, 2026-09-30: dependency graph, Dependabot alerts, Dependabot version updates and AI Scan for pull requests were off; code scanning was "not available" because Actions is disabled; secret alerts to partners are always on for public repos. No malware-alerts option appeared. Details and caveats are in the [addendum](the-purloined-config-addendum.md).

#### Scripts used for this piece

All in this repo's [`scripts/`](../scripts/). The scanner and the two sampling scripts only read files; the verify script runs installs, but only inside its own throwaway fixture.

- [`verify-trigger-table.sh`](../scripts/verify-trigger-table.sh) — reproduces the table above: a `prepare` script runs on an install with real work to do and writes to the local `.git/config`, and doesn't on one without. Uses a throwaway fixture; needs `pnpm` and network.
- [`repo_scan.py`](../scripts/repo_scan.py) — counts what a repo can do to your machine when you build it: install scripts, hook installers, `.npmrc` overrides, agent instruction files, CI. Counts, doesn't score.
- [`install_script_sampler.py`](../scripts/install_script_sampler.py) — samples JavaScript and TypeScript repos from GitHub by language and star band, and counts how many declare an install-lifecycle script in their root `package.json`.
- [`install_script_classifier.py`](../scripts/install_script_classifier.py) — labels each declared script by what its command, or the script file it runs, mentions: hook installer, patcher, build step, and so on.

## One smaller ask of `git`

Some `git` config keys aren't preferences. They name a command `git` will run, or a place it
will send things: `core.hooksPath`, `credential.helper`, `core.sshCommand`, `core.fsmonitor`,
and a few more. What I'd want is that a value for one of those, sitting in a repo's own local
config, does nothing until I allowlist that repo, the way `safe.directory` already works for
ownership. At the very least, `git config` could say so out loud when something sets one. I'd
have found mine in seconds, not nine hours. The reasoning, and what `git` has already tried,
is in the [proposal addendum](the-purloined-config-proposal.md).

## Final Thoughts

I'm never going to get those nine hours back, so my first notion was that I should write this up so others might not waste their nine hours, and also add some basic protections and/or detections.

But my scary thought was, this is a well known project, created by well intentioned people, but this mechanism could be hijacked for almost any open source project these days. The social engineering aspect of relying on an engineer’s common behaviors is just enough to
widen a window that I honestly thought was already closed.

I was just lucky to have caught it.

But still the part that sticks with me, a file that I own, was modified to add behaviors I didn't approve.

For the verification Claude ran on this, see the [addendum](the-purloined-config-addendum.md).

