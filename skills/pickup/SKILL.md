---
name: pickup
description: "Pick up a session where an earlier one left it, from the pickup item the Stop hook wrote for that session. Use when the user says \"resume\", \"pick up\", \"/pickup\", \"/pickup\" with a branch, owner/repo#n or PR URL, \"fix up this PR\", \"pick up where we left off\", or opens a session meaning to continue work rather than choose new work. Not `/resume` — that name is claimed by Claude Code's own terminal-session resume."
argument-hint: "[<branch> | owner/repo#n | PR URL]"
---

# Pickup

Thin by design. `pickup-list` holds the parsing and the listing; this
skill picks an item and starts. The Stop hook writes one pickup item per
session under the state repo's `state/global/pickup/` — machine facts
above the `---`, the hand-off body below it — so even a session that died
mid-work left one.

A session opened this way starts **from the item, not from `worklist`**.
Don't run `worklist`, don't survey the project, don't re-derive what to do:
the previous session already decided, and re-deciding is the cost this exists
to avoid. That trusts the plan, not every option on the card: one that crosses
a ruling or a guard is fixed, not relayed — the standing orders'
already-ruled check.

## 0. Which form was it

`/pickup owner/repo#n`, or a pull request URL, is a **PR fixup**: a branch
with more facts on it and a clearer finish line than a pickup item has. Skip
§1 and §4 entirely — there is no item to pick and none to take — and go to
§2, §3, §6 in that order. Everything else is a pickup item: §1.

## 1. Read the list

Run `~/.claude/bin/pickup-list`.

- **A `Hard --` block above the list** — those are PRs a fixer already gave
  up on, and each carries the line saying why. With no argument, offer the top
  one before the newest item: a human is otherwise its next reader, which
  outranks an item a session can pick up any time. The user picks; if they take
  it, it is a PR fixup — §0.
- **`Pickup: BROKEN STORE -- <cause>`** (exit 1) — the store could not be
  read, so the list may be short. Say so with the cause before anything
  else; never report it as "no items".
- **No items** — say so in one line and stop. There is nothing to resume;
  `worklist` is the tool for choosing new work, and the user will ask for it.
- **One item** — take it.
- **Several** — if the user named a branch or an id, take that item; read the
  candidates with `pickup-list show <id>` (the `branch:` field carries the
  branch). Otherwise print the list and ask for a one-line pick. That is the
  one question this skill is allowed to ask.

A `◆` line is a card from the board's `## Claude's`, not a session's item: its
id is its `id:` field (its link, on a card from before ids), it has no branch,
and the card text is the whole hand-off. A hand-off that says `card <id>` names
one: `pickup-list show <id>` prints it, `pickup-list take <id>` claims it.
Skip §3's checkout; the link is where the work starts.

A batch parent, filed by `/scoping`, carries `driver=` in its log: its brief
is the driver's whole prompt, and the session that takes it is the driver.
`work-item show <id>` prints the log. On `driver=workflow`, run the batch
with the Workflow tool; scoping logs that by default, `subagents` only when
the user typed `--subagents`. On `driver=subagents`, or a
parent filed before the fact existed, run it with sub-agents. A worker's
first command is `~/.claude/bin/worker-start`, alone in its Bash call (flags
in its header): where a chain of fetch, branch and log asks, it is allow-listed.

**The driver dispatches; it does not do the work.** It holds the plan and one
line per child, and never reads a diff, a CI log or a review thread body into
its own context: a worker does that and returns one line. Context re-read on
every turn is most of a session's cost, and a driver that pulls PR content in
grows fastest.

- **Picking a worker's model, unseen.** It reads metadata, never content:
  the child card's model and effort (scoping set them), and the numbers CI
  already posts on the PR. One call returns each headline (the complexity,
  coverage and maxims-check comments; a repo with no coverage job has none):
  `gh api repos/<o>/<r>/issues/<n>/comments --paginate --jq '.[]|select(.body|test("complexity-report|### Coverage:|check:maxims-check"))|.body as $b|$b|split("\n")|map(select(test("^### |breaks, ") or (($b|test("check:maxims-check")) and test("^- ")))|sub("^- (?<m>[^,]+),.*";"\(.m)"))|join(" | ")'`
  (the maxims headline ends with each undeclared break's maxim, name only),
  plus `gh pr view <n> --json changedFiles,reviewDecision,statusCheckRollup`
  for files and failing check names. Read: complexity delta (`+N across M
  functions`), coverage of changed lines and the total's move, which maxims
  have undeclared breaks, failing checks. The card's model stands; a fixer
  goes up one tier (Sonnet to Opus) on any of (guesses, not measured):
  complexity +20 or more, changed-line coverage under 60% or total down over
  2 points, an undeclared fail-fast, Chesterton's fence, SOLID or SoC break,
  3 or more failing checks. Other maxims never escalate alone: they are
  flagged too often to tell PRs apart. No signal posted, or a verdict
  these cannot settle: a Haiku sub-agent returns a one-line triage.
- **Every worker gets its model by name.** On `driver=workflow`, each
  `agent()` call sets `model` explicitly, never the default; on
  `driver=subagents`, each spawn does.
- **Relay at about 100k context.** The context line the session hook adds
  at the first rung is the signal. The driver writes the plan state to the
  parent's log with `work-item log` (children and their PRs, rounds spent,
  what is parked, the next step), then runs
  `~/.claude/bin/driver-start --relay <parent-id>`, which releases the
  parent, starts a successor and logs its session; the old driver then ends.
  Only the session holding the parent can relay; it keeps the batch's name.
  The successor reads the parent card and its log and nothing else.

## 2. Restate it, in three lines

Before touching anything, three lines and no more:

```
Resuming <branch> (<repo>) — <the body's next step, verbatim>
<the link the body names, or the item's `pr:` / `where:`>
Model: <model> · Effort: <effort>
```

For a PR fixup there is no item, so the three lines come from the PR:

```
Fixing up <owner/repo#n> — <its title>
<the PR URL>
Model: <model> · Effort: <effort>
```

The body's `model` and `effort` lines are the *previous* session's
recommendation (a PR fixup reads them off the PR's hand-off prompt); with
none, the choice is this session's own to state. If the running session is
on something else, say so in one line — never silently.

Then read the link — the PR, issue or card — for live state. The item
names where the work is (`pr:`, `where:`, the body's link); it does not
carry its state, which is stale the moment it is written.

## 3. Take your own worktree

The item hands over a branch, an issue and a PR. It does **not** hand over a
directory, and the previous session's worktree is not yours to work in even
when it is sitting right there with the branch already checked out —
the languette plugin's `guard-worktrees` refuses it, and the reason it refuses
is that the owning session may still be running and may be archived out from under you
mid-turn (PR #162).

Fork one: `EnterWorktree(name=<short-name>)`, then inside it

```
~/.claude/bin/worker-start --head <the branch the item names>
```

If it stops on `a branch named <b> already exists`, run
`git worktree list | grep '\[<b>\]'`. A line names the holder, and the check
below applies. No line means a stale local branch:
`git checkout <b> && git merge --ff-only origin/<b>`.

If git refuses because the branch is checked out in another worktree:
read [held-branch.md](held-branch.md) before anything else. It checks
whether the holder is live, dead, parked or waiting, and says how to
take the branch without entering its worktree.

Then claim it on the card, so a session on *another machine* — which git
cannot see — knows:

```
~/.claude/hooks/claim-stamp.py claim -C . <this session id>
```

It prints nothing when the branch is free. A warning means another session
holds the branch right now: relay it in one line, naming the session and the
claim's age, and push nothing until it has let go. The SessionStart hook claims
for a session that *opens* on the branch; a pickup checks out afterwards, so
this is the one place the claim is asked for.

Everything handed over is on the remote. What isn't pushed isn't handed over:
work from the pushed state and say in one line what is missing.

One exception, and it is not a hand-off: when the checkpoint the item's
`where:` names has a `## Stop-commit`
section naming a `wip/<session-id>` ref, the previous session ended with a dirty
tree and the Stop hook salvaged it to that ref rather than onto the branch
(dotfiles#285). It is a machine's snapshot of work nobody chose to publish, so
offer it, don't merge it:

```
git fetch origin wip/<session-id> && git diff <branch>..FETCH_HEAD
```

For a **PR fixup** the branch is the PR's head branch, and the same three
rules hold — your own worktree, fetch first, no push to a branch a live
worktree holds:

```
gh pr checkout <n> --repo <owner/repo>     # or: git fetch origin && git checkout <head branch>
```

Then read the three briefs. `pr-blockers` comes first, and its lines are the
work list in its order: open conversations, then conflicts, then the rest.
Act on the one branch command the others name. Nothing else in this skill
makes a branch decision, and neither do you:

```
~/.claude/bin/pr-blockers <owner/repo#n>    # what keeps it from merging, threads first
pr-label-audit --pr <owner/repo#n>          # the GitHub side: verdict, threads, failing checks
python3 ~/.claude/lib/state.py branch_brief <repo root> <head branch>   # the local side: base, ahead/behind, conflicts, unsigned
```

`branch_brief`'s last line is `recommend:` followed
by one command — rebase, merge, resign, or a refusal to guess. That line is
the base decision. Run it; do not second-guess it from the diff.

## 4. Take it

Do this **as you start**, not at the end: a session that dies mid-work
should not hand the same item to the next one as if nothing happened, and an
item still listed open after two sessions took it is worse than none.

```
~/.claude/bin/pickup-list take <id>
```

`pickup-list` drops it from the default view from then on; the file keeps
the record (`--closed` shows it). On a card, `take` is a claim through
`claim-stamp.py`, keyed by the link: a second session reads it taken, and a
refusal names the session that holds it. Relay that and pick again.

## 5. Then work

Nothing else belongs to this skill. An item leaves the view when a session
takes it or marks it `done`; nothing is dropped for being uncheckable, so a
reader who wants live state follows `pr:` or `where:`.

## 6. The fixup contract

One text, two runners: this section is what a session works a PR to, and it
is the same text `grind --prs` hands its headless workers. Lift it verbatim;
do not paraphrase it into a second version that can drift from this one.

1. **Threads first.** Run `~/.claude/bin/pr-blockers --leave-easy <PR>`; its
   lines are the work list, in its order. Address every unresolved review
   thread, reply on it, resolve it; a `fixer's:` line is the CI fixer's, left
   to it under the PR-ownership rules in `rules/code.md`. Before the checks, always: a session watching CI with an
   unanswered comment on the PR is spending the only resource that matters on
   the lowest-priority thing there is.
   Each round first reads the maxims-check and arete-check summaries that
   github-actions[bot] posts on the PR, and the full reports they link in
   the state repo when those are readable, as inputs to the revision before
   any code changes: a KISS break suggests `/simplify` on the item, a DRY
   break suggests lifting the repeated literals, and arete's recommendation
   can mean the PR body or the change's justification needs rework, not a
   line fix.

2. **Base second.** Only a conflict needs a hand. A branch that is merely
   behind its base is left as is: the queue brings it up to date when it
   merges. When it conflicts, merge the base in, resolve, and never
   linearize the branch afterwards. A merge commit carries the
   hand-resolution in its tree and a later rebase throws it away.

3. **CI third.** Fix what is red. A failure that originates in another
   repository — a reusable workflow, a dependency this PR does not own — is
   hard, not yours: it goes to the stop rule in 6.

4. **Commits sign themselves on this machine.** Never
   `-c commit.gpgsign=false`, never `git commit-tree`. If
   `no-unsigned-push.py` denies the push, it prints the line that fixes it —
   run that line. An unsigned commit fails the gate, so a shortcut here buys
   nothing and costs the branch.

5. **Push with `--force-with-lease`,** never a bare `--force`, from your own
   checkout. The branch tracks its own remote branch, never main. Never `--no-verify`.
   A refused lease is not an obstacle to retry past: it means
   someone else pushed to this branch while you worked. Stop, and say whose
   push you found.

6. **Finish is `pr-blockers` printing nothing for the PR.** Run it again
   after the last push, once the review bots have had their pass: a bot
   thread lands minutes after the push that caused it. The report opens
   with what it prints, conversations first. The session never merges the
   PR.
   One exception: a driver session whose parent card's log carries
   `lane=autonomous` adds `merge`, `churn-ok` and `mixed-loops-ok`
   itself, where the diff stays inside the parent's driver brief, once
   the final reviews are clean, and names that brief by the parent's id
   in the PR body, except where the repo's own instructions forbid naming
   cards: there the reference goes on the card's log only. A refused label
   is retried once, with the clean review named, then the driver carries on
   and never hands the label to the user. The review is the CI bot's; the
   driver has a worker work its threads and starts no reviewer of its own, and a head
   the bot never reviewed is not clean: the labels wait. A diff outside
   the brief gets none of the three and waits
   for the user. A gated child, or a parent logging `lane=gated`, keeps
   the user's merge, and every other session keeps the rule above.

   After **one honest attempt**, or about **$1 of spend**, stop instead:
   label the PR `fixup-hard`, leave exactly one comment saying what was
   tried, why it is hard and what it cost, and end. That comment is the
   entire handover — a human, or a bigger session, reads it and nothing
   else. Giving up loudly and cheaply is the wanted outcome, not a failure.

## Writing the hand-off

A session *leaving* work (the user's `/handoff`, the Stop nag, "update
the hand-off"): read [handoff.md](handoff.md) before writing it.
