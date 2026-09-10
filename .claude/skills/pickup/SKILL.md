---
name: pickup
description: Pick up a session where an earlier one left it, from the resume block that session wrote into its own checkpoint. Use when Solace says "resume", "pick up", "/pickup", "/pickup <branch>", "pick up where we left off", or opens a session meaning to continue work rather than choose new work. Not `/resume` — that name is claimed by Claude Code's own terminal-session resume.
---

# Pickup

Thin by design. `resume-list` holds the parsing, the drop rules and the
table; this skill picks a row and starts.

A session opened this way starts **from the block, not from `worklist`**.
Don't run `worklist`, don't survey the project, don't re-derive what to do:
the previous session already decided, and re-deciding is the cost this exists
to avoid.

## 1. Read the list

Run `~/.local/bin/resume-list`.

- **No rows** — say so in one line and stop. There is nothing to resume;
  `worklist` is the tool for choosing new work, and Solace will ask for it.
- **One row** — take it.
- **Several** — if Solace named a branch (`/pickup <branch>`), take that row.
  Otherwise print the table and ask for a one-line pick. That is the one
  question this skill is allowed to ask.

## 2. Restate it, in three lines

Before touching anything, three lines and no more:

```
Resuming <branch> (<repo>) — <the block's next step, verbatim>
<the link the block names>
Model: <model> · Effort: <effort>
```

The block's `model` and `effort` are the *previous* session's
recommendation for this work. If the running session is on something else,
say so in one line — never silently.

Then read the link — the PR, issue or card — for live state. The block
names where the work is; it does not carry its state, which is stale the
moment it is written.

## 3. Mark it consumed

Do this **as you start**, not at the end: a session that dies mid-work
should not hand the same block to the next one as if nothing happened, and a
block still listed after two sessions took it is worse than none.

`resume-list --files` prints `<branch><TAB><checkpoint path>`. In the chosen
branch's checkpoint, append one line inside the `## Resume` block:

```
- consumed: session <this session id, 8 chars> at <UTC timestamp>
```

`resume-list` drops it from then on. The Stop hook carries the whole block,
consumed line included, into every later rewrite of that checkpoint, so it
stays as a record of who took it.

## 4. Then work

Nothing else belongs to this skill. Blocks are dropped on their own when the
branch goes level with the default branch or its PR merges, so there is no
tidying to do.

## Writing a block

The other half, for a session that is *leaving* work: write the block into
**your own** checkpoint — `state/global/log/auto/<date>-<repo>-<id>.md` — when
the Stop nag blocks once, or when Solace says "update resume". Four lines,
house hand-off spec, under a `## Resume` heading:

```
## Resume

- next: <one sentence, imperative, what the next session does first>
- link: <the branch, PR, issue or card it acts on>
- model: <opus | sonnet | haiku>
- effort: <low | medium | high>
```

One block per checkpoint; the newest replaces. `next` is a step, not a
status — "add the fixture for a consumed block", never "resume-list is
half done". No state adjectives: the link carries state, live, at the other
end.

This is not a wrap-up. A block costs four lines; `/wrapup` costs a log, a
sweep and a prompt, and is for a session holding something no issue, PR or
card carries. If the checkpoint's verdict line says `archivable`, a block is
usually all that is wanted, and often not even that.
