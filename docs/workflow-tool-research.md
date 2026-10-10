# Workflow tool as the worker: what it takes

Research for issue #65. Provenance tags: **[M]** measured from the 2026-10-10
session transcripts named below; **[V]** stated by the Workflow tool's own
authoring reference; **[I]** inference, not tested; **[?]** unknown.

No production change here and no saved workflow: the issue asks for one "if
it proves out", and it has not yet (see Verdict).

## Evidence

One session, two Workflow runs, on this machine (16 CPUs), under
`~/.claude/projects/-home-solace-languette--claude-worktrees-parallel-issues-prs-ce61e8/045d4803-.../`
(`workflows/`, `subagents/workflows/`):

| Run | Shape | Result |
|---|---|---|
| `wf_1f4543cc-0a1` triage | 4 Sonnet scouts, read-only, one schema row per issue | completed: 240 s wall, 323k tokens reported, 66 tool calls [M] |
| `wf_c83eca79-de8` wave 1 | 20 workers, one item each, each to open one PR | in flight when read: 18 started, 4 returned [M]. PR outcomes not measured here. |

The comparison with `/orchestrate` rests on this one session and the
2026-09-22 session as `skills/orchestrate/SKILL.md` records it (22 workers,
22 PRs, one hour). Two data points; every ratio below is [I].

## What the Workflow tool already does for us

| Job `/orchestrate` does with prose | Workflow equivalent |
|---|---|
| Fan out N workers, 5 to 10 in flight | `parallel`/`pipeline`, capped at min(16, CPUs minus 2) [V]. Seen: 14 started together, the other 4 as slots freed [M] |
| Worker contract pasted into each dispatch | one `RULES` constant in the script, interpolated into every prompt [M] |
| Free-text final report | `schema`: the worker must call `StructuredOutput`, validated and retried on mismatch [V]. All 4 scouts returned conforming rows [M] |
| Worktree per worker | `isolation: 'worktree'` per agent (languette items); hand-made `git worktree add` for the rest [M] |
| A worker that dies | `agent()` returns `null`; the script maps it to a `no_pr` row [M, script] |
| Re-dispatch after a pause | `resumeFromRunId` replays the unchanged prefix from `journal.jsonl` [V, untested here] |

## The issue's questions

### 1. How does a worker see the standing orders and code rules?

[M] Each worker starts with `~/.claude/CLAUDE.md` (17.7k chars), the
**project** CLAUDE.md of the **orchestrator's cwd** (languette's, 270
chars), the auto-memory index for the orchestrator's project, and the full
skill listing (18.5k chars). First-call context was 38.1k to 40.9k tokens
for all 22 workers across both runs.

- Standing orders arrive; no need to paste them (the tool says so too [V]).
- **Wrong repo's rules.** A worker aimed at `~/.claude` or `nav-wright`
  gets languette's CLAUDE.md and languette's memory, not its target's. The
  script covered it with one line in `RULES` ("read that repo's CLAUDE.md
  first") [M, script]. Whether each worker obeyed: [?].
- **`rules/code.md` is not loaded**; CLAUDE.md only points at it. In the
  in-flight snapshot 2 of 20 worker transcripts opened it [M]. The PR body
  shape lives there, so the script restates it in `RULES`. That restatement
  is the main hand-kept text left and can drift from `rules/code.md`.
- Workable budget under a 110k cap is ~70k after the ~40k start.
  `/orchestrate` says ~45k start; close.

### 2. Worktrees

[M] Languette workers got `isolation: 'worktree'`, at
`<repo>/.claude/worktrees/wf_<run>-<n>`. Others made theirs by hand; the
isolation option builds a worktree of the orchestrator's repo only [I, from
how the script had to split `iso` items].

- Cleanup: the harness removes an unchanged isolated worktree [V]; one with
  commits stays, as do hand-made ones. Detach-on-finish (in `RULES`) frees
  the branch; deleting the directory is nobody's job. Count of leftovers
  after the run: [?], the run was live.
- Shared stash stack: the environment text warns every worker. A grep of
  tool inputs in the transcripts found no `git stash` call [M]. It is a
  warning, not a guard.
- A guard (`guard-worktrees`) refused this report's own author a write into
  a worktree it had created in a separate shell call [M, first-hand]. So a
  hand-made worktree must be created and entered in one command, or live
  under the scratchpad. `RULES` tells workers neither; a worker that
  follows its text literally can hit it [I].

### 3. Where it stops

- **Concurrency**: cap 14 on this box [V+M]. A 20-item wave is 14 running
  and 6 queued, so wall time is about two worker lifetimes [I].
- **Tokens seen**: triage 323k for 4 scouts, 62k to 105k each [M]. Wave 1
  so far, 18 workers: 17.8M cache-read, 1.25M cache-creation, 740 fresh
  input, 36.8k output [M, partial]. Dollar cost not computed: no pricing
  source in this repo; cache-read bills at a fraction of input [V,
  `cost-practices.md`].
- **Cold start**: the first workers of each run paid ~40k cache-creation;
  later ones read ~21k from cache [M]. Launching 14 at once forfeits most
  of that saving [I].
- **The context cap is only prompt text.** "110k hard" is in `RULES`;
  nothing stops a worker. `/orchestrate` enforces it with a `Monitor` over
  transcripts. Workflow's `budget` is a per-turn *output* ceiling shared by
  everything, not a per-worker context cap [V]. Peak context across the 18
  wave-1 transcripts: 45.9k to 82.4k [M]; none neared 95k, so the cap is
  untested.
- **Session death, usage limit**: [?]. The journal is on disk
  (`started`/`result` per agent) and resume is documented, but no run was
  killed. A resumed worker cut after pushing would re-run live; the
  "branch already exists, report and stop" line in `RULES` is what would
  catch it [I].
- Scripts cannot call `Date.now()` or `Math.random()` [V]; timestamps go in
  `args`.

### 4. Verdict schemas

[M] Two schemas exist and both worked first try: scout `ROW` (verdict enum
`dispatch|skip`, `governing_doc` boolean, `human_ruling` string) and worker
`REPORT` (status enum `pr_open|checkpoint|no_pr`, `look` enum
`quick|critical`, `human_decide`, `followup_issue`).

A script can route on them with no model: `status != pr_open` to a fixer
queue; `look == critical` or non-empty `human_decide` to the user. The gap:
the schema asserts a PR URL but nothing checks it exists or that the body's
`Head:` sha matches the pushed head. The issue's review, verify and judge
schemas are not built. The authoring reference's adversarial-verify shape
(N skeptics returning `refuted`) is the pattern to copy [V, untried].

### 5. A saved workflow under `~/.claude/workflows/`

[?] Not demonstrated. That directory does not exist. Each run auto-saves
its script to `<session>/workflows/scripts/`, and the tool describes a
registry reachable by `name` [V], but I did not find where it reads from
and did not test it. The wave script is nearly generic already: the item
table and `RULES` are the only run-specific parts. A saved version would
take `args.items` (id, repo, checkout, branch, task, model, effort) and
keep `RULES` as a constant.

## Comparison with `/orchestrate`

| | `/orchestrate` (2026-09-22, per its skill) | Workflow (this session) |
|---|---|---|
| PRs out | 22 from 22 workers in about an hour | unknown: run in flight |
| Orchestrator context before first dispatch | 105k, then a Haiku scout cut it | the fan-out itself costs the orchestrator nothing; scouting was a separate 4-agent script [M] |
| Per-run prompt work | issue text, plan table, contract paste | one ~120-line script, about a third of it `RULES` [M] |
| Worker context cap | enforced by Monitor at 95k/110k | text only |
| Result format | free text under 200 words | validated schema |
| Mess left | `.claude/worktrees/agent-*` | same, plus `wf_*` isolated trees |
| Resume | re-dispatch from a checkpoint comment | `resumeFromRunId` [V] |
| Target-repo rules | per-dispatch text | none: inherits the orchestrator's CLAUDE.md |

## Verdict

Per run, Workflow removes the fan-out mechanics, the contract paste and the
report parsing. A saved, parameterized script would leave one `items` list
per run. It does not remove the spend watch, the target-repo rules gap or
the `RULES` restatement of `rules/code.md`.

Recommendation: save the workflow once gaps 1 and 2 below are closed. Until
then `/orchestrate` keeps the one thing Workflow lacks, an enforced cap.

## Follow-up

Build issue (drafted, not filed):

1. Per-worker context cap: a hook over the worker transcript, or measure the
   prompt-only cap's overshoot over two more runs.
2. Target-repo rules: have `RULES` name the target repo's CLAUDE.md and
   `rules/code.md` as the first two reads; count how many workers comply.
3. Post-run verifier stage: `gh pr view` each `pr_open` URL, compare `Head:`
   with the pushed sha, check for a `Pencil:` line.
4. Kill a small run mid-flight and resume it once to settle session death.
5. Find where saved workflows load from; save the wave script parameterized
   by `args.items`.
