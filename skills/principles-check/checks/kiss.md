# KISS — keep it simple

The smallest form that does the whole job. A break is a moving part the
need does not call for.

## Detectors

- **Indirection with one user** — a new layer, interface, registry,
  base class or config file with one implementation and one caller.
  `grep` for each new name's uses.
- **Parts against the ask** — new files, functions, parameters and
  branches, set against what the linked record asked for. `count`.
- **A hand-built thing the platform has** — code that re-does what the
  language, a library already in the manifest or a tool the repo uses
  provides. `grep` the manifest and the repo for it.

## Declared looks like

The author naming the extra part and the need it is for, in the PR body,
the commit or a comment at the site.

## `mu` when

The target adds no parts: a deletion, a rename, a doc that governs no
mechanism.
