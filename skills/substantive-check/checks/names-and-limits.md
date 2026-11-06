# Criterion 7 — Names and limits

Did you rename a thing others call by name, or move a stated limit?
Two kinds of change that look small in a diff and are expensive
everywhere else. A name: an identifier, a label, a tag, a field, a
command, a term of art, a heading others link to, a curia id, a
decisions line's key word. Every consumer, every link, every memory
and every habit holds the old one, so a rename is never cosmetic
(IADA: identifiers are the costliest layer to change, since every
party must change with them). A limit: a cap, a budget, a window, a
WIP limit, a word count, a retention, a sample size, stated in a rule
rather than inside a measure (a threshold inside a measure is
criterion 8; a change that fits both gets a row under each).

Lineage: 10 CFR 50.59(c)(2)(vii), a design basis limit exceeded or
altered; for names, the IADA ranking and the record's own rule that
internal names are not cosmetic.

## What a name or a limit is here

A skill name, a slash command, a hook's name, a `bin/` tool's name; a
label on GitHub; a tag in a transcript the metrics count; a field in a
card, a ledger line, a JSON row, a config key; a section heading others
anchor to; a curia id; a vocabulary term a design document defines; an
env var; an artifact name. A limit: `max-reviews`, a WIP of 2 to 3, a
1,500-word cap, a 5-minute job, a 28-day window, a $ budget, a cap on
children per driver, a retention period. The list is examples, never a
fence.

## Detectors

- **An identifier renamed** — a name any other file, repo, link, tool,
  memory or person refers to, changed; include a heading others anchor
  to and a term a document defines. `grep` for the old name outside the
  diff; cite one consumer or say none found.
- **A name's meaning moved** — the same name now denotes something
  wider, narrower or different (a tag counted differently is also
  criterion 8). `read`.
- **A stated limit moved** — a cap, budget, window, count, size, age or
  duration a rule states, changed. `git`, both values.
- **A limit added or removed** — a bound where none stood, or none
  where one stood. `git`.
- **A unit changed** — minutes to turns, dollars to tokens, lines to
  files, on a limit a rule states. `git`.

A name corrected for a typo where nothing refers to the misspelling,
or a limit restated in the same unit and value, is form. A rename that
touches every consumer in the same change is still substantive: the
row says so and cites the consumers updated, and the reader weighs it.

## Declared looks like

A line under `## Substantive:` naming the file, `substantive (7)`, and
the name or limit that moved: old beside new, and one consumer of it.

## `mu` when

The target names nothing others refer to and states no limit, and is
referred to and bounded by nothing that changed.
