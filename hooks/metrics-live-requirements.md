# metrics-live.sh: requirements

From the strategy review in
[dotfiles#149](https://github.com/mark-brannan/dotfiles/issues/149) and the
review threads on the PRs before it. Each item is the intent and one line it
governs. Values in the examples are tuning, not part of the ruling.

## What is shown, and how often

**A notice on every event, and one notice per event.** On every Stop, every
tool invocation, and every prompt (`UserPromptSubmit` renders the block too,
[dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137))
— high frequency, one block each time. Louder and *more often* is the
direction; going quieter is never a cleanup, and display lines cost no
tokens, so frequency is free. This is the default for any new wiring too:
don't ask per-event whether high frequency applies — it does, unless told
otherwise for that specific case.

This corrects what was written here before. `#149` was read as a ruling about
lines *per event*: "more lines, not fewer... do not coalesce, dedupe or fire
at the right time", so a jump across four rungs printed four lines. See [dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137):
that was never the ask. The user was pushing back on repeated attempts to make the
readout appear **less often**. Frequency, not line count. A four-rung jump
renders one block with four 💸 in it.

```
💸😫🌌🧘⛔ $  2.39 ⛁  46k/155k ⏱1h33 🧘🌌😫💀
⏱️🫩😩😫
💸💸💸💸 ⛔⛔(x2)
⇢ 1 ⚙ 59
```

## The block's shape

**Four lines, each with one job.** Line 1 is the steady one: five state
slots, the numbers, and a tail saying how the user is likely to feel. Line 2
is the time ladder. Line 3 is the glyph runs, the messy part that grows as
things get worse. Line 4 is turns and git. Lines 2 and 3 appear only once
they have something on them; lines 1 and 4 are always there.

```
day, 10 min, nothing crossed
🪙⏳🌌🧘✅ $  0.42 ⛁   3k/ 12k ⏱0h10 🧘🌌⏳
⇢ 1 ⚙ 4

night, 40 min, nothing else crossed
🪙🌙🌌🧘✅ $  0.81 ⛁   9k/ 30k ⏱0h40 🧘🌌🌙
🌙
⇢ 2 ⚙ 12

day, 35 min, 4 decisions, friction at rung 2
🪙⏱️⚡🤔✅ $  0.95 ⛁  12k/ 40k ⏱0h35 🤔🙄⏱️
⏱️
⚡⚡(x2) 🤔⚖⚖⚖(x4)
⇢ 2 ⚙ 14

day, 50 min, friction at rung 3
🪙🫩⚡🧘✅ $  1.10 ⛁  20k/ 60k ⏱0h50 🧘😠😩🥀
⏱️🫩
⚡⚡⚡(x3)
⇢ 2 ⚙ 20

night, 3h05, everything maxed
💸😵⚡🤔⛔ $123.00 ⛁ 650k/850k ⏱3h05 🤔🤬😵💀
🌙🫩😩😫😵‍💫😵
💸💸💸💸💸(x9) ⚡⚡⚡⚡⚡(x9) 🤔⚖⚖⚖⚖⚖(x12) ⛔(x4)
⇢ 103 ⚙ 1310 ⎇ 12c14~3↑unpushed  ← not safe to kill
```

**The front is five slots, each good or bad.** A slot keeps its place and
shows its calm glyph until its field crosses a rung, then its bad one.

| slot | good | bad |
|---|---|---|
| context | 🪙 | 💸 |
| time | ⏳ | the time ladder's latest face: ⏱️ or 🌙, 🫩, 😩, 😫, 😵‍💫, 😵 |
| friction | 🌌 | ⚡ |
| decisions | 🧘 | 🤔 |
| blocked | ✅ | ⛔ |

**The numbers keep a constant width.** Dollars, then
`output_tokens/context_peak`, then the clock, padded with figure spaces
(U+2007, one digit wide) so line 1 is the same width in every case up to
the tail's fourth glyph. The clock is always `H"h"MM`. Past `$999.99` or
`999k` a figure turns compact (`1.2k`, `1.2M`) at the same width.

**The tail is how the user is likely to feel:** cognitive load, friction,
fatigue, and a fourth glyph once things are bad. It is the most important
thing on the screen, so it repeats the front with more grades.

| tail slot | good | progression |
|---|---|---|
| cognitive load | 🧘 | 🤔 once decisions reach 3, and it stops there |
| friction | 🌌 | ⚡ 🙄 😠 😡 🤬, one per friction rung |
| fatigue | ⏳ | ⏱️ or 🌙, 🫩, 😩, 😫, 😵‍💫, 😵, at the higher of the time and friction rungs |
| fourth | absent | 🥀 at rung 3 of friction or fatigue, 💀 at rung 4 and above |

Cognitive load tops out at 🤔 and never earns a face or a skull: a session
heavy with decisions is expected and fine. Paired with friction or fatigue,
it is the mirror the tail exists for. Fatigue can show 😩 in daylight,
because friction alone can drive it.

**The time ladder leads with the hour.** Its first rung is ⏱️ by day and
🌙 by night, a soft limit after ⏳; the faces follow, one per rung, and the
line keeps every face it has earned. The front's time slot shows the latest.

```
⏱️🫩😩😫
🌙🫩😩😫😵‍💫😵
```

**The runs follow the front's slot order:** 💸 context, ⚡ friction, ⚖
decisions, ⛔ blocked. Time is not here; it has line 2. Decisions lead with
🤔 once they reach 3. A counted field carries its count, `⚡⚡(x2)`; context
carries one only at overflow.

**A rung value is never a number on screen.** The block's only `a/b` is
`output_tokens/context_peak`; a rung reaches the reader as glyph repetitions
and nothing else. The threshold lines rendered `context_peak/rung` — the same
shape, one line away, meaning something different.

**The session's dollars appear once in each readout.** `$2.39`, sub-agents
included, from the live cache's `cost_usd`; a cache without it shows no dollars.

```
💸😫🌌🧘✅ $  2.39 ⛁  46k/155k ⏱1h33 🧘🌌😫💀
⏱️🫩😩😫
💸💸💸💸 ⚖⚖(x2)
⇢ 3 ⚙ 31 ⎇ 2c1~3↑unpushed  ← not safe to kill
```

**A counted field never vanishes; zero is a state with a glyph.** 🧘
decisions, 🌌 friction, ✅ blocked hold their front slots when nothing has
happened, so "nothing happened" and "this is not measured" never look the
same. See [dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137).
Each calm glyph names its own field, so it carries no family prefix.

**The persistent block appears on every displayed event,** with no counter
or throttle. It always has its status line and its turns line. The turns
line never disappears on a clean tree; git state is appended only when
there is some.

**Nothing is wrong reads as calm glyphs, never words.** No "still room"
filler: a session with nothing to report shows the five good slots, the
calm tail, and lines 1 and 4 only. See
[dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137).

```
🪙⏳🌌🧘✅ $  0.12 ⛁  20k/ 41k ⏱0h05 🧘🌌⏳
⇢ 3 ⚙ 0 ⎇ 1~
```

**Two glyph ladders, one for counts and one for times.** Each escalates
with crossings and never resets within a session. A ladder keeps extending
at the top rather than going quiet; the overflow count is the settled
shape for that.

```
💸💸💸💸💸(x9)
```

**Bias toward more information.** Adding a number or a line never needs a
ruling. Removing one does: a number removed once was missed and had to be
restored. This is a bias for the foreseeable future, not an ultimatum; if
the display proves stable and legible, the user may later ask for more
measured output. Until then, more.

## The ratio in the persistent block

The ratio shown is two real, measured numbers from the session:
`output_tokens` on top, `context_peak` on bottom.

Rung crossings drive glyphs only, never the numbers.

No rung value, no ladder value, no window-size lookup, and no separate
output-tokens badge — settled after repeated attempts on
[dotfiles#144](https://github.com/mark-brannan/dotfiles/pull/144). Don't
re-propose them.

```
💸⏳🌌🧘✅ $  1.28 ⛁  20k/152k ⏱0h00 🧘🌌⏳
💸💸💸💸
```

## Stop output

**Order on Stop:** the block, then the archival line last. The bucket ahead
of the block still exists — the sitting and gate lines feed it — and still
prints first when it has anything in it.

**The archival line always appears on Stop,** with reasons when the session
is not archivable, and both Stop hooks read those reasons from one shared
source so they can never disagree.

```
📦 not archivable: worktree dirty.
```

**The block never depends on a file another hook may delete.** A missing
block on Stop is a bug, not a display choice
([dotfiles#152](https://github.com/mark-brannan/dotfiles/issues/152)).

## Model-facing text and screen text

**They never mix.** Screen text is free and never reaches the model. Model
text is separate and terse, and fires only for stop-worthy crossings:
context past the stop rung, the sitting clock, decision load, friction.
The two are never concatenated into one string.

```
additionalContext: Sitting 2h03 at this machine, past 2h00. Write the single next step as the body (below `---`) of this session's pickup item, <state>/pickup/*-<id>.md, without showing it. Standing orders: "At a sitting rung".
```

**One injection per rung crossed, and one deliberate repeat.** A model line
fires on the event that crosses a rung and says nothing on the events after
it, the same edge-triggered cadence the screen lines use
([dotfiles#282](https://github.com/mark-brannan/dotfiles/issues/282)).

The exception is context, and only context. A rung raised and not acted on
is said again after `METRICS_MODEL_CONTEXT_REPEAT` tool calls of silence,
with the tool count as the new number. Context is the one counter that
climbs while the model works rather than between prompts, so an autonomous
run can spend a whole rung's worth without ever reaching a prompt — and
edge-triggered there means the line is said once, tens of thousands of
tokens before it matters, and never again. Injections also run on
PostToolUse, not prompts alone, so the rung is spoken when it is crossed.
See
[dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137).

**The screen ladder and the model-facing ladder are separate.** Whether
their values coincide is tuning. Both are adjusted in the same place as
every other threshold.

**The sitting clock is one per machine,** driven by prompts only, and
restarts after a long gap. The tail after the context figure varies with the
hour; this sample is the sunset tail, and its minutes drift with the date and
place, so read the shape, not the number.

```
⏱ 2h05 · context 42k · sun sets in 1h 52
```

**Nags stay quiet during a live curia sitting, and gentle ones wait for its
close.** A curia sitting is live while a `state/global/curia/*/LIVE` file names
this session and no close has been recorded for it since; a marker older than 8
hours is ignored, for a session resumed long after a sitting that never closed.
Reactive nags (friction, decision gates, the
two-hour arming of the Stop hand-off) stay silent. Gentle, non-reactive ones
(the sitting clock, bedtime) are not lost: they are held and said once, on the
first prompt after the sitting is no longer live, where they help rather than
interrupt. Counting continues and every metrics file is still written.

**A batch driver and a live curia sitting are hushed.** A driver is a session
that claimed an item carrying a `driver=` Log line. For it and for a live
curia sitting, nothing nags the model: no context line or its repeat, no
sitting line, and the Stop block never asks for a hand-off, whatever armed it.
Crossings are still counted and recorded, and the block still shows them:
hush is about what reaches the model, never the record.

## Thresholds

**Every threshold is easily modifiable by the user,** in one obvious place,
without touching logic. Which values are live today is tuning, not a
requirement. The glyph shapes and the line formats are frozen; the numbers
are not. This reverses the earlier "hard-code, no override" reading of the
[dotfiles#138](https://github.com/mark-brannan/dotfiles/pull/138) review.

## Process

**Display text is plain shell `printf`** the user can edit unassisted. jq
parses the transcript only.

**Small diffs, one concern per PR.** A display change and a threshold
change never share one. Diffs read line by line: whitespace, no long
compound conditions, low cyclomatic complexity. Comments are general and
short, so they survive churn.

**A change to a frozen glyph family is proposed with rendered before/after
examples,** in chat and in the PR body, generated from the examples script,
never captured from a live session. Prose describing a line does not count.
