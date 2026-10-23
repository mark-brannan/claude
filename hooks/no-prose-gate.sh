#!/bin/sh
# Stop: blocks a turn whose closing line asks permission to do what was
# ordered ("Want me to...?", "Shall I...?", "Proceed?", "Go?", "Merge it?")
# when no AskUserQuestion ran since the human last spoke. Once per turn:
# stop_hook_active on the retry exits 0, as in pr-threads-gate.sh. On
# 2026-10-01 it matched 328 of 1116 prose asks in state metrics/decisions.
# CONVENIENCE: no jq or no transcript -> exit 0; it nags, it never traps.
set -u
command -v jq >/dev/null 2>&1 || exit 0
p=$(cat) || exit 0
[ "$(printf '%s' "$p" | jq -r '.stop_hook_active // false' 2>/dev/null)" = true ] && exit 0
tp=$(printf '%s' "$p" | jq -r '.transcript_path // empty' 2>/dev/null)
[ -f "$tp" ] || exit 0
m=$(printf '%s' "$p" | jq -r '.last_assistant_message // empty' 2>/dev/null)
last=$(tail -n 400 "$tp" | jq -rs --arg m "$m" '
  (to_entries | map(select(.value.type == "user" and (.value.isMeta | not) and ((.value.message.content | type) == "string" or any(.value.message.content[]?; .type == "text"))) | .key) | last // -1) as $h
  | .[$h + 1:] | if any(.[]; .type == "assistant" and any(.message.content[]?; .type == "tool_use" and .name == "AskUserQuestion")) then ""
    else (if $m != "" then $m else ([.[] | select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text] | last // "") end)
    | split("\n") | map(select(test("\\S"))) | last // "" end' 2>/dev/null) || exit 0
printf '%s' "$last" | grep -Eiq '\?[*_ ]*$' || exit 0
printf '%s' "$last" | grep -Eiq '(^|[^a-z])(want me to|shall (i|we)|should i|ok(ay)? to|may i|go ahead|proceed|merge it|push it|ship it|good to (go|add|merge|push|ship)|want (it|that|this|them)( [a-z]+){0,2}\?)|(^|[.!:-] *)go\?' || exit 0
jq -n --arg l "$last" '{decision: "block", reason: ("no-prose-gate: the turn ends asking permission (\"" + $l + "\") without AskUserQuestion. Inside the order: do it now, then report. A one-way door: ask with AskUserQuestion and options. Anything else: take the default, put a ruling card (default, undo, until, risk) in the global board'"'"'s ## Needs ruling via /card-write, and carry on. Then end the turn again; this gate does not fire twice.")}'
