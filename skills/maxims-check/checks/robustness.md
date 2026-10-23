# Robustness — Postel's law

Be conservative in what you send, liberal in what you accept. A break is
a sender that emits what the spec allows but a plain receiver would not
take, or a receiver that rejects what the spec allows.

The rival reading, RFC 9413 (the harmful consequences of the robustness
principle), rows the tolerant receiver itself as a break under
`fail-fast`: tolerance hides the sender's defect and freezes it into
the protocol. Both rows stand.

## Detectors

- **Strict receiver** — a parser, validator or loader that rejects
  input the format, schema or caller's record allows: a required field
  the spec marks optional, a case-sensitive match on a case-insensitive
  name, a version pin on a compatible range. `read`, the spec's line
  beside the code's; `grep` for the raise or exit.
- **Loose sender** — output, a file written or an API call that uses
  the edge of what the consumer accepts: optional fields relied on,
  unordered output where the consumer reads order, a new field the
  consumer's parser was not shown. `grep` the consumer for the field.
- **Silent repair** — a receiver that fixes or guesses at bad input
  and does not log, count or return that it did. `grep` the branch for
  a log or a counter.

## Declared looks like

The author naming the strictness or tolerance and why ("rejects
unknown keys on purpose; see RFC 9413"), in the PR body, the commit, a
comment at the site or the format's own spec.

## `mu` when

The target reads no input from, and sends no output to, another party:
a pure doc, an internal refactor of one function.

## Competes with

Fail fast, directly; POLA, where tolerance means the unit does more
than its contract says. The same receiver may carry a row under each,
paired on the `Tensions:` line.
