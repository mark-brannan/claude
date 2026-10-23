# Decided: <id>

<!-- The ledger, for the agent and lint; digest.md is its synthesis. One
     line per ruling, landed at once in the sitting: what was ruled, who
     settled it and how firmly (pen / pencil), the date, the reference
     `<id>/roll.md#<stamp>`, and a link to what it produced, if anything.
     A pen line may carry two more fields, optional, after its reference:
     `embedded: <guard, hook, test or CI check, by path> (<date>)`, the
     mechanism that fires on the governed action, and `effective when:
     <count> <from> → <to> by <date>`, the number the ruling named at pen
     time and the date it is due to have moved, with `effective: pending,
     review <date>` until the review; a pen line with neither is legal,
     and lint lists it (SKILL.md, The ledger as a queue). One line, filled:
     - A runaway worker is bounded by spend — pen, 2026-10-22,
       [roll.md#20261022t074012z](roll.md#20261022t074012z).
       embedded: `hooks/spend-gate.py` (2026-10-22). effective when:
       workers killed by spend 3 → 0 by 2027-01-22. effective: pending,
       review 2027-01-22
     Grouped by topic under bold headings. A queue, not an archive
     (SKILL.md, The ledger as a queue): lint moves pencil to pen, marked
     as lint's, where the line's link resolves to a merged commit, spec
     row or decisions line, and a pen line leaves for its spec row or
     decisions line, moved never copied. A line a later ruling replaces
     moves under Superseded, prefixed with what replaced it, and is
     deleted at the next prune; git and the roll keep it. -->

**Superseded**
