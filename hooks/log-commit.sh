#!/usr/bin/env bash
# Appends one JSON line per real git commit, so commits are traceable back
# to the session and machine that made them.
#
# Fires on PostToolUse for Bash and returns immediately unless the command
# actually committed something. Filters on the command text, not the
# matcher (see measure-cherry-pick.sh for why matcher-side filtering
# doesn't work here).
set -euo pipefail

input=$(cat)
tool=$(printf '%s' "$input" | jq -r '.tool_name // ""')
[ "$tool" = "Bash" ] || exit 0

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
printf '%s' "$cmd" | grep -qE '\bgit\b.*\bcommit\b' || exit 0

cwd=$(printf '%s' "$input" | jq -r '.cwd // ""')
[ -n "$cwd" ] && cd "$cwd" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

commit=$(git rev-parse HEAD 2>/dev/null || echo "")
[ -n "$commit" ] || exit 0

repo=$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "$cwd")")
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
sid=$(printf '%s' "$input" | jq -r '.session_id // env.CLAUDE_CODE_SESSION_ID // ""')

# Same placement rule as log-decisions.sh / measure-cherry-pick.sh: this is
# session content, and dotfiles is public. Fall back to a gitignored local
# dir when the private state repo isn't cloned on this machine.
log_dir="$HOME/claude_prompts_scratch/state/global"
[ -d "$HOME/claude_prompts_scratch/.git" ] || log_dir="$HOME/.claude/journal"
mkdir -p "$log_dir"

jq -nc \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg session_id "$sid" \
  --arg remote_session_id "${CLAUDE_CODE_REMOTE_SESSION_ID:-}" \
  --arg repo "$repo" --arg branch "$branch" --arg commit "$commit" \
  --arg version "${CLAUDE_CODE_VERSION:-}" \
  '{ts:$ts, session_id:$session_id, remote_session_id:$remote_session_id, repo:$repo, branch:$branch, commit:$commit, claude_code_version:$version}' \
  >> "$log_dir/commits.jsonl"

exit 0
