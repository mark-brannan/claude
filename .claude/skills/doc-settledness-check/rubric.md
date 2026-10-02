# The settledness rubric — twelve rows

Read by the measuring sub-agent. Each row gets a measured value and a mark:
`ok`, `--` (a gap to declare), or a short word when neither fits
(`choose at PR`). A row that does not apply reads `n/a` in the measured
column and leaves the mark blank. A mark is a reading, not a gate.

After the table, one line per row saying **how** it was measured:
`count` (counted in the text), `grep` (a pattern search), `gh` (a GitHub
query), `git` (history), or `read` (judgment on reading). A row measured by
`read` says so; that is the honest answer, not a failure.

## Rows

1. **open questions** — how many questions are still open, of how many
   asked. Open ones ride into the public record as "Open". Outside a curia:
   an "Open questions" or "Unresolved" section, TODO/TBD markers, or
   questions left unanswered in review comments on a PR.
2. **decisions by owner** — each decision, by who made it and at what
   grade: the user's *pen* (ruled), *for now* (explicitly provisional),
   *pencil* (a default taken, tacit approval); or an agent's. Outside a
   curia, where grades are not written: count decisions that name an owner,
   and those that name none.
3. **agent defaults to declare** — decisions an agent took that touch the
   design, named so the reader knows no human weighed in.
4. **lint** — the last lint of the document: date, findings applied, any
   ruling-grade finding still open. No lint record in the read-set →
   `not found`, mark `--`; the reader cannot tell never-run from unkept.
5. **reopen condition** — one line: the evidence from loop one that sends
   this back to deliberation. When absent, the stub is: *"unsettled;
   reopens by the user's word in an agora or a direct order; no automatic
   trigger yet."* Absent → measured `stub`, mark `--`.
6. **unverified claims** — anything in the settled text marked unverified,
   unchecked, "should", "probably", or a path/link that does not resolve.
7. **private terms** — hosts, boats, accounts, private plans in the text
   bound for (or already in) a public repo. A curia's derived sections are
   bound for a public repo, so they are measured even though the folder is
   private. `n/a (private)` only when nothing in the target is bound
   anywhere public.
8. **sittings** — *curia only*: sittings opened, and any left unclosed.
   Opened: the `roll.md` entries whose prompt begins `/curia <id>`, which
   every sitting opens with; the roll has one entry per prompt, so its
   entry count is not the answer. Unclosed: a `LIVE` file, with its
   session and age. A curia with no `roll.md` yet → `not found`, mark
   `--`. Elsewhere `n/a`.
9. **promoted so far** — *curia only*: each link a Decided line carries to what
   the curia produced, with its PR or issue state. Elsewhere `n/a`.
10. **implementation** — whether loop one has an issue or PR against this
    design. Informational, never blocking; an ADR may precede its code.
11. **destination** — where the public record goes in this repo, and
    whether the promote machinery (an ADR directory, an index, a template)
    exists there. Already public → where it is.
12. **related open work** — open curiae, issues and PRs whose question
    overlaps or depends on this one; the record names them.

## Format

```
| check                     | measured                                  |    |
|---------------------------|-------------------------------------------|----|
| open questions            | 2 of 5                                    | -- |
| decisions by owner        | user 3 (pen 2, pencil 1) · agent 1        | ok |
| agent defaults to declare | 1 — toil (file naming)                    | ok |
| lint                      | not found                                 | -- |
| reopen condition          | stub                                      | -- |
| unverified claims         | 0                                         | ok |
| private terms             | none                                      | ok |
| sittings                  | n/a                                       |    |
| promoted so far           | n/a                                       |    |
| implementation            | example-org/widget#12 open                | ok |
| destination               | docs/adr/ exists, INDEX.md present        | ok |
| related open work         | 1 — example-org/widget#9 (same schema)    | -- |

Verdict: not yet — two open questions and no lint; the rest would ride
as declared gaps.
```

The verdict is one line: `settled`, `good enough` (with the gaps it
would carry), or `not yet` (with what stands in the way).
