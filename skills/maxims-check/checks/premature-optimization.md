# Premature optimization — the root of all evil

Knuth, in full: "We should forget about small efficiencies, say about
97% of the time: premature optimization is the root of all evil. Yet we
should not pass up our opportunities in that critical 3%." A break is
work spent making something faster, smaller or cleverer before a
measurement against the plain alternative and the real budget said it
was needed. Design-level more than code-level: a format, a cache, a
package split or a protocol counts as much as a loop.

The record behind this check is the portolani post-mortem
(mark-brannan/portolani#25): a raw file measured once, a custom
compact format minutes later, three repos by evening, and no benchmark
against the plain file until weeks on.

## Detectors

- **Optimization without a baseline** — a cache, index, custom format,
  compression, batching, hand-rolled parser, lazy path or early-exit
  added with no measurement of the plain form in the PR, the linked
  issue or a design doc the target names. `gh` and `read` the record
  for a number; `grep` the diff for the mechanism.
- **Ratio without a budget** — a measurement given as a ratio or a
  percentage ("5.5× smaller") with no absolute figure and no budget it
  is set against. `read` the record, `count` the absolutes.
- **Baseline against the clever** — a benchmark that compares the
  mechanism with other mechanisms and never with the plain alternative
  (the raw file, the library call, the sequential loop). `read` the
  benchmark's cases.
- **Fidelity traded unrecorded** — an optimization that drops
  precision, cases, fields or detail, with the loss unstated or stated
  only as a ratio. `read` the record for what was dropped and for whom
  it matters.
- **A drop threshold in the diff** — a constant or flag that discards
  or coarsens input to save size or time: a minimum extent, area or
  length, a tolerance, an epsilon, a quantisation scale, a sample rate,
  a row limit, a truncation. `grep` the diff for each one and name, in
  the record's units, what falls under it (the features below the
  minimum, the digits past the scale). A threshold the record never
  names, or names without what it drops, is a row, even when the PR's
  ask is a feature and not a speed-up.
- **Measured in the wrong quantity** — the figure that justifies the
  mechanism is in one quantity and the budget it answers to is in
  another: bytes on disk or uncompressed against a budget spent on the
  wire after gzip, file size against parse time or memory, a
  microbenchmark against end-to-end latency. Name the budget's quantity
  and the measured one; a mismatch, or a budget with no quantity
  named, is a row. `read` the record for both.

## Declared looks like

A measurement: the plain alternative's figure, the budget it broke, the
mechanism's figure, in the PR body, the linked issue or a design doc
the target names. "Measured: raw 53 KB gzipped against a 50 KB budget;
simplified 8 KB" is a declaration. A ratio alone is not, and neither
is a figure in another quantity than the budget's.

## `mu` when

The target adds no mechanism whose purpose is speed, size or cost: a
doc, a fix, a feature with no performance claim. A drop threshold is
such a mechanism wherever it sits, so a diff that adds one never reads
`mu` here.

## Competes with

Premature pessimization, directly: the simple form chosen now may be
the one that cannot be made fast later. Robustness and fail fast, where
an optimization removes a check. Both rows stand.
