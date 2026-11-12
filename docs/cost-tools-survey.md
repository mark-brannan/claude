# Cost and usage tools: what else exists, and when to look again

A survey of software that overlaps `lib/claude_costing`: price tables,
transcript pricing and plan-usage readouts, from Anthropic and from third
parties. Done 2026-11-11 by three research agents reading source and docs,
with the claims that drove action rechecked by hand. It led to claude#458
(prices generated from LiteLLM, checked against Claude Code's stored totals).
claude#458 is open as of writing; rows marked "since #458" and the "After"
column assume it.
The telemetry side continues in the epic claude#460.

Tags: **[V]** read or measured in the survey session · **[U]** an agent's
report, not rechecked · **[?]** not determined.

## Where things stand

Keep `claude_costing`; it is small, and its transcript reading is sound.
What it got wrong was the data: the hand-kept rate card was stale for every
5.2 and 5.5 model.

| Measure, last 14 days | Before #458 | After |
|---|---|---|
| Ours over Claude Code's stored total, Opus 5.5 sessions | 1.67 | 0.97 [V] |
| Same, Fable 5.2 | 1.91 | 0.98 [V] |
| Same, Haiku 5.5 | 5.36 | 0.96 [V] |
| All 853 sessions with a stored total | $2,818 vs $1,836 | — |

Repriced correctly, we land 2–4% under Claude Code and never over [V]. The
shortfall is probably calls that never reach the transcript [?].

## Anthropic and Claude Code

Nothing in the API SDKs, the Models API or the Admin usage and cost API helps
on a Max plan: no price fields, or Console organisations only [V]. The overlap
is all inside Claude Code.

| Source | What it gives | Reach | Status |
|---|---|---|---|
| `cost-state`, last line of a transcript | Session total and per-model cost, sub-agents included | Clean exit only; absent live or after a crash | [V] in 853 of 995 transcripts; undocumented |
| Statusline stdin | Live `cost.total_cost_usd`; `rate_limits.five_hour` and `seven_day` used % and reset time | Statusline scripts only, not hooks, not desktop | [V] in docs; [?] on our own input |
| `claude -p --output-format json`, Agent SDK result | `total_cost_usd`, per-model cost, sub-agents included | Headless and batch callers | [V] docs |
| OpenTelemetry | `claude_code.cost.usage`, `claude_code.token.usage`, `api_request` events with per-request cost, model, session, main vs sub-agent | Needs a collector; claude#460 | [?] whether it emits on Max |
| Agent SDK `get_usage`, `SDKRateLimitEvent` | Plan window utilisation | SDK sessions; `get_usage` marked unstable | [U] |
| Price table inside the native binary | The table Claude Code prices from | Extractable by regex; not a contract | [V] |
| `/api/oauth/usage` and rate-limit headers | What `/usage` reads | Undocumented; needs the OAuth token | [U] |
| `pricing.md` on the docs site | The official card as one markdown table | Fetchable; no JSON | [V]; the table `OFFICIAL` in `lib/claude_costing.test.py` (#458) copies |

## Third-party price tables

All checked against the official card for 21 models [V].

| Table | Correct use | Notes |
|---|---|---|
| LiteLLM `model_prices_and_context_window.json` | The sync source since #458, pinned by commit | 18/18 current models exact; never pip install it (compromised twice in 2026) [U] |
| pydantic `genai-prices`, v2 `data.json` | Second opinion; has retired models and dated history | Lacks Mythos; v1 path is frozen and wrong |
| Langfuse default prices | Drift check; regex rules like ours | Licence mixed |
| Portkey `pricing/anthropic.json` | Drift check; smallest full file (41 KB) | MIT |
| models.dev | Drift check on input, output, cache read | `api.json` flattens the cache-write split |
| OpenRouter `/api/v1/models` | Launch-date oracle | Live only, not pinnable |
| simonw `llm-prices` | None | Sonnet 5.5 cache read wrong; no cache write |
| tokencost, tokonomics, Helicone, tokenlens, npm `llm-cost` | None | Stale or wrappers over LiteLLM |

## Third-party Claude Code usage tools

| Tool | What it does | Correct use |
|---|---|---|
| ccusage (MIT, Rust behind npm) | LiteLLM prices; dedups on message + request id; reads sub-agents | Occasional cross-check of our totals; batch only |
| Claude-Code-Usage-Monitor (Python) | Captures official `rate_limits`; own table is stale | The idea, not the library |
| tokscale (Rust) | Three price sources, nested sub-agents | Second cross-check |
| ccstatusline, claude-powerline (Node) | Statusline readouts; ccstatusline documents the stdin schema | Schema reference |
| splitrail (Rust) | Keeps the most complete record whole | The idea, if block usage ever diverges |
| claude-code-log (Python) | Typed transcript models | Reference for line types |
| sniffly, ccost, claude-code-otel, cccost, claudelytics and others | Not read past a keyword scan | Unknown |

Several of these read Claude Code's OAuth credentials file to call the
undocumented usage endpoint [V]. The statusline field gives the same numbers
without touching the credential.

## What we still model ourselves

| Gap | Why it stays ours today |
|---|---|
| Live spend gate mid-session | `cost-state` exists only at exit; hooks get no cost field |
| Unknown model priced at the top rate | Third-party tools price it at $0, wrong for a gate |
| Plan-week share estimated from list prices | The real percentage reaches statusline scripts only |
| Fast mode 2x, US-only 1.1x, web search fees | Unused locally (`speed: standard` throughout) [V] |
| Cross-session dedup | Not needed per session; a batch total over resumed files would double-count |

## When to look again

Each row names what would change the answer and which way.

| Trigger | Then consider |
|---|---|
| claude#460's first run shows `claude_code.cost.usage` emitting on Max | Reading cost per request from telemetry; the gate and batch tools price less themselves |
| Hooks gain a session cost or `rate_limits` field | Dropping the plan-week estimate for the real figure |
| The weekly prices-sync PR fails or diverges from the official card | genai-prices or Portkey as the source, LiteLLM as the check |
| `cost-state` is documented, or shows up live mid-session | Batch tools and the gate reading it instead of recomputing |
| A batch tool starts summing across resumed sessions | ccusage's dedup, or shelling out to it |
| A tool appears that reads OTLP from Claude Code and prices it | Integrating instead of building on the collector |
