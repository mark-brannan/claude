---
name: sweep
description: Garbage-collect the global board's ruling and click-work cards (items owned human-ruling and human-click) — find cards already ruled elsewhere or gone stale, show them with proof, retire or defer only what the user ticks, and rerank the rest by what they block. Use on "/sweep", "sweep the board", "what's stale", "prune the rulings", and before `worklist` or `/card-helper` shows the board. `--dry-run` reports and changes nothing.
---

# Sweeping the board

Garbage collection for the two kinds of card the user reads: rulings (owner
`human-ruling`, once `## Needs ruling`) and click work (owner `human-click`,
once `## Human's`). It runs before the board is shown, and on its own. Cards
owned `agent` are not swept here; that queue is yours to work, not to tidy.

The board is one file per item under `state/global/items/`, written only
through `~/.claude/bin/work-item`. Read the cards to sweep with
`work-item list | awk -F'\t' '$2 != "agent"'`: columns are id, owner, status,
holder, updated, repo, then the card line. Read one item whole with
`work-item show <id>`.

`worklist` now carries the ruling counts: total, ready and waiting by `until:`, with `--waiting` and `--all` to drill.

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
   `## Human's` click-work card; `/card-write` allows
   one without it — ranks above every card that has one: it never expires on
   a date, so treat it as always blocking until the user clears it by hand. A
   card that blocks nothing and has no consequence is not shown; take its
   default, record it where the work lands, and propose the card for
   deletion with that as the proof.

A sweep finds proof that a question was answered or dissolved. It never
answers the question itself.

## Branches

Run `prune-branches` before the dialog; its "would delete" lines are one more
proposed item; its "keep" lines are not shown. On a tick, `prune-branches --delete`; otherwise leave it.

## The dialog

Show the list: proposed deletions, each with its proof, the branch prune's
summary line, then the reranked survivors. Then one multi-select (AskUserQuestion): tick the cards to act on.
Every ticked card gets exactly one explicit action, chosen at tick time —
the user has caught wrong deletions before; nothing leaves the board, or
changes, on a bare tick with no action attached:

- **Retired** — the card leaves the board: it ends at `done`, and stays on disk
  (see After the tick). A proposed deletion (rank step 3) defaults to this.
- **Answered** — the question is settled now; recorded per
  [Where a ruling lands](../agora/SKILL.md#where-a-ruling-lands)
  (see After the tick).
- **Deferred** — not now. Push `until:` out to a date or event the user names.
  A card with no `until:` gets one for the first time here, rather than an
  existing value being rewritten.
- **Dig** — opens the conversation for that card only, right now, instead of
  picking one of the above; whatever it resolves to is then one of the three
  actions above, applied the same way.

Never a free-text question outside Dig.

A `learn` card under `## Human's` is never proposed. It drops only when
the user says they have it.

A `churn-ok` card is never shown as a question: the label is the user's
alone, given on the PR. Propose any you find as a Retired deletion; its
proof is the `churn-ok` line in `docs/decisions.md`.

## After the tick

- **Retired:** retire the item (below); the proof is its `evidence=`.
- **Answered:** record the answer where
  [Where a ruling lands](../agora/SKILL.md#where-a-ruling-lands) says:
  the state repo's log by default; a dated line
  `- YYYY-MM-DD — <short name>: <the answer> ([link])` in the primary repo's
  public `docs/decisions.md` only when that section admits it. When the
  answer already landed as an ADR or a Q-nn, point there rather than
  repeating it. Then retire the item.
- **Deferred:** write or rewrite `until:` per the rule above, in the brief
  (readers take `until:` from the brief's text). `brief` does not check the
  holder, so first read `work-item fold <id>`: a `holder=` that is set with
  `holder_stale=no` means a live session has the card; say who holds it and
  since when, leave the card, move on. Otherwise print it with `work-item
  show <id>`, copy the text under `## Brief` (minus the `points:` line),
  change or add the `until:` field, and send it back with `work-item brief
  <id> -` on stdin. The card is not shown again before then.
- **Dig:** hold the conversation for that one card, then apply whichever of
  Retired / Answered / Deferred it settles on.

**Retire** is how a card leaves the board, per
[the lifecycle](../../docs/work-item-lifecycle.md): it ends at `done`, with
evidence, and stops there. No skill writes `closed`; that is the user's, on a
later sweep of an accepted parent. Read the status with `work-item fold <id>`
(the `status=` line) and start where the table says:

| status now | do |
|---|---|
| `open` | `log <id> status=ready`, then the `ready` row |
| `ready`, `blocked` | `claim <id>`, then `log <id> status=done 'evidence=<link>'` |
| `claimed` (stale holder) | the same two; `claim` takes it over |
| `done`, `closed` | nothing |

`<link>` is the proof: where the ruling landed, or the PR that shows the card
moot; for a stale card with no link, one clause with no `=` in it. A
refused `claim` (exit 1: a live session holds the item) leaves the card where
it is: say who holds it and since when, and move on, never around it. A `done`
that fails after the claim takes `work-item release <id>`; either goes in the
output.

**Quoting.** A value that may hold `'` (a link, a clause, a card title) is never
written inside single quotes. Put it in a quoted here-doc, read it into a
variable, and pass the variable in double quotes; nothing in the text is then
special to the shell:

```sh
ev=$(cat <<'EOF'
<link>
EOF
)
~/.claude/bin/work-item log <id> status=done "evidence=$ev"
```

`'evidence=<link>'` above, and in the other skills, is shorthand for this.

The board is not committed by hand: the item files are plain files in the state
repo and the Stop hook commits and pushes them. Proofs live in the log's
`evidence=`.

## Output

Under 15 lines: what was retired and why, what moved and where, the
reranked list. A dry run prints the same with `would` in front.
