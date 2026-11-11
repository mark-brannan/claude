# The curia's layers and its ledger

<!-- pen (the user, 2026-10-02): roll.md for the words, digest.md for the
     document, the reference form `<curia>/roll.md#<stamp>` (amended by
     the user the same day from `:<stamp>`, with the session id dropped from
     the heading: the anchor must be the bare stamp). pencil: the
     rest of the layout and private-deliberation/public-produce are
     assumed, not ruled (design doc, open question on /curia <id>
     mechanics). pen (the user, 2026-10-02, session 4d6d005a): "References
     plus cleaned, edited, curated quotes. The linting agent may make
     minor edits for typos, readability, or to cut unnecessary sections
     of a long quote." It replaces "agents never quote" (#489). There is
     no pin: nothing in roll.md moves, and curation in the digest does
     the pin's work (the curia's Design section on curation). No separate file lists what a curia
     produced: each Decided line links its own, and the ADR link goes in
     digest.md's `adr:` header field at promotion. -->

**Layers, each with its reader and home.** `roll.md` is the user's words,
as above. `decided.md` is the ledger, for the agent and lint: one line per
ruling — what was ruled, pen or pencil, the date, the stamp — by topic, a
**Superseded** group last; a ruling lands there at once. `digest.md` is
the design, for a human reading cold, shaped like an ADR
([template.md](template.md)): the header, **Where this stands**, **The
problem**, **The design** — one numbered section per mechanism, each in
five parts: what hurt, the decision in prose, what it costs to change in
IADA terms, what is open, the rulings by stamp, pen then pencil —
**Vocabulary**, **Open questions**, **Notes and inputs**. **The decision**
says only what the ledger holds, sentence by sentence; the other four parts
are the agent's reading of the roll, the inputs and the code. A pencil
stamp under **Rulings** is glossed with what it holds, so a reader knows
which sentences may move. A section's heading is the record's own words
for the mechanism, never a coined name.
The worked example of one Design section sits in a curia's own `inputs/`
folder, reached from its ledger, never from here. Specs are not in the folder:
a spec lives in the public repo beside the code it governs
(`docs/work-item-lifecycle.md` in the claude repo is the precedent for
the shape; its roll stamps predate the ruling), each row marked pen or
pencil with its date and citing the line in its repo's public decisions
file once one exists, never a roll stamp or a Design section number; the
ledger line links the row, not the other way. A spec takes three inputs: the
rulings, the existing code, and the incidents in `inputs/`. One document
per question; parallel files per layer and per form. A Design section
leaves the digest only when it is promoted to an ADR in its public repo,
and a line linking the ADR stays in its place. The epic issue below
replicates `digest.md` alone.

<!-- pencil (2026-10-07): a trial, all of it — the ledger split out of the
     digest, the digest as an ADR-shaped narrative, forms as sidecar
     files, synthesis by the edit facet, lint's narrative-against-ledger
     check, specs in the public repo. The user's lean on the agent's
     proposal in a curia sitting of that day, not
     ruled; its ledger holds the stamps. -->

**Prune what agents load, never the record.** `roll.md` and
`agent_decisions.md` are append-only and never shrink, as is `pruned.md`. The digest's header
carries a `read-from:` line, one stamp per append-only file a sitting reads —
`roll.md#<stamp> · agent_decisions.md#<stamp>` — and an agent reads each
file from that stamp to its end, never from the top. Lint moves each
stamp forward to the last one **Where this stands** cites; a file it
cites nothing from keeps its stamp, and `none` means the top. A repo's public decisions log, once
one exists, gets its own read-from entry in the digest header, pointing
at a line of its own; the log carries nothing back. For a settled ruling
an agent reads the spec, whose row cites the decisions line, not the log
that produced it. `decided.md` takes no read-from point: it is pruned by
moving lines out ([The ledger as a queue](#the-ledger-as-a-queue)).

<!-- pen (the user, 2026-10-07): prune what agents load, never the record;
     a stored starting point per append-only file, read from there to
     the end; the curia's ledger holds the stamp. pencil: the
     field's name and form, `read-from:`, that lint is what moves it, and
     that decided.md takes none, are the agent's default. -->

## The ledger as a queue

A line enters `decided.md` as pencil — pen only when the user's words say
so — with its stamp, and moves on:

| From | To | Trigger | Who |
|---|---|---|---|
| pencil | pen, marked as lint's | the line's link resolves to a merged commit, spec row or decisions line and the user has not reversed it | lint, shown in its diff and listed in its findings |
| pen, governs code | a spec row in the public repo beside the code, citing its repo's decisions line; the ledger line links the row. The steering rung of embedded, below | the spec PR merges | the spec PR's author; lint moves the ledger line to `pruned.md` |
| pen, governs how we work, not code | the standing orders or `rules/code.md` | the user's hand | the user |
| pen, settled and built, no spec row | the repo's public `docs/decisions.md`, one line in [the agora's format](../agora/SKILL.md#where-a-ruling-lands) | an agora or the user's hand | lint moves the ledger line to `pruned.md` |
| pen, private, no work to file | stays | scoping promotes it when it files the work | scoping |
| refused name or discarded idea | one line in agent-notes Working memory (*refused: …*), and the line itself to `pruned.md` with its reason | the prune | lint |
| superseded | the **Superseded** group, then to `pruned.md` with what replaced it | the prune | lint |

**The archive.** `pruned.md`, in the curia's folder, is append-only like
`roll.md`: lint appends each line it prunes from `decided.md` whole, with
its date and its reason (spec row, decisions line, superseded by,
refused). Nothing in it is edited or deleted, and no sitting reads it, at
open or after: it is the record, not what agents load, and no `read-from:`
points at it. Existing curiae get no backfill.

One home per fact: the ledger line itself is moved whole to the archive,
never copied. Its public destination carries no stamp and keeps its
brief *because*; the digest's Rulings resolve through the ledger line,
which stays until the prune and then through its spec row or decisions
line.
Beyond the table, one more hop: a decisions log is periodically pruned and
rewritten as a spec or a requirement. Settled decisions leave every curia;
nothing accumulates here for its own sake.

**Embedded and effective.** Two optional fields on a pen line, after its
stamp: `embedded: <guard, hook, test or CI check, by path> (<date>)` and
`effective when: <count> <from> → <to> by <date>`, the second carrying
`effective: pending, review <date>` until the review. A pen line with
neither stays legal: nothing asks for the fields, and nothing gates the
move from pencil to pen on them; when the line leaves for its spec row or
decisions line, the fields go with it. Lint reports the count of pen lines with
neither and lists the reviews past due, read from `ledger-review` in
`bin/`, which prints them by curia; a count and a list, never an ask.

Embedded has three rungs. Prose is a good intention. A spec row alone is
steering: partially and probabilistically embedded, with a measurable
effect and no determinism, fit for defence in depth and not for a safety
rule; the spec-row step in the table is this rung. A spec row backed by a
Given-When-Then test or an equally robust, mature and well-defined test,
a guard, a hook or a CI check is a mechanism, and the `embedded` field
names it by path.

A decision is effective when the count it named at pen time has moved from
`<from>` to `<to>` by the date it named. For a tested spec row the
measure is the test's pass rate and its git history showing no drift.
The counters that exist today are the metrics
readouts' decisions by kind, corrections, rebukes, overrides and
pushback; a decision that names a count none of them keeps names the
counter it needs, or it has no effective state to reach. A review whose
count did not move is a finding for the sitting, never lint's fix.

<!-- pen (the user, 2026-10-22, outside a sitting; the curia-loop
     ledger holds the line and its link): the three rungs, a spec
     row as partially embedded, a tested spec row as embedded, and pass
     rate with no-drift history as its effective measure; also that pen
     stays unconditional on either state. pencil (the secretary): the
     field names `embedded` and `effective when`, the pending form, and
     that lint owns the review rather than the agora, the table row
     named as the steering rung, and a failed review as the sitting's
     finding. Reopens at the curia-loop sitting that reads the input of
     2026-10-22 against the digest's exit-test line of the same day.
     Undo: drop the two fields and lint's bullet; the queue table stands
     without them. -->

<!-- pencil (2026-10-07): the table is the agent's, from its proposal in
     a curia sitting of that day, not yet ruled; the user's
     lean, "I think they do", and the extra hop; the curia's
     ledger holds the stamps. The Superseded row joins the trial's
     Superseded group to the proposal's prune; the agent's
     reconciliation. The archive's shape (`pruned.md`, append-only, a
     reason per line, read by no sitting) is pencil, the agent's default.
     Lint marks a line it promotes as its own, so a pen
     line the user made stays distinguishable; making the promotion a
     finding instead is the undo. -->

