# SoC — separation of concerns

Each unit addresses one concern, and the concerns a reader would keep
apart (what to do, how to show it, where to keep it, how to reach it)
live apart. A break is two concerns in one unit, or one concern spread
over units that each do a bit of it.

Overlaps SOLID's S: S reads reasons to change, SoC reads kinds of
work. A unit that mixes rendering with storage rows here; a unit
changed for two unrelated asks rows under S; a unit that does both rows
under each.

## Detectors

- **Mixed layers** — presentation, logic, persistence or transport in
  one function or file: a formatter that writes a file, a hook that
  parses, decides and prints. `read`, with the lines of each concern
  cited; `count` the concerns.
- **A concern in many homes** — one kind of work (argument parsing,
  path resolution, output formatting) done a little in each of several
  units rather than in one. `grep` for its distinctive calls, `count`
  the sites.
- **Cross-cutting by hand** — logging, auth, retries or metrics
  threaded through each unit's body where the platform offers a
  decorator, middleware or wrapper. `grep` for the repeated call.

## Declared looks like

The author naming the mix and its reason ("one file, so the hook has no
imports"), in the PR body, the commit or a comment at the site.

## `mu` when

The target is one concern by its nature: a data file, a pure doc, a
single-purpose script under a screen long.

## Competes with

KISS, where the split is a layer with one user; WET and AHA, where the
one home for a concern is an abstraction before its third use.
