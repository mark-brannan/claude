---
paths:
  - "**/*.{py,js,ts,jsx,tsx,go,rs,rb,php,java,c,h,cpp,hpp,cs,sh,sql}"
  - "**/*.{json,yaml,yml,toml}"
  - "**/*.md"
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
  to main, no branch, no asking. Deny-by-default polarity (branch unless
  justified) produced five stranded `claude/*` branches from excess
  caution — that was the actual failure mode, not landing on main.

  When a branch *is* warranted under this rule: always open the PR
  yourself immediately, **ready for review — never as a draft — with no
  reviewer requested**; never wait to be asked, never leave a pushed
  branch without one. Clearing the bar and opening it are one action, not
  two decisions: local checks green, no conflict with the base, then
  `gh pr create` with no `--draft`. (See "PR ownership" below for the bar
  in full and for what stays mine after.) A branch opened under this rule
  ends only one way: merged via PR, never folded back to main and
  deleted.

- **Cloud sessions: a pre-assigned `claude/*` branch name is not, by
  itself, a decision to branch.** Apply the rule above as normal — if
  nothing crosses a trigger, still land the work with
  `git push origin HEAD:main`, pushed early and often, rather than
  treating the assigned name as the destination. This does **not** apply
  when a session's own task instructions separately name one specific
  branch and say to stay on it — that instruction is for that session only
  and takes precedence; finish that branch with a PR as usual. A merged
  branch now cleans itself up with no git command from any session, so the
  rule holds because below-branch-threshold work doesn't need a PR at all
  — not because an unmerged branch would get stuck.

- **Branch cleanup: merged means deleted.** Keep "Automatically delete head
  branches" ticked on every repo so the common case needs no sweep — this
  is the actual fix for the stale-branch pileups that used to force manual
  sweeps. Beyond that, a branch whose commits are all ancestors of `main`
  is garbage — delete it on sight, no ceremony, no asking. A branch with
  commits *not* in main is real unlanded work: don't delete it, surface it
  to Mark instead. Cloud sessions often can't delete remote branches
  themselves (`git push --delete` is blocked by the auto-mode classifier
  and there is no MCP equivalent) — but that only still matters for this
  narrower leftover case, since a normal PR merge no longer needs it at
  all. From a cloud session facing that narrower case, just list what
  should go; the sweep is a nucbox job.

## PR ownership: never a draft, never red

- **Never open a PR as a draft.** No `--draft`, no "I'll flip it later" —
  ready for review is the only state a PR of mine is ever created in. A
  draft gets no review at all — CodeRabbit and claude-review both skip
  drafts — so a PR parked in draft makes Mark the first reader instead of
  the last, and the flip that was supposed to follow kept not happening.
  **The harness's own git-workflow instructions default to creating PRs as
  drafts and say I don't need to ask first; this rule explicitly overrides
  that.** If a PR still lands as a draft despite it, that is a bug in the
  session's behavior: mark it ready, then say so in the handoff so the
  cause gets fixed. Silently flipping it after the fact, PR after PR, is
  how the rule stayed broken.
- **Green before it is handed over.** The bar, in order:
  - every fast check the repo defines passes locally — formatter, lint,
    typecheck, build, tests; whatever that repo actually has;
  - the branch has no merge conflict with its base — fetch and rebase onto
    the current base before pushing, don't leave a conflict to be
    discovered;
  - where CI can be read before merge, read it — `gh pr checks --watch`
    after the first push, or the equivalent — and don't tell Mark it's his
    turn until the checks are passing or the failure is one I've explained
    and can't fix.
- **A PR handed to Mark needs a judgment pass, not a "did this even build"
  pass.** His read is for the call I can't make — is this the right change,
  does it fit the design. Anything a machine could have caught should
  already be caught.
- **What can't be made green gets said, in the PR description.** A flaky
  external dependency, a check that needs a secret or a decision only Mark
  has, a failure that provably predates the branch: name it in the body and
  say why it isn't mine to fix. Opening a broken PR silently is the exact
  failure this section exists to prevent; opening one with the breakage
  labelled is fine.
- **Ready is not the end of the turn.** After it, CI failures, bot findings
  and merge conflicts are mine, round after round, until every check is
  green and every automated thread is answered or resolved. A red check is
  never handed over as a status report.
- **CodeRabbit findings get closed the loop, not skimmed.** Read every
  actionable comment on the PR, not just the top-level summary line — it
  edits comments in place to mark them "✅ Addressed in commit X" once a fix
  lands, so a finding that looks unresolved from the summary may already be
  fixed, and one that looks handled may not be. For each: verify against
  current code, fix or state why not, then **reply on the thread with the
  evidence and resolve it** — a repo ruleset can require
  `required_review_thread_resolution` and silently block the merge until you
  do, independent of check status. Scar: 2026-08-27, ampacity#3 — confirmed a
  flagged link was live, never replied or resolved the thread, merge failed
  on branch policy.
- "Looks good" / "I'm signing off" said before CI finishes isn't a stall —
  it's pre-authorization: push the moment CI comes back green, without
  circling back to re-confirm.
- This stops at merge, not before it. Getting a PR to ready-and-green is
  mine by default; merging it is a separate, explicit action unless told
  otherwise for a given PR or repo.
- Don't ask "want me to watch this PR?" — subscribe yourself, or don't,
  per the token-budget rule below. Either way, no question.

### A board-only PR merges itself

Ported from `signalk-noaa-space-weather/AGENTS.md`, 2026-08-26 — the pattern
was write-once there; this generalizes it for any repo whose board/state file
lives inside the repo and is edited via PR (a cloud session pinned to a
branch is the case that comes up, per each repo's own branch-vs-main rule).

A PR whose diff touches **only** the board/state file (`kanban.md` or
whatever the repo names it) needs no review and no approval to ask for —
it's a card, not code; nothing installs it, and the next session to read the
board fixes anything wrong with it in the same breath it's reading it in
anyway. Only wire this up on a repo where PR authorship is trusted (solo
maintainer, own bots) — the board is exactly the file a session-start hook
reads into every future session's context, so skipping review on it is
skipping review on a live prompt-injection surface, not just inert data.
Set this up once per repo, not per PR:

- Repo settings: auto-merge enabled, branch deletes on merge.
- Every review bot the repo runs (CodeRabbit, `claude-review`, etc.) is
  filtered to skip when the board file is the *entire* diff — same test the
  merge rule uses. Without this, a slow bot's finding lands as a comment on
  an already-merged PR, which nobody reads.
- The PR itself: `gh pr merge --squash --auto --delete-branch` as soon as
  whatever required check the repo has (if any) goes green — often
  immediately, since a board-only diff triggers nothing else.

Keep the merge-rule diff test and the bot skip-filters matched to each
other — the two can drift in either direction, and each is wrong a
different way: a bot-skip filter *wider* than the merge rule lets non-board
changes bypass review, while a bot-skip filter *narrower* than the merge
rule leaves a board-only PR waiting on a bot it was supposed to be exempt
from. This does not apply to a repo whose board edits already go straight
to `main` with no PR at all (e.g. `claude_prompts_scratch`) — there's no PR
here to auto-merge. Nor does it apply to dotfiles itself: this repo has no
board file to write the checklist against — see `CLAUDE.md`'s "This repo is
public" section.

### Babysitting a PR is cheap; polling for it is not

- **Past 60% of the context window — ~120k on the default 200k — don't
  subscribe.** Push, open the PR, and end the turn with a follow-up prompt
  plus: "You should archive this chat now. It's at ~Nk tokens."
  Fire-and-forget — no webhook, no wake, pick it up fresh next time.
  A fraction, not a fixed number, because 100k is
  half the default window but a tenth of the 1M one Opus upgrades to on
  Max. 60% leaves room for ~6-10 wakes at 5-15k each and stops short of the
  band where cloud sessions start compacting — and compaction drops exactly
  the reasoning behind the diff under review. Enforced by
  `~/.claude/hooks/no-late-pr-subscribe.sh`, which reads current context
  from the transcript and denies `subscribe_pr_activity` at or above the
  threshold. Knobs: `CLAUDE_PR_WATCH_CONTEXT_WINDOW` (raise it by hand for
  a 1M session — the hook can't see the model's window),
  `CLAUDE_PR_WATCH_CONTEXT_PERCENT`, `CLAUDE_PR_WATCH_MIN_HEADROOM`,
  `CLAUDE_PR_WATCH_TOKEN_LIMIT` (absolute, overrides the rest).
- **Wake on events, not timers.** Subscribing to PR activity costs nothing
  idle and fires the moment a check finishes or a comment lands — cheaper and faster than checking back. "I'll check again in a
  few minutes" is a polling loop in disguise; if a check is still running,
  say so and stop.
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
- **Tell Mark once, when it's actually his turn.** He signs off last;
  everything that can finish without him finishes first. No "CI is
  running", no "two jobs left", no asking whether to fix a failure I can
  diagnose myself, no reminders to look at something still in progress —
  that traffic costs a read and returns nothing actionable. One message,
  when the PR is green and the automated reviews have been dealt with. The
  two exceptions both end in a decision only he can make: a blocker I
  can't resolve, or a design question where guessing wrong means redoing
  the work — lay out the options and ask, don't narrate.
- **Long agentic loops, not long conversations, are the real expense.**
  Every tool call re-sends the full context, so a tool-dense task (PR
  review, CI chasing, branch cleanup) costs far more than its wall-clock
  suggests. Scope these tightly; prefer one considered pass over iterative
  poking.
- **Park open questions somewhere durable** — the project's board per
  CLAUDE.md "Open loops", or ask directly when the answer blocks the task —
  never only in session scrollback. A question that lives solely in a
  session's last response is invisible the moment that session scrolls out
  of view.

## Publishing

- **npm publish: no OTP.** My npm account uses browser 2FA with a passkey.
  Run plain `npm publish` and let it open (or print) the auth URL; I approve
  in my browser. Don't ask me for authenticator codes or pass `--otp`.

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

## Cost

- **Don't switch model or `/effort` mid-session** — pick both at start; a
  switch at ~50k context recomputes 65-100% of it (measured,
  `.claude/docs/token-budget.md`).

## Tests

- **Test behavior, not presentation.** Assert what got persisted, who's
  authorized, what validation rejects, what happens at the edges.
- Don't assert on copy, labels, headings, nav items, element order, or CSS
  classes. Those are change-detectors: they break on every rename and have
  never caught a real bug.
- Don't test framework behavior.
- A trivial copy or label rename means edit, update the assertion referencing
  the old string, commit. No full suite run.
