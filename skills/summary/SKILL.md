---
name: summary
description: A terse account of the session so far, in the agent's words — the goal as it was set, whether it was reached, changed course or left open, what it produced, what is left, and where a fresh session would take it next. Printed in the chat; no log, no pickup item, no launch. For a hot context, or between parts of a session the user is building in steps. Not for summarizing a file, a PR or a document.
---

# Summary

What only this session's agent knows: what the user set out to do and how
it went. The numbers (time, decisions, friction, context) are the Stop
hook's and show in the notice already; none of them is restated here.

## The shape

Six lines, each one rendered line, in this order:

```
Goal: make /lastword functional for a curia close (Solace's words: "a reasonably functional point")
Outcome: changed course: dropped the narrative log; the roll already keeps the final words
Produced: mark-brannan/claude#426 (lastword, summary), one commit
State: pushed, CI running, nothing uncommitted
Left: confer and agora closure; the nag still asks for a stopping point, not a summary
Next: point the hot-context nag at /summary
```

- **Goal** is the goal as set, quoting the user where they gave it in words.
  If it moved during the session, the first one, with the move under Outcome.
- **Outcome** is one of `reached`, `changed course: <to what, why>` or
  `open: <what stands in the way>`. Say which; never blend them.
- **Produced** is links: PRs, issues, cards, commits. Nothing produced says
  `nothing`.
- **State** is what a fresh session would find: pushed or not, uncommitted
  work, what is running.
- **Left** is what remains, by concept. Nothing left says `nothing`.
- **Next** is one line: where a fresh session would take it. A
  recommendation, not a launch.

Then stop. It opens nothing: no question, no offer, no "shall I". The user
decides whether to go on, `/handoff` or stop.

## Open

- Whether the hot-context nag points at this skill, in place of asking
  for a stopping point. Until then it runs when the user asks for it.
- Whether the model may invoke it on its own. It is model-invocable now,
  since the nag would be what asks for it.
