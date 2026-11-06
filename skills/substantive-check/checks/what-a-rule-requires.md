# Criterion 2 — What a rule requires

Did you change what is required, forbidden or permitted? A rule's
obligation (must, never, always, only), its scope (who, when, where,
which paths, which repos), its strength (must to should, should to may),
its exceptions, waivers and defaults, or the trigger that brings it into
force. The standing orders' screen asks this first: "does it change
what a rule requires".

Lineage: 10 CFR 50.59(c)(2)(i) and (iii), a more than minimal increase
in the frequency or the consequences of an outcome already evaluated;
here, a rule relaxed lets a known bad outcome happen more often, and a
rule tightened changes what every agent under it must do. Both
directions are substantive: a stricter rule is still a new rule.

## What a rule is here

Any sentence a reader is bound by: a standing order; a line in
`rules/`; a CLAUDE.md instruction; a SKILL.md's "Never" list and its
steps; a rubric's criterion; a guard's or hook's stated policy (in its
docstring, its config, or the code that implements the policy); a
Mergify condition; a branch protection; a required CI check; a
CODEOWNERS line; a permission allow or deny list; a design document's
"must"; a spec row; a decisions line; a card's `default:` or `until:`.
A code comment that states what the code around it may not do is a
rule. The list is examples, never a fence.

## Detectors

- **Strength moved** — must/never/always/only to should/may/usually,
  or the reverse; a "never" qualified; an "always" given an exception.
  `git`, old beside new.
- **Scope moved** — the rule now covers more or fewer people, agents,
  repos, paths, surfaces, times or sessions; a glob widened or
  narrowed; a list of covered cases grown or trimmed. `git`.
- **An exception, waiver, default or bypass** — added, removed or
  changed: a label that skips a check, a `--force` path, a default
  value a rule falls back to, an "unless". `git`.
- **A trigger moved** — when the rule fires: the event, the condition,
  the threshold stated in the rule's own words (a threshold inside a
  measure is criterion 8). `git`.
- **A required step added or dropped** — a step a process must take,
  an artifact it must produce, an approval it must get, a check it must
  pass before merge. `git`, or `read` for a workflow's required checks.
- **A permission widened or narrowed** — what an agent, a token, a
  workflow or a user may do: an allow rule, a deny rule, a scope, a
  role. `git`.
- **An obligation reworded past its meaning** — the same rule in new
  words, where a careful reader would now do, or refrain from, something
  different in some case. `read`, both wordings quoted; the case named.

A rule reworded, rewrapped, moved, renumbered, or given a clearer
example, where every case it covered it still covers with the same
strength and the same exceptions, is form.

## Declared looks like

A line under `## Substantive:` naming the file, `substantive (2)`, and
what moved: the old requirement beside the new in a clause, with the
case that now goes differently.

## `mu` when

The target binds no one and is bound by nothing that changed: pure
data, generated output, a test of a tool's own behaviour with no policy
in it.
