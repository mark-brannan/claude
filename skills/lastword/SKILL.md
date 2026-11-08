---
name: lastword
disable-model-invocation: true
description: The user's own /lastword, typed by the user only — close a curia sitting so the user's words come last and the sitting reads as closed until the next one. Runs the curia skill's Closing, writes the next sitting into this session's pickup item, and then answers whatever the user says with one line. The agent cannot invoke it. Not for a plain hand-off (that is /handoff); replaces /wrapup for a curia.
---

# Last word

The user wants one thing from the end of a curia sitting that no other
skill gives: the sense of getting their words in last, and that the sitting
is closed until they are ready to discuss again. Typing `/lastword` is the
moment the curia skill's Closing calls "the user says when".

The curia skill owns the closing mechanics; this skill runs them and adds
what makes the close hold. It copies none of them.

## 0. Is a sitting live in this session

Find the curia whose `LIVE` file (`state/global/curia/<id>/LIVE`) names
this session. None: say in one line that no sitting is live here, and stop.
Closure for a confer or the agora is not built yet.

## 1. Capture before closing

Anything opened in the sitting and not closed — a thread, a question, a
doubt — goes into the curia's own document now, where its next opening
reads it: an open question under **Open questions**, the rest in **Where
this stands** (step 2). Nothing is carried in the closing message that is
not written there first.

## 2. Run the curia skill's Closing

All six steps, in order, as the curia skill writes them: land the edits and
rewrite the two sections, spawn the runner in the background, say what is
open, print the paste-again prompt, write `CLOSED`, open nothing.

## 3. Write the next sitting into the pickup item

Before the closing message. The Stop hook asks for a hand-off when a
context or clock line has been crossed, and it stays silent only when this
session's pickup item already has one; without it, the hook's ask lands
after the close and the agent, not the user, speaks last.

```
~/.claude/bin/pickup-list handoff "$(~/.claude/bin/pickup-list own "${CLAUDE_CODE_SESSION_ID:0:8}")" <<'EOF'
Open the next sitting: /curia <id>
link: state/global/curia/<id>/
model: <from the curia document's header>
effort: <from the curia document's header>
title: <id> curia, next sitting
EOF
```

This writes the hand-off only; it launches nothing. The next sitting starts
when the user types `/curia <id>`.

## 4. Release the branch

`~/.claude/hooks/claim-stamp.py release -C . --scan $CLAUDE_CODE_SESSION_ID`
— a no-op when the sitting held no claim.

## 5. The closing message

Exactly two things: the paste-again prompt from Closing, and links to any
decision or click-work cards the sitting wrote. It opens nothing: no new
question, doubt, hint or "one more thing". It may say "next time we discuss
X" only for an X already written in step 1. It never asks the user to
review or merge.

## 6. The user speaks last

`LIVE` stays in place after `CLOSED`, so the roll hook keeps appending what
the user types to the curia's `roll.md`, verbatim and stamped. The agent
writes nothing for it.

Answer whatever the user says next with one line at most, naming where it
landed (`<id>/roll.md`). If the words change the next sitting's first
action, update the pickup item's first line and say so inside that same
line. Then stop, and stay stopped: a Stop-hook block after this point is
answered with what it asks for and the same one line.

## Open

- **A narrative log.** None here: `roll.md`, **Where this stands** and the Trace hold what `/wrapup`'s did.
- **Confer sessions and the agora.** Whether they want the same closure;
  step 0 refuses them for now.
- **Retiring `/wrapup`.** Once this and `/handoff` cover its uses and its
  user-only flag shows it unused.
