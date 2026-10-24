# DRY — one home per fact

Each fact, rule or piece of logic lives in one place. A break is a
second home: two copies that must change together and will drift.

## Detectors

- **Duplicated logic** — new code that matches existing code in the repo
  closely enough that a fix to one would be wanted in the other. `grep`
  for the distinctive names and literals, `count` the matching lines.
- **A restated fact** — a constant, path, threshold or rule written out
  where it already has a home, in code or in prose. `grep` for the value.
- **A parallel mechanism** — a second state machine, validation flow or
  loader beside one that already does the job. `read`, both sites cited.

## Declared looks like

The author naming the copy and why it stands apart (a hook kept free of
imports, a test fixture, a frozen snapshot) in the PR body, the commit
or a comment at the site.

## `mu` when

The target adds nothing: a deletion, a move with no copy left behind.

## Competes with

WET and AHA. A copy that DRY rows as a second home keeps WET while it
is under three and AHA while no abstraction is earned; a shared home
WET or AHA rows as hasty keeps DRY. The `Tensions:` line names the pair
at the site.
