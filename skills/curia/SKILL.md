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
durable document is the point), Architecture Decision Records (ADR),
"Working Backwards" PR/FAQ.

## What a curia is

- **One question, one document.** `/curia <id>` opens or continues the
  curia on the document for `<id>`; open and continue are the same
  prompt.
- **A loop over sessions, not a session.** The user's last words carry over
  by reference to the roll; every unsettled question carries over. Fresh
  context each time; what is settled lands at once.
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
goes in the `adr:` field of `digest.md`'s header.

```
state/global/curia/<id>/
  roll.md     the user's words: append-only, one stamped entry per prompt, written by a hook
  digest.md   the document: where it stands, decided, open questions
  LIVE        the last sitting's session id and ISO timestamp; closing leaves it
  agent-notes.md the agent's working memory and trace, for the next agent (see Agent notes)
  inputs/     read-only side products: spikes, side-chat pastes, subagent reports
```

Two files, two grains. **`roll.md` is append-only.** While a `LIVE` file
naming the session is in the folder, a hook appends each of the user's
prompts verbatim under a stamp heading, `### 20261002t054107z` (UTC date and
time to the second, no separators, lower-case `t` and `z`, nothing else);
nothing edits an entry after. No agent writes `roll.md`; the roll stays
raw. **`digest.md` is derived**: rewritten in place, and it carries the
user's words as references, `<curia>/roll.md#<stamp>`, plus cleaned,
curated quotes, each with its reference. A quote may be edited lightly for
typos or readability, or cut where a long passage runs past its point;
never reworded into something the user didn't say. The stamp is the
heading, so the reference is the GitHub anchor and stays a link. Which
quotes and references it carries is lint's call, made with an editor's
discretion: it pulls a quote in where a ruling or open question rests on
it and prunes one that has stopped earning its place. One a later ruling
contradicts is removed and shown, since a reversal is a finding, not an
error. A reference into another curia's roll takes the same form.

<!-- pen (Solace, 2026-10-02): roll.md for the words, digest.md for the
     document, the reference form `<curia>/roll.md#<stamp>` (amended by
     Solace the same day from `:<stamp>`, with the session id dropped from
     the heading: the anchor must be the bare stamp). pencil: the
     rest of the layout and private-deliberation/public-produce are
     assumed, not ruled (design doc, open question on /curia <id>
     mechanics). pen (Solace, 2026-10-02, session 4d6d005a): "References
     plus cleaned, edited, curated quotes. The linting agent may make
     minor edits for typos, readability, or to cut unnecessary sections
     of a long quote." It replaces "agents never quote" (#489). There is
     no pin: nothing in roll.md moves, and curation in the digest does
     the pin's work (one-entry-point §8). No separate file lists what a curia
     produced: each Decided line links its own, and the ADR link goes in
     digest.md's `adr:` header field at promotion. -->

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
   the folder and adds `formerly: <old-id>` to the digest's header, the
   only trace of the old id; nothing stays at the old path.

Only then: create the folder, copy [template.md](template.md) to
`digest.md`, fill in the question, the origin link, the date, who ordered
it and a reference to the words, and `related:` — the ids of open curiae from
gate 4 that touch it, ids only; lint keeps it derived from then on — and
commit. That placeholder is the
whole opening; the first sitting does the rest. Say the id in the opening
session's record.
Also create `agent-notes.md` from the header in
[forms/agent-notes.md](forms/agent-notes.md).

## Form

A curia starts open-ended. [template.md](template.md) seeds one open
question, *what form does this curia need to take?*, with the forms the
skill can offer, and nothing else. **The user directs the early sittings.**
The agent never forces a form: it proposes one only when the dialogue has
taken a shape it is confident matches one, says which and why in one
line, and waits for the word. A form, once the user chooses it, adds its
sections to `digest.md` from its file under [forms/](forms/):

| Form | Ancestor | Fits when |
|---|---|---|
| working-backwards | Amazon PR/FAQ; Covey's "begin with the end in mind" | the end state is felt but unwritten |
| problem-then-solution | the design doc's diagnosis-then-design | the pain is clear, the fix is not |
| bdd | behaviour-driven development, given/when/then | behaviour is the contract |
| mvp-and-narrative | lean startup's MVP, plus its story | the user wants to test by using |
| success-metric | OKR / North Star metric | the measure is the hard part |

A curia may mix forms, and may change them; the user says which. Each
choice is a dated Decided line with its reference, and a change is a new
line naming the one it replaces. A dropped form's sections leave
`digest.md` with it; what they held that still earns its place moves to
**Decided** or **Open questions**, and lint shows the move: a reversal is
a finding, not an error.

A section's `<!-- -->` comment is a rule or a prompt. A rule says how the
section is kept (*Derived; rewritten in place…*) and stays. A prompt says
what to write (*One number, how it is measured…*) and is replaced by its
answer the first time the section is written.

## Agent notes

`agent-notes.md` is the agent's extended memory for the curia, read in
full at every opening, with two parts. **Working memory**: at most 60
lines, rewritten at every close, holding what the next agent must know
before the first question: live traps, the user's leanings not yet ruled,
what not to re-ask. **Trace**: newest first, one entry per sitting, a few
lines each, pruned by lint once an entry stops earning its place. Both
point to roll stamps, inputs and commits, never copy them. Not here: the
user's words (`roll.md`), rulings (`digest.md`), reports (`inputs/`).
`state/global/curia/one-entry-point/agent-notes.md` is the worked example.

If a session finds itself past gate 1 with a folder it created, the fix
is not to delete it but to fold it into an open curia: its files into that
curia's `inputs/`, its question under its `## Open questions`, and card
the fold as a unilateral call.

## Opening (`/curia <id>`)

0. **List the open curiae** first, whatever the argument, exactly as bare
   `/curia` does — a deterministic pre-step, one line each, count in view:
   each open curia's id, timestamp and working title.
1. **Resolve the id.** Read `state/global/curia/<id>/digest.md`.
   **No folder → check the `formerly:` lines** in every digest's header;
   a match is the renamed curia, and opens without asking.
   **No folder and no match → say the id didn't resolve, then guess.** From the step 0 list, pick the curia the argument most
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
3. **Lint by sub-agent, on Sonnet.** A read-only sub-agent (no worktree, no
   sub-agents of its own; it writes one file, its patch) checks the derived sections for contradictions,
   stale claims and orphan terms, and reports overlap with the other open
   curiae from step 0 — a question this one shares with another — from
   which this session rewrites `related:`. It reads every `roll.md`
   entry after the last words that **Where this stands** cites, and any
   input quoting the user verbatim, and proposes quotes to pull and
   prune under the rule above: a ruling, a lean, a correction or a
   reopening with no line citing it is a pull. It hands back a patch of
   the mechanical fixes, written under `<id>/inputs/`, and a findings
   list of at most 600 words; only the list enters this context. Lint is
   toil: apply the patch with one `git apply` and show the diff for the
   record; beside it, size from `wc -lw`, one line per file —
   the document step 1 read, and `agent-notes.md` — before
   and after the fixes: `digest.md 2,242 → 2,198 lines · 33,516 → 32,870
   words`. Only a
   finding that touches a ruling or a name becomes a question in the
   dialogue. <!-- pencil: lint-is-toil is assumed
   (design doc, the lint-diff-is-toil open question). -->
   In the same step, whatever the argument points at — a PR, a diff, a
   log, a hand-off — goes to its own read-only sub-agent, run beside
   lint; only its summary enters the sitting.
4. Write the `LIVE` file, before the first question: the hook records
   the user's words only while it names this session, so a sitting
   without it records nothing. Read the header and **Where this stands**:
   the reference to the user's last words, the unsettled questions, the X
   of Y position. Read deeper history only as a question needs it — never
   the whole document by default.
5. State where the question stands in one line and ask the next
   question, X of Y.

## During

The hook records the user's words; the agent never writes `roll.md`.
Keep `digest.md` current as you go, citing words by reference or by a
curated quote with its reference, and commit as you land — a sitting's record
must survive the session dying mid-turn.

A sitting that uncovers a second hard question does not open a second
curia for it. It becomes a line under `## Open questions` here, or a
`## Needs ruling` card if it belongs to no curia — the petition at gate 2.

## Closing (the user says when)

1. Land every edit; rewrite **Where this stands** — the last words by
   reference, `<id>/roll.md#<stamp>`, what is unsettled, the X of Y
   position for next time, and the size lines again, all three counts
   on one line — before lint, after lint, now: `digest.md 2,242 → 2,198
   → 2,310 lines · 33,516 → 32,870 → 34,020 words · context at first
   question 74k`, that last figure read from the transcript. One
   sitting's closing count is the next one's opening. If the user has ruled the
   question itself settled, set `status: settled` in the header too —
   bare `/curia` lists
   open curiae, and nothing else retires one.
2. Say what is still open on this question, by concept.
3. Print the paste-again prompt: `/curia <id>`, with the model and effort
   from the document's header. Nothing else to paste, nothing to hold in
   memory. A hand-off prompt names `/curia <id>` only for a folder that
   exists; it never proposes a new one.
4. Leave the `LIVE` file in place.
5. The user has the final word; the hook records it. Open nothing new.

## Bare `/curia`

List the open curiae, newest-touched first (recency matters;
first-in-last-out), each as its id, question and last-touched in one
line, with the count in view against the WIP limit at gate 5. Open means
`status: open` in `digest.md`'s header.
Recommend one and why, in one sentence. Open nothing until the user names
an id, and never a new one from here. If the list is long, say so
plainly — a perpetually full list is a decision-making process failure,
and folding a small question into an existing curia is always on the
table.
