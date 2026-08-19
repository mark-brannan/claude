#!/usr/bin/env bash
# PostToolUse: log the git events that carry a cost Mark ends up paying.
#
# Three kinds, and only three -- logging every commit would make this a commit
# log wearing a metrics label, and the signal is the whole point:
#
#   cherry-pick  shuttling a commit between branches; the original question
#                was how much of that is actually happening
#   branch       `rules/code.md` says a branch requires Mark's explicit ask,
#                because a branch demands a PR and a PR is a decision pushed
#                to him. Five stranded `claude/*` branches is what prompted
#                that rule; this is the counter that would have shown them
#   pr           the decision itself, logged as high-cost by definition
#
# Supersedes measure-cherry-pick.sh, whose matcher bug is worth remembering:
# it was once `Bash(git commit.*)`, which is permission-rule syntax. As a
# regex that requires a tool literally named `Bashgit commit...`, so the hook
# never fired once. Match the tool NAME; filter the command in here.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"

command -v jq >/dev/null 2>&1 || exit 0

input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // ""')
cwd=$(printf '%s' "$input" | jq -r '.cwd // ""')
sid=$(printf '%s' "$input" | jq -r '.session_id // "unknown"')
ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

SD="$(state_dir)/metrics/git-events"
emit() {  # kind, detail-json
  mkdir -p "$SD" 2>/dev/null || exit 0
  jq -nc --arg ts "$ts" --arg sid "$sid" --arg kind "$1" \
         --arg repo "$repo" --arg branch "$branch" --argjson d "$2" \
    '{ts:$ts, session_id:$sid, kind:$kind, repo:$repo, branch:$branch} + $d' \
    >> "$SD/$sid.jsonl"
}

case "$tool" in
  *create_pull_request)
    repo=$(printf '%s' "$input" | jq -r '.tool_input.repo // ""')
    branch=$(printf '%s' "$input" | jq -r '.tool_input.head // ""')
    emit pr "$(printf '%s' "$input" | jq -c '{title: (.tool_input.title // ""),
                                              base: (.tool_input.base // "")}')"
    exit 0
    ;;
  Bash) ;;
  *) exit 0 ;;
esac

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
printf '%s' "$cmd" \
  | grep -qE '\bgit\b.*\b(commit|cherry-pick|checkout|switch)\b|\bgh\b.*\bpr\b.*\bcreate\b' \
  || exit 0

[ -n "$cwd" ] && cd "$cwd" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
repo=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$cwd")")
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

# PR opened from the CLI
if printf '%s' "$cmd" | grep -qE '\bgh\b.*\bpr\b.*\bcreate\b'; then
  emit pr '{"title":"","base":""}'
fi

# Branch created. `git checkout -b` / `git switch -c` is the moment a PR
# becomes inevitable, so that is the moment worth counting.
newbr=$(printf '%s' "$cmd" \
  | sed -nE 's/.*\bgit[[:space:]]+(checkout[[:space:]]+-b|switch[[:space:]]+-c)[[:space:]]+([^[:space:];&|]+).*/\2/p' \
  | head -1)
[ -n "$newbr" ] && emit branch "$(jq -nc --arg b "$newbr" '{created_branch:$b}')"

# Cherry-pick: identified from the commit trailer, not from the command, so a
# `git commit` finishing a conflicted pick still counts.
commit=$(git rev-parse HEAD 2>/dev/null || echo "")
[ -n "$commit" ] || exit 0
msg=$(git log -1 --format=%B "$commit" 2>/dev/null || echo "")
if printf '%s' "$msg" | grep -q "^(cherry picked from commit"; then
  original=$(printf '%s' "$msg" \
    | sed -n 's/^(cherry picked from commit \([a-f0-9]*\).*/\1/p' | head -1)
  last=$(tail -1 "$SD/$sid.jsonl" 2>/dev/null | jq -r 'select(.kind=="cherry_pick") | .commit // ""' 2>/dev/null)
  [ "$last" = "$commit" ] || \
    emit cherry_pick "$(jq -nc --arg c "$commit" --arg o "$original" \
                          '{commit:$c, original_commit:$o}')"
fi
exit 0
