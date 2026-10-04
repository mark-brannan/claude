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

### 20261004t035542z
- stop-continuity spec: Evidence is one column with three values (test / code / item N), not a Source and Test split Undo: a doc PR splitting the column (mark-brannan/claude#36)
- stop-continuity spec: a Then may hold several assertions behind ';', and 'or' in a Given is two fixtures sharing the Then Undo: split the rows (mark-brannan/claude#36)
- stop-continuity spec: sections 1 to 13 are facts about the bash until the Python replaces it; section 14 holds while its ruling does; a disagreement goes to the curia, never to the spec Undo: edit the preamble (mark-brannan/claude#36)
### 20261004t035750z
- work-item create: a replay of one create (same id, same content) prints the same id and exits 0 instead of being refused; the pen line says a second write of the same id is refused, and a replay is read as the one write landing twice, not a second write Undo: delete replayed() in bin/work-item and refuse on every FileExistsError ([#37](https://github.com/mark-brannan/claude/pull/37))
### 20261004t033255z
- A grind item's hard cap, its worker's --max-budget-usd, is 3x its soft cap. Undo: change the 3 in grind's item_hard ([#47](https://github.com/mark-brannan/claude/pull/47))
- grind's run hard budget defaults to 1.5x --session-budget ($30 at the $20 default). Undo: change the 1.5 where grind defaults session_hard_budget ([#47](https://github.com/mark-brannan/claude/pull/47))
- A pr item's soft cap is not scaled by model or effort: the fixup contract's stop is a flat ~$1 every fixup worker reads. Undo: scale the pr branch of item_soft_cap like the others ([#47](https://github.com/mark-brannan/claude/pull/47))
- grind reads a card's budget= off its log lines itself; work-item fold does not carry it, its facts being the format ruled in pen. Undo: add budget to work-item's FACTS and read it from fold ([#47](https://github.com/mark-brannan/claude/pull/47))

### 20261004t050721z
- grind: an item's hard cap is 3x its soft cap, never cut by what the run has left, and the run hard budget (--session-hard-budget, 1.5x) is gone -- Solace's ruling on #47: soft stops, not hard ones; a worker is ended only three times past the stop it was told; more cautious hard stops are a later revisit. Supersedes the 1.5x entry above. Undo: revert the commit on #47 that removed session_hard_budget from bin/grind ([#47](https://github.com/mark-brannan/claude/pull/47))

### 20261004t071038z
- work-item read_brief turns CRLF into a newline before checking, so a brief piped with Windows line endings is accepted as on main; a lone CR is still refused Undo: revert d935ba0 ([#39](https://github.com/mark-brannan/claude/pull/39))

### 20261004t072330z
- Shared helpers named lib/lock.py and lib/gitrun.py Undo: git mv both modules and update the six importers and INSTALL ([#40](https://github.com/mark-brannan/claude/pull/40))
- bin/prune-worktrees keeps its own git runner; gitrun.run takes no env= or input= Undo: add env= and input= to gitrun.run and repoint prune-worktrees ([#40](https://github.com/mark-brannan/claude/pull/40))
