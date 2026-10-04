# Agent decisions

Append-only. Each entry is a call an agent made in pencil: a default it took
under the one-way-door test, with its undo. Written by `agent-decision`; the
heading is the UTC stamp, so `agent_decisions.md#<stamp>` links one entry.

### 20261004t002454z
- Each repo keeps its own docs/agent_decisions.md, written in the PR that makes the call; the claude repo's starts here. Undo: move the entries to one repo. ([#33](https://github.com/mark-brannan/claude/pull/33))
- A curia's copy is <curia>/agent_decisions.md, the same name as the repo file. Undo: rename it. ([#33](https://github.com/mark-brannan/claude/pull/33))
- The trigger is a hand-over line in rules/code.md, not a skill, so every PR session sees it. Undo: revert that line. ([#33](https://github.com/mark-brannan/claude/pull/33))
- Calls in the same second share one heading, as roll.md's words do. Undo: one heading per call. ([#33](https://github.com/mark-brannan/claude/pull/33))
