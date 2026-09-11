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

## 3. Take your own worktree

The block hands over a branch, an issue and a PR. It does **not** hand over a
directory, and the previous session's worktree is not yours to work in even
when it is sitting right there with the branch already checked out —
`no-foreign-worktree.sh` refuses it, and the reason it refuses is that the
owning session may still be running and may be archived out from under you
mid-turn (PR #162).

So fork one: `EnterWorktree(name=<short-name>)`, then inside it

```
git fetch origin
git checkout <the branch the block names>
```

If git refuses because the branch is checked out in another worktree, that is
a live claim by a session that has not released it. Say so — name the branch
and the worktree git named — and stop. Don't take it away from them, and
don't work anywhere else on the same branch.

Everything the previous session wanted handed over is on the remote. If it
isn't pushed, it isn't handed over: work from the pushed state and say in one
line what you found missing.

## 4. Mark it consumed

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

## 5. Then work

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

Push before you write it — the block points at a branch, and a branch that
only exists in your worktree hands over nothing. A session that is *finished*
(pushed, PR open) also releases its worktree, so the branch is free for
whoever picks it up; one that is pausing mid-work keeps it, and the branch
stays claimed until it comes back.

One block per checkpoint; the newest replaces. `next` is a step, not a
status — "add the fixture for a consumed block", never "resume-list is
half done". No state adjectives: the link carries state, live, at the other
end.

This is not a wrap-up. A block costs four lines; `/wrapup` costs a log, a
sweep and a prompt, and is for a session holding something no issue, PR or
card carries. If the checkpoint's verdict line says `archivable`, a block is
usually all that is wanted, and often not even that.
