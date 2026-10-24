# GRASP — general responsibility assignment

Who should hold which responsibility: the unit that has the information
(information expert), the one that holds the parts (creator), a thin
coordinator (controller), low coupling, high cohesion, polymorphism over
type tests, a pure fabrication where no domain unit fits, indirection
to decouple, and protected variations behind a stable seam. One row per
break under `GRASP`, each row naming the pattern.

## Detectors

- **Information expert broken** — logic placed in a unit that has to
  fetch most of its inputs from one other unit. `count` the fields or
  calls reached into another unit (the Law of Demeter chain `a.b.c.d`
  is the grep).
- **Low coupling broken** — a new import, call or shared global between
  two units that were independent. `grep` the import graph before and
  after; `count` the new edges.
- **Low cohesion** — a unit whose members do not use each other's
  state or each other: a `utils` grab-bag grown by one more function.
  `count` the members and the members that share state.
- **Type test where polymorphism serves** — `isinstance`, `case` on a
  type tag or a string kind in a unit whose neighbours dispatch. `grep`.
- **Protected variations missing** — a point known to vary (named by a
  linked issue, a design doc or a second implementation in the repo)
  reached by callers directly rather than through one seam. `grep` the
  callers, `count` them.

## Declared looks like

The author naming the assignment and why ("the hook holds it; the lib
cannot import the hook"), in the PR body, the commit, a comment at the
site or a design doc the target names.

## `mu` when

The target has one unit: a single script or doc with no neighbours to
assign anything to.

## Competes with

KISS, YAGNI and AHA, on indirection and protected variations: a seam
GRASP rows as missing keeps them, and one they row as unneeded keeps
GRASP. DRY, where
information expert moves logic to the unit that holds the data and
leaves a copy behind.
