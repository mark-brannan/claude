# Premature pessimization — don't pessimize prematurely

Sutter and Alexandrescu, C++ Coding Standards item 9: all else equal,
prefer the form that is not needlessly slow, large or wasteful, when
the better form costs no complexity. A break is a choice that forecloses
performance a later owner will need, taken where the efficient form was
as simple: a quadratic loop where a set lookup reads the same, a file
re-read per call, a copy where a reference served, a sync call in the
hot path with an async neighbour, a per-item network round trip.

Design-level as well: a storage shape, an identifier, or a wire format
that cannot be made fast without a migration (the `/iada` skill ranks
those costs).

## Detectors

- **Needless cost at equal complexity** — a construct with a known
  cheaper form of the same length: `in list` on a large list, string
  concatenation in a loop, `n` calls where the API takes a batch,
  reading a file inside a loop over lines. `grep` for the construct,
  `count` the occurrences and the loop depth.
- **Hot path by the record** — a unit the linked issue, a design doc or
  a metric names as hot (per-keystroke, per-request, per-Stop) given a
  form its cold neighbours use. `read` the record for the path's
  frequency.
- **Foreclosed later** — a shape fixed now (a format, a schema, an id)
  whose efficient form needs a migration later, where the efficient
  form was available now at the same cost. `read`, with the `/iada`
  rank.

## Declared looks like

The author naming the cost and the measurement that made it acceptable
("linear scan; the list is under 50, measured 0.2 ms"), in the PR body,
the commit or a comment at the site.

## `mu` when

The target has no path that runs more than once, or the record names no
budget and no frequency.

## Competes with

Premature optimization, directly. A loop may carry a row under each:
optimised before a measurement, or left slow where the fast form was
free. KISS, where the efficient form is a moving part.
