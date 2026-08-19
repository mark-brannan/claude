---
paths:
  - "**/*.{py,js,ts,jsx,tsx,go,rs,rb,php,java,c,h,cpp,hpp,cs,sh,sql}"
  - "**/*.{json,yaml,yml,toml}"
  - "**/{Makefile,Dockerfile,docker-compose*,*.tf}"
---

# Code

Loads when Claude works with source files. Personal conventions only —
project-specific facts belong in that project's own CLAUDE.md.

## Git

- **Stage explicitly.** Never `git add -A` or `git add .`. Stage by path,
  check `git status --porcelain` before committing, unstage foreign files.
- **No destructive operations without approval.** Nothing that drops,
  truncates, force-pushes, or rewrites shared history.
- Recover a tangled graph by branching from current HEAD, not by rewriting
  commits under my feet. Re-check HEAD against the remote before any history
  surgery; it may have moved since session start.
- Prefer `rm` or an edit over `git rm` for files being replaced, so deletions
  stay unstaged until I commit them.
- **Work on main by default. Branch-vs-main is a rule, not a judgment
  call — don't ask.** Commit straight to main in small, verified commits,
  pushed early and often, unless one of these triggers:
  - **Explicit phrase** — I say "make this a feature," "make this a
    branch," or "this needs review." Skip the metric check; branch
    immediately.
  - **Metric threshold crossed** (placeholders, tune later): **>50 lines
    of code changed** (excluding docs), **>200 lines of docs changed**,
    **session >100k tokens**, or **session >30 min wall clock**.

  Everything else — small fixes, doc edits, config tweaks — goes straight
  to main, no branch, no asking. Reversed 2026-08-19 from the prior
  deny-by-default polarity ("commit to main requires no branch reason");
  the old rule produced five stranded `claude/*` branches from excess
  caution, which was the actual failure mode, not landing on main.

  When a branch *is* warranted under this rule: always open the PR
  yourself immediately, **as a draft, with no reviewer requested** — never
  wait to be asked, never leave a pushed branch without one. A branch
  opened under this rule ends only one way: merged via PR, never folded
  back to main and deleted.

- **Cloud sessions: a pre-assigned `claude/*` branch name is not, by
  itself, a decision to branch.** Apply the rule above as normal — if
  nothing crosses a trigger, still land the work with
  `git push origin HEAD:main`, pushed early and often, rather than
  treating the assigned name as the destination. Decided 2026-08-19, see
  `claude_prompts_scratch/state/global/log/2026-08-19-git-vocabulary-worktrees.md`
  (cloud sessions cannot delete their own remote branches, so the cheapest
  fix is not creating one). This does **not** apply when a session's own
  task instructions separately name one specific branch and say to stay on
  it — that instruction is for that session only and takes precedence;
  finish that branch with a PR as usual.

## Publishing

- **npm publish: no OTP.** My npm account uses browser 2FA with a passkey.
  Run plain `npm publish` and let it open (or print) the auth URL; I approve
  in my browser. Don't ask me for authenticator codes or pass `--otp`.
  (Added 2026-08-08.)

## Design

- **Reuse before build.** Search for an existing pattern first. Escalate in
  order: reuse → extend → extract → configure → strategy/plugin → new. A new
  implementation is the last option, not the first.
- If you'd copy more than ~20% of an existing file, stop and justify the
  duplication before proceeding.
- Watch for parallel implementations, repeated state machines, repeated
  validation flows, and copy-paste feature development. Those are the smell.

## Verification

- **Verify an identifier exists before using it** — enum values, icon names,
  library symbols, route names, config keys. Don't infer from convention.
- **A package in the manifest is not proof it's used.** Confirm it's
  registered and referenced before relying on it or recommending it.
- Dry-run flags are not always dry. `make -n` executes recursive `$(MAKE)`
  lines for real. Read the file instead of trusting the flag.

## Tests

- **Test behavior, not presentation.** Assert what got persisted, who's
  authorized, what validation rejects, what happens at the edges.
- Don't assert on copy, labels, headings, nav items, element order, or CSS
  classes. Those are change-detectors: they break on every rename and have
  never caught a real bug.
- Don't test framework behavior.
- A trivial copy or label rename means edit, update the assertion referencing
  the old string, commit. No full suite run.
