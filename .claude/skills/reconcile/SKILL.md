---
name: reconcile
description: Check the board and its memos against GitHub reality — a card on a merged/closed PR, a memo silent about being overtaken, a "Pending:" tail nobody resolved — and correct the record. Mechanical, not judgment: every finding is a `gh` check with proof. Use on "/reconcile", "reconcile the board", or when `worklist` reports it hasn't run today.
---

# Reconcile

Record vs. reality. Every board card, decision memo and "Pending:" tail is a
claim about GitHub or repo state; this skill checks the claim, not the
decision behind it. Sonnet-shaped: many cheap `gh` calls, no open questions.
`/sweep` prunes and reranks `## Needs ruling` / `## Solace's`; reconcile
corrects stale *facts* anywhere in the board or the memos, including
`## Claude's`. Run one after the other, not instead of.

## What to check

For every card and every memo with a linked PR, issue, or ADR:

1. **PR/issue state** — `gh pr view` / `gh issue view`. Merged, closed,
   still open with new commits since the card was written.
2. **Superseded** — a memo that took a position later overtaken by an ADR,
   a PR, or a later memo, and says nothing about it.
3. **"Pending:" tails** — a card or memo ending in an implicit unresolved
   question with no typed contract. Flag it for `/sequence`, don't answer
   it here.
4. **Done cards claiming open state** — "awaiting review" a week after
   merge, "re-test after merging" past the merge.

A reconcile finds a mismatch between what's written and what `gh` (or the
linked file) says. It never decides which one is right when both could be —
that's a `/sequence` card.

## Fixes, applied directly (no dialog — these are corrections, not calls)

- **Done card / merged PR, text still open:** prefix `Done/Ruled <date> —
  <link>`, keep the original text as evidence, per `/sweep`'s convention.
- **Stale memo:** append a one-line dated annotation under the memo's H1
  naming what superseded it. Never reword or delete the body.
- **"Pending:" tail with no contract:** don't resolve it — rewrite it as a
  proper card with input (the exact question) and output type, or hand it
  to `/sequence` if it needs judgment now.

## Output

Under 15 lines: what was checked (counts, not a list), what was corrected
and its proof link, what's left as a `/sequence` candidate. Commit the
board/memo corrections in the state repo with the `gh` evidence in the
commit message.
