# Agent decisions

Append-only. Each entry is a call an agent made in pencil: a default it took
under the one-way-door test, with its undo. Written by `agent-decision`; the
heading is the UTC stamp, so `agent_decisions.md#<stamp>` links one entry.

### 20261004t002454z
- Each repo keeps its own docs/agent_decisions.md, written in the PR that makes the call; the claude repo's starts here. Undo: move the entries to one repo. ([#33](https://github.com/mark-brannan/claude/pull/33))
- A curia's copy is <curia>/agent_decisions.md, the same name as the repo file. Undo: rename it. ([#33](https://github.com/mark-brannan/claude/pull/33))
- The trigger is a hand-over line in rules/code.md, not a skill, so every PR session sees it. Undo: revert that line. ([#33](https://github.com/mark-brannan/claude/pull/33))
- Calls in the same second share one heading, as roll.md's words do. Undo: one heading per call. ([#33](https://github.com/mark-brannan/claude/pull/33))

### 20261004t004955z
- docs/agent_decisions.md merges as union, and agent-decision adds that .gitattributes line to any repo it writes in, so parallel PRs that each append an entry rebase without a conflict. Undo: drop the line and ensure_union(). ([#33](https://github.com/mark-brannan/claude/pull/33))

### 20261004t021019z
- prune-worktrees waits 24h of HEAD/reflog idleness before a worktree is eligible Undo: change --hours default in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))
- prune-worktrees lets ignored files (node_modules, dist, settings.local.json) go with a removed worktree Undo: add an ignored-files keep rule ([#34](https://github.com/mark-brannan/claude/pull/34))
- stale worktrees are pruned by a daily 04:30 systemd timer, not the Stop hook Undo: disable prune-worktrees.timer ([#34](https://github.com/mark-brannan/claude/pull/34))

### 20261004t021506z
- prune-worktrees keeps metadata for a missing worktree whose parent directory is also missing (read as an unmounted disk), locking it across the prune Undo: drop prune_metadata's spare list in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))
- prune-worktrees force-removes a worktree with submodules when no submodule holds a commit on none of its remotes, rather than always keeping it Undo: keep every submodule worktree in bin/prune-worktrees ([#34](https://github.com/mark-brannan/claude/pull/34))

### 20261004t035750z
- work-item create: a replay of one create (same id, same content) prints the same id and exits 0 instead of being refused; the pen line says a second write of the same id is refused, and a replay is read as the one write landing twice, not a second write Undo: delete replayed() in bin/work-item and refuse on every FileExistsError ([#37](https://github.com/mark-brannan/claude/pull/37))
