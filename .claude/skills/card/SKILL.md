---
name: card
description: Walk the user through one open-loop card, one step at a time, with exact links, click paths and copy-paste commands. Use when they say "walk me through card N", "/card", "escort me through this", or ask to work a specific item off kanban.md or a similar open-loops list. Not for doing the work autonomously — this is for loops only the user can close, in UIs and accounts an agent cannot reach.
---

# Walking a card

The user is at a keyboard in front of a UI you cannot see. You supply the
knowledge; they supply the clicks. Anything they report about what is on
their screen outranks anything you believe about it.

## Pick the card

Find the board the way the standing orders' Continuity section says to —
this project's own `kanban.md` if it has one, else the global board. Read
the whole file, then default to walking one card from `## Yours`: that's
the work only the user can close, which is what this skill is for. If the
argument names a different card or section, walk that one instead. Never
start a second card without being asked.

## Load the real context first

Before the first step, follow the card's links and read them: the PR
comment, the issue, the settings doc, the file. A card is a pointer, not a
briefing.

If the links don't tell you enough to give an exact instruction, say that
plainly and go find out — search the docs, read the API, check the repo.
Guessing a menu label wastes their time twice: once following it, once
recovering.

## One step per message

A step is one of:

- a **URL** to open, complete and clickable;
- a **click path** through a UI: `Settings → Copilot → Coding agent`, naming
  what they should see when they arrive;
- a **command**, fenced, copy-paste ready, with real values already
  substituted — no placeholders they have to fill in, no `<...>`;
- a **question** about what they see, when the next step genuinely depends
  on it.

Then stop and wait. Do not stack steps "so they have them". Do not preview
the remaining ones. A step they can act on in five seconds beats a plan
they have to read.

Say what they should expect to see when the step lands, so they know
immediately whether it worked. That's what makes "that isn't there"
possible.

## When they say it isn't there

"That menu isn't on that page." "The JSON doesn't contain that." "There's
no such button." Treat every one of these as **ground truth about the
world** and your instruction as the thing that was wrong.

- Never repeat the same instruction in different words.
- Say what you got wrong, in one line, and move on. No apology paragraph.
- Ask for exactly what would resolve it — the page title, the visible menu
  items, the actual JSON, a screenshot — and nothing more.
- Then re-derive from what they report. If the UI has genuinely changed and
  you cannot find the new path, say so and park the card rather than
  improvising.

Questions asked mid-walk are answered in place, then you resume from the
same step. Losing their position is the one thing worse than a wrong step.

## Closing the card

When the card is done, close it the way the board says to, and commit with
a message naming what was closed. Say in one line what changed and stop.

If the walk stalls, write what you learned **into the card** before ending
— the step that failed, what the UI actually showed, what would unblock
it. A card that has been half-walked twice with nothing recorded is worse
than one nobody touched.

## Cadence

Short messages. No preamble, no recap of what they just did, no
encouragement. The user is doing the work; your job is to be the next
instruction and then get out of the way.
