---
name: handoff
disable-model-invocation: true
description: The user's own /handoff, typed by the user only — push the branch, write the hand-off into this session's pickup item and launch a background session that runs /pickup on it, all in one turn. The agent cannot invoke it and never runs handoff-start on its own. Not for a curia sitting (that is /wrapup).
---

# Hand off

One turn. When the turn ends, the next session is already running.

## 1. Land the work

On a branch with work on it: commit what is uncommitted (stage by path),
then push, `git push -u origin HEAD`. The next session starts in the
repo's main worktree and fetches the branch, so anything that isn't on
origin doesn't reach it. A comment on the PR or issue is where anything the
next reader would otherwise redo goes. Skip it when there is nothing to say.

Release the branch, so the next session doesn't read this one as its live
holder: `~/.claude/hooks/claim-stamp.py release -C . --scan $CLAUDE_CODE_SESSION_ID`.

## 2. Launch

Write the hand-off and start the session with one command:

```
~/.claude/bin/handoff-start --body - <<'EOF'
<one sentence, imperative: the next session's first action>
link: <the PR, issue, card or branch it acts on>
model: <opus | sonnet | haiku>
effort: <low | medium | high>
title: <a few words a person would name the session by>
EOF
```

`link` is the work's home: the PR if there is one, else the issue or card,
else the branch. Write links, not state ("#42", not "#42, CI green"). A
session with no home hands off the same way, with the branch as the link.

## 3. Close

Relay the lines `handoff-start` prints, and nothing else: no summary, no
question, no new loop. If it refuses, give its one-line reason and the five
lines above in a fenced block, so the user can paste them into a new session.
