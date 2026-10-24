# WET — write everything twice, and the rule of three

A copy is cheaper than a wrong abstraction until the third use shows
what the copies share. A break is a shared home built before the third
caller, or a copy that outlived its third.

## Detectors

- **Abstraction before three** — a new helper, base class, shared
  module or template extracted while it has one or two callers. `grep`
  the callers, `count` them.
- **Coupling through the shared home** — a change in one caller that
  reached the helper and so reached a caller that did not want it:
  a new parameter, flag or branch in the shared code serving one
  caller. `git` (the diff to the helper beside its callers).
- **Past the third** — three or more copies of the same lines still
  standing. `grep` the distinctive literals, `count` the copies. This
  detector reads with DRY, not against it.

## Declared looks like

The author naming the copies as deliberate ("two copies for now, the
third decides") or the shared home as earned ("three callers:
a, b, c"), in the PR body, the commit or a comment at the site.

## `mu` when

The target adds no shared code and no copy.

## Competes with

DRY. A second copy DRY rows keeps WET; an abstraction before three WET
rows keeps DRY. The `Tensions:` line names the pair at the site. Which
was right is the owner's call.
