#!/usr/bin/env bash
# PreToolUse guard for mcp__Claude_Code_Remote__add_repo.
#
# The continuity state repo must attach silently in every cold cloud session,
# including auto mode -- that was the point of allowing add_repo at all. But a
# bare allow rule can't see arguments, so it also let ANY repo attach with
# push credentials, no prompt, on the say-so of whatever text steered the
# session. This hook keeps the standing allow for exactly the one repo the
# continuity hooks need and lets every other add_repo fall through to the
# normal permission flow (a prompt when Mark is present, a refusal in auto).
set -uo pipefail

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)

owner=$(jq -r '.tool_input.owner // ""' <<<"$input")
repo=$(jq -r '.tool_input.repo // ""' <<<"$input")

if [ "$owner" = "mark-brannan" ] && [ "$repo" = "claude_prompts_scratch" ]; then
  jq -n '{hookSpecificOutput:{hookEventName:"PreToolUse",
          permissionDecision:"allow",
          permissionDecisionReason:"continuity state repo -- standing allow"}}'
fi

exit 0
