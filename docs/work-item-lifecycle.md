# Work items: how a card ends

Read from the one-entry-point curia's lifecycle rulings. The curia governs;
a disagreement goes back to it. `work-item` enforces the transitions, nothing
more.

## The rules

| Rule | Standing |
|---|---|
| `claimed` comes from `ready`, `blocked`, `done` or `closed`, never `open`: an `open` item gets a `status=ready` line first | pen: "Transitions", roll `20261002t012203z`; `work-item` refuses `open -> claimed` |
| `done` comes only from `claimed`, written by the claim's holder | pen: "Transitions", roll `20261002t012203z`; `work-item` refuses another session while the claim is live |
| `closed` comes only from `done`, by the user's acceptance: never on a clock or on silence | pen: "Transitions", roll `20261002t012203z`; "Done-done is acceptance, never silence", roll `20261002t011351z` |
| The archive window counts from `closed`, never from `done`; an item left at `done` is waiting for acceptance | pen: "Done-done is acceptance, never silence", roll `20261002t011351z` |
| A parent goes `done` and holds. `closed` is written only by a sweep of the whole tree, for a parent item the user has accepted, after an acceptance period that follows the acceptance and never stands in for it; no skill writes it today | pencil, the user's, 2026-10-03, not yet in the roll: "it happens only on a sweep of the whole tree for a parent item that has been accepted" |
| What counts as acceptance, the acceptance period and the sweep's mechanics | open: "We can figure that out later" |

## Two words, two writers (pencil, the agent's reading)

| Status | Means | Who writes it | The log line carries |
|---|---|---|---|
| `done` | the holder says the work is finished | the claim's holder | `evidence=<link>`: the PR, commit, roll anchor or decisions line that shows it |
| `closed` | the user accepted the parent and its tree | the whole-tree sweep, once it exists | open |

`work-item log` refuses `status=done` with no `evidence=<link>`; the skills write the link.

## Each ending, as the skills write it (pencil, the agent's reading)

| Ending | Sequence | Written by |
|---|---|---|
| Agent work lands | claim → `done evidence=<PR>` | the worker |
| A ruling, made in agora | claim → `done evidence=<roll or decisions line>` | agora, in the ruling's turn |
| Click work the user confirms | claim → `done evidence=<their words>` | card-helper, in the confirming turn |
| Stale, moot or ruled elsewhere | claim → `done evidence=<why moot>` | sweep, on the user's tick; reconcile |
| grind retires a card | claim → `done evidence=<PR>` | grind |
