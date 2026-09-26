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
- **Work in your own worktree; fork one. Never work in another session's.**
  A hand-off carries a branch, an issue and a PR, never a directory — the
  owning session may still be running and may be archived out from under you
  mid-turn. Read another branch from where you stand (`git log/show <branch>`,
  `git show <branch>:<path>`); to work it, fork your own worktree and check it
  out there. If git says the branch is checked out elsewhere, that is a live
  claim: report it and stop. Enforced by
  `~/.claude/hooks/no-foreign-worktree.sh`.
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
  to main, no branch, no asking. Branching by default is the failure
  mode here, not landing on main.

  When a branch *is* warranted: push it and open the PR yourself, as
  early as the work is worth looking at — local checks need not have
  finished. Never wait to be asked, never leave a pushed branch without a
  PR. Draft or ready, reviewer or none, is yours to judge; the
  `awaiting-human` label is what says it is my turn. A branch opened this
  way ends only one way: merged via PR, never folded back to main and
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
  to the user instead. Cloud sessions often can't delete remote branches
  themselves (`git push --delete` is blocked by the auto-mode classifier
  and there is no MCP equivalent) — but that only still matters for this
  narrower leftover case, since a normal PR merge no longer needs it at
  all. From a cloud session facing that narrower case, just list what
  should go; the sweep is a nucbox job.

## PR ownership

The bar is computed, not prose: Mergify adds `awaiting-human` when
`ci-gate / gate` is green and no review thread is unresolved, and removes
it when either stops being true. Until it is on, the PR is mine. A draft
carries no label and gets no CodeRabbit or claude-review pass, so it sits
in nobody's queue but this session's.

- **Read the conversation before you watch the checks.** On any PR — mine or
  one I am reviewing — the order is: review comments and unresolved threads
  first, then the fix and the push, then CI. Waiting on a check is the lowest
  priority thing a session can be doing, and never the only thing: a long
  local suite or a running GitHub check is background, so start it and go work
  the threads while it runs. A session idling on `gh pr checks --watch` or a
  test run while an unanswered comment sits on the PR is wasting the one
  resource that matters. `--watch` is for the last look before hand-over,
  after the threads are answered — not for the middle of the work.
- **Green before hand-over.** In order:
  - every fast check the repo defines passes locally — formatter, lint,
    typecheck, build, tests; whatever that repo actually has;
  - the branch is current with its base and has no conflict — `git fetch
    origin <base> && git rebase origin/<base>` before the first push AND
    again immediately before handing the PR over. Main moves while a
    session works; a branch that was clean an hour ago is not clean now;
  - **when that rebase conflicts, merge instead of rebasing.** `git merge
    origin/<base>`, resolve, commit — the merge commit is signed like any
    other and carries the hand-resolution in its tree — then push it as a
    plain fast-forward. Do NOT then `git rebase`/`resign-branch.sh` to
    linearize it: a rebase replays only single-parent commits, so every
    edit that lives only in the merge commit's tree is silently dropped
    (`resign-branch.sh` refuses this case for that reason). Two traps
    on the push: mergify-cli's pre-push hook blocks any push when the
    *checked-out* branch has `Change-Id` trailers, whatever ref is being
    pushed — push from a detached throwaway worktree, not `--no-verify`;
    and `mergify stack push` is only for a branch whose commits map to
    PRs in `mergify stack list` — a Change-Id trailer alone does not make
    a stack, and on a plain PR branch it opens one new PR per commit;
  - the merge state says so, not just the checks — `gh pr view --json
    mergeable,mergeStateStatus`. `gh pr checks` is green on a branch that
    conflicts with main, so green checks are not a mergeable PR;
  - where CI can be read before merge, read it — `gh pr checks --watch`
    before hand-over, not as a way to pass the time after the first push;
  - **the body carries a `Head: <sha>` line naming this push** — the last
    edit before hand-over, so a head that moves afterward (one more commit,
    a rebase, a resign) is visible on the PR page before anyone merges it,
    not discovered after (dotfiles#286). Add the line if it's missing,
    replace it if it's there: `gh pr edit <n> --body "$new_body"` with the
    line set to `git rev-parse HEAD`.
- **A PR handed to the user needs a judgment pass, not a "did this even build"
  pass.** His read is for the call I can't make — is this the right change,
  does it fit the design. Anything a machine could have caught should
  already be caught.
- **What can't be made green gets said, in the PR description.** A flaky
  external dependency, a check that needs a secret or a decision only the user
  has, a failure that provably predates the branch: name it in the body and
  say why it isn't mine to fix. Opening a broken PR silently is the exact
  failure this section exists to prevent; opening one with the breakage
  labelled is fine.
- **Ready is not the end of the turn.** After it, CI failures, bot findings
  and merge conflicts are mine, round after round, until every check is
  green and every automated thread is answered or resolved. A red check is
  never handed over as a status report.
- **"Resolve conversation" is mine to do, not the user's.** The REST API and
  `gh` CLI have no resolve-thread call, which reads like a dead end —
  it isn't; GitHub only exposes it over GraphQL:
  `gh api graphql -f query='mutation($id:ID!){resolveReviewThread(input:{threadId:$id}){thread{isResolved}}}' -f id=<threadId>`
  (thread ids from `reviewThreads(first:N){nodes{id isResolved}}` on the PR,
  not the REST comment id). Telling the user to click "Resolve" herself because
  the obvious tool doesn't have it is asserting a limitation without
  checking whether a less-obvious one does — verify before you claim
  something can't be done from here.
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
- **Resolve threads one at a time, by id, after reading and responding to each one.** Never
  loop over "all unresolved threads" — a review bot can post between your
  listing and your resolve, and the loop closes findings nobody read. Scar:
  2026-09-01, dotfiles#60 — resolved three CodeRabbit threads unread this
  way, one of which asked to disable pre-commit hooks.
- **Every subagent prompt that touches a PR carries the resolve requirement
  verbatim.** Delegating the fix does not delegate away this rule — an agent
  told only "fix the CI failure" fixes it and leaves the thread open, and the
  thread is then mine, discovered a turn later by the gate. Any prompt that
  sends an agent at a PR states: read the thread, fix it, reply with the
  evidence, resolve it by id, in the same pass; and report the thread ids it
  resolved. Scar: 2026-09-08, the six-PR conflict sweep — six agents launched,
  only two carried the instruction, and the user had to ask again.

- **A repeated CodeRabbit comment gets re-verified live, not answered from
  turn memory.** When the same finding text shows up again (re-pasted, or a
  fresh review pass after a push), re-fetch the actual thread state — GraphQL
  `reviewThreads` (path, `isResolved`, comment body) — before telling the user
  it's already handled, even when you're confident it's the same one. State
  what you found: thread id, resolved status, which commit fixed it. Scar:
  2026-08-28, signalk-noaa-space-weather#214 — said "nothing further to do"
  from memory of an earlier fix; the conclusion happened to be right, but it
  was asserted, not checked, on the very question "is this fully closed."
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
- **Tell the user once, when it's actually his turn.** He signs off last;
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
- **Park open questions somewhere durable** — as an issue or card per
  `/card-write`, or ask directly when the answer blocks the task —
  never only in session scrollback. A question that lives solely in a
  session's last response is invisible the moment that session scrolls out
  of view.

## Our own workflows and actions

- **Call our own reusable workflows and composite actions at the tip of
  `main`, never a SHA or a version tag.** `uses:
  mark-brannan/.github/.github/workflows/<name>.yml@main`, and the same for
  `.github/actions/<name>@main`. One copy to fix is the whole point of
  putting them in `mark-brannan/.github`: a pin means a fix there does not
  reach the repo that needs it until someone remembers to re-pin, across a
  dozen repos, which nobody does. Ruled by Solace, 2026-09-14.
- The supply-chain argument for pinning is about code we do not control.
  These are the user's own repos under the user's own account, already
  covered by the same branch protection as everything else, so the pin buys
  a guarantee that was not missing and costs the fleet-wide fix.
- **Third-party actions are the opposite** and keep their pins —
  `actions/checkout@v7` and friends stay as the upstream publishes them.
- If a shared workflow ever needs to change in a way callers cannot absorb,
  the fix is to keep it backward-compatible or to change the callers, not to
  strand them on an old ref.

## Provisional until decided

- **A fast first version is not the design.** Decidedness is a gradient and
  usually unstated, so default to treating a decision as soft unless the user
  has said it is settled or it is written into a reviewed spec. Reading a
  firm decision as soft costs one re-ask; reading a soft one as firm anchors
  them to something they meant as temporary, which is the expensive direction.
- **Mark provisional code where the next reader is standing** — in the file,
  as a pointer to the issue holding the open question, never a restatement
  of it. A link stays true; a summary rots and then lies with authority.
- **On something provisional, the default recommendation is "decide it or
  harden it,"** never "close the question because working code exists."
- Scar, 2026-09-01: on dotfiles #60, an explicitly fast v1, I recommended
  closing #59 and deleting its policy file — twice treating what shipped
  first as what was intended.

## Comments and docs

- **Bias toward fewer comments.** Add one only where a reader would likely
  trip on non-obvious behavior later — a why, not a what. Default to a
  single line; two only when genuinely needed, and say the essential thing
  plainly rather than reasoning through it in prose.
- **Don't touch README/docs/design-docs on a small or mechanical change**
  unless skipping the edit would leave them factually wrong. A defensive
  guard, a rename, a bug fix: code and tests only. Scar: repeated doc/comment
  churn on past PRs that cost review attention without changing a decision.
- **A runbook is the operator's, not the agent's.** An entry earns its place
  only if the user would run it in an emergency or on the day-to-day critical
  path: the commands, in order, and the one check that says it worked. No
  background, no session findings, no agent-only debugging. Every change
  that touches a runbook or the system it covers is a chance to cut from
  it; the no-churn rule above never protects a runbook from a deletion.
- Tests may carry more description than production code — lean on names,
  `it.each` labels, and assertion text to self-document rather than adding
  narration comments above them.

## Publishing

- **npm publish: no OTP.** My npm account uses browser 2FA with a passkey.
  Run plain `npm publish` and let it open (or print) the auth URL; I approve
  in my browser. Don't ask me for authenticator codes or pass `--otp`.
- **A new package's first publish is mine, from the CLI.** Trusted-publisher
  CI can't create a name that doesn't exist yet, and npm reports that as
  E404 on the `PUT`, not 403. Don't edit the workflow; run `/npm-first-publish`
  and ask me inline — not a card, it's thirty seconds.

## Design

- **Reuse before build.** Search for an existing pattern first. Escalate in
  order: reuse → extend → extract → configure → strategy/plugin → new. A new
  implementation is the last option, not the first.
- If you'd copy more than ~20% of an existing file, stop and justify the
  duplication before proceeding.
- Watch for parallel implementations, repeated state machines, repeated
  validation flows, and copy-paste feature development. Those are the smell.

## Screenshots and Playwright

- **Every browser launch defaults to a light background unless told
  otherwise, and that default is per-invocation** — a repo's checked-in
  capture script can hardcode `colorScheme: 'dark'` and still leave every
  ad-hoc Playwright script (a throwaway `chromium.launch()` to eyeball
  something) unset, because nothing carries the setting forward. That's why
  "always use dark" corrections don't stick: each new script is a fresh
  default, not a continuation of the last one.
- **So set it explicitly, every time, in the script itself** — not as a
  one-off correction. `newContext({ colorScheme: 'dark' })` (or
  `page.emulateMedia({ colorScheme: 'dark' })` if reusing a context), before
  `goto`. Do this whether the script is a permanent repo asset or a
  five-line throwaway.
- Exception: the page being captured has no dark mode at all (a vendor admin
  UI, a light-only third-party page). Then light is correct — say so in a
  comment so the choice reads as deliberate, not missed.
- If a project's own capture tooling already threads a `--theme`/`theme:`
  option (check for one before adding a flag), pass dark through that
  instead of hardcoding — see this repo's
  [scripts/screenshots/capture.mjs](scripts/screenshots/capture.mjs) and
  [scripts/screenshots/states.mjs](scripts/screenshots/states.mjs) for the
  pattern.

## Verification

- **Verify an identifier exists before using it** — enum values, icon names,
  library symbols, route names, config keys. Don't infer from convention.
- **A package in the manifest is not proof it's used.** Confirm it's
  registered and referenced before relying on it or recommending it.
- Dry-run flags are not always dry. `make -n` executes recursive `$(MAKE)`
  lines for real. Read the file instead of trusting the flag.
- **A PR merging is not the fix landing, for anything published as a
  package.** "Done" means the release workflow completed and the registry
  reflects it — check `npm view <pkg> dist-tags` (or the equivalent for the
  registry in play), don't infer publish from a merged PR or a green
  release-please run. In the gap between merge and publish, label the issue
  (e.g. `blocked`) or leave a comment saying what it's waiting on, rather
  than closing early or leaving it ambiguous. Scar: 2026-09-08,
  colregs-engine#32 — closed on PR merge, reopened three minutes later
  because `npm view colregs dist-tags` still showed the pre-fix version.

## Cost

- **One action per Bash call; never chain what a gate might refuse.** A
  permission rule matches a whole command, and the `lib-shell-words.awk`
  gates judge every segment of a chain with ambiguity resolving toward deny.
  So one refused segment kills the whole call, and the retry re-emits every
  other segment with it. `git fetch && git rebase && git diff` is one block
  plus a full re-send; as three calls it is three allowlist hits. Reads are
  not exempt — they are the usual casualties, dragged down by a write they
  were stapled to. Measured 2026-09-16 over 1334 blocked Bash calls
  (`state/global/metrics/blocked/`): 919 (69%) were chains, and `git status`
  and `git log` were blocked 176 times between them purely as passengers.
- **A gate that redirects needs a small thing to redirect.** These hooks are
  meant to send the work down a better path, not just refuse it; a redirect
  landing on a five-command chain can't say which part to change, and costs
  the whole chain to act on. Keep the call small enough that the hook's
  reason is the next action.
- **Don't paste a bulk allowlist to quiet the prompts.** Rules get proposed
  in tables by frequency, which measures nothing about whether the rule is
  safe or even load-bearing. Scar: 2026-09-16, a four-row table covering
  4 of 1334 blocks — two rows already live at user scope, and
  `Bash(gh api repos/*/contents/*)` labelled read-only while its trailing
  `*` matched `-X DELETE` and every `-f` (which flips `gh api` to POST).
  Write `*` only after the subcommand: Claude Code warns that a wildcard
  before it, as in `Bash(git *)`, also approves injected `-c`/`--exec-path`,
  which run arbitrary commands.
- **Don't switch model or `/effort` mid-session** — pick both at start; a
  switch at ~50k context recomputes 65-100% of it (measured,
  `.claude/docs/token-budget.md`).
- **A classifier denial is a stop and a report, not a prompt to reach the
  same outcome another way.** The classifier reads the transcript, not just
  the one command, so a second route to an already-denied outcome gets
  denied too, under a different label, and can cascade into denying plain
  reads. Report what was denied and why; the workaround is the user's call.
  Scar: 2026-09-22, colregs-engine PR #138 — three different pushes at the
  same denied outcome (branch rename, detach, plain refspec), three denial
  labels, then reads started failing.

## Tests

- **Test behavior, not presentation.** Assert what got persisted, who's
  authorized, what validation rejects, what happens at the edges.
- Don't assert on copy, labels, headings, nav items, element order, or CSS
  classes. Those are change-detectors: they break on every rename and have
  never caught a real bug.
- Don't test framework behavior.
- A trivial copy or label rename means edit, update the assertion referencing
  the old string, commit. No full suite run.
