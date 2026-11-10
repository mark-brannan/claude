---
name: lastword
disable-model-invocation: true
description: The user's own /lastword, typed by the user only — close a curia sitting so the user's words come last and the sitting reads as closed until the next one. Runs the curia skill's Closing, writes the next sitting into this session's pickup item, and then answers whatever the user says with one line. The agent cannot invoke it. Not for a plain hand-off (that is /handoff); replaces /wrapup for a curia.
---

# Last word

Typing `/lastword` is the moment the curia skill's Closing calls "the user
says when". This skill runs that Closing and adds only what keeps the
user's words last. The curia skill owns the closing steps; none are copied
here.

## 0. Is a sitting live in this session

Find the curia whose `LIVE` file (`state/global/curia/<id>/LIVE`) names
this session, with no `CLOSED` beside it stamped at or after that `LIVE`.
None: say in one line that no sitting is live here, and stop.
Closure for a confer or the agora is not built yet.

## 1. Run the curia skill's Closing, with two additions

Anything the sitting opened and did not close goes into the curia's
document in Closing step 1, so the closing message carries nothing that
is not written there.

**Before Closing step 4, write the next sitting into the pickup item.**
Past a context or clock line, the Stop hook asks for a hand-off unless
the pickup item already holds one. That ask would land after the close
and give the agent the last word.

```
~/.claude/bin/pickup-list handoff "$(~/.claude/bin/pickup-list own "${CLAUDE_CODE_SESSION_ID:0:8}")" <<'EOF'
Open the next sitting: /curia <id>
link: state/global/curia/<id>/
model: <from the curia document's header>
effort: <from the curia document's header>
title: <id> curia, next sitting
EOF
```

It launches nothing; the next sitting starts when the user types
`/curia <id>`.

**After Closing step 5, release the branch:**
`~/.claude/hooks/claim-stamp.py release -C . --scan $CLAUDE_CODE_SESSION_ID`
(a no-op when the sitting held no claim).

Closing steps 2 to 4 make up the closing message, together with links to
any decision or click-work cards the sitting wrote. Nothing else goes in it.

## 2. The user speaks last

The roll hook records what the user types after the close; the agent
writes nothing for it. Answer with one line at most, naming where it
landed (`<id>/roll.md`). If it changes the next sitting's first action,
update the pickup item's first line and say so in that same line. Then
stop. A Stop-hook block after this gets what it asks for and the same one
line.

## Open

- **Confer sessions and the agora.** Whether they want the same closure;
  step 0 refuses them for now.
- **Retiring `/wrapup`.** Once this and `/handoff` cover its uses and its
  user-only flag shows it unused.
