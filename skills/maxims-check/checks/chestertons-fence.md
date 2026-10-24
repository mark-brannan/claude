# Chesterton's fence

Do not remove a thing until you know why it was put there. A break is a
removal, a loosening or a bypass whose original reason the diff and the
record never name.

## Detectors

- **Removal without its reason** — a deleted check, guard, branch,
  config line, dependency pin or test, where neither the PR body, the
  commit nor a comment names what it was for and why that no longer
  holds. `git log -S` or `git blame` on the removed lines for the
  commit that added them; `read` whether the target names it.
- **Loosened without its reason** — a threshold raised, a timeout
  lengthened, a lint rule disabled, a permission widened, with no
  reason named. `git`, the old line beside the new.
- **Bypassed without its reason** — a `--no-verify`, a `# noqa`, a
  `skip`, an `allow` list entry added, with no reason at the site.
  `grep` for the bypass marker.

## Declared looks like

The author naming the fence and why it is no longer needed ("added in
#143 for the pre-Mergify queue; the queue checks this now"), in the PR
body, the commit or a comment at the site. "Unused" counts only with
the `grep` that showed it.

## `mu` when

The target removes, loosens or bypasses nothing.

## Competes with

YAGNI and KISS, which a removal keeps: the fence they would call a part
with no caller is the one this check rows as gone unexplained. The
`Tensions:` line names the pair at the removal; the owner reads the
commit that built it.
