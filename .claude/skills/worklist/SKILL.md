---
name: worklist
description: Report a project's overall status and the next unblocked work items, in one standard format, to help decide what to kick off in a new session, a subagent, or a stream. Use when Mark asks "what's next", "what can we work on", "project status", "what's on the roadmap", or "/worklist".
---

# Worklist: status + next work

Read-only. This skill never files issues, ticks boxes, or starts work — it
answers "what's the state of things and what could a session pick up right
now," then stops and lets Mark choose.

## Which project

If Mark named one, use it. If not, ask — one question, not a guess — unless
the current repo makes it obvious.

## Where to look, in order

Read narrowly and iteratively. Don't `cat` whole repos; grep for the
project name, read the specific file a hit points to, stop once the picture
is clear. If the sweep would take more than a few targeted reads, delegate
it to an Explore agent and take its summary rather than reading everything
yourself.

1. **The project's own `kanban.md`** (repo root, or wherever its own
   CLAUDE.md says) — small loose cards, not epic-level plans.
2. **The global board** — `~/claude_prompts_scratch/state/global/kanban.md`
   — for cards that fell out of sessions but belong to no project board.
3. **Epic files** — `~/claude_prompts_scratch/state/global/epics/*.md` —
   grep for the project name. An epic holds phases, sessions, dependencies,
   and a `## Status` log; that log is the source for the status summary,
   not your own inference from ticked boxes.
4. **Public tracking issues** — if the epic names one (e.g. "public:
   `<repo>#N`"), treat it as authoritative for phase *definitions* when the
   epic says so; the epic file stays authoritative for session-level
   sequencing and model/effort sizing.
5. **Open GitHub issues** in every repo the project spans —
   `gh issue list --repo <owner>/<repo> --state open --json number,title`.
   These are real, independently-startable work whether or not they're on
   any board yet.

## Computing "unblocked"

An item is ready now only if every dependency it names (`Depends:`, a
blocking card, a prerequisite issue) is already done. Say what it depends
on even when satisfied — don't just drop the dependency silently. Personal/
learning items with no repo output are their own category: never blocking,
never blocked by the rest.

## Output format

Always this shape, always cite a source (file, line, or issue link) for
every claim — never assert a status you haven't just read.

```
# <Project> — status & next work
_as of <date>_

## Status
<1-3 lines from the epic's own Status log or board, with source>

## Ready now (unblocked)
- **<item>** — <repo/file it touches> — <recommended model, effort> —
  <one line why it's ready> (<source link>)

## Blocked
- <item> — blocked on <dependency> (<source link>)

## Personal / learning (parallel, non-blocking)
- <item> (<source link>)

## Needs Mark's decision first
- <item> — <the one-line question> (<source link>)
```

Skip a section entirely rather than writing "none."

## After reporting

Stop. Don't recommend a single item unless asked — the point of this skill
is to hand over the ranked list so Mark can pick what fits the moment
(one session, a subagent, or a stream of several). If asked which one you'd
start, give one sentence naming it before any explanation, per standing
orders.
