---
name: reconcile
description: Check the board and its memos against GitHub reality — a card on a merged/closed PR, a memo silent about being overtaken, a "Pending:" tail nobody resolved — and correct the record. Mechanical, not judgment: every finding is a `gh` check with proof. Use on "/reconcile", "reconcile the board", or when `worklist` reports it hasn't run today.
---

# Reconcile

Record vs. reality. The board is one item file per card under
`state/global/items/`, read with `~/.local/bin/work-item list --all` (or
`show <id>` for one) and written only with `work-item`. Every board card,
decision memo and "Pending:" tail is a claim about GitHub or repo state; this
skill checks the claim, not the decision behind it. Sonnet-shaped: many cheap `gh` calls, no open questions.
`/sweep` prunes and reranks `## Needs ruling` / `## Human's`; reconcile
corrects stale *facts* anywhere in the board or the memos, including
`## Claude's`. Run one after the other, not instead of.

## What to check

For every card and every memo with a linked PR, issue, or ADR:

1. **PR/issue state** — `gh pr view` / `gh issue view`. Merged, closed,
   still open with new commits since the card was written.
2. **Superseded** — a memo that took a position later overtaken by an ADR,
   a PR, or a later memo, and says nothing about it.
3. **"Pending:" tails** — a card or memo ending in an implicit unresolved
   question with no typed contract. Flag it for `/agora`, don't answer
   it here.
4. **Done cards claiming open state** — "awaiting review" a week after
   merge, "re-test after merging" past the merge.
5. **Blocked issues past their blocker** — for every open issue labelled
   `blocked` in the project's repos, read the body's `Blocked by` line.
   `Blocked by owner/repo#N`: `gh issue view owner/repo#N --json state,url`
   (or `gh pr view`) — if `CLOSED` or `MERGED`, the block is over.
   `Blocked by <party> until <YYYY-MM-DD>`: if the date is before
   `date -u +%F`, the wait is over. Either way relabel:
   `gh issue edit <url> --remove-label blocked --add-label ready`, and put
   the proof (the `state` line, or the date next to today's) in a one-line
   comment on the issue and in the reconcile commit message, if there is one. A `blocked` issue with
   no parseable `Blocked by` line is a finding to report, not a flip.

A reconcile finds a mismatch between what's written and what `gh` (or the
linked file) says. It never decides which one is right when both could be —
that's a `/agora` card.

## Fixes, applied directly (no dialog — these are corrections, not calls)

- **Done card / merged PR, text still open:** prefix the brief with
  `Done/Ruled <date> — <link>`, keep the original text as evidence, per
  `/sweep`'s convention: `work-item show <id>`, copy the text under `## Brief`
  (minus the `points:` line), and send the prefixed text back with
  `work-item brief <id> -`. Edit briefs only: the status is left alone and
  `/sweep` retires it.
- **Stale memo:** append a one-line dated annotation under the memo's H1
  naming what superseded it. Never reword or delete the body.
- **"Pending:" tail with no contract:** don't resolve it — rewrite it as a
  proper card with input (the exact question) and output type (a card's brief
  by `work-item brief <id> -`; a memo's tail as a new card with `work-item
  create`, title quoted as `/sweep` quotes a value), or hand it to `/agora`
  if it needs judgment now.
- **Blocked issue whose blocker is closed or dated past:** relabel `ready`,
  proof in the issue comment.

## Output

Under 15 lines: what was checked (counts, not a list), what was corrected
and its proof link, what's left as a `/agora` candidate. A card a live session
holds (the holder column of `work-item list --all`) is reported, not edited:
`brief` does not check the holder, so you do. Board corrections are item files the Stop
hook commits, so their proof is the link in the brief; commit memo corrections in
the state repo with the `gh` evidence in the commit message.
