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
- **A check's reach changed** — only where the test or guard is itself a
  method (see above): it decides whether a rule is kept or work is done.
  Its assertion loosened or tightened, a case skipped or added, a path
  class or file pattern added to or removed from it, a new waiver or
  bypass, an exit code that now passes. A test of a tool's own behavior
  (a new case for a new code path) is not a method. `git`, both sides
  cited.
- **An evaluator changed** — the read-set a review or check reads
  (whole files to excerpts, a section dropped), the model or effort it
  runs at, or who supplies the measure (a human's call to an agent's,
  a measurement to a reading). `read`.
- **A done criterion reworded** — "done when", acceptance criteria, a
  success metric or an exit condition in a design document, curia,
  card or ADR, where the new words would pass work the old ones would
  not, or fail work they passed. `read`, both wordings quoted.
- **A governing statement the code contradicts** — a rule, threshold or
  behavior a doc states that the code does not do. `read`, both quoted.
  Where the change made the contradiction, it is a row like any other.
  Where it stood before the change, it is still called out, but in the
  output's standing block, not as a row: it asks the author for no
  declaration.
- **A governing comment** — a code comment that states what a guard
  requires, what it may not loosen, or why a measure is shaped as it
  is, changed so that the rule it states changes. `read`.

A change that only renames, moves, reformats or rewords a measure
while every result it gives stays the same is form: one row per file
reading `nothing: form only` with a count and the detectors that found
them, so the author can declare `form` in one line. A method change
whose results are `essentially the same` in every case is form too, by
50.59(a)(2)'s own words (no departure): the file reads `form` unless
another criterion fired; `more conservative` and `less conservative`
are substantive.

## Declared looks like

A line under the PR body's `## Substantive:` section naming the file,
`substantive (8)`, and one of 50.59(a)(2)'s three values: `essentially
the same`, `more conservative`, or `less conservative: <what moves>`.
Criterion 8 keeps those words because they are its lineage's: a method
change is a departure only when its results are not conservative or
not essentially the same.

## `mu` when

The target measures nothing and is measured by nothing that changed: a
typo fix in prose no check reads, a new file no test, guard or readout
names. Also a tool that acts and judges nothing, and tests that only
pin its own behavior: a new branch in `bin/sign-commits` that signs a
PR's commits, with cases for it, moves no rule's measure.
