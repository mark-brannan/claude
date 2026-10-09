#!/usr/bin/env bash
# SubagentStop: a finished sub-agent lets go of its branch.
#
# Why: Claude Code removes a sub-agent's worktree on exit only when nothing
# changed in it. A sub-agent that committed keeps its worktree, and with it
# the branch checked out -- for good, since nothing ever comes back to
# release it. git then refuses that branch to every other worktree, and the
# pickup skill reads the refusal as a live claim: claude#108 sat unworkable
# behind a sub-agent that had finished hours before.
#
# A session releases its worktree when it finishes (pushed, PR open); this
# does the same for a sub-agent, at the moment it finishes. It detaches the
# worktree's HEAD and nothing else -- the worktree, its files and the branch
# all stay, so there is nothing to undo, and `git switch <branch>` inside it
# takes the branch back.
#
# Only when the work is safe elsewhere: the tree is clean (untracked files
# count) and every commit on HEAD is on some remote-tracking ref. A dirty or
# unpushed worktree keeps its branch, so its work stays where a human looking
# for it will find it. No network: a remote ref that is stale only makes the
# check stricter.
#
# Locates the worktree from the sub-agent's own transcript (its cwd), falling
# back to <repo>/.claude/worktrees/agent-<agent_id> under the parent's repo --
# where the Agent tool puts it. Fails open, silently: a session must never be
# unable to end because a branch could not be released.
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)
IFS=$'\t' read -r id tr cwd <<<"$(printf '%s' "$input" | jq -r \
  '[(.agent_id // "-"), (.agent_transcript_path // "-"), (.cwd // "-")] | @tsv')"
case $id in '' | - | *[!A-Za-z0-9_-]*) exit 0 ;; esac

wt=
if [ "$tr" != - ] && [ -f "$tr" ]; then
  wt=$(grep -o "\"cwd\":\"[^\"]*/\.claude/worktrees/agent-$id\"" "$tr" | head -1 |
    sed 's/^"cwd":"//; s/"$//')
fi
if [ -z "$wt" ] && [ "$cwd" != - ]; then
  common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) &&
    wt="$(dirname "$common")/.claude/worktrees/agent-$id"
fi
[ -n "$wt" ] && [ -d "$wt" ] || exit 0
[ "$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null)" = "$wt" ] || exit 0

git -C "$wt" symbolic-ref -q HEAD >/dev/null || exit 0 # already detached
[ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ] || exit 0
unpushed=$(git -C "$wt" rev-list -n1 HEAD --not --remotes 2>/dev/null) || exit 0
[ -z "$unpushed" ] || exit 0

git -C "$wt" switch -q --detach 2>/dev/null || true
exit 0
