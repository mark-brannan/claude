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
| Typed prompt | A user transcript record whose content is a string no machine wrote: not an injected tag (`<system-reminder>`, `<task-notification>`), not a relayed hook or session message, not a headless run's fixed opening prompt. A typed slash command counts, as the command name. Sidechain (subagent) records are excluded. |
| Pasted | Text inside `<pasted_content>` blocks. Counted apart; pasting is not typing. |
| Touch | One typed prompt. |
| Headless session | A session with zero typed prompts. |
| Keyboard hours | Sum of each session's `human_seconds`, as recorded by the Stop hook. |
| Agent hours | Sum of each session's `agent_seconds`, as recorded by the Stop hook. |
| Day of a session | The UTC date of its `started_at`. |
| Day of a typed prompt | The date of the first typed prompt in its transcript; a transcript is never split across days. |
| Week | Monday to Sunday, from the date part of the timestamp. |
| Project | The repo's `project-*` GitHub topic with the prefix removed; `other` if none. |

## Windows

Daily series cover the last 56 days (`--days`, minimum 14). Weekly series
cover the whole record. Every tile compares the last 7 days with the 7 before.
Open-work tiles compare today with 7 days ago.

## Tiles

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
| rulings waiting | board cards owned `human-ruling` whose latest status is not `done` or `closed` | down | Is my decision queue draining? |

## Sections and charts

### Open work

Issues and PRs are rebuilt from GitHub created and closed timestamps, so
history is complete. Board cards start when the item store did.

| Chart | Formula | Question |
|---|---|---|
| Open issues, by project | open issues per day, grouped by project | Where is the backlog? |
| Open pull requests | open PRs per day, all repos | Is review keeping up? |
| PRs merged per week | merged PRs by week, split `claude/*` head branch vs other | How much lands from agent branches? |
| Board cards waiting on the user | cards per day owned `human-ruling` and `human-click`, latest status not `done`/`closed` | What do I owe the board? |
| Board cards in the agent's queue | same, owner `agent` | What is queued for the agent? |

### Sessions and friction

| Chart | Formula | Question |
|---|---|---|
| Hours per day | keyboard hours and agent hours | Where does the time go? |
| Sessions per day | headless vs interactive | Mix of unattended and attended work |
| Friction per day, by type | correction, override, rebuke, pushback counts | What kind of friction? |
| Decisions pushed per day, by type | scoping, inline, gate counts | Which decisions reach me, and when? |
| Friction per 100 prompts, weekly | 100 x friction events / typed prompts | Is friction falling relative to effort? |
| Decisions per keyboard hour, weekly | decisions / keyboard hours | Is decision load falling relative to time? |

### Typing

| Chart | Formula | Question |
|---|---|---|
| Prompts per day | typed prompts by first-prompt day | How much do I type? |
| Words per day | typed words by first-prompt day | same |
| Words per prompt, weekly | words / prompts | Am I saying more per touch? |
| Characters per prompt, daily | chars / prompts, rounded | same, finer |

### Agent work vs touches

| Chart | Formula | Question |
|---|---|---|
| Sessions per week, by prompts typed | buckets 0, 1, 2-5, 6+ | Do sessions need fewer touches? |
| Merged PRs per week, by prompts typed on the branch | prompts typed into every session that committed on the PR's head branch; buckets 0-1, 2-5, 6+, no session | How few touches does landed work take? |
| Tool calls per prompt, weekly | tool calls / typed prompts | How much does one touch buy? |
| Agent hours per keyboard hour, weekly | agent hours / keyboard hours | Leverage |
| Commits per prompt, weekly | commits / typed prompts | How much lands per touch? |

## Open for ruling

- Are the "wanted" directions right? Two are debatable: headless sessions up,
  and prompts typed down, which could mean less steering as well as less toil.
- Which figures are the ones that matter, and which should go?
- Session day is UTC; the user's day is not.
- "Rulings waiting" counts `human-ruling` only; `human-click` appears only in
  the chart.
