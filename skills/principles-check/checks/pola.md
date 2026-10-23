# POLA — the principle of least astonishment

The item does what its name, its record and its neighbours lead a
reader to expect. Every other check's undeclared, seen-after break is
also an astonishment; this check is for the ones no other principle
names.

## Detectors

- **Name against behaviour** — a function, flag, file or skill whose
  name or header says one thing and whose body does another or more: a
  reader that writes, a check that edits, a `--dry-run` that is not dry.
  `read`, with both lines cited.
- **Scope against the record** — files or behaviour the diff changes
  that the linked issue, card or PR title did not ask for. List the
  touched paths with `gh pr diff --name-only` and set them against the
  ask. `gh`.
- **A changed default** — an existing default, exit code, output shape
  or path that now differs for a caller who changed nothing. `git`
  (the old line beside the new).
- **Against house convention** — a pattern the repo's rules files name,
  done another way here without saying why. `grep` for the convention,
  `read` for the break.

## Declared looks like

The PR body or commit naming the wider scope or the changed default;
a comment at the site saying why the name and behaviour differ.

## `mu` when

The target changes no behaviour a reader could expect anything of: a
typo fix, a pure deletion of dead code.
