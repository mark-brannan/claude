# Metrics dashboard: what each number means

Status: **skeleton, unruled.** The definitions below were lifted from what
`bin/metrics-db` and `bin/metrics-dashboard` compute on 2026-10-09; they
describe today's behaviour and are the starting text to rule on, not rulings.
The "Question" column is the drafter's guess at why each figure exists. Where
this doc and the code disagree once it is ruled, the doc is the intent and the
code is the work to do.

This is the one place the dashboard's metrics are defined. Code comments and
READMEs say where things are and how to view them; they do not define.

## Terms

| Term | Definition today |
|---|---|
| Typed prompt | A user record a human typed, not a tag, relay or headless opening. Slash commands count. |
| Pasted | Text inside `<pasted_content>` blocks. Counted apart; pasting is not typing. |
| Touch | One typed prompt. |
| Typed-prompt series | One row per typed prompt (transcript, session, timestamp, words, chars, pasted chars), from the same scan and under the same rules as the per-transcript typing totals. It is what words typed per minute is drawn from; per transcript, its rows sum to the totals. Counts, times and ids only, never prompt text. |
| Headless session | A session with zero typed prompts. |
| Keyboard hours | Sum of each session's `human_seconds`, as recorded by the Stop hook. |
| Agent hours | Sum of each session's `agent_seconds`, as recorded by the Stop hook. |
| Day of a session | The UTC date of its `started_at`. |
| Day of a typed prompt | The date of the first typed prompt in its transcript; a transcript is never split across days. |
| Week | Monday to Sunday, from the date part of the timestamp. |
| Project | The repo's `project-*` GitHub topic with the prefix removed; `other` if none. |
| Open card | A board card whose latest status is not `done` or `closed`. |
| API-equivalent $ | The Stop hook's estimate of a session's cost at API list price, pricing its four token counts per model. A weight for comparing sessions, models and weeks, not a bill. A sub-agent's spend lands on its own model. |
| Cold context | Context tokens written to the cache instead of re-read from it. A write is priced far above a re-read; a gap past the cache window makes the next turn cold for the whole context. |
| Context tokens | Cache-read + cache-creation + uncached input tokens. |

## Windows

Daily series cover the last 56 days (`--days`, minimum 14). Weekly series
cover the whole record. Every tile compares the last 7 days with the 7 before.
Open-work tiles compare today with 7 days ago.

## Overview

The page opens on one card per aim, each the last 7 days against the 7 before, with twelve
such windows as a trend line. Each card opens the tab that holds its charts. A card with no
wanted direction keeps its delta grey.

| Aim | Card | Formula | Wanted | Tab |
|---|---|---|---|---|
| Your time | hours at the keyboard, 7d | sum `human_seconds` / 3600 | down | Your time |
| Smoothness | friction per keyboard hour, 7d | sum `fr_total` / keyboard hours | down | Decisions & friction |
| Decision load | decisions per keyboard hour, 7d | sum `dec_total` / keyboard hours | none | Decisions & friction |
| Waiting on you | board cards owned by you, today | open cards owned `human-ruling` or `human-click` | down | Decisions & friction |
| What lands | PRs merged, 7d | PRs with `merged_at` in window | none | Work landed |
| Your words | words you typed per merged PR, 7d | typed words / PRs merged, same window | down | Work landed |
| Cost | API-equivalent $, 7d | sum of session `cost_usd` | down | Cost |

## Tiles

Each tab opens with the tiles for its charts.

Delta colour: green when the change moves in the wanted direction.

| Tile | Formula | Wanted | Question |
|---|---|---|---|
| sessions, 7d | count of sessions started in window | up | How much work is being started? |
| of them headless, 7d | sessions with zero typed prompts | up | How much runs without me? |
| hours at the keyboard, 7d | sum `human_seconds` / 3600 | down | How much of my time does it cost? |
| agent hours, 7d | sum `agent_seconds` / 3600 | up | How much work happens unattended? |
| prompts typed, 7d | sum of typed prompts | down | How often must I intervene? |
| words typed, 7d | sum of whitespace-split words in typed text | down | How much must I say? |
| friction events, 7d | sum `fr_total` | down | How often does the agent get it wrong? |
| gate decisions, 7d | sum `dec_gate` | down | How often am I pulled mid-flight? |
| open issues | issues created on or before the day and not closed by it | down | Is the backlog shrinking? |
| open PRs | same, for pull requests | down | Is review keeping up? |
| rulings waiting | open cards owned `human-ruling` | down | Is my decision queue draining? |
| API-equivalent $, 7d | sum of session `cost_usd`, rounded | down | What does the work cost? |
| cold context share, 7d | 100 x cache-creation / (cache-creation + cache-read) tokens | down | How much context is paid for at the write price? |
| context per turn, 7d | context tokens / assistant turns, in thousands | down | How heavy is each turn? |

## Sections and charts

### Open work (tab: Work landed)

Issues and PRs are rebuilt from GitHub created and closed timestamps, so
history is complete. Board cards start when the item store did.

| Chart | Formula | Question |
|---|---|---|
| Open issues, by project | open issues per day, grouped by project | Where is the backlog? |
| Open pull requests | open PRs per day, all repos | Is review keeping up? |
| PRs merged per week | merged PRs by week, split `claude/*` head branch vs other | How much lands from agent branches? |
| Board cards in the agent's queue | open cards per day owned `agent` | What is queued for the agent? |

### Sessions (tab: Your time)

| Chart | Formula | Question |
|---|---|---|
| Hours per day | keyboard hours and agent hours | Where does the time go? |
| Sessions per day | headless vs interactive | What is the mix of unattended and attended work? |

### Friction (tab: Decisions & friction)

| Chart | Formula | Question |
|---|---|---|
| Friction per keyboard hour, weekly | friction events / keyboard hours | Is it getting smoother, whatever the week's volume? |
| Engaged sessions with no friction, weekly | 100 x sessions with `human_seconds` >= 60 and no friction / such sessions | How often does a session go clean? |
| Repeat share of friction, weekly | 100 x `fr_repeat` / `fr_total` | Are lessons being learned? |
| Friction per day, by type | correction, override, rebuke, pushback counts | What kind of friction? |
| Friction per 100 prompts, weekly | 100 x friction events / typed prompts | Is friction falling relative to effort? |
| Tool calls refused per week | `blk_classifier`, `blk_rule`, `blk_user` | Who stops the agent, and how often? |

### Decisions (tab: Decisions & friction)

| Chart | Formula | Question |
|---|---|---|
| Decisions per keyboard hour, weekly | decisions / keyboard hours | Is decision load falling relative to time? |
| Decisions pushed per day, by type | scoping, inline, gate counts | Which decisions reach me, and when? |
| Board cards waiting on the user | open cards per day owned `human-ruling` and `human-click` | What do I owe the board? |

### Typing (tab: Your time)

| Chart | Formula | Question |
|---|---|---|
| Prompts per day | typed prompts by first-prompt day | How much do I type? |
| Words per day | typed words by first-prompt day | Is the volume of my speech growing? |
| Words per prompt, weekly | words / prompts | Am I saying more per touch? |
| Characters per prompt, daily | chars / prompts, rounded | How long is a single touch? |

### Agent work vs touches (tab: Work landed)

| Chart | Formula | Question |
|---|---|---|
| Words you typed per merged PR, weekly | typed words / merged PRs, by week | How much must I say per landed change? |
| Sessions per week, by prompts typed | buckets 0, 1, 2-5, 6+ | Do sessions need fewer touches? |
| Merged PRs per week, by prompts on the branch | typed prompts on the head branch's sessions; buckets 0-1, 2-5, 6+, none | How few touches does landed work take? |
| Tool calls per prompt, weekly | tool calls / typed prompts | How much does one touch buy? |
| Agent hours per keyboard hour, weekly | agent hours / keyboard hours | Does agent time grow faster than my time? |
| Commits per prompt, weekly | commits / typed prompts | How much lands per touch? |

A session counts toward a branch when it committed on the head branch.

### Cost (tab: Cost)


| Chart | Formula | Question |
|---|---|---|
| API-equivalent $ per week, by model | session cost by week and model; the three biggest spenders named, the rest as `other` when more than four | Which models carry the spend? |
| API-equivalent $ per merged PR, weekly mean | each merged PR's dollars are those of the sessions that committed on its branch, each session's figure split evenly across the branches it committed on; PRs with no session left out | What does landed work cost? |
| Cold context share, weekly | 100 x cache-creation / (cache-creation + cache-read) tokens | Is the cache doing its job? |
| Context per turn, weekly mean | context tokens / assistant turns, in thousands | Are turns getting heavier? |
| Turns per session, weekly mean | assistant turns / sessions | Are sessions getting longer? |
| Sessions per week, by length | elapsed under 5 min, 5 min to 1 h, over 1 h | What is the mix of short and long sessions? |

## Open for ruling

- Are the "wanted" directions right? Two are debatable: headless sessions up,
  and prompts typed down, which could mean less steering as well as less toil.
- Which figures are the ones that matter, and which should go?
- Session day is UTC; the user's day is not.
- "Rulings waiting" counts `human-ruling` only; `human-click` appears only in
  the chart.
