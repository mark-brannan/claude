# Fail fast

Detect a bad state at the first point it can be known and stop there,
loudly, rather than carry it on. A break is a defect that travels: a
check that could have run earlier, an error swallowed, a default that
stands in for a missing value.

## Detectors

- **Swallowed error** — a `catch`, `except`, `|| true`, `2>/dev/null`
  or `set +e` around a call whose failure the rest of the unit then
  assumes did not happen. `grep` for the construct, `read` what
  follows.
- **Late check** — a validation of an input that runs after the input
  was used, or at the leaf after several callers passed it along.
  `read`, the first use beside the check.
- **Default for a missing thing** — `.get(key, default)`, `${VAR:-x}`
  or a fallback branch standing in for a value the record says is
  required. `grep` the record for whether it is required.
- **Guessed recovery** — a retry, fallback or repair with no bound, no
  log or no counter. `grep` the branch for its bound and its log.

## Declared looks like

The author naming the tolerance and its reason ("the hook must never
block Stop; errors go to the log"), in the PR body, the commit, a
comment at the site or the repo's rules.

## `mu` when

The target has no failure path: a doc, a data file, a pure function
with total inputs.

## Competes with

Robustness. A hook that must never block the harness is a declared
robustness break and a declared fail-fast break at once; row both. The
`Tensions:` line pairs them.
