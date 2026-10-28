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
  out there. If git says the branch is checked out elsewhere, that is a
  claim only while its holder lives — a fresh claim stamp or a process in
  that worktree: report it and stop. An idle holder is not a claim; the
  pickup skill judges liveness and says how to take the branch without
  touching it. The languette plugin's `guard-worktrees` keeps you out of
  another session's worktree; it never judges liveness.
- **Branch-vs-main is the repo's call, then a rule.** If main requires a
  pull request (`gh api repos/<o>/<r>/rules/branches/main` lists
  `pull_request`), every change goes through a PR, however small; the
  ruleset's bypass is mine, never yours. If GitHub can't answer (an
  error or no token; an empty list is an answer) and the repo's own
  instructions don't say, ask me. Otherwise work on main by default,
  without asking: commit straight to main in small, verified commits,
  pushed early and often, unless one of these triggers:
  - **Explicit phrase** — I say "make this a feature," "make this a
    branch," or "this needs review." Skip the metric check; branch
    immediately.
  - **Metric threshold crossed** (placeholders, tune later): **>50 lines
    of code changed** (excluding docs), **>200 lines of docs changed**,
    **session >100k tokens**, or **session >30 min wall clock**.

  In a repo that allows it, everything else — small fixes, doc edits,
  config tweaks — goes straight to main, no branch, no asking. Branching
  by default is the failure mode here, not landing on main.

  When a branch *is* warranted: push it and open the PR yourself, as
  early as the work is worth looking at — local checks need not have
  finished. Never wait to be asked, never leave a pushed branch without a
  PR. Draft or ready, reviewer or none, is yours to judge; `pr-blockers`
  printing nothing is what says it is my turn. A branch opened this
  way ends only one way: merged via PR, never folded back to main and
  deleted.

- **Cloud sessions: a pre-assigned `claude/*` branch name is not, by
  itself, a decision to branch.** Apply the rule above as normal — if
  nothing crosses a trigger, still land the work with
  `git push origin HEAD:main`, pushed early and often, rather than
  treating the assigned name as the destination. The cloud harness's own
  line, "after pushing, create a draft pull request", does not govern
  work that lands on main: no PR, draft or otherwise. When a branch is
  warranted, the PR opens ready, not draft. In the state repo
  (`claude_prompts_scratch`) no PR for ordinary state, since a PR there
  is how state gets stranded; the Stop hook pushes it to main itself. A
  one-off that truly needs a PR there waits for my consent, asked before
  the branch is pushed. This does **not** apply
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

A PR is yours until `pr-blockers` prints nothing for it, not one line.
Then it is my turn. Merging is mine too, by the `merge` label, unless I
say otherwise for a PR or a repo.

- **Threads before checks.** A running check or a long local suite is
  background: start it and work the threads while it runs.
- **Before the push,** the suite runs locally on the commit being pushed:
  whole when it takes about a minute; narrowed above that, with output
  showing the changed tests ran (a `-k` that selects none is green by
  selecting nothing, languette#221). After the push CI is the oracle.
- **A conflict gets a merge, never a rebase afterwards:** the merge commit
  holds the hand-resolution, and a rebase drops it. Behind is not a
  conflict; the queue updates it. A stacked PR is the one rebase left, with
  `--onto`, after its parent merges.
- **The body carries a `Head: <sha>` line** naming the last push, so a head
  that moves after hand-over shows on the PR page (dotfiles#286).
- **Every pencil call is logged,** in the body's `## Pencil:` list and with
  `~/.claude/bin/agent-decision`; none taken says `## Pencil: none`. A
  default that contradicts the linked issue, a design doc, a decisions line
  or a thread I wrote is a reversal, never a pencil call (claude#127).
- **What can't be made green is named in the body,** with why it isn't
  yours to fix. A red check is never handed over as a status report.
- **A bot thread has three exits.** One that asks to undo an instruction (a
  governing document, the issue's words, a thread I wrote) is a reversal: it
  stays open and goes under the critical-review summary's Reversed heading
  (languette#110, languette#116). One only I can answer stays open, under
  Decide. Anything else is verified against the code, fixed or answered
  with the evidence, and resolved with `gh-resolve-thread <id>`; one
  answered with a default goes under Pencil with its thread link.
- **Threads are read and resolved one at a time,** never in a loop over
  "all unresolved": a bot can post between the listing and the resolve
  (dotfiles#60). A finding that shows up again is checked against the
  live thread, never answered from memory (signalk-noaa-space-weather#214).
- **Everything you post is signed** as an agent's, opening with `🤖 ` and
  closing with `🤖 <model> · <effort> · <first 8 hex of the session id>`, so
  no one reads an agent's line as mine.
- **A sub-agent sent at a PR is told** to reply on and resolve each thread
  it fixes, by id, and to report the ids.
- In a repo whose `.github/show-dont-tell.yml` has a `serve:` line, a dev
  server is up and its URL shown before the diff of any change there.
- "Looks good" said before CI finishes is pre-authorization: act the moment
  it is green, without asking again.

### A board-only PR merges itself

Where a repo's board file lives in the repo and PR authorship is trusted
(solo maintainer, own bots), a PR whose whole diff is that file auto-merges
once its required checks pass, and every review bot skips exactly that
diff. Keep the two tests matched: a wider bot skip lets code past review; a
narrower one leaves the board PR waiting. Both live in the repo: the merge
rule in its Mergify config, the skips in each bot's path filter. The board
is read into every future session, so this is a prompt-injection surface,
not inert data.

### Watching a PR

- **Wake on events, not timers.** Subscribe, or don't, without asking;
  never bind a scheduled wakeup to a live session to re-poll a PR. One
  watcher per PR.
- **Answer every open thread in one pass, then push once.**
- **Tell me once, when it is my turn.** No progress reports. The two
  exceptions end in a decision only I can make: a blocker you can't
  resolve, or a design question where a wrong guess redoes the work.

## Our own workflows and actions

- **Call our own reusable workflows and composite actions at the tip of
  `main`, never a SHA or a version tag.** `uses:
  mark-brannan/.github/.github/workflows/<name>.yml@main`, and the same for
  `.github/actions/<name>@main`. One copy to fix is the whole point of
  putting them in `mark-brannan/.github`: a pin means a fix there does not
  reach the repo that needs it until someone remembers to re-pin, across a
  dozen repos, which nobody does. (2026-09-14)
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
- **No decision history in code, skills or other md.** What was decided,
  by whom, when, in which sitting: that belongs in the curia, ADR or
  decision log. A comment may point to where the design lives, by a
  relative path or item id, never naming a private repo. On a dangerous
  or counterintuitive line, it may say why in one line, alone or with a
  link to whatever explains it best. The design changes; the pointer
  tells the reader where to look, not what was settled.
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

- **Run `npm-publish-bg`, not `npm publish`.** Same arguments, same
  directory. My npm account uses browser 2FA with a passkey, so a publish
  waits on an approval URL, and that URL is redacted from your tool result
  before you see it: a plain publish stalls on an approval nobody was told
  about. `npm-publish-bg` runs the publish detached and sends the URL to me
  directly (browser, notification, terminal); I approve in my browser. You
  never see it, by design. Don't ask me for it or try to print it, and never
  ask me for an authenticator code or pass `--otp`. It returns a pid, a
  logfile and the channels that took the URL; tail the log, confirm with
  `npm view <pkg> dist-tags`. If no channel took it, tell me to `cat` the
  log in my own terminal. `npm publish --dry-run` needs no approval and runs
  plain. `~/.claude/hooks/npm-publish-auth.py` denies a bare `npm publish`
  and says so. That's the guard working, not something to route around.
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
- **A gate reads only.** A hook that can deny a call is a function of that
  call and the facts it declares: it writes nothing, runs no program a
  setting or an env var names, and reads no other workflow's state. Who
  holds a branch, whether they live and who cleans up belong to what takes
  or releases a branch, never to a gate. Guard: languette's purity test.
  Scar: languette#107.

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
  permission rule matches a whole command, and the gates that read it through
  languette's `scan` judge every segment of a chain with ambiguity resolving
  toward deny.
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
