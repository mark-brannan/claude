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
  `claude_prompts_scratch/state/global/log/2026-08-19-git-vocabulary-worktrees.md`.
  This does **not** apply when a session's own task instructions separately
  name one specific branch and say to stay on it — that instruction is for
  that session only and takes precedence; finish that branch with a PR as
  usual. The original justification here was "cloud sessions can't
  reliably delete their own remote branches, so the cheapest fix is not
  creating one" — true, but as of 2026-08-20 no longer the operative
  reason (see next bullet: a merged branch now cleans itself up with no
  git command from any session). The rule still holds because below-branch
  threshold work doesn't need a PR at all, not because a branch would be
  stuck.

- **Branch cleanup: merged means deleted.** Keep "Automatically delete head
  branches" ticked on every repo (dotfiles: on, confirmed 2026-08-19 when
  PR #5's head vanished on merge; symphony: on, confirmed 2026-08-20 when
  PR #15's and PR #22's heads both vanished within moments of merge with no
  session action) so the common case needs no sweep — this is the actual
  fix for the stale-branch pileups that used to force manual sweeps.
  Beyond that, a branch whose commits are all ancestors of `main` is
  garbage — delete it on sight, no ceremony, no asking. A branch with
  commits *not* in main is real unlanded work: don't delete it, surface it
  to Mark instead. Cloud sessions often can't delete remote branches
  themselves (`git push --delete` is blocked by the auto-mode classifier
  and there is no MCP equivalent) — but that only still matters for this
  narrower leftover case, since a normal PR merge no longer needs it at
  all. From a cloud session facing that narrower case, just list what
  should go; the sweep is a nucbox job. (Decided 2026-08-19; reasoning
  updated 2026-08-20.)

## PR ownership: draft → ready is mine

- When I open a PR as a draft, driving it to ready is my job, not something
  to wait on. Resolve bot/reviewer comments, fix CI failures, and flip it
  out of draft the moment CI is green and comments are addressed — don't
  wait to be asked, and don't leave a green, comment-free PR sitting in
  draft for a human to notice and un-draft.
- "Looks good" / "I'm signing off" said before CI finishes isn't a stall —
  it's pre-authorization: push (and mark ready) the moment CI comes back
  green, without circling back to re-confirm.
- This stops at merge, not before it. Getting a PR to ready-and-green is
  mine by default; merging it is a separate, explicit action unless told
  otherwise for a given PR or repo. (Added 2026-08-20.)

### Babysitting a PR is cheap; polling for it is not

- **Wake on events, not timers.** Subscribing to PR activity costs nothing
  idle and fires the moment a check finishes or a comment lands — cheaper
  and faster than checking back. "I'll check again in a few minutes" is a
  polling loop in disguise; if a check is still running, say so and stop.
- **Never bind a scheduled wakeup to a live session** to re-poll a PR — no
  `send_later`, no `create_trigger` carrying a persistent session id or
  missing a fresh-session flag. Each firing re-sends that session's whole
  accumulated context, so the cost compounds with every wake, and a
  PR-watching session gets asked to re-arm before ending its turn, which
  reproduces the same shape again. Take whatever redirect the harness
  offers instead of working around it.
- **One watcher per PR.** Check whether another session already has it
  before subscribing or scheduling.
- **Batch review responses.** Address every open thread in one pass, then
  push once — don't wake per comment.
- **Long agentic loops, not long conversations, are the real expense.**
  Every tool call re-sends the full context, so a tool-dense task (PR
  review, CI chasing, branch cleanup) costs far more than its wall-clock
  suggests. Scope these tightly; prefer one considered pass over iterative
  poking.
- **Park open questions somewhere durable** — the project's own
  working-state file if it has one, otherwise ask directly — never only in
  session scrollback. A question that lives solely in a session's last
  response is invisible the moment that session scrolls out of view.
  (Added 2026-08-20; generalized from `symphony/CLAUDE.md`'s "PR
  automation and session cost" section, which stays the canonical version
  for that repo's specifics.)

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
