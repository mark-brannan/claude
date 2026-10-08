#!/usr/bin/env bash
# PostToolUse Edit|Write|MultiEdit: after a markdown or JSON file is written
# inside a repo that has a prose-budget config, run the tree rules on that
# one file and hand any findings back as additionalContext. Advisory only:
# it never blocks, and the commit hook and CI are the gates.
#
# Silent on the quiet path (no jq, no engine, no config, other file types,
# clean file under 2/3 of its cap): every line printed here is charged to the session.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
ENGINE="${PROSE_BUDGET:-$(command -v prose-budget 2>/dev/null || echo "$HERE/../bin/prose-budget")}"

command -v jq >/dev/null 2>&1 || exit 0
[ -x "$ENGINE" ] || exit 0

input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
case "$file" in *.md|*.json) ;; *) exit 0 ;; esac
[ -f "$file" ] || exit 0

errf=$(mktemp); trap 'rm -f "$errf"' EXIT
out=$(cd "$(dirname "$file")" && "$ENGINE" --tree --file "$file" 2>"$errf")
rc=$?
# The engine reports a budgeted file's count as "lines: <file> 398/400".
count=$(sed -n 's/^prose-budget: lines: .* \([0-9]*\/[0-9]*\)$/\1/p' "$errf" | head -1)

case "$rc" in
  1|2) msg=$(printf '%s\n' "prose-budget on $file${count:+ ($count lines)}:" "$out" \
         "$(grep -v '^prose-budget: [a-z_]*: ' "$errf")" "Fix these before the push; CI fails on them.") ;;
  # A clean budgeted file speaks only past 2/3 of its cap.
  0) [ -n "$count" ] && [ $((${count%/*} * 3)) -gt $((${count#*/} * 2)) ] || exit 0
     msg="prose-budget: $file $count lines." ;;
  *) exit 0 ;;
esac
printf '%s\n' "$msg" | sed '/^$/d' \
  | jq -Rn --rawfile ctx /dev/stdin '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
