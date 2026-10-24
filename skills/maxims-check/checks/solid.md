# SOLID — five object-design maxims

One file, five detectors, one row per break under `SOLID`, each row
naming its letter. Written for classes; the detectors read equally on
modules, scripts and skills, which is where this repo lives.

## Detectors

- **S, single responsibility** — a unit with more than one reason to
  change: a module whose diff history, or this diff, touches it for two
  unrelated asks. `git log --oneline -- <path>` and `read` the subjects;
  `count` the distinct reasons.
- **O, open/closed** — a new case added by editing a `switch`, `if`
  chain or table inside an existing unit, where the unit's neighbours
  extend it from outside; or the inverse, an existing extension seam
  bypassed. `read`, both lines cited.
- **L, substitution** — a subtype, override or implementation that
  weakens what the parent promised: a method stubbed to raise, a
  narrower input, a wider output, a changed exit code. `read`, the
  parent's line beside the child's.
- **I, interface segregation** — a caller made to depend on, import or
  implement more than it uses: a fat interface, a module import for one
  name, a config object passed whole for one field. `grep` what the
  caller uses, `count` against what it takes.
- **D, dependency inversion** — a high-level unit naming a concrete
  low-level one directly (a hard-coded path, a specific client, a
  global) where a neighbour takes it as a parameter. `grep` for the
  concrete name in the unit.

## Declared looks like

The author naming the coupling and why ("one script on purpose; it is
a hook, no imports"), the switch as the one home for the cases, or the
dependency as fixed by the platform, in the PR body, the commit or a
comment at the site.

## `mu` when

The target has no unit boundaries to read: a doc, a data file, a
one-line fix inside one function.

## Competes with

KISS, YAGNI and AHA. A seam D or O rows as missing keeps them, and a
layer KISS rows as indirection with one user, or YAGNI as uncalled,
keeps D and O. The `Tensions:` line names the pair at the site.
