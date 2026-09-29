---
name: agora
description: Run an agora sitting — the quick decisions, in batch, one fresh subagent per item, Solace rules. Use on "/agora", "walk the decision cards", "what needs deciding", or when Solace says they have the headspace to rule on a queue of open decisions. Not for toil; that is grind. Not for a hard multi-turn question; that is a curia (a confer), and "confer" is a closed answer here.
---

# Agora

Solace's analogue of grind: the sitting in which the quick judgment items
are consumed in batch. Each item is quick by construction; a hard one is
answered with the one word **confer**, the sitting moves past it, and it
goes to its own `/curia <id>` session. This skill absorbs `/ruling` (retired by
Solace, 2026-09-29, in the design confer): the typed per-item contract below
was ruling's.

Ancestor concepts: GTD inbox processing, office hours, a replenishment
cadence; the ruling's default that holds is "act after a veto window".

## The sitting

<!-- Sourcing is settled in design (awake items from the board's
     ## Needs ruling); the awake/asleep mechanism (worklist rung 3) is not
     built. Until then: -->

Pull candidates from `## Needs ruling` in kanban.md, anything `/reconcile`
flagged as an implicit "Pending:" tail, and anything Solace names. That
list is the **agora-docket**. Count it before the first question, and show
the count on every question. <!-- When worklist awake/asleep lands, filter
to awake only. -->

## Per item: the contract

Every item this skill touches gets, and keeps:

- **Input** — the exact question, one sentence, answerable yes / no / a
  number / a named choice, plus the four fields `default`, `undo`,
  `until`, `risk`. Not "figure out X"; that is unscoped work, sent back
  to be scoped.
- **Output** — exactly one of:
  - **Ruling** — Solace answers; written at once to `docs/decisions.md`
    in the primary repo, or the state repo's log if it fails the
    private-terms check.
  - **Spawned work item** — the answer was "build X to find out"; open
    the issue or card, link it, this item closes.
  - **Item (partly) unblocked** — the ruling removes one dependency; say
    which, and what still blocks.
  - **Confer** — Solace's one word; the item leaves the sitting for a
    `/curia <id>` session (see below). Not a failure of the item; a
    rating of its difficulty and possibly of the question's quality.

## Per item: the steps

1. A fresh subagent gathers the item's context and returns the typed
   question with its four fields and a **direct link** to the stored
   context, readable by Solace. A subagent has no channel to Solace, so it
   never asks; it only prepares. <!-- Context budget and return format:
   open (design doc, open question on the agora procedure). -->
2. The sitting asks that question, as returned, in one `AskUserQuestion`
   dialog: the agent's pick first and why, then the alternatives. Every
   question carries **X of Y** and the total. Nothing else from the
   subagent enters the sitting's context.
3. Solace rules: yes / no / a value / **confer** / other.
4. Apply the output per the contract, immediately; don't batch.
5. Discard the subagent. Next item.

## Confer: handing a hard item to a curia

On the word *confer*: mint an identifier for the item, record it on the
card (<!-- format open --> `confer: <id>`), and move on. At the end of the
sitting, print one `/curia <id>` prompt per deferred item, each naming
model and effort. The sitting never opens the hard discussion itself; that
would bloat its context.

## Difficulty and model

Before the first item, rate each candidate twice from its `default:` /
`risk:` text, as a triage table does: Solace's difficulty and a
high-stakes agent's, each low / medium / high. If the running model is
weaker than the hardest agent rating calls for, print one line offering a
model switch or an `Agent` call with a `model` override for that item,
then continue.

## Output

Per item: the question, the outcome, the link. At the end, one line:
how many ruled, spawned, unblocked, deferred to a curia, still open, out
of the docket's total.

## Open (design doc, open question on the agora procedure)

- Awake/asleep filter: depends on worklist rung 3.
- Subagent context budget and return format.
- How a confer deferral is recorded on the card.
- Where rulings land when the item has no obvious home repo.
