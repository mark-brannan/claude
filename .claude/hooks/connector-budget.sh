#!/usr/bin/env bash
# SessionStart hook: shout if too many MCP connectors are enabled.
#
# Connectors are the one line of the token floor that can grow without limit
# and without being noticed -- in a local CLI their schemas load in full.
# Measured floor breakdown and the reasoning: .claude/docs/token-budget.md
#
# Silent at or below the threshold. Every line printed here is charged to
# every session, so the quiet path must cost exactly zero.
set -uo pipefail

MAX="${CLAUDE_CONNECTOR_MAX:-5}"
CONF="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
JSON="$HOME/.claude.json"

command -v jq >/dev/null 2>&1 || exit 0

names=""
add() { [ -n "$1" ] && names="$names$1"$'\n'; }

# Global and per-project servers in ~/.claude.json, plus a project .mcp.json.
[ -f "$JSON" ] && {
  add "$(jq -r '.mcpServers // {} | keys[]' "$JSON" 2>/dev/null)"
  add "$(jq -r --arg d "$PWD" '.projects[$d].mcpServers // {} | keys[]' \
         "$JSON" 2>/dev/null)"
}
[ -f "$PWD/.mcp.json" ] && \
  add "$(jq -r '.mcpServers // {} | keys[]' "$PWD/.mcp.json" 2>/dev/null)"

# Servers explicitly denied in settings don't load, so they don't count.
denied=""
for s in "$CONF/settings.json" "$PWD/.claude/settings.json" \
         "$PWD/.claude/settings.local.json"; do
  [ -f "$s" ] && denied="$denied$(jq -r '.deniedMcpServers // [] | .[].serverName' \
                                  "$s" 2>/dev/null)"$'\n'
done

enabled=$(printf '%s' "$names" | sed '/^$/d' | sort -u \
          | grep -vxF -f <(printf '%s' "$denied" | sed '/^$/d' | sort -u) 2>/dev/null \
          || printf '%s' "$names" | sed '/^$/d' | sort -u)
# grep -c, not wc -l: the last name carries no trailing newline.
n=$(printf '%s\n' "$enabled" | grep -c '[^[:space:]]' || true)

[ "$n" -le "$MAX" ] && exit 0

{
  echo "## !! CONNECTOR BUDGET EXCEEDED: $n enabled, limit $MAX !!"
  echo
  echo "Enabled: $(printf '%s' "$enabled" | sed '/^$/d' | paste -sd, - | sed 's/,/, /g')"
  echo
  echo "Tell Mark this in your FIRST reply, before anything he asked for."
  echo "In a local CLI every one of these loads its full tool schemas into"
  echo "the floor of every session. Offer to disable the ones this task does"
  echo "not need (\`deniedMcpServers\` in settings.json), then continue."
} | jq -Rn --rawfile ctx /dev/stdin \
      '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$ctx}}'

exit 0
