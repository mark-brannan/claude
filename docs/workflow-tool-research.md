# Workflow tool as the worker: what it takes

Research for issue #65. Tags: **[M]** measured in the 2026-10-10 session
transcripts; **[V]** stated by the Workflow tool's authoring reference;
**[I]** inference, not tested; **[?]** unknown.

No production change and no saved workflow: the issue asks for one "if it
proves out", and it has not yet (see Verdict).

## Evidence

One session, two Workflow runs, on a 16-CPU machine. Transcripts are under
`<session>/workflows/` and `<session>/subagents/workflows/`.

| Run | Shape | Result |
|---|---|---|
| `wf_1f4543cc-0a1` triage | 4 read-only Sonnet scouts | done: 240 s, 323k tokens, 66 tool calls [M] |
| `wf_c83eca79-de8` wave 1 | 20 workers, one PR each | 17 PRs, 1 checkpoint, 2 no-PR [M] |

Wave 1 final tally: 1.40M subagent tokens in 27 minutes of wall clock [M].
Most claude-repo workers could not enter the worktree they had created in an
earlier Bash call (the `guard-worktrees` hook) and used a scratchpad one [M].

The `/orchestrate` comparison rests on this session and the 2026-09-22 one
(22 workers, 22 PRs, one hour, per its skill). Two points; ratios are [I].

## What the Workflow tool already does for us

| Job `/orchestrate` does with prose | Workflow equivalent |
|---|---|
| Fan out N workers, 5 to 10 in flight | `parallel` capped at min(16, CPUs minus 2) [V] |
| Worker contract pasted per dispatch | one `RULES` constant in the script [M] |
| Free-text final report | `schema`: validated, retried on mismatch [V] |
| Worktree per worker | `isolation: 'worktree'`, or hand-made `git worktree add` [M] |
| A worker that dies | `agent()` returns `null`; the script writes a `no_pr` row [M] |
| Re-dispatch after a pause | `resumeFromRunId` replays from `journal.jsonl` [V] |

## The issue's questions

### 1. How does a worker see the standing orders and code rules?

Each worker starts at 38.1k to 40.9k tokens across all 22 workers [M]. That
is `~/.claude/CLAUDE.md`, the orchestrator's project CLAUDE.md and memory,
and the full skill listing.

- Standing orders arrive; no need to paste them [V].
- A worker aimed at another repo gets the orchestrator's CLAUDE.md, not its own [M].
- `RULES` covers that with "read that repo's CLAUDE.md first"; compliance is [?].
- `rules/code.md` is not loaded: 2 of 20 in-flight transcripts opened it [M].
- `RULES` restates the PR-body shape from `rules/code.md`, and can drift [I].
- Budget under a 110k cap is ~70k after the ~40k start [M].

### 2. Worktrees

- Languette workers got `isolation: 'worktree'`, under `.claude/worktrees/wf_*` [M].
- Isolation builds a worktree of the orchestrator's repo only; others are hand-made [I].
- The harness removes an unchanged isolated worktree [V]; committed ones stay.
- Leftovers after the run: [?], the run was live.
- No `git stash` call in any worker's tool inputs [M]; the shared stack is a warning only.
- `guard-worktrees` refuses writes to a worktree made in an earlier shell call [M].
- `RULES` does not warn of it, so a literal-minded worker can hit it [I].

### 3. Where it stops

- Concurrency cap is 14 on this box [V]; a 20-item wave runs 14, then 6 [I].
- Triage cost 323k tokens for 4 scouts, 62k to 105k each [M].
- Dollar cost is not computed: no pricing source in the repo.
- The first workers of a run paid ~40k cache-creation; later ones read ~21k [M].
- Launching 14 at once forfeits most of that cache saving [I].
- The 110k cap is prompt text; nothing stops a worker [M].
- `/orchestrate` enforces it with a `Monitor` over transcripts.
- Workflow `budget` is a per-turn output ceiling, not a per-worker cap [V].
- Peak worker context was 45.9k to 82.4k over 18 transcripts, so the cap is untested [M].
- Session death or usage limit: [?]; no run was killed.
- A resumed worker cut after pushing would re-run live [I].
- `RULES` says "branch already exists, report and stop", which would catch it [I].
- Scripts cannot call `Date.now()` or `Math.random()`; pass timestamps in `args` [V].

### 4. Verdict schemas

- Scout `ROW` and worker `REPORT` schemas both worked first try [M].
- A script can route on them with no model, such as `status != pr_open` to a fixer queue [I].
- Nothing checks the PR URL exists or that the body's `Head:` sha matches [M].
- The issue's review, verify and judge schemas are not built.
- The adversarial-verify shape (N skeptics returning `refuted`) is the one to copy [V].

### 5. A saved workflow under `~/.claude/workflows/`

- Not demonstrated [?]: that directory does not exist.
- Each run auto-saves its script to `<session>/workflows/scripts/` [M].
- A registry reachable by `name` is described [V]; where it loads from is [?].
- The wave script is nearly generic: only the item table and `RULES` are specific [I].

## Comparison with `/orchestrate`

| | `/orchestrate` (2026-09-22, per its skill) | Workflow (this session) |
|---|---|---|
| PRs out | 22 from 22 workers in about an hour | 17 from 20 workers in 27 minutes [M] |
| Orchestrator context | 105k before first dispatch | no figure taken; fan-out cost [?] |
| Per-run prompt work | issue text, plan table, contract paste | one ~120-line script [M] |
| Worker context cap | enforced by Monitor at 95k/110k | text only |
| Result format | free text under 200 words | validated schema |
| Mess left | `.claude/worktrees/agent-*` | same, plus `wf_*` isolated trees |
| Resume | re-dispatch from a checkpoint comment | `resumeFromRunId` [V] |
| Target-repo rules | per-dispatch text | none: inherits the orchestrator's |

## Verdict

Workflow removes the fan-out mechanics, the contract paste and the report
parsing. A saved, parameterized script leaves one `items` list per run. It
does not remove the spend watch, the target-repo rules gap or the `RULES`
restatement of `rules/code.md`.

Recommendation: save the workflow once items 1 and 2 below are closed. Until
then `/orchestrate` keeps what Workflow lacks, an enforced cap.

## Follow-up

Build items, to go under `mark-brannan/claude#65`:

1. Per-worker context cap: a hook over the transcript, or measure the overshoot.
2. Target-repo rules: `RULES` names the target's CLAUDE.md and `rules/code.md` first.
3. Post-run verifier: `gh pr view` each `pr_open` URL; compare `Head:`; check `Pencil:`.
4. Kill a small run mid-flight and resume it once to settle session death.
5. Find where saved workflows load from; save the wave script keyed by `args.items`.
