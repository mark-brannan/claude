---
name: card-helper
description: Walk the user through one open-loop card, one step at a time, with exact links, click paths and copy-paste commands. Use when they say "walk me through card N", "/card-helper", "escort me through this", or ask to work a specific card off the board or a similar open-loops list. Not for doing the work autonomously — this is for loops only the user can close, in UIs and accounts an agent cannot reach.
---

# Walking a card

The user is at a keyboard in front of a UI you cannot see. You supply the
knowledge; they supply the clicks. Anything they report about what is on
their screen outranks anything you believe about it.

## Pick the card

Run `/sweep` first, so a card already closed elsewhere is never walked.
Find it the way `/card-write` routes; its rules are the contract, don't
paraphrase them here. An issue is walked exactly like a card. A card is an
item file under `state/global/items/`: `~/.claude/bin/work-item show <id>`
prints it whole, and `work-item list` lists the live ones (owner
`human-click` is what used to sit under `## Human's`). A card can be
named by its id (`card 1790836842077c62eb`): `~/.claude/bin/worklist card <id>`
prints it with its section, and every message about it carries the id. The default
is the card or issue the user names, else the top card owned `human-click`:
that's the work only the user can close, which is what this skill is for.
A card there carries `why you:` and `why this:`; read both before the
first step, and if `why this:` no longer holds — the cause was something
else, the secret was already in sops — say so and stop rather than walk
the wrong fix. A `why you: learn` card is walked at the user's pace and
stays until they say they have it. Never start a second one without being
asked.

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

Questions asked mid-walk are answered in place, then you continue from the
same step. Losing their position is the one thing worse than a wrong step.

## Closing the card

When the card is done, retire it as `/sweep` does, its Retire steps and
[the lifecycle](../../docs/work-item-lifecycle.md): `work-item claim <id>`
(an `open` card gets `log <id> status=ready` first), then `log <id> status=done
'evidence=<link>'` (the link that shows it; with none, one clause of the
user's words with no `=` in it; quoted as `/sweep` quotes it, here-doc and
variable, so a `'` in the text is safe), and stop. No skill
writes `closed`. The Stop hook commits the item files. A card owned
`human-ruling` stays until the ruling has landed somewhere durable — the PR,
the ADR, the doc it settles — then it is retired the same way. Say in one
line what changed and stop.

If the walk stalls, write what you learned **into the card or issue**
(a card: first `work-item fold <id>`; a `holder=` that is set with
`holder_stale=no` means another live session has it, so say who and leave it
alone, since `brief` does not check. Otherwise `work-item show <id>`, copy the
text under `## Brief` minus the `points:` line, add the lines, send it back
with `work-item brief <id> -`)
before ending — the step that failed, what the UI actually showed, what
would unblock it. A loop that has been half-walked twice with nothing
recorded is worse than one nobody touched.

## Cadence

Short messages. No preamble, no recap of what they just did, no
encouragement. The user is doing the work; your job is to be the next
instruction and then get out of the way.
