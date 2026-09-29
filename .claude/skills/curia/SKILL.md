---
name: curia
description: Open or continue a curia — the hard, multi-turn decision session on one question, over as many sessions as it takes. Use on "/curia <id>", bare "/curia", "confer <id>", "confer on X", or when an agora sitting answered an item with the word "confer". Not for quick rulings in batch; that is /agora. Not for toil; that is grind.
---

# Curia

Curia Regis: the inner court, the hard decision taken in council. **Confer
is a synonym**; `curia` names the skill and the session type in code and
files (Solace, 2026-09-29).

Ancestor concepts: the one-way-door test (why it is here at all), the
coaching kata (the same prompt, every sitting), context engineering (the
durable document is the point).

## What a curia is

- **One question, one document.** `/curia <id>` opens or continues the
  curia on the document for `<id>`; open and continue are the same
  prompt.
- **A loop over sessions, not a session.** Solace's last words carry over
  verbatim; every unsettled question carries over. Fresh context each
  time; what is settled lands at once.
- **A dialogue.** Many short exchanges: one short question at a time,
  then wait. Every question shows **X of Y** with the total, and the
  numbering continues across sessions — a curia parked at 4 of 9 reopens
  at 5 of 9, and when Y moves, say so. Refer to things by concept and
  domain word, never a bare number; put the ancestor concept beside every
  design term.
- **Solace stops it, not the agent.** If a clock or nag fires, name it
  and ask; never obey it silently. A curia that produces no exchange has
  failed.
- **Nothing of significance is named without Solace's say-so.** An id is
  a description, not a name (see minting); anything christened — a
  mechanism, a skill, a concept — waits for the say-so.
- **Side work never pollutes the curia's context.** A lint, an audit or a
  fetch goes to a read-only sub-agent (no worktree, no sub-agents of its
  own) that returns a summary. Its product — and any spike or side chat's
  — lands in the curia's folder and is committed the moment it is
  produced, never held for the close. A fork that never lands loses it.

## Where a curia lives

One folder per curia in the state repo. Deliberation is private and stays
there; only what a curia **mints** — an ADR, an issue, a card — goes to a
public repo.

```
state/global/curia/<id>/
  thread.md   the document: where it stands, the derived record, Solace's words
  notes.md    the agent's own notes, any format it likes (optional)
  inputs/     read-only side products: spikes, side-chat pastes, subagent reports
  minted.md   links to what this curia minted (created when it first mints something)
```

Two grains in `thread.md`: **Solace's words are append-only** — a new
dated sub-heading per sitting, old ones never edited. The **derived
sections** (where it stands, decided, open questions) are rewritten in
place. The one exception to the append-only grain is a **pin**: a passage
moved to the top of the words section for importance — moved, never
edited. Importance, not settledness.

<!-- pencil: layout, filenames, the two grains, the pin exception and
     private-deliberation/public-mint are assumed, not ruled (design doc,
     open question on /curia <id> mechanics). -->

## Minting an id

Whichever session defers or opens the question mints the id: an agora
sitting on the word *confer*, or any session where Solace says "confer on
X". The id is a kebab-case slug of the question's own words —
`widget-retirement`, not a coined name — so minting one is not naming
anything. Solace renames at will; a rename moves the folder and leaves a
one-line redirect `thread.md` at the old id.

To mint: create the folder, copy [template.md](template.md) to
`thread.md`, fill in the question, the origin link and the date, and
commit. That placeholder is the whole mint; the first sitting does the
rest. Say the id in the minting session's record.

## Opening (`/curia <id>`)

1. **Resolve the id.** Read `state/global/curia/<id>/thread.md`. A
   one-line redirect points at a document elsewhere (a grandfathered
   curia); follow it — that document's own loop section then governs read
   order and replaces step 4's reading, while the LIVE check, the lint
   and every dialogue rule still apply, with the LIVE file in the
   redirect's folder. No folder at all → treat as bare `/curia` and say
   the id didn't resolve.
2. **Check for another sitting.** If the folder holds a `LIVE` file
   (session id and ISO timestamp, written at step 4) from a different
   session, say so in one line and ask — Solace runs parallel sittings on
   purpose sometimes, and stale markers happen. Never refuse outright.
3. **Lint by sub-agent.** A read-only sub-agent (no worktree, no
   sub-agents of its own) checks the derived sections for contradictions,
   stale claims and orphan terms; only its list enters this context. Lint
   is toil: apply the mechanical fixes and show the diff for the record;
   only a finding that touches a ruling or a name becomes a question in
   the dialogue. <!-- pencil: lint-is-toil is assumed (design doc, the
   lint-diff-is-toil open question). -->
4. Write the `LIVE` file. Read the header and **Where this stands**:
   Solace's last words verbatim, the unsettled questions, the X of Y
   position. Read deeper history only as a question needs it — never the
   whole document by default.
5. State where the question stands in one line and ask the next
   question, X of Y.

## During

Record Solace's words verbatim under a new dated sub-heading in the words
section; never edit an old one. Keep the derived sections current as you
go, and commit as you land — a sitting's record must survive the session
dying mid-turn.

## Closing (Solace says when)

1. Land every edit; rewrite **Where this stands** — last words verbatim,
   what is unsettled, the X of Y position for next time. If Solace has
   ruled the question itself settled, set `status: settled` in the header
   too — bare `/curia` lists open curiae, and nothing else retires one.
2. Say what is still open on this question, by concept.
3. Print the paste-again prompt: `/curia <id>`, with the model and effort
   from the document's header. Nothing else to paste, nothing to hold in
   memory.
4. Remove the `LIVE` file.
5. Solace has the final word; record it verbatim. Open nothing new after
   it.

## Bare `/curia`

List the open curiae, newest-touched first (recency matters;
first-in-last-out), each as its id and question in one line, with the
count in view. Open means `status: open` in the header; a redirect has
no header, so one pointing at another curia folder collapses into its
target, and one pointing elsewhere (grandfathered) counts as open until
its document says settled. Recommend one and why, in one sentence. Open
nothing until Solace names an id. If the list is long, say so plainly — a perpetually
full list is a decision-making process failure, and folding a small
question into an existing curia is always on the table.

## Grandfathered

The one-entry-point curia predates this skill; its document stays at its
dated path in the state repo's log, reached through the redirect at
`state/global/curia/one-entry-point/`. Its own loop section governs it.
