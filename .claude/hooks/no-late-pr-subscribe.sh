#!/usr/bin/env bash
# Blocks subscribe_pr_activity once this session's context has grown past the
# point where watching is cheaper than starting fresh.
#
# Why: subscribing is free while idle, but every wake re-sends the session's
# whole accumulated context as cache-read input, and the session only grows
# from there. A watcher armed at 30k tokens is cheap; the same watcher armed
# at 150k pays that 150k back on every comment, every check, for the life of
# the PR. Past the threshold the fire-and-forget path is strictly cheaper:
# push, open the PR, end the turn, archive the chat, pick the PR up fresh.
#
# This is the enforcement half of the "Babysitting a PR is cheap; polling for
# it is not" rule in ~/.claude/rules/code.md, which was prose-only and so was
# only followed when it happened to be in context.
#
# The threshold is a fraction of the window, not a fixed 100k, because a fixed
# number means different things on different plans: 100k is 50% of the default
# 200k window but 10% of the 1M window Opus auto-upgrades to on Max, where it
# would refuse watching for no reason. 60% is the number:
#   - a realistic wake costs 5-15k (event payload, CI logs, diff, a fix turn),
#     so 40% headroom on a 200k window is roughly 6-10 wakes
#   - cloud/web sessions -- exactly the class that subscribes to PR activity --
#     compact as they *approach* the limit rather than at it, and what
#     compaction drops is the reasoning behind the diff under review
#   - prompt cache lives 1h on a subscription; PR events routinely arrive
#     further apart than that, so a large share of wakes are cache misses that
#     reprocess the whole context at ~10x the cached rate
# Plus a hard floor: never subscribe with less than 60k of headroom, whatever
# the window, so the fraction cannot authorize a watch that has no room to run.
# Sources: code.claude.com/docs/en/{model-config,costs,context-window}.
#
# Token count is not passed to hooks directly. It is derived the same way
# statusline-metrics.sh derives it: the last assistant `usage` block in the
# transcript, whose input + cache_read + cache_creation is the context that
# request actually carried. Only the tail is scanned -- transcripts run to
# tens of MB and the newest usage record is always near the end.
set -uo pipefail

# Override any of these per-session. WINDOW must be raised by hand for a 1M
# session -- the hook payload does not carry the model's context window.
WINDOW=${CLAUDE_PR_WATCH_CONTEXT_WINDOW:-200000}
PERCENT=${CLAUDE_PR_WATCH_CONTEXT_PERCENT:-60}
FLOOR=${CLAUDE_PR_WATCH_MIN_HEADROOM:-60000}

# Whichever binds first: the fraction, or the headroom floor.
LIMIT=$(( WINDOW * PERCENT / 100 ))
[ $(( WINDOW - FLOOR )) -lt "$LIMIT" ] && LIMIT=$(( WINDOW - FLOOR ))
# An explicit absolute limit still wins outright.
if [ -n "${CLAUDE_PR_WATCH_TOKEN_LIMIT:-}" ]; then
  LIMIT=$CLAUDE_PR_WATCH_TOKEN_LIMIT
  basis=""
else
  basis=" (${PERCENT}% of a $(( WINDOW / 1000 ))k window)"
fi
[ "$LIMIT" -gt 0 ] || exit 0

input=$(cat)

# No jq means no measurement; fail open rather than blocking blind.
command -v jq >/dev/null 2>&1 || exit 0

transcript=$(printf '%s' "$input" | jq -r '.transcript_path // ""' 2>/dev/null)
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

ctx=$(tail -n 500 "$transcript" 2>/dev/null | jq -s -r '
  [ .[] | select(.type == "assistant") | .message.usage
    | select(. != null)
    | ((.input_tokens // 0) + (.cache_read_input_tokens // 0)
       + (.cache_creation_input_tokens // 0)) ]
  | (max // 0)' 2>/dev/null) || exit 0

case "$ctx" in ''|*[!0-9]*) exit 0 ;; esac
[ "$ctx" -ge "$LIMIT" ] || exit 0

k=$((ctx / 1000))
limk=$((LIMIT / 1000))

jq -n --arg r "Blocked by ~/.claude/hooks/no-late-pr-subscribe.sh: this session is at ~${k}k tokens, at or over the ~${limk}k watch threshold${basis}. Every wake on this subscription would re-send that whole context, and it only grows from here. Take the fire-and-forget path instead: push, open the PR (draft, no reviewer), then end the turn with the follow-up prompt that would resume the work, plus \"You should archive this chat now. It's at ~${k}k tokens.\" No webhook, no wake -- pick the PR up fresh in a new session." '
  {hookSpecificOutput: {
     hookEventName: "PreToolUse",
     permissionDecision: "deny",
     permissionDecisionReason: $r}}'
exit 0
