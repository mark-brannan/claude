# Criterion 6 — How it fails

Did you change what happens when something goes wrong? Fail-closed to
fail-open or the reverse; an error now swallowed, or now raised; a
safety net removed or weakened: a snapshot, a backup, a revert path, a
transaction, a ledger entry, a test, a timeout read as a signal; a
one-way door opened where a default with an undo stood; a race or a
shared state introduced. The standing orders ask for "real safety
mechanics, transactions, reversibility, snapshots, not hedging"; this
criterion guards them.

Lineage: 10 CFR 50.59(c)(2)(ii), (iv) and (vi), the likelihood of a
malfunction, its consequences, and a malfunction with a different
result. Here a component important to safety is a hook, a guard, a
sanctioned script, a CI check, a sync, a record writer; what matters is
how it fails and what is lost when it does.

## What a failure mode is here

The `except` that passes; the `|| true`; the exit code a caller reads;
a hook's behaviour when its input is missing or malformed; a guard's
default when its config is absent; a timeout and what follows it; a
retry; a lock; a snapshot before an edit; a WIP commit before a rebase;
a dry run; a `--force`; the undo named for a default; a record written
before or after the action it records; what a sync does on conflict;
what a routine does when a step fails midway. The list is examples,
never a fence.

## Detectors

- **Fail-closed to fail-open, or the reverse** — on error or missing
  input, the thing now allows where it blocked, or blocks where it
  allowed. `git`, both sides.
- **An error swallowed or surfaced** — an exception caught and
  dropped, a non-zero exit ignored, a warning downgraded; or the
  reverse. `git`.
- **A safety net removed or weakened** — a snapshot, backup, transaction,
  revert path, dry run, confirmation, or the record that makes an action
  auditable, dropped, made optional or moved to after the action. `git`.
- **A one-way door opened** — an action that had an undo now has none:
  a delete without a snapshot, a force-push, a public post, a rewrite of
  history, a secret rotated with no fallback. `read`.
- **A timeout, retry or lock changed** — a timeout padded past the
  measured cost or removed; a retry added where it hides a fault or
  removed where it covered one; a lock dropped. `git`.
- **A new shared state or race** — two writers to one file, a sync
  that can clobber, an order of operations that now matters. `read`.
- **A test or assertion removed** — a case deleted, an assertion
  loosened, a test skipped, where the test guarded a failure mode (a
  test that guards a rule's measure is criterion 8). `git`.

A failure path refactored with the same outcome on every failure is
form.

## Declared looks like

A line under `## Substantive:` naming the file, `substantive (6)`, and
the failure whose outcome changed: on what fault, old outcome beside
new, in a clause.

## `mu` when

The target has no failure path of its own and guards none that
changed: prose, data, a pure function with no error branch.
