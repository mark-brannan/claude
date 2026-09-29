---
name: curia
description: Open or continue a curia — the hard, multi-turn decision session on one question, over as many sessions as it takes. Use on "/curia <id>", "confer <id>", "confer on X", or when an agora sitting answered an item with the word "confer". Not for quick rulings in batch; that is /agora. Not for toil; that is grind.
---

# Curia

Curia Regis: the inner court, the hard decision taken in council. **Confer
is a synonym**; `curia` names the skill and the session type in code and
files (Solace, 2026-09-29). Stub: the design is not signed off, and the
loop is run by hand from the design doc's prompt until this skill can.

Ancestor concepts: the one-way-door test (why it is here at all), the
coaching kata (the same prompt, every sitting), context engineering (the
durable document is the point).

## What a curia is

- **One question, one document.** `/curia <id>` opens or continues the
  curia on the document for `<id>`; open and continue are the same
  prompt. <!-- Where the document lives, and what a placeholder is before
  one exists: open (design doc, open question on `/curia <id>` mechanics). -->
- **A loop over sessions, not a session.** Solace's last words carry over
  verbatim; every unsettled question carries over. Fresh context each
  time; what is settled lands at once.
- **A dialogue.** Many short exchanges: one short question at a time,
  then wait. Every question shows **X of Y** and the total. Refer to
  things by concept and domain word, never a bare number; put the
  ancestor concept beside every design term.
- **Solace stops it, not the agent.** If a clock or nag fires, name it
  and ask. A curia that produces no exchange has failed.
- **Nothing of significance is named without Solace's say-so.**
- **Side work never pollutes the curia's context.** A lint, an audit or a
  fetch goes to a read-only sub-agent (no worktree, no sub-agents of its
  own) that returns a summary, and its product lands in the document at
  once, not at close.

## Opening

1. A read-only sub-agent lints the document first: contradictions, stale
   claims and orphan terms across decided so far, open questions, the word
   ledger and the domain model, returned as a diff. Show the diff before
   the dialogue starts; only its list enters this context (Solace,
   2026-09-29).
2. Read the document's loop section, then Solace's word and design
   preferences, Solace's words (every pass), decided so far, and the open
   question named by `<id>`.
3. State where the question stands in one line and ask the first
   question, 1 of Y.

## During

Record Solace's words verbatim under a new dated sub-heading in the
document's "Solace's words" section; never edit an old one. Keep decided
so far, open questions and the word ledger current as you go.

## Closing (Solace says when)

Land every edit. Say what is still open on this question. Print the
paste-again prompt for `/curia <id>` with model and effort. Solace has the
final word; record it verbatim. Open nothing new.

## Today's instance

The one-entry-point design confer, run by hand from
`state/global/log/2026-09-27-one-entry-point-design.md` in the state repo
(its loop section holds the prompts, one per open question marked confer).
