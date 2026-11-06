# Criterion 5 — What can act, and its reach

Did you give something a new power, or a longer arm? A capability or a
reach that did not exist before the change, or one removed: code that
runs automatically where a person acted; a permission widened; remote
content fetched and executed; a credential held, printed or moved; a
writer added to a record; a push to a protected branch; a post to a
public surface; a deletion that nothing else could do; a guard or a
sandbox removed from a path. This repo's own instruction to a reviewer
names the set: "anything that executes automatically (hooks), widens
permissions, fetches and runs remote content, or puts a credential in
the diff." A change here is substantive even when every test passes,
because a test proves the thing does what its author meant, not that
the meaning is safe.

Lineage: 10 CFR 50.59(c)(2)(v), the possibility of an accident of a
different type than any previously evaluated. A new power is a new way
for things to go wrong that no existing evaluation covers.

## What a capability is here

A hook, a guard, a cron, a routine, a workflow trigger, a Stop-hook
action; a `permissions:` or `allowedTools` grant; a token, a key, a
secret and where it is readable; a `curl | sh`, an unpinned action, a
dependency added; a script that writes, pushes, posts, labels, merges,
deletes or publishes; a sandbox, container or sops boundary; a public
surface (an artifact published, a comment posted, an issue filed); the
`bin/` tools and what each may touch. The list is examples, never a
fence.

## Detectors

- **A new automatic actor** — code that now runs on an event, a timer
  or a stop where nothing ran, or that ran only when asked. `git`.
- **A permission or tool grant widened** — an allow rule, a token
  scope, an `allowedTools`, a `permissions:` block, a sudo, a
  `dangerouslyDisableSandbox`. `git`, both sides.
- **Remote content executed** — a fetch whose result runs; an action,
  package or script added or unpinned; a version pin loosened. `git`.
- **A credential's exposure** — a secret read, echoed, logged, moved,
  passed to a new process, or granted to a new workflow; the sops key's
  private half touched in any way. `grep` and `git`.
- **A new writer or a new destination** — something now writes to a
  record, a branch, a repo, a board, a public surface or an external
  service it did not reach before. `git`.
- **A guard, sandbox or boundary removed or bypassed** — a path no
  longer fenced, a check no longer run, a container no longer used.
  `git`.
- **A destructive reach** — delete, force-push, rewrite history, purge,
  reset, where the change adds the capability or widens what it can
  touch. `grep` and `git`.

A capability refactored, renamed or moved, with the same actors, the
same grants, the same destinations and the same fences, is form.

## Declared looks like

A line under `## Substantive:` naming the file, `substantive (5)`, and
the power or reach that changed: what can now act, on what, that could
not before, in a clause.

## `mu` when

The target acts on nothing and grants nothing: prose, data, a test
that only pins behaviour.
