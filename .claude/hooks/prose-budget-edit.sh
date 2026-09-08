#!/usr/bin/env bash
# PostToolUse Edit|Write|MultiEdit: after a markdown or JSON file is written
# inside a repo that has a prose-budget config, run the tree rules on that
# one file and hand any findings back as additionalContext. Advisory only:
# it never blocks, and the commit hook and CI are the gates.
#
# Silent on the quiet path (no jq, no engine, no config, other file types,
# clean file): every line printed here is charged to the session.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENGINE="${PROSE_BUDGET:-$(command -v prose-budget 2>/dev/null || echo "$HERE/../../.local/bin/prose-budget")}"

command -v jq >/dev/null 2>&1 || exit 0
[ -x "$ENGINE" ] || exit 0

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
case "$file" in *.md|*.json) ;; *) exit 0 ;; esac
[ -f "$file" ] || exit 0

out=$(cd "$(dirname "$file")" && "$ENGINE" --tree --file "$file" 2>&1)
rc=$?
case "$rc" in 1|2) ;; *) exit 0 ;; esac

printf '%s\n' "prose-budget on $file:" "$out" "Fix these before committing; the commit hook will deny the commit otherwise." \
  | jq -Rn --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
