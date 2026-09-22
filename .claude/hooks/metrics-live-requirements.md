# metrics-live.sh: requirements

Rulings by the user, 2026-09-10, from the strategy review in
[dotfiles#149](https://github.com/mark-brannan/dotfiles/issues/149) and the
review threads on the PRs before it. Each item is the intent and one line it
governs. Values in the examples are tuning, not part of the ruling.

## What is shown, and how often

**A notice on every event, and one notice per event.** On every Stop and on
most tool invocations — high frequency, one block each time. Louder and *more
often* is the direction; going quieter is never a cleanup, and display lines
cost no tokens, so frequency is free.

This corrects what was written here before. `#149` was read as a ruling about
lines *per event*: "more lines, not fewer... do not coalesce, dedupe or fire
at the right time", so a jump across four rungs printed four lines. Ruled by
Solace, 2026-09-22 ([dotfiles#137](https://github.com/mark-brannan/dotfiles/issues/137)):
that was never the ask. He was pushing back on repeated attempts to make the
readout appear **less often**. Frequency, not line count. A four-rung jump
renders one block with four ⛁ in it.

```
⛁⛁⛁⛁ 46k/155k ⚖(x1) 🔧⛔(x2) ⏱1h33⏱️⏱️⏱️⏱️ — 💸 propose stopping.
⇢ 1 ⚙ 59
```

**A rung value is never a number on screen.** The block's only `a/b` is
`output_tokens/context_peak`; a rung reaches the reader as glyph repetitions
and nothing else. The threshold lines rendered `context_peak/rung` — the same
shape, one line away, meaning something different.

**The persistent block appears on every displayed event,** with no counter
or throttle. It always has its status line and its turns line. The turns
line never disappears on a clean tree; git state is appended only when
there is some.

```
» 20/41k 🔧✅(x0) — still room.
⇢ 3 ⚙ 0 ⎇ 1~
```

**Two glyph ladders, one for counts and one for times.** Each escalates
with crossings and never resets within a session. A ladder keeps extending
at the top rather than going quiet; the overflow count is the settled
shape for that.

```
⛁⛁⛁⛁⛁(x9) 10/350k 🔧✅(x0) ⏱0m — 💸 propose stopping.
```

**Bias toward more information.** Adding a number or a line never needs a
ruling. Removing one does: a number removed once was missed and had to be
restored. This is a bias for the foreseeable future, not an ultimatum; if
the display proves stable and legible, the user may later ask for more
measured output. Until then, more.

## The ratio in the persistent block

The ratio shown is two real, measured numbers from the session:
`output_tokens` on top, `context_peak` on bottom.

Rung crossings drive only the leading glyph, never the numbers.

No rung value, no ladder value, no window-size lookup, and no separate
output-tokens badge — settled after repeated attempts on
[dotfiles#144](https://github.com/mark-brannan/dotfiles/pull/144). Don't
re-propose them.

```
⛁⛁⛁⛁ 20/152k 🔧✅(x0) ⏱0m — 💸 propose stopping.
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
additionalContext: Sitting 2h03, past 2h00. Already raised at 1h00 and not acted on. Stop here and run /wrapup.
```

**One injection per rung crossed, never a repeat.** A model line fires on
the prompt that crosses a rung and says nothing on the prompts after it,
the same edge-triggered cadence the screen lines use
([dotfiles#282](https://github.com/mark-brannan/dotfiles/issues/282)).

**The screen ladder and the model-facing ladder are separate.** Whether
their values coincide is tuning. Both are adjusted in the same place as
every other threshold.

**The sitting clock is one per machine,** driven by prompts only, and
restarts after a long gap.

```
⏱ sitting 1h00 — context 41k: stand up.
```

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
