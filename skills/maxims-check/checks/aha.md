# AHA — avoid hasty abstractions

Prefer duplication over the wrong abstraction; optimise for change
first. A break is an abstraction whose shape was fixed before the uses
that would shape it existed, or one grown to fit each new use by a
flag.

## Detectors

- **The flag-fed abstraction** — a shared function or class whose body
  branches on a parameter that each caller sets differently; the
  callers would be simpler as separate code. `count` the boolean or
  mode parameters and the branches on them.
- **Abstraction ahead of its second use** — a generic name
  (`Base`, `Abstract`, `Generic`, `Strategy`, `Factory`, `Manager`)
  on a thing with one concrete form. `grep` for the name's subclasses
  and callers.
- **Wrong-shape evidence** — callers that unwrap, special-case or
  bypass the abstraction to get what they need. `read`, both sites
  cited.

## Declared looks like

The author naming the abstraction's intended uses ("shared by the three
loaders, the fourth is dotfiles#17") or the duplication as chosen, in
the PR body, the commit or a comment at the site.

## `mu` when

The target adds no shared code: a leaf change, a deletion.

## Competes with

DRY, from the WET side: a hasty abstraction AHA rows keeps DRY. SOLID
(OCP, DIP) and GRASP (polymorphism, protected variations), which ask
for the seam AHA says to wait for. WET, KISS and YAGNI agree with AHA
on a one-caller helper; each rows it.
