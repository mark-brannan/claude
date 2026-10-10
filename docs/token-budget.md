# Token budget: where the floor comes from and what moves it

Measured 2026-08-20 in a cloud container, `claude` 2.1.236, by running
headless probes (`claude -p "ok" --output-format json`) against real config
and reading `usage` off each. Every number below is measured, not estimated.
Re-measure before trusting these after a CLI upgrade.

## The floor, line by line

Local terminal CLI, nothing loaded but this repo's config: **36,657 tokens**
before the first word of work.

| line | tokens | mine? |
|---|---|---|
| Claude Code system prompt | ~20,000 | no |
| built-in tool schemas | ~9,100 | no, in practice |
| `.claude/CLAUDE.md` | 4,123 | **yes** |
| `settings.json` + 10 hooks + SessionStart brief | 318 | yes |
| skills listing (9 skills) | 79 | yes |
| MCP | 0 when off | yes |

Remote/managed session (desktop or web routed through a cloud container):
**47,796 tokens**. The +11,139 is harness text I do not control — container
instructions, GitHub integration, PR babysitting rules, branch requirements,
plus three extra tools (Artifact, Workflow, ToolSearch).

Two facts that reframe the bill:

- The floor is **cached**. 26,754 of 32,277 came back as `cache_read`, billed
  at 10%. The floor costs context window, not much money.
- My own config is **4,520 of 47,796 — 9%**. Halving CLAUDE.md buys 2k. It is
  not the lever, despite what CLAUDE.md's own preamble implies.

## What actually works, ranked

**1. Terminal CLI for anything small. −11,139 tokens, free.**
Same account, same config, no cloud container. Floor 47.8k → 36.7k, which
leaves ~13k of headroom under 50k instead of ~2k.

**2. `/clear` between unrelated tasks.** The whole game — see below.

**3. Search via subagents.** A subagent burns its own context window and
returns a paragraph. A 60-line directory dump should have been one.

**4. Read less per call.** Codified in CLAUDE.md under "Execution".

**5. Connectors: on for remote sessions, off for local ones.** In a managed
remote session MCP tools arrive *deferred* — ~110 tool names, no schemas
until one is requested. In a local CLI they load in full. That asymmetry is
the whole rule. `.claude/hooks/connector-budget.sh` warns above 5.

### Dead end, tested and rejected

Denying tools does not help. `--disallowedTools` on NotebookEdit, WebSearch,
WebFetch and the entire Task family saves **33 tokens**. Agent+Task saves
2,039. The only large savings come from denying Bash/Read/Edit/Write/Glob/
Grep — the six that make the tool useful. Do not revisit this.

## Cache churn: what a mid-session switch actually costs

Measured 2026-08-20 the same way — headless probes (`claude -p --output-format
json --resume <session-id>`), reading `usage.cache_creation_input_tokens` /
`cache_read_input_tokens` off real requests, at ~50k tokens of context built
from real repo files. Two runs each; no estimates.

- **Model switch mid-session: 65,000-70,000 tokens of unwanted recompute.**
  A same-model control turn at ~50k context hit cache at 94.7-95.1%
  (4.7-5.3% recomputed). Switching model on the next turn hit cache at only
  24.3-26.5% — 73.5-75.7% of the ~95k-token context was recomputed from
  scratch, confirmed on two independent runs. The break is scoped to the
  switch turn itself: reverting to the original model on the *following*
  turn mostly re-hits cache (94.9%) — it is a one-time tax, not a permanent
  fork.
- **`/effort` change mid-session: worse — 100% recompute.** high→low effort
  on the next turn showed `cache_read_input_tokens: 0` against a same-effort
  control at 95.1%. Every token of context was rebilled at full
  cache-write rate.
- Cache-write tokens bill above base input price; cache-read bills around
  10%. So this isn't just latency — a stray `/model` or `/effort` tap at
  50k context is a real cost multiplier, and it gets worse the deeper the
  session already is.

**Practical rule: pick model and effort at session start. Don't change
either mid-session** unless the task genuinely requires it — know going in
that the next turn eats a near-full-context recompute.

`/rewind` could not be probed headlessly — it's refused outright in `-p`
mode (`"/rewind isn't available in this environment"`, no request sent,
zero usage). Whether it re-enters a cached prefix is still unverified;
testing it requires the interactive REPL, not a scripted probe.

## Harness share of the starting context, by source (2026-10-10)

Method: first assistant turn of 386 main-thread sessions on Claude Code
2.1.288-2.1.295 under `~/.claude/projects`, total = `input_tokens` +
`cache_read_input_tokens` + `cache_creation_input_tokens`. Transcripts record
the text of each injected source (system-prompt snapshot, CLAUDE.md files,
skill and agent listings, deferred tool names, MCP instructions, hook
context) but not tool schemas, so source sizes are bytes in the transcript
and tokens are bytes ÷ 4. One `/context` reading calibrates that: the skills
listing is 17.9 KB here and 4.7k tokens in mark-brannan/claude#74 (about 3.8
bytes per token), so ÷ 4 understates every estimated row by about 5%.

**First-turn total, measured: median 49,750 (min 43,319, max 68,042).** The
2.1.258 runs in #74 and the 36.7k above were lower; the floor has risen
about 13k since.

| # | Source | Tokens | Switch-off |
|---|---|---|---|
| 1 | Skills listing (user, plugin, built-in) | ~4.5k | `--disable-slash-commands`; shorten `SKILL.md` descriptions; `enabledPlugins` per plugin |
| 2 | User CLAUDE.md | ~4.3k | prune the file; `rules/*.md` are path-globbed, not in the start |
| 3 | System-prompt text recorded in transcript | ~2.4k | none |
| 4 | SessionStart hook context | ~1.4k | `disableAllHooks` (drops every gate too) |
| 5 | Deferred tool names | ~1.3k | `--strict-mcp-config` drops the MCP names |
| 6 | Agent listing | ~0.7k | none |
| 7 | Env, model, date, other attachments | ~0.6k | none |
| 8 | MCP server instructions (github-pat) | ~0.5k | `--strict-mcp-config` |
| 9 | Auto-memory index and project CLAUDE.md | ~0.2k, up to 7k | prune `MEMORY.md` |
| 10 | Residual: total minus rows 1-9 (15.9k) | ~33.8k | none for tools and prompt |

Rows 1-9 are estimated (KB ÷ 4); row 10 is the measured total minus them.
"None" means not configurable. Row 4 is one hook's share, where #74 measured
2.8k for all SessionStart output. Row 3 is the system prompt that #74
measured at 3.4k, counted once. Row 10 holds the tool schemas and the first
user message; #74 gave tools as 12.4k or 20.3k (unresolved there), so 13k to
21k of row 10 is unattributed. Tool schemas load as MCP schemas at 19.7k in
#74 when not deferred.

Not a start-of-session cost, but the same family: the continuity hook
`pr-ownership-context.sh` (13.8 KB) is **not** injected whole. Claude Code
persists a hook output over ~12 KB to a file and puts a 2.3 KB preview plus a
path in context: 2,284 median bytes (about 0.6k tokens) across 1,400+ firings
in these transcripts. #74 estimated 3.5k for this row; 0.6k is what the model
sees, and the rest only enters if it reads the file. Trimming the block
below ~12 KB would put the whole rule text in context instead of a preview,
so the 13.8 KB is no longer the lever #74 took it for.

### Follow-up

The rows worth switching, largest first: skills listing (4.5k, 17.9 KB),
user CLAUDE.md (4.3k), SessionStart hook context (1.4k to 2.8k),
and plugin skills. Tool schemas and the system prompt (rows 3 and 10, over
36k together) are the bulk and not configurable. Re-measure the unattributed
13k to 21k with one `/context` run on the current version.

## Why `/clear` is the whole game

The floor is a one-time charge; growth is charged every turn. In the session
that produced this document the first assistant turn cost 47,796 tokens, the
second 61,475, the third 65,894 — and none of that growth was config. It was
tool output: files read, command results, probe JSON, all of it pinned in
context and re-sent on every subsequent request. Nothing I configure touches
that curve. A session is a ratchet that only turns one way, and the only
release is starting a new one.

So the wish for sub-50k sessions is not really a wish about configuration. It
is a wish for **one task per session**, and `/clear` is how that wish gets
enforced. Clear when the task changes, not when the context bar turns red;
by then the expensive part already happened. A cleared session restarts at
the floor, pays the cheap cached rate for it, and gives back the full working
window for the next thing. Two 40k sessions cost less than one 100k session
and both of them think more clearly, because nothing in the window is stale.

The habit is small and unglamorous: finish a thing, log it, clear, pull the
next thing off the board. That is the change.
