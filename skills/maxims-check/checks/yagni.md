# YAGNI — you aren't gonna need it

Built for the need in hand. A break is code, options or generality for a
need no caller and no record has.

## Detectors

- **No caller** — a new flag, parameter, branch, export or file that
  nothing in the read-set calls or reads. `grep` for each new name
  outside its definition and tests.
- **Generality with one case** — a parameter, plugin point or format
  version that has one value in use. `grep` its call sites, `count` the
  distinct values.

## Declared looks like

The author naming the hope it is built for: "intentionally ahead of
need, because ...", a linked issue for the future use, a comment at the
site, or a design doc, curia or issue in any repo (the state repo
included) that names the stub, flag or parameter as the seam for a
planned feature. A placeholder ahead of a cross-repo interface, so
named, reads `declared: yes`, not a break.

## `mu` when

The target adds nothing new to call: a deletion, a fix inside an
existing path.

## Competes with

SOLID (OCP) and GRASP (protected variations): the extension point YAGNI
rows as uncalled is the one they ask for. Premature pessimization: the
simple form chosen now may be the one that cannot be made fast later.
