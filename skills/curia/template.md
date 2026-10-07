# Curia: <the question, one line>

<!-- This is digest.md, the design: a narrative a reader follows cold,
     shaped like an ADR. The user's words are in roll.md beside it, raw,
     written by a hook; the rulings are in decided.md, one line each, and
     every sentence of The decision here has one behind it. This file refers to one
     roll entry as
     `<curia>/roll.md#<stamp>`, the stamp being the entry's heading and so
     its GitHub anchor, e.g. `one-entry-point/roll.md#20261002t054107z`.
     It may quote one too, cleaned and curated by lint, always with its
     reference. -->

- id: `<id>`
- opened: <date>, on the user's order: <reference to the words that ordered it>
- origin: <link to the card that petitioned the agora, or the doc section that raised it>
- related: <ids of open curiae this one touches, comma-separated, or none; ids only, derived by lint>
- model: Fable · effort: high
- adr: <links to the ADRs, one per promoted Design section or one for the whole, or none>
- issue: <owner/repo#n of the curia's private [Epic] issue in the state repo, filed at opening>
- status: open

## Where this stands

<!-- Derived; rewritten at every close, short: the position, the last
     words by reference, what is unsettled by pointer, the size line.
     Everything a fresh session needs: never make it re-read the whole
     history. -->

Not yet sat. The first sitting reads the origin and opens the dialogue at
1 of Y.

- **Position:** 1 of Y
- **The user's last words:** (none yet; then a reference, `<id>/roll.md#<stamp>`)
- **Unsettled:** the question as posed above (then pointers: an open question's number, a Design section's number)
- **Size:** (none yet; then `wc -lw` per file, opening → after lint → now)

## The problem

<!-- Derived; rewritten at close. What hurts, for whom, with evidence by
     reference (roll stamps, inputs, metrics). No mechanism here. -->

## The design

<!-- Derived; rewritten at close, each section the sitting's rulings
     touched. One numbered section per mechanism of the solution,
     `### <n>. <mechanism>`, headed by the record's own words for it,
     never a coined name, in five parts: **What hurt.** **The
     decision.**, in prose, saying only what decided.md holds. **What it costs to change.**, in IADA terms:
     the layer each part sits in (Identifiers, API, Data, Architecture)
     and what moving it needs. **Open.** **Rulings.**, roll stamps, pen
     then pencil, each pencil stamp glossed with what it holds. A section leaves this file only when promoted to an ADR
     in its public repo; a line linking the ADR stays in its place. -->

## Vocabulary

<!-- Derived; rewritten at close. One row per noun and per identifier a
     mechanism uses, each with its own decided.md line; a word no
     mechanism uses earns no row and no line. An identifier's shape also
     gets a spec row, since code parses it; whether a noun does is open,
     the user's to debate (2026-10-07; the curia's ledger holds the
     stamp). -->

| Noun or identifier | Meaning | Ancestor concept | Standing | Stamp |
|---|---|---|---|---|

## Open questions

<!-- Derived; rewritten in place. Numbered across sessions — numbering
     continues, never restarts. One line each, by concept and domain word,
     with a pointer to the roll entry or input that holds it. -->

1. **What form does this curia need to take?** Open-ended until the user
   says, or the dialogue takes a shape the agent is confident matches one
   (SKILL.md, Form): working-backwards, problem-then-solution, bdd,
   mvp-and-narrative, success-metric, or a mix; each but
   problem-then-solution adds its own file beside this one. The user may
   change it later.

## Notes and inputs

<!-- A link the moment a side product lands: decided.md, agent-notes.md,
     each form's sidecar, inputs/. -->
