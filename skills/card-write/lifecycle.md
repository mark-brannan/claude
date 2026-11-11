## Lifecycle

- **Cards die when done, never by an edit to the brief.** Per
  [the lifecycle](../../docs/work-item-lifecycle.md), an `open` item gets
  `work-item log <id> status=ready` first (the second call above), then
  `work-item claim <id>`, then `work-item log <id> status=done
  'evidence=<link>'` — the PR, commit or decisions line that shows it. Stop
  there: no skill writes `closed`; that waits on the user's acceptance and a
  sweep of the whole tree. `work-item` refuses `done` without a claim. The
  endings below are the lifecycle doc's reading, still pencil.
- **An answered ruling moves, it is not deleted.** `/agora` records the answer
  at once and retires the card as above; where `/sweep` finds one answered
  elsewhere it records the answer where
  [Where a ruling lands](../agora/SKILL.md#where-a-ruling-lands) says
  (private by default; a pointer line when the ruling landed as an ADR or a
  Q-nn) and retires it the same way.
- No cap and no expiry: `/sweep` prunes what was ruled elsewhere or went
  stale. A card that blocks nothing and has no
  consequence is never shown; take its default and record it.
- A sweep — "reconcile", "what's outstanding", "what's stale" — is
  `worklist` for work state, which never edits, and `/sweep` for the cards.
- Writes are plain files in the state repo; the Stop hook commits and pushes.
