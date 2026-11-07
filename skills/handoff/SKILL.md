---
name: handoff
description: Hand a session to the next one in a single turn — push the branch, write the pickup item's hand-off, start the next session, and report where to find it. No narrative log, no paste prompt, no `start` word. Use when the user says "hand off", "hand-off", "next session", "kick off the next one", "call it there", or a session is ending with work that has a home (a PR, an issue, a card or a pushed branch). Not for a curia sitting or a session whose work has no home yet; those are /wrapup.
---

# Handing off

The hand-off is what you do on the user's word. Nothing waits for a second
word. The Stop hook already saves the session record and the checkpoint,
so this skill writes only what it alone can: the next step, and the
session that takes it.

## When it is /wrapup instead

- a curia sitting (`/curia <id>` ran this session), whose meaning belongs
  in a narrative log;
- the user said "wrap up" or "log it";
- the work has no home: no PR, no issue, no card, and no branch worth
  pushing. Give it one first (a card through `/card-write`, or push the
  branch); then it is a hand-off again.

## Steps, all in one turn

1. **Push the branch** if the session has one: `git push -u origin <branch>`.
   A `/pickup` on another machine finds nothing on a branch that is not on
   origin.
2. **Leave what was learned at the home.** If the session tried and dropped
   something the next reader would redo, put it in one comment on the PR or
   issue. Nothing learned, no comment.
3. **Write the hand-off** into this session's pickup item, the four lines
   (plus `title:`) on stdin:

   ```
   ~/.claude/bin/pickup-list handoff <item-id> <<'EOF'
   <one imperative sentence: the next session's first action>
   link: <the PR, issue, card or branch it acts on>
   model: <opus | sonnet | haiku>
   effort: <low | medium | high>
   title: <a few words a person would name the session by>
   EOF
   ```

   The item id is the Stop hook's pickup item for this session
   (`pickup-list` lists it). Links, not state adjectives; never "review"
   or "merge" as the action, since the PR is where those live.
4. **Start it:** `~/.claude/bin/handoff-start --title "<title>" <item-id>`.
   It runs the next session in the repo's main worktree.
5. **Release the branch:** `~/.claude/hooks/claim-stamp.py release -C . --scan <session id>`,
   unless the session is only pausing and keeps its worktree.

## The closing message

The lines `handoff-start` printed, under one line naming the hand-off:

```
Handed off: <the first line of the hand-off> (<model> · <effort>)
pickup started: Hand-off <id>: <title>, session <sid>, in <dir>
  Claude Desktop: the session list, "Hand-off <id>: <title>"
  browser:        https://claude.ai/code/…
  this terminal:  claude attach <short>
```

Add links to any decision or click-work cards the session wrote, and
nothing else: no question, no recap, no "one more thing".

If `handoff-start` refuses, relay its refusal and the hand-off's first
line as a prompt to paste. That is the only case where anything is pasted.

## The user's last word

If the user replies after the close, answer in one line. If their words
change the next action and the session has not picked the item up yet,
update the item's first line and say so in that same line.
