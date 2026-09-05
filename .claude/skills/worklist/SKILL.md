---
name: worklist
description: Report a project's overall status and the next unblocked work items, in one standard format, to help decide what to kick off in a new session, a subagent, or a stream. Use when Mark asks "what's next", "what can we work on", "project status", "what's on the roadmap", or "/worklist".
---

# Worklist: status + next work

Read-only. This skill never files issues, ticks boxes, or starts work — it
answers "what's the state of things and what could a session pick up right
now," then stops and lets Mark choose.

## Which project, and which repos it spans

If Mark named a project, use it. If not, ask — one question, not a guess —
unless the current repo makes it obvious.

A project is usually **not** one repo. Resolve its full repo set before
reading anything else:

1. Check the epic file first (see below) — it typically states its scope up
   front ("Spans colregs (data), colregs-engine (evaluator), searoom
   (simulator/demo)..."). That line is the repo list.
2. If there's no epic, or it doesn't name repos, check that project's own
   `kanban.md` for repo links, and check whether a GitHub org/user search
   (`gh repo list <owner> --limit 100 | grep -i <project>`) turns up
   siblings — a data repo, an engine/library repo, a demo/app repo are the
   common split.
3. If still unclear, ask which repos count rather than guessing and missing
   one — a worklist that silently skips a repo is worse than a slower start.

Once resolved, treat every repo in the set as in scope for every step below.
Name the repo alongside every item in the output — never let a multi-repo
project's report read as if it were about one repo.

## Where to look, in order

Read narrowly and iteratively. Don't `cat` whole repos; grep for the
project name, read the specific file a hit points to, stop once the picture
is clear. If the sweep would take more than a few targeted reads — likely
once there are 3+ repos — delegate it to an Explore agent (or one agent per
repo, run concurrently) and take its summary rather than reading everything
yourself.

1. **Each repo's own `kanban.md`** (repo root, or wherever its own
   CLAUDE.md says) — small loose cards, not epic-level plans. Check every
   repo in the set; don't stop at the first one that has a board.
2. **The global board** — `~/claude_prompts_scratch/state/global/kanban.md`
   — for cards that fell out of sessions but belong to no project board.
   Match on any repo in the set, not just the project's name as a string.
3. **Epic files** — `~/claude_prompts_scratch/state/global/epics/*.md` —
   grep for the project name or any repo in its set. An epic holds phases,
   sessions, dependencies, and a `## Status` log; that log is the source
   for the status summary, not your own inference from ticked boxes.
4. **Public tracking issues** — if the epic names one (e.g. "public:
   `<repo>#N`"), treat it as authoritative for phase *definitions* when the
   epic says so; the epic file stays authoritative for session-level
   sequencing and model/effort sizing.
5. **Open GitHub issues in every repo in the set** —
   `gh issue list --repo <owner>/<repo> --state open --json number,title`,
   one call per repo. These are real, independently-startable work whether
   or not they're on any board yet. A dependency can cross repos (an engine
   phase waiting on a data-repo issue) — say so explicitly when it does.

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
_as of <date> · repos: <owner/repo1>, <owner/repo2>, ... + global board_

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
