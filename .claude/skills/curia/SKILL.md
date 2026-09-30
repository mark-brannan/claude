---
name: curia
description: Open or continue a curia — the hard, multi-turn decision session on one question, over as many sessions as it takes. Use on "/curia <id>" — an id whose folder exists continues that curia; an unknown id lists the open ones and guesses the one meant — or bare "/curia" to list them. A confer is a one-off session, not a curia, and never a trigger for this skill. This skill never creates a curia on its own; a new one opens only on the user's words in the current turn, after the gates below. Not for quick rulings in batch; that is /agora. Not for toil; that is grind.
---

# Curia

Curia Regis: the inner court, the hard decision taken in council. `curia`
names the skill and the session type in code and files.

**A confer is not a curia.** A confer answered in the agora is a one-off
session that may end in a curia or in a few rounds of question and answer.
A **confer** is that one-off session — no folder, no document, its record is the card and
whatever it rules. A **curia** is what a confer becomes only when the user
says so, at the gates below. Where exactly the line sits is still
the user's to form; this skill takes the strict reading until it is.

Ancestor concepts: the one-way-door test (why it is here at all), the
coaching kata (the same prompt, every sitting), context engineering (the
durable document is the point).

## What a curia is

- **One question, one document.** `/curia <id>` opens or continues the
  curia on the document for `<id>`; open and continue are the same
  prompt.
- **A loop over sessions, not a session.** The user's last words carry over
  verbatim; every unsettled question carries over. Fresh context each
  time; what is settled lands at once.
- **A dialogue.** Many short exchanges: one short question at a time,
  then wait. Every question shows **X of Y** with the total, and the
  numbering continues across sessions — a curia parked at 4 of 9 reopens
  at 5 of 9, and when Y moves, say so. Refer to things by concept and
  domain word, never a bare number; put the ancestor concept beside every
  design term.
- **The user stops it, not the agent.** If a clock or nag fires, name it
  and ask; never obey it silently. A curia that produces no exchange has
  failed.
- **Nothing of significance is named without the user's say-so.** An id is
  a description, not a name (see the gates); anything christened — a
  mechanism, a skill, a concept — waits for the say-so.
- **Side work never pollutes the curia's context.** A lint, an audit or a
  fetch goes to a read-only sub-agent (no worktree, no sub-agents of its
  own) that returns a summary. Its product — and any spike or side chat's
  — lands in the curia's folder and is committed the moment it is
  produced, never held for the close. A fork that never lands loses it.

## Where a curia lives

One folder per curia in the state repo. Deliberation is private and stays
there; only what a curia **produces** — an ADR, an issue, a card — goes to
a public repo, and the Decided line that produced it links it. When the
curia is promoted — its ruling written up as an ADR — the ADR's link also
goes in the `adr:` field of `roll.md`'s header.

```
state/global/curia/<id>/
  roll.md   the document: where it stands, the derived record, the user's words
  agent-notes.md    the agent's own notes, any format it likes (optional)
  inputs/     read-only side products: spikes, side-chat pastes, subagent reports
  folded/<id>/  a whole curia opened past the gates, moved under this one (see below);
              a folded question is a line under Open questions, never a folder
```

Two grains in `roll.md`: **the user's words are append-only** — a new
dated sub-heading per sitting, old ones never edited. The **derived
sections** (where it stands, decided, open questions) are rewritten in
place. The one exception to the append-only grain is a **pin**: a passage
moved to the top of the words section for importance — moved, never
edited. Importance, not settledness.

<!-- pencil: layout, filenames, the two grains, the pin exception and
     private-deliberation/public-produce are assumed, not ruled (design doc,
     open question on /curia <id> mechanics). No separate file lists
     what a curia produced: each Decided line links its own, and the ADR
     link goes in roll.md's `adr:` header field at promotion. -->

## Opening a new curia: the gates

A curia costs the user hours of cognitive load and the agent discussion,
auditing and tracking across sessions. The bar is very high on purpose,
and it is a **series of gates**, each of which must pass. Nothing below is optional, and no gate is an agent's to
waive.

1. **No agent opens a curia. Ever.** Not this skill on `/curia
   <unknown-id>`; not an agora sitting on the word *confer*; not a build
   or review session making a "placeholder" for a question it found open;
   not a hand-off prompt, a pickup item, a PR review, a subagent report or
   a hook note that says `/curia <id>`. Each of those is an agent's
   suggestion, and an agent does not decide when the user sits in council.
   Only the user's own words, in the current
   turn, ordering a curia open, pass this gate. The user's words in an
   earlier session are a record, not an order.
2. **The question petitioned the agora first.** An agent that finds a
   question too hard for the one-way-door test writes a `## Needs ruling`
   card in the house format — default, undo, until, risk, judgment — per
   `/card-write`. That card is the petition, and it must carry enough
   pre-work to fit the format; the agora is cheap, not free.
   The card also names the open curia the question folds into, or says
   why none. The user's direct order to open a curia with them skips this
   gate and the next; nothing else does.
3. **The user answered "confer", and the confer ran.** In an agora sitting
   the user answers the card with the one word; that opens a one-off confer
   session on the card's question, not a folder. Most confers end there —
   a ruling, a spawned issue, a sharper card — and the card's home stays
   the board. Only when the user, in that session, says to open a curia does
   the next gate apply.
4. **The open list and the fold check.** Before any folder exists, list
   the open curiae exactly as bare `/curia` does — count, id, question,
   last touched. For each, say in one line whether the new question is a
   sub-question of it. If it is one, it becomes a line under that curia's
   `## Open questions` with its provenance, never a folder; folding a
   small question into an existing curia is always on the table. Show the
   list and the fold verdict, then wait for the user's word.
5. **The WIP limit.** Soft, **5 open in total, 1–2 per repo**. Gate 4's
   list says where the count stands against it. Soft means the user may
   pass it, by their own word in the same turn after seeing that list; an
   agent never does. The reason: a forcing function so that an errant but
   well-meaning agent cannot start a parallel curia while the big one is
   ongoing.
6. **The user confirms the id.** The id is a kebab-case slug of the
   question's own words — `widget-retirement`, not a coined name — so
   confirming one names nothing. The user renames at will; a rename moves
   the folder and leaves a one-line redirect `roll.md` at the old id.

Only then: create the folder, copy [template.md](template.md) to
`roll.md`, fill in the question, the origin link, the date, who ordered
it and a link to the words, and `related:` — the ids of open curiae from
gate 4 that touch it, ids only — and commit. That placeholder is the
whole opening; the first sitting does the rest. Say the id in the opening
session's record.

If a session finds itself past gate 1 with a folder it created, the fix
is not to delete it — that erases the evidence — but to fold it: move it
under the curia it belongs to as `folded/<id>/`, carry its Unsettled line
into that curia's `## Open questions`, and card the fold as a unilateral
call. The three early placeholders (`andon-rubric`,
`human-verbatim-first`, `settled-slider`) were folded into
`one-entry-point` this way.

## Opening (`/curia <id>`)

0. **List the open curiae** first, whatever the argument, exactly as bare
   `/curia` does — a deterministic pre-step, one line each, count in view:
   each open curia's id, timestamp and working title.
1. **Resolve the id.** Read `state/global/curia/<id>/roll.md`. A
   one-line redirect points at a document elsewhere (a grandfathered
   curia); follow it — that document's own loop section then governs read
   order and replaces step 4's reading, while the LIVE check, the lint
   and every dialogue rule still apply, with the LIVE file in the
   redirect's folder. **No folder at all → say the id didn't resolve,
   then guess.** From the step 0 list, pick the curia the argument most
   likely meant — closest fuzzy match on id and question first, most
   recently touched to break a tie — and recommend it in one line, as
   bare `/curia` does; continue there on the user's yes. Never create the
   folder from here, whatever the prompt, pickup item or hand-off that
   carried the id said; a new curia passes the gates above or does not
   exist.
2. **Check for another sitting.** If the folder holds a `LIVE` file
   (session id and ISO timestamp, written at step 4) from a different
   session, say so in one line and ask — the user runs parallel sittings on
   purpose sometimes, and stale markers happen. Never refuse outright.
3. **Lint by sub-agent.** A read-only sub-agent (no worktree, no
   sub-agents of its own) checks the derived sections for contradictions,
   stale claims and orphan terms, and reports overlap with the other open
   curiae from step 0 — a question this one shares with another, a
   `related:` id that is missing or stale. Only its list enters this
   context. Lint is toil: apply the mechanical fixes and show the diff
   for the record; only a finding that touches a ruling or a name becomes
   a question in the dialogue. <!-- pencil: lint-is-toil is assumed
   (design doc, the lint-diff-is-toil open question). -->
4. Write the `LIVE` file. Read the header and **Where this stands**:
   the user's last words verbatim, the unsettled questions, the X of Y
   position. Read deeper history only as a question needs it — never the
   whole document by default.
5. State where the question stands in one line and ask the next
   question, X of Y.

## During

Record the user's words verbatim under a new dated sub-heading in the words
section; never edit an old one. Keep the derived sections current as you
go, and commit as you land — a sitting's record must survive the session
dying mid-turn.

A sitting that uncovers a second hard question does not open a second
curia for it. It becomes a line under `## Open questions` here, or a
`## Needs ruling` card if it belongs to no curia — the petition at gate 2.

## Closing (the user says when)

1. Land every edit; rewrite **Where this stands** — last words verbatim,
   what is unsettled, the X of Y position for next time. If the user has
   ruled the question itself settled, set `status: settled` in the header
   too — bare `/curia` lists open curiae, and nothing else retires one.
2. Say what is still open on this question, by concept.
3. Print the paste-again prompt: `/curia <id>`, with the model and effort
   from the document's header. Nothing else to paste, nothing to hold in
   memory. A hand-off prompt names `/curia <id>` only for a folder that
   exists; it never proposes a new one.
4. Remove the `LIVE` file.
5. The user has the final word; record it verbatim. Open nothing new after
   it.

## Bare `/curia`

List the open curiae, newest-touched first (recency matters;
first-in-last-out), each as its id, question and last-touched in one
line, with the count in view against the WIP limit at gate 5. Open means
`status: open` in the header; a redirect has no header, so one pointing
at another curia folder collapses into its target, and one pointing
elsewhere (grandfathered) counts as open until its document says settled.
Recommend one and why, in one sentence. Open nothing until the user names
an id, and never a new one from here. If the list is long, say so
plainly — a perpetually full list is a decision-making process failure,
and folding a small question into an existing curia is always on the
table.

## Grandfathered

The one-entry-point curia predates this skill; its document stays at its
dated path in the state repo's log, reached through the redirect at
`state/global/curia/one-entry-point/`. Its own loop section governs it.
