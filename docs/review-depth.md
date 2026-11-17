# Review depth: one owner

How hard a pull request is reviewed has one owner, so a skill, a governing
document or a hook never rates low by size alone (claude#343). The owner is
the CI tier, and depth is never set from line count (docs/decisions.md,
2026-11-17). Below are the mapping and the measurement behind it.

## The owner

**The CI tier owns review depth, and line count sets none of it.**
`/critical-review` takes its `/code-review`
level from the tier the review workflow already picks (mark-brannan/.github#68,
whose tiers are current thinking), in place of the 100/500 line stand-in:

| CI tier | `/code-review` level |
|---|---|
| deep | `high` |
| default | `medium` |
| none (a review typed in a session) | `high` |

Nothing reviews at `low`. The review workflow's brief names the tier today only
in passing, in its triage sentence; one line naming it as a field the skill reads
is the only change outside this repo. The tiers themselves do not change.

Why the tier and not `bin/prt`'s score:

- **The tier is where review is spent.** CI reviews every PR; sessions ran `/code-review` five times (section 1).
- **The tier owns the cost lever.** Model moves $ per fix four to six times; tier, a third at most (section 2).
- **prt's score does not sort findings.** Its high band costs most per fix (section 3).
- **Only the tier is measured.** The metrics script already splits spend by tier.

The prt score measures how much a human's eyes are worth (threads, pencils,
desk paths), a different question. A typed review runs `high`: the user asked
for it, and all but one measured run did anyway.

## What was measured

Two sources, both read 2026-11-17. Lines are additions plus deletions at the
PR's state today, not at review time. Spend is the CLI's API-equivalent price.

- **Session reviews:** 225 critical-review metrics rows, 2026-10-09 to 2026-11-12, joined to transcript and PR.
- **CI reviews:** 2026-11-06 snapshot, newest 300 runs over 9 repos: 112 paid runs on 77 PRs, 2026-11-04 to 11-06.

Each bot thread is charged to the last paid run on its PR before it. *Fixed*
means resolved with its anchored lines changed after it.

### 1. Findings per `/code-review` level: not measurable yet

No row records the level. Read from the transcripts, 5 of the 225 session
reviews called `/code-review`:

| PR | level run | the line rule says | prt says | lines | threads posted |
|---|---|---|---|--:|--:|
| languette#415 | high | high | medium | 11 | 3 |
| claude#427 | high | high | medium | 89 | 4 |
| ampacity#14 | high, then medium on #17 | high | medium | 1251 | 2 |
| colregs-mcp#69 | high | high | medium | 132 | 4 |
| languette#357 | high | high | high | 1168 | 0 |

No `low` run; the one `medium` was on ampacity#17, which has no row of its own. The
`high` the line rule gives for languette#415, claude#427 and colregs-mcp#69 comes from its
path arm (a desk path or a `SKILL.md`), not their size. Of the other 220 rows, 210 predate the rule and
10 are prt-dispatched agents that never called `/code-review`.

### 2. CI runs, by the level the line rule would assign and by tier

Whether CI's run used the level the rule assigns is not recorded.

| group | paid runs | median lines | threads per run | silent | $ per fixed thread |
|---|--:|--:|--:|--:|--:|
| rule: low | 24 | 33 | 0.67 | 54% | $1.41 |
| rule: medium | 11 | 247 | 1.55 | 36% | $1.01 |
| rule: high | 77 | 150 | 2.06 | 23% | $1.05 |
| tier: default | 79 | 106 | 1.32 | 35% | $0.70 |
| tier: deep | 33 | 150 | 2.67 | 21% | $1.50 |

The same split by model, which the tier picks:

| tier and model | paid runs | threads per run | $ per fixed thread |
|---|--:|--:|--:|
| default, Sonnet | 59 | 1.02 | $0.45 |
| default, Opus | 13 | 2.54 | $0.45 |
| deep, Opus | 7 | 3.14 | $0.44 |
| default, Fable | 7 | 1.57 | $2.64 |
| deep, Fable | 25 | 2.64 | $1.91 |

These rows sum to 111 of the 112 paid runs: one deep run has no model
recorded. At Opus the cost per fixed thread is flat across tiers; at Fable it
drops by about a third in deep. Across models it moves four to six times over.

### 3. CI runs, by prt's score

The score's static part (lines, files, governing and safety paths, pencils);
the thread and depends-on terms are left out, since they depend on when prt reads the PR.

| prt band | paid runs | median lines | threads per run | $ per fixed thread |
|---|--:|--:|--:|--:|
| low | 39 | 45 | 1.23 | $0.94 |
| medium | 39 | 127 | 2.13 | $0.77 |
| high | 34 | 313 | 1.79 | $1.70 |

### 4. What else moves cost

| paid run on the PR | runs | threads per run | silent | $ per fixed thread |
|---|--:|--:|--:|--:|
| first | 77 | 2.03 | 27% | $0.84 |
| second | 25 | 1.20 | 32% | $1.59 |
| third and later | 10 | 0.60 | 60% | $5.05 |

Re-reviews cost more per fix than any depth split, as the 2026-10-21 run on
mark-brannan/.github#70 also found ($0.38 first, $1.79 third and later).

## Open numbers

Findings per level at one model is the number this choice turns on. It needs
the level written into the critical-review metrics row and the CI review row;
until then the rule bands in section 2 are a proxy.

- **Findings per level at one model:** unmeasured; no row records the level.
- **Whether "fixed" is real:** no human labels yet on mark-brannan/.github#70.
- **The tier today:** the snapshot's tiers came from paths, not the verdict.
- **Skip by size:** the workflow's opt-in `skip-under-lines` and `docs-skip-lines` still read line count.

The 40-thread label sheet on #70 has no human labels; an agent's blind pass
agreed with the script on 31 of 40, with no *fixed* overturned. The workflow
now sets tiers from the substantive-check verdict, which no snapshot has measured.
