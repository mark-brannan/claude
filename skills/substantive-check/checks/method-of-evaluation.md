# Criterion 8 — Method of evaluation

Did you change the ruler? A change to how impact or compliance is
measured, when the measure decides whether something counts as
impactful, compliant or done. It protects the meaning of every other
criterion, not the work directly: a rule kept word for word means
something else once the test of it moves.

Lineage: 10 CFR 50.59(c)(2)(viii), a change needs prior approval when it
would "result in a departure from a method of evaluation described in
the FSAR (as updated)". The softness is in 50.59(a)(2)'s definition of
departure: a new method whose results are conservative, or essentially
the same, is no departure. NEI 96-07, endorsed by Regulatory Guide
1.187, heads the question "Does the Activity Result in a Departure from
a Method of Evaluation". In the standing orders it is the screen's
second question, "how compliance is judged".

## What a method is here

Whatever measures rather than builds. For example: the metrics
readouts and their counters and tags; a test, guard, hook or CI check
that a curia ledger or design document names as how a rule is enforced;
the curia lint's rules and the ledger review's measures; a guard's
thresholds, path classes and waivers; a success metric or done
criterion in a design document, spec or ADR; the settledness rubric;
the arete check's and this skill's own criteria. The list is examples,
never a fence: a method in a file no one thinks of as one is the case
this check exists for.

## Detectors

- **A measure redefined** — a counter, tag, rubric row, grade or
  metric whose definition, inputs or unit changed: what it counts now
  differs from what it counted. `git`, the old line beside the new.
- **A threshold moved** — a cutoff, budget, cap, window or sample size
  in a guard, check or readout. Name both values. `git`.
- **A check's reach changed** — a test assertion loosened or tightened,
  a case skipped or added, a path class or file pattern added to or
  removed from a guard, a new waiver or bypass, an exit code that now
  passes. `git`, both sides cited.
- **An evaluator changed** — the read-set a review or check reads
  (whole files to excerpts, a section dropped), the model or effort it
  runs at, or who supplies the measure (a human's call to an agent's,
  a measurement to a reading). `read`.
- **A done criterion reworded** — "done when", acceptance criteria, a
  success metric or an exit condition in a design document, curia,
  card or ADR, where the new words would pass work the old ones would
  not, or fail work they passed. `read`, both wordings quoted.
- **A governing comment** — a code comment that states what a guard
  requires, what it may not loosen, or why a measure is shaped as it
  is, changed so that the rule it states changes. `read`.

A change that only renames, moves, reformats or rewords a measure
while every result it gives stays the same is form: row it under the
detector that found it, with "what moves" reading `nothing: form only`,
so the author can declare `essentially the same` in one line.

## Declared looks like

A line under the PR body's `## Method of evaluation:` section naming
the file and one of `essentially the same`, `more conservative`, or
`less conservative: <what moves>`.

## `mu` when

The target measures nothing and is measured by nothing that changed: a
typo fix in prose no check reads, a new file no test, guard or readout
names.
