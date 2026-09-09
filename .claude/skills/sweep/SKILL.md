---
name: sweep
description: Garbage-collect the global board's `## Needs ruling` and `## Solace's` sections — find cards already ruled elsewhere or gone stale, show them with proof, delete or move only what Solace ticks, and rerank the rest by what they block. Use on "/sweep", "sweep the board", "what's stale", "prune the rulings", and before `worklist` or `/card-helper` shows the board. `--dry-run` reports and changes nothing.
---

# Sweeping the board

Garbage collection for the two sections Solace reads. It runs before the
board is shown, and on its own. `## Claude's` is not swept here; that queue
is yours to work, not to tidy.

## Modes

- **Interactive** — the default, before `worklist`, before `/card-helper`,
  and standalone: list, confirm, edit.
- **Dry run** — `--dry-run`, and always at wrap-up: the same list, no
  dialog, no edits. Wrap-up is late for extra turns; the list goes in the log
  and the next session acts on it.

## For each card, in order

1. **Ruled elsewhere?** Look where the answer would have landed: the linked
   ADR, `docs/decisions.md`, a `requirements.md` Q-nn, the issue's comments,
   the PR that implements the choice. A hit with a link is proof.
2. **Stale?** The question lost its subject: the branch merged, the repo
   archived, the feature cut, the `until:` event passed with nothing built
   on it. State the reason in one clause.
3. **Rank** the survivors: what the card blocks now, then the consequence of
   leaving it, then its `until:`. A card with no `until:` at all — a
   `## Solace's` click-work card; `/card-write` and `kanban-lint.sh` allow
   one without it — ranks above every card that has one: it never expires on
   a date, so treat it as always blocking until Solace clears it by hand. A
   card that blocks nothing and has no consequence is not shown; take its
   default, record it where the work lands, and propose the card for
   deletion with that as the proof.

A sweep finds proof that a question was answered or dissolved. It never
answers the question itself.

## The dialog

Show the list: proposed deletions, each with its proof, then the reranked
survivors. Then one multi-select (AskUserQuestion): tick the cards to act on.
Every ticked card gets exactly one explicit action, chosen at tick time —
Solace has caught wrong deletions before; nothing leaves the board, or
changes, on a bare tick with no action attached:

- **Deleted** — the card is gone. A proposed deletion (rank step 3) defaults
  to this.
- **Answered** — the question is settled now; goes to `docs/decisions.md`
  (see After the tick).
- **Deferred** — not now. Push `until:` out to a date or event Solace names.
  A card with no `until:` gets one for the first time here, rather than an
  existing value being rewritten.
- **Dig** — opens the conversation for that card only, right now, instead of
  picking one of the above; whatever it resolves to is then one of the three
  actions above, applied the same way.

Never a free-text question outside Dig.

A `learn` card under `## Solace's` is never proposed. It drops only when
Solace says she has it.

## After the tick

- **Deleted:** remove the line; the proof goes in the commit message.
- **Answered:** append `- YYYY-MM-DD — <short name>: <the answer> ([link])`
  to `docs/decisions.md` in the project's primary repo — the repo whose name
  the `project-<name>` topic shares, else the repo the card links — newest
  first, then remove the card. When the answer already landed as an ADR or a
  Q-nn, the line points there rather than repeating it. On a public repo the
  line must pass the private-terms check; failing that, it goes to the state
  repo's log with the same date.
- **Deferred:** write or rewrite `until:` per the rule above; the card is not
  shown again before then.
- **Dig:** hold the conversation for that one card, then apply whichever of
  Deleted / Answered / Deferred it settles on.
- Commit the board in the state repo, with the proof.

## Output

Under 15 lines: what was deleted and why, what moved and where, the
reranked list. A dry run prints the same with `would` in front.
