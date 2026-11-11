# The facets, and the word cap

| Facet | Does | Writes |
|---|---|---|
| [lint](facets/lint.md) | contradictions, stale claims, flip candidates in the roll, orphan terms, uncited quotes, the narrative against the ledger, overlap with the other open curiae; moves pencil to pen where the line's link resolves to a merged commit, spec row or decisions line, marked as its own; prunes per the queue table; counts the pen lines with no embedded or effective state and lists the reviews past due, from `ledger-review`; moves `read-from:` forward | one patch and a findings list (at most 600 words) under `inputs/`; a decision or name finding as a line under **Open questions** |
| [edit](facets/edit.md) | rewrites the Design sections every decision landed since its last run touches; decomposes a curia the user has decided to split, by hand or at close only, never from a routine; posts the diff to the epic for the user's redline; the user's hand edits to `digest.md` are pen, by a commit the user authored with no agent trailer | `digest.md`; the epic body and one comment; child folders on a split |
| [status](facets/status.md) | counts: open questions; ledger lines by pen, pencil and unmarked; lines pruned since its last run; sittings since the last pen line landed; the word cap, words at open per section and together against 1,500, and the context at first question as a bare figure, both as the sitting passed them | one line beside **Size** in **Where this stands**; a table row under the newest Trace entry |

The word cap is on trial from 2026-10-07, revisited once `status` has
measured it over a period and not before 2026-12-08, on the user's word
of 2026-11-07 (card 179136412936a787ac): **a sitting reads
at most 1,500 words at open** — Where this stands ≤ 250, Working memory
≤ 750, Open questions ≤ 500. Measured basis: the three sections 1,356
words that day. Context at first question has no cap; `status` shows
the figure bare, with no mark. Cost is context × turns.

<!-- pen (the user, 2026-10-07): facets lint, edit, status; the by-hand
     line; spawned at close, run by a routine, never only at close; the
     word cap and its basis; status not gauge; the curia's ledger
     holds the stamps. pencil: a facet commits its own fixes instead of
     handing a patch to a caller, since a background facet has no caller
     left to apply one; one runner in sequence instead of three parallel
     spawns; edit never decomposes from a routine; the agent's calls. -->

