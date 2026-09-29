---
name: curia
description: Run a curia sitting — batch-consume awake ruling items, one per fresh subagent. Use on "/curia" or when Solace says they have the headspace to rule on a queue of open decisions. Not for toil; that is grind. Not for hard multi-turn questions; those are confers.
---

# Curia

Solace's analogue of grind. A sitting in which awake ruling items are
consumed in batch. Each item is quick by construction. One that turns out
hard is deferred and opens a **confer** — a new session — rather than
blocking this one.

## The sitting

<!-- How items are sourced: settled in design (awake ruling items from the
     board's ## Needs ruling), but the awake/asleep mechanism (worklist rung 3)
     is not yet built. Until then: -->

Pull candidates from `## Needs ruling` in kanban.md. <!-- When worklist
awake/asleep lands, filter to awake only. -->

## Per item

For each candidate:

<!-- The exact context budget, subagent prompt shape, and return format are
     open — design doc §6 item 2: "the curia procedure in detail: how much
     context a one-shot question carries, what the subagent returns, how a
     deferral is recorded. Design work for rung 4." -->

1. A fresh subagent gathers context for the item and returns one typed
   question with its **default**, **undo**, **until** and **risk**. A
   subagent has no channel to Solace, so it never asks; it only prepares.
2. The sitting asks that question, as returned, in an `AskUserQuestion`
   dialog. Nothing else from the subagent enters the sitting's context.
3. Solace rules.
4. Record the ruling immediately, at the place the work lands.
   <!-- Where "the work lands" is defined per item type: decisions.md,
        the card itself, a referenced issue. Not yet specified uniformly. -->
5. Discard the subagent. Next item.

## Deferring to a confer

If an item turns out hard — Solace re-rates it by deferring, or the agent
judges it a confer at the start:

<!-- How a deferral is recorded (card update? new session prompt?) is open. -->

Open a **confer**: a new session scoped to that one item. Name it in the
hand-off prompt.

## Output

<!-- Format not yet specified. -->

At the end of the sitting: how many ruled, how many deferred to a confer,
how many still open.

## Open questions (not answers — empty for a reason)

- Awake/asleep filter: depends on worklist rung 3.
- Subagent context budget per item.
- Subagent return format.
- How a deferral is recorded on the card.
- Where rulings are written when the item has no obvious home repo.
- Whether `/ruling` is called as the per-item step or its logic is inlined here.
