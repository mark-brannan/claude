# Decided: <id>

<!-- The ledger, for the agent and lint; digest.md is its synthesis. One
     line per ruling, landed at once in the sitting: what was ruled, who
     settled it and how firmly (pen / pencil), the date, the reference
     `<id>/roll.md#<stamp>`, and a link to what it produced, if anything.
     Grouped by topic under bold headings. A queue, not an archive
     (SKILL.md, The ledger as a queue): lint moves pencil to pen, marked
     as lint's, where the line's link resolves to a merged commit, spec
     row or decisions line, and a pen line leaves for its spec row or
     decisions line, moved never copied. A pen line may carry two
     optional fields after its stamp, `embedded: <guard, hook, test or
     CI check, by path> (<date>)` and `effective when: <count> <from> →
     <to> by <date>`, with `effective: pending, review <date>` until the
     review (SKILL.md, The ledger as a queue, Embedded and effective); a
     pen line with neither stays legal, and lint counts them from
     `ledger-review`. One line, filled, for the shape, on one physical
     line as `ledger-review` reads it:
     - A runaway worker is bounded by context size and by spend — pen, 2026-10-22, [roll.md#20261022t074012z](roll.md#20261022t074012z). embedded: `hooks/spend-gate.py` (2026-10-22). effective when: sessions past the spend cap 4 → 0 by 2026-11-22; effective: pending, review 2026-11-22
     A line a later decision replaces
     moves under Superseded, prefixed with what replaced it, and is
     deleted at the next prune; git and the roll keep it. -->

**Superseded**
