# Fixtures: cases the check must get right

Each case is a literal diff, small enough to read whole, with the
verdict and criteria the check must return. The first two are the
user's smoke tests of 2026-11-06. A case the check gets wrong in the
field goes here with the review finding that caught it, and the
criterion that should have fired grows a detector. A runner may walk
these one day; until then a change to any criterion is read against
them by hand, and the PR says so.

| # | Case | Expected verdict | Criteria |
|---|---|---|---|
| 1 | A standing order rewrapped | form | — |
| 2 | A spec embedded in code beside a behaviour change | substantive | 2, 8 |
| 3 | A Mergify condition renamed only | form | — |
| 4 | A workflow gains a required check before merge | substantive | 2, 4 |
| 5 | A hook's missing-input path turned from fail-closed to fail-open | substantive | 6 |
| 6 | A standing order's "never" softened to "avoid" | substantive | 2 |
| 7 | A skill's "Never" list moved to its own section, unchanged | form | — |
| 8 | A guard's path class gains a glob | substantive | 8 (and 2) |
| 9 | A label name changed in code that applies it | substantive | 7 |
| 10 | A cron step added that posts a summary to the PR | substantive | 5 |
| 11 | A tenet's weight reversed | substantive | 1 |
| 12 | A code comment stating what a guard may not loosen, deleted | substantive | 2 |

## 1. A standing order rewrapped — form

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@
-- **Never chain rebase and push.** A conflicted rebase leaves HEAD detached
-  and the chained push runs anyway.
+- **Never chain rebase and push.** A conflicted rebase leaves HEAD
+  detached and the chained push runs anyway.
```

Every obligation, scope and strength stands. One row, `nothing: form
only`, `read`. Verdict `form`; `governing` true.

## 2. A spec embedded in code beside a behaviour change — substantive (2, 8)

```diff
--- a/hooks/stop.py
+++ b/hooks/stop.py
@@
-# Spec: the sitting-clock nag fires once per session, at the first
-# crossing of a rung, and never again that session.
-def nag_due(crossings):
-    return len(crossings) == 1
+# Spec: the sitting-clock nag fires at every crossing of a rung, each
+# rung once.
+def nag_due(crossings):
+    return crossings[-1] not in crossings[:-1]
```

The comment is a spec: a rule (criterion 2, what the hook requires of
itself: once per session → once per rung) and the code is the
mechanism that enforces it. The nag is a measure the metrics read
(criterion 8, a check's reach: fires once → fires per rung). Two rows,
`git`. Verdict `substantive (2, 8)`.

## 3. A Mergify condition renamed only — form

```diff
--- a/.mergify.yml
+++ b/.mergify.yml
@@
-  - name: queue on merge label
+  - name: queue when labelled merge
     conditions:
       - label=merge
       - check-success=review
```

A rule's display name, referred to by nothing (grep finds no consumer).
Verdict `form`; `governing` false. The config path is not the point:
nothing it requires moved.

## 4. A workflow gains a required check before merge — substantive (2, 4)

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@
   jobs:
     test:
       runs-on: ubuntu-latest
+    substantive:
+      uses: mark-brannan/.github/.github/workflows/substantive.yml@main
```

```diff
--- a/.mergify.yml
+++ b/.mergify.yml
@@
       - check-success=test
+      - check-success=substantive
```

A required step added (criterion 2) and the merge's finish line moved
(criterion 4). Verdict `substantive (2, 4)`.

## 5. A hook's missing-input path, fail-closed to fail-open — substantive (6)

```diff
--- a/hooks/languette-gate.py
+++ b/hooks/languette-gate.py
@@
     if not config_path.exists():
-        sys.exit(2)  # deny: no config, no call
+        return allow("no config found")
```

On a missing config the gate now allows where it denied. One row,
`git`. Verdict `substantive (6)`. Also criterion 5 if the reader judges
the fence removed; one row under each is correct.

## 6. A standing order's "never" softened — substantive (2)

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@
-- **Never disagree silently.** Say so in one line, then do it well.
+- **Avoid disagreeing silently.** Say so in one line where you can.
```

Strength moved, never → avoid; a qualifier added. Verdict `substantive
(2)`; `governing` true.

## 7. A skill's "Never" list moved, unchanged — form

```diff
--- a/skills/curia/SKILL.md
+++ b/skills/curia/SKILL.md
@@
-- **The user stops it, not the agent.** If a clock or nag fires, name it
-  and ask; never obey it silently.
+## Never
+
+- **The user stops it, not the agent.** If a clock or nag fires, name it
+  and ask; never obey it silently.
```

Same words, same strength, a new heading. Verdict `form`. A heading
others link to would make it criterion 7; grep finds no anchor to the
old position.

## 8. A guard's path class gains a glob — substantive (8, and 2)

```diff
--- a/bin/mixed-loops-screen.py
+++ b/bin/mixed-loops-screen.py
@@
 GOVERNING = (
     "CLAUDE.md",
     "rules/*.md",
+    "skills/*/checks/*.md",
 )
```

The guard's reach widened: a change to a check file now trips it
(criterion 8, a check's reach). The guard is also a rule's enforcement,
so what the rule covers moved (criterion 2, scope). Verdict
`substantive (2, 8)`; the criterion 8 declaration is `more
conservative`.

## 9. A label name changed in code that applies it — substantive (7)

```diff
--- a/bin/pr-blockers
+++ b/bin/pr-blockers
@@
-LABEL = "needs-ruling"
+LABEL = "human-ruling"
```

An identifier others hold: Mergify rules, the board, the agora skill
read the label by name. Verdict `substantive (7)`, the row citing one
consumer found by grep.

## 10. A cron step added that posts to the PR — substantive (5)

```diff
--- a/.github/workflows/sweep.yml
+++ b/.github/workflows/sweep.yml
@@
+on:
+  schedule:
+    - cron: "0 6 * * *"
+jobs:
+  sweep:
+    steps:
+      - run: gh pr comment "$PR" --body-file summary.md
```

A new automatic actor with a new destination (a comment on the PR).
Verdict `substantive (5)`; also criterion 3 if the summary's words
count as a reviewer's.

## 11. A tenet's weight reversed — substantive (1)

```diff
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@
-A flourishing life, not throughput.
+Throughput in service of a flourishing life.
```

The same two values, their weight moved. Verdict `substantive (1)`;
`governing` true.

## 12. A governing comment deleted — substantive (2)

```diff
--- a/hooks/metrics-live.py
+++ b/hooks/metrics-live.py
@@
-# A correction is counted only when the user's turn opens with "no,"
-# or "not that": never from an agent's own words. Do not widen this.
 CORRECTION = re.compile(r"^(no,|not that)")
```

The code stands; the rule stating what it may not do is gone. A reader
of the new file may widen the pattern the old file forbade. Verdict
`substantive (2)`; also criterion 8, a governing comment, the row
reading `rule: stated → unstated`.
