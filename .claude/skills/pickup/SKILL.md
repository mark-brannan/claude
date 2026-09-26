---
name: pickup
description: Pick up a session where an earlier one left it, from the resume block that session wrote into its own checkpoint. Use when Solace says "resume", "pick up", "/pickup", "/pickup <branch>", "/pickup owner/repo#n" or a PR URL, "fix up this PR", "pick up where we left off", or opens a session meaning to continue work rather than choose new work. Not `/resume` — that name is claimed by Claude Code's own terminal-session resume.
---

# Pickup

Thin by design. `pickup-list` holds the parsing, the drop rules and the
table; this skill picks a row and starts.

A session opened this way starts **from the block, not from `worklist`**.
Don't run `worklist`, don't survey the project, don't re-derive what to do:
the previous session already decided, and re-deciding is the cost this exists
to avoid.

## 0. Which form was it

`/pickup owner/repo#n`, or a pull request URL, is a **PR fixup**: a branch
with more facts on it and a clearer finish line than a resume block has. Skip
§1 and §4 entirely — there is no block to pick and none to consume — and take
§2, §3, §6 in that order. Everything else is a resume block: §1.

## 1. Read the list

Run `~/.local/bin/pickup-list`.

- **A `Hard --` block above the table** — those are PRs a fixer already gave
  up on, and each carries the line saying why. With no argument, offer the top
  one before the newest block: a human is otherwise its next reader, which
  outranks a block a session can pick up any time. Solace picks; if she takes
  it, it is a PR fixup — §0.
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

For a PR fixup there is no block, so the three lines come from the PR:

```
Fixing up <owner/repo#n> — <its title>
<the PR URL>
Model: <model> · Effort: <effort>
```

The block's `model` and `effort` are the *previous* session's
recommendation for this work. If the running session is on something else,
say so in one line — never silently.

For a PR fixup there is no block, so read them off the PR instead: the
hand-off prompt in its description or its own last comment, if one named
them. If none did, that's the session's own call to make and state.

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

Then claim it on the card, so a session on *another machine* — which git
cannot see — knows too:

```
~/.claude/hooks/claim-stamp.sh claim -C . <this session id>
```

It prints nothing when the branch is free. When it prints a warning, another
session holds the branch right now: relay it to Solace in one line, naming the
session and how old the claim is, and don't push to the branch until you know
that session has let go. The SessionStart hook claims automatically for a
session that *opens* on the branch; a pickup checks the branch out afterwards,
so this is the one place the claim has to be asked for.

Everything the previous session wanted handed over is on the remote. If it
isn't pushed, it isn't handed over: work from the pushed state and say in one
line what you found missing.

One exception, and it is not a hand-off: when the checkpoint's `## Stop-commit`
section names a `wip/<session-id>` ref, the previous session ended with a dirty
tree and the Stop hook salvaged it to that ref rather than onto the branch
(dotfiles#285). It is a machine's snapshot of work nobody chose to publish, so
offer it, don't merge it:

```
git fetch origin wip/<session-id> && git diff <branch>..FETCH_HEAD
```

For a **PR fixup** the branch is the PR's head branch, and the same three
rules hold — your own worktree, fetch first, refuse a branch another worktree
holds:

```
gh pr checkout <n> --repo <owner/repo>     # or: git fetch origin && git checkout <head branch>
```

Then read the two briefs, and act on the one command they name. Nothing else
in this skill makes a branch decision, and neither do you:

```
pr-label-audit --pr <owner/repo#n>          # the GitHub side: verdict, threads, failing checks
branch_brief <repo root> <head branch>      # the local side: base, ahead/behind, conflicts, unsigned
```

`branch_brief` is a shell function in `~/.claude/hooks/lib-state.sh`, so
`. ~/.claude/hooks/lib-state.sh` first. Its last line is `recommend:` followed
by one command — rebase, merge, resign, or a refusal to guess. That line is
the base decision. Run it; do not second-guess it from the diff.

## 4. Mark it consumed

Do this **as you start**, not at the end: a session that dies mid-work
should not hand the same block to the next one as if nothing happened, and a
block still listed after two sessions took it is worse than none.

`pickup-list --files` prints `<branch><TAB><checkpoint path>`. In the chosen
branch's checkpoint, append one line inside the `## Resume` block:

```
- consumed: session <this session id, 8 chars> at <UTC timestamp>
```

`pickup-list` drops it from then on. The Stop hook carries the whole block,
consumed line included, into every later rewrite of that checkpoint, so it
stays as a record of who took it.

## 5. Then work

Nothing else belongs to this skill. Blocks are dropped on their own when the
branch goes level with the default branch or its PR merges, so there is no
tidying to do.

## 6. The fixup contract

One text, two runners: this section is what a session works a PR to, and it
is the same text `grind --prs` hands its headless workers. Lift it verbatim;
do not paraphrase it into a second version that can drift from this one.

1. **Threads first.** Address every unresolved review thread, reply on it,
   resolve it. Before the checks, always: a session watching CI with an
   unanswered comment on the PR is spending the only resource that matters on
   the lowest-priority thing there is.

2. **Base second.** Run the one command `branch_brief` printed on its
   `recommend:` line. Rebase when the branch is clean; merge when it
   conflicts — and once you have merged, never linearize the branch
   afterwards. A merge commit carries the hand-resolution in its tree and a
   later rebase throws it away.

3. **CI third.** Fix what is red. A failure that originates in another
   repository — a reusable workflow, a dependency this PR does not own — is
   hard, not yours: it goes to the stop rule in 6.

4. **Commits sign themselves on this machine.** Never
   `-c commit.gpgsign=false`, never `git commit-tree`. If
   `no-unsigned-push.sh` denies the push, it prints the line that fixes it —
   run that line. An unsigned commit fails the gate, so a shortcut here buys
   nothing and costs the branch.

5. **Push with `--force-with-lease`,** never a bare `--force`, from your own
   checkout — unless the branch carries mergify-cli `Change-Id` trailers, in
   which case its pre-push hook blocks any push from that checkout whatever
   ref is being pushed. There, push from a detached throwaway worktree
   instead, per `code.md`'s PR-ownership section: `git worktree add --detach
   <tmp> <sha>`, push `--force-with-lease` from there, then remove it. A
   refused lease is not an obstacle to retry past either way: it means
   someone else pushed to this branch while you worked. Stop, and say whose
   push you found.

6. **Finish is `awaiting-human` back on the PR** — and Mergify puts it there,
   computed from a green `ci-gate / gate` and no unresolved thread. The
   session never applies that label and never merges the PR.

   After **one honest attempt**, or about **$1 of spend**, stop instead:
   label the PR `fixup-hard`, leave exactly one comment saying what was
   tried, why it is hard and what it cost, and end. That comment is the
   entire handover — a human, or a bigger session, reads it and nothing
   else. Giving up loudly and cheaply is the wanted outcome, not a failure.

## Writing a block

The other half, for a session that is *leaving* work: write the block into
**your own** checkpoint — `state/global/log/auto/<date>-<repo>-<id>.md` — at
`/wrapup` step 2b (every wrap-up that hands anything off), when the Stop nag
blocks once, or when Solace says "update resume". The nag is a backstop, not
the trigger: it arms on a context, clock or friction crossing, and a session
that ends cleanly never sees it. Four lines,
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
status — "add the fixture for a consumed block", never "pickup-list is
half done". No state adjectives: the link carries state, live, at the other
end.

This is not a wrap-up. A block costs four lines; `/wrapup` costs a log, a
sweep and a prompt, and is for a session holding something no issue, PR or
card carries. If the checkpoint's verdict line says `archivable`, a block is
usually all that is wanted, and often not even that.
