## Writing the hand-off

The other half, for a session that is *leaving* work: the Stop hook already
wrote **your own** pickup item — `state/global/pickup/<start>-<sid8>.md`,
body defaulted to the last prompt line — and it keeps any edit you make to
the body, forever. the user's `/handoff` writes it (and `/wrapup` step 2b), as does a
session when the Stop nag blocks once, or when the user says "update
the hand-off". The nag is a backstop, not the trigger: it arms on a
context, clock or friction crossing, and a session that ends cleanly never
sees it. Replace everything below the `---` with five lines, house hand-off
spec, through `~/.claude/bin/pickup-list handoff <id>` with the lines on
stdin:

```
<one sentence, imperative — what the next session does first>
link: <the branch, PR, issue or card it acts on>
model: <opus | sonnet | haiku>
effort: <low | medium | high>
title: <a few words a person would name the session by>
```

Push before you write it — the item points at a branch, and a branch that
only exists in your worktree hands over nothing. A session that is *finished*
(pushed, PR open) also releases its worktree, so the branch is free for
whoever picks it up; one that is pausing mid-work keeps it, and the branch
stays claimed until it comes back.

One item per session; the newest edit replaces. The first line is a step,
not a status — "add the fixture for a taken item", never "pickup-list is
half done". No state adjectives: the link carries state, live, at the other
end.

This is not a wrap-up. The hand-off costs five lines; `/wrapup` costs a
log and is for a curia sitting or a session the user asks to log. If the
checkpoint's verdict line says `archivable`, the five lines are usually all
that is wanted, and often not even that.
