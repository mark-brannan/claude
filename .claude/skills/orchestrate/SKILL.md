---
name: orchestrate
description: Work a repo's open issues as the PM — triage and cluster them, dispatch one worker agent per issue in its own worktree, watch each worker's context and stop it before it runs dry, and keep five to ten PRs awaiting Solace's look, refilling as they drain. Use on "/orchestrate", "prioritise the issues and sequence the work", "be the orchestrator / PM / taskmaster", "work the backlog with sub-agents". Not for one PR (/critical-review, /pickup) and not headless (grind). Fable or Opus; workers Sonnet, Opus for an issue rated hard.
---

# Orchestrate

The judgment half of working a backlog. `grind` is the zero-token half:
one headless worker per Ready item, spend measured exactly. It cannot rate
an issue's difficulty, notice that two issues edit the same function, or
fold a capped worker's leftover into a new dispatch. This skill does those
things and keeps the mechanics — worktrees, the spend watch, the worker
contract — as fixed as it can.

Source: the 2026-09-22 session, logged as `2026-09-22-dotfiles-orchestration.md`
in the state repo: 22 workers, 22 PRs, one hour. Every number below was
measured there.

## 1. Facts before judgment

Gather with one Sonnet subagent, not your own reads — the 2026-09-22
orchestrator had spent 105k of context before its first dispatch. Ask for a
table, one row per open issue: number, labels, the files the body names,
any open PR or branch already carrying it, what it says blocks it. Plus
the open PRs and their state (conflicting, red, awaiting-human) and the
branches other sessions hold (`claim-stamp.sh read`, the worktree list).

Then rule on each row yourself:

- **Skip, with the proof:** an open PR carries it; it is closed or ruled
  elsewhere; it is an epic with no acceptance criteria (its concrete
  sub-items dispatch, the epic does not).
- **`blocked` is checked, not trusted.** Most mean "after issue N" — an
  order inside a cluster, not a skip. Nothing from this pass goes to
  `## Needs ruling` (Solace, 2026-09-22: "nothing should need my ruling
  right now"); a genuine one becomes a card after wave 1 is out.
- **A red or conflicting open PR gets a fixer** unless a live claim stamp
  (`claim-stamp.sh read`, stale after 2h) or a human's review thread shows
  a session already on it. Labels are not the signal: `awaiting-human` is
  computed by Mergify and says "done", `fixup-hard` is session-applied and
  says nothing about who is there. A fixer finding no thread and a current
  base stops at no cost, so a second fixer on the same PR is harmless; two
  at once is what the stamp and `--force-with-lease` catch. Solace ruled
  so, 2026-09-22. Green PRs are the review sessions'.
- **Rate each issue for an agent** — low / medium / high, the triage
  convention. Low and medium go to Sonnet, high to Opus.

## 2. Sequence

- **Cluster by file.** Issues that edit the same script run in series
  inside one cluster; clusters run in parallel, five to ten workers in
  flight.
- **One issue per worker.** Two-issue workers capped out after the first
  issue almost every time. The second issue is its own dispatch, stacked on
  the first's PR when it depends on it.
- **Stack only on a real dependency**, per `CLAUDE.md`: the worker branches
  from the base PR's head and writes `Depends-On: #<n>` in its body.
- **Order by value** — what it unblocks, what is broken now, what Solace
  has asked for — and let the file constraint only reorder within that.
  The tail of the queue never runs: Solace stopped new dispatch after an
  hour and every deferred item was a hard one.

Show the plan as one table (cluster, issues in order, model) with the skip
list and its proofs; ask only what gates wave 1, which is usually nothing;
launch in the same turn. Write the plan to the state repo first —
`log/YYYY-MM-DD-<repo>-orchestration.md`: skipped and why, queue, then
progress and spend appended as they happen. Compaction will come; the log
is what survives it.

## 3. The worker contract

One text. A dispatch is the task — issue number, files, what it depends on,
which PR head to branch from if stacked — followed by this block verbatim.

```
## Ground rules (from the orchestrating session)

You are a worker agent in <owner/repo>, in your own git worktree under
`.claude/worktrees/agent-*`. Work only there.

- Branch from origin/main as `claude/issue-<n>-<slug>`. One issue, one
  branch, one PR. A stacked task names the PR head to branch from and
  needs `Depends-On: #<n>` in the PR body.
- Never touch the main checkout, $HOME, or any other worktree or branch.
  If git says a branch is checked out elsewhere, report it and stop.
- Stage by path, never `git add -A`. Commits end with the Co-Authored-By
  line the session reminder gives.
- Before the PR: the fast local checks for what you touched (the test file
  beside a hook, `sh -n`, shellcheck where CI runs it), then rebase on
  origin/main; merge instead if the rebase conflicts. Push the way the
  repo's pre-push hook requires.
- Open the PR: `area: what changed` title, `Closes #<n>`, what and why,
  how verified, the Claude Code attribution line. Then `git checkout
  --detach`, so the branch is free for the next session, and stop. Do not
  wait for CI, watch checks, poll for reviews or label the PR. A later
  session does that with a fresh context.
- Budget: 110k of context, hard. Past ~95k with no PR open: commit by path
  and push what you have, leave a checkpoint comment on the issue (branch,
  commit, done, left), run `git checkout --detach`, and stop. The
  orchestrator dispatches a fresh worker to resume from that branch.
- Scope: the issue as written. File no cards or issues; anything off-scope
  or needing a human's judgment goes in your final report.
- Final report, under 200 words: PR URL, branch, what changed, checks run
  and their result, anything undone, anything a human must decide.
```

Worker findings are yours to route. The 2026-09-22 workers surfaced three
new issues and two already-done ones; the orchestrator filed and closed
them with the proof, per `/card-write`.

## 4. Watch the spend

A worker starts at ~45k context from the system prompt and the repo's
standing orders, so "100k" is 55k of work. Finished workers ran 59k–147k.
One `Monitor` over the sub-agent transcripts, each threshold crossed once
per worker; an issue rated hard on Opus gets every row +40k, which the
script applies from the `HARD` list, so keep that list current as you
dispatch.

| context | action |
|---|---|
| 95k | nudge: open the PR now, start nothing new, report, stop |
| 110k | hard cap: commit by path, push, PR or checkpoint comment, report, stop |
| 140k | `TaskStop`; open the PR from the pushed branch yourself |

```sh
D=<project dir>/<session-id>/subagents; seen=""
HARD="agent-<id> agent-<id>"   # workers on an issue rated hard: +40k per row
while true; do
  for f in "$D"/agent-*.jsonl; do
    [ -f "$f" ] || continue; n=$(basename "$f" .jsonl)
    case " $HARD " in *" $n "*) off=40000;; *) off=0;; esac
    p=$(jq -rs '[.[] | select(.type=="assistant") | .message.usage
        | (.input_tokens//0)+(.cache_read_input_tokens//0)+(.cache_creation_input_tokens//0)]
        | max // 0' "$f")
    for base in 95000 110000 140000; do
      t=$((base + off))
      [ "$p" -ge "$t" ] && ! echo "$seen" | grep -qF "$n:$base" \
        && { seen="$seen $n:$base"; echo "SPEND $n context_peak=$p crossed $t"; }
    done
  done; sleep 60
done
```

A nudge is one `SendMessage`, imperative, naming the number and the issue.

## 5. The loop

What is capped is not workers but **PRs awaiting Solace's look**: every PR
this session opened or fixed that is still open and unclaimed — no thread
from Solace, no other session's claim stamp on its branch. Merged, closed
or claimed drops it off the list. (Solace, 2026-09-22.)

- **Band: five to ten.** Below five, dispatch to refill, five to ten
  workers in flight across clusters. At ten, stop dispatching; running
  workers finish and report. Solace reviews in batches of that size.
- **The list is complete, never a delta.** Post it when the count first
  reaches five and again each time it changes while in band: PR, issue,
  one line of what, and a `look` column — `quick`, or `critical` with the
  reason from the worker's report (a part left undone, something a human
  must decide, a wide diff). About one PR in three is `critical`. Name the
  stacks and their merge order.
- **Refill when it drains.** At the cap with nothing running, watch the
  listed PRs (one `Monitor`, a `gh` recount every few minutes) and resume
  dispatch when the count drops below five — while the session cap holds
  and the queue still has an item whose files no open PR of this session
  touches.
- **The session cap** is a row in the plan table before wave 1: default
  20 workers, about $60 at the measured $0.80–$4.90 each; Solace changes
  it with a word. "No new work" from Solace means drain: running workers
  finish and report, nothing new launches.
- **A checkpoint is not a finish.** A worker that stopped with no PR (its
  own budget, the 110k cap, or a `TaskStop`) leaves its issue in the queue
  with the pushed branch named; the next dispatch for it says to resume
  from that branch, not from `origin/main`.
- **You hold no branch and edit no PR.** The one PR action that is yours
  is opening one from a stopped worker's pushed branch (`gh pr create
  --head`, no checkout). Keep your own reads small; act on reports and on
  the recount.
- **A worker's `gh pr view` can land in your session's pr-threads record**
  (the #224 shape). A Stop gate naming a PR you never worked is that:
  clear the read from the record, not the PR.

## 6. Ending

Nothing running, no branch held, every worker worktree detached. The last
message: the full ready list with stacks bottom-up; issues with no PR and
why; closed-as-done and filed, by number; the spend range. Then the
hand-off, then offer the break, once.

```
/pickup the <repo> review backlog. <n> PRs are open from the <date>
orchestration session; list, stacks and deferrals are in
claude_prompts_scratch state/global/log/<date>-<repo>-orchestration.md.
Work them oldest-first: threads, rebase, checks, hand over. Skip any PR
Solace has a thread on. Model: sonnet. Effort: medium.
```
