# Criterion 1 — Purpose and values

Did you change what the thing is for? A change to the stated purpose
of a system, a rule, a skill or a repo; to whom it serves and whom it
refuses; to the values it names and the weight it gives them; to what it
calls good, harm, success or waste. This is the side of the screen with
the most potential to do harm: not a wrong line of code but a wrong
idea of what the code is for, carried forward by every reader and agent
that follows it. The standing orders open with "What this is for"; this
criterion guards that section and every statement of the same kind.

Lineage: the design basis itself, which 10 CFR 50.59's eight criteria
exist to protect; in the standing orders, loop two's governing
variables (Argyris), and "Values, risk, direction and what matters are
mine." A purpose statement sits above design and design above code
(the standing orders, "Write at the reader's altitude"); a change here
changes every layer below it.

## What a purpose statement is here

The opening of a governing document that says what it is for; a tenet,
a principle, a "why" paragraph; a statement of whom the work serves or
of what it refuses to do; a value named by weight ("a flourishing life,
not throughput"); the stated aim of a check, a guard, a hook or a skill
(the first paragraph of a SKILL.md, the docstring that says what a
guard is for); an ADR's context and consequences; a card's `risk:` or
`judgment:` field; a repo README's first paragraph. The list is
examples, never a fence.

## Detectors

- **A purpose reworded so the aim moves** — what the thing is for,
  stated differently such that a reader would now pursue a different
  end, or weigh two ends differently. `read`, both wordings quoted.
- **A value added, dropped or reweighted** — a named value appears,
  disappears, or moves in rank relative to another ("over", "before",
  "never at the cost of"). `read`.
- **Who it serves or refuses** — the people or uses a document names
  as served, or as out of scope, change. `read`.
- **A refusal or a "never" on values** — a line that refuses something
  as wrong, not merely as unavailable, added, removed or softened.
  `git`, old beside new.
- **A good or a harm redefined** — what counts as a good outcome, a
  harm, a waste or a success in the document's own terms. `read`.

A purpose restated in other words, moved to another section or file,
or trimmed of an example while the aim, the values and their weights
stay, is form.

## Declared looks like

A line under the PR body's `## Substantive:` section naming the file,
`substantive (1)`, and what moved: the old aim beside the new in a
clause.

## `mu` when

The target states no purpose and is governed by none that changed: a
lockfile, generated code, a data file, a test that pins behaviour.
