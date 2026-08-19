#!/usr/bin/env bash
# statusLine: the always-on readout. Reads the cache `metrics-live.sh` wrote;
# recomputes only when that cache has gone stale, so the jq pass over the
# transcript happens on the order of once per 15s rather than per render.
#
# Free in context terms: statusline output is never sent to the model.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"

# No jq means no readout rather than a broken statusline row.
command -v jq >/dev/null 2>&1 || exit 0

input=$(cat 2>/dev/null || echo '{}')
IFS=$'\t' read -r sid model <<<"$(printf '%s' "$input" \
  | jq -r '[(.session_id // ""), (.model.display_name // "")] | @tsv' 2>/dev/null)"
[ -n "${sid:-}" ] || exit 0

printf '%s' "$input" | bash "$HOOK_DIR/metrics-live.sh" statusline 15

# A custom statusline replaces the default row, so the model name it used to
# carry has to come back from here.
[ -n "${model:-}" ] && printf '%s  ' "$model"

F="$(state_dir)/metrics/live/$sid.json"
[ -f "$F" ] || { printf '⛁ warming up'; exit 0; }

# A cache written before these fields existed, or one caught mid-write, used
# to render "null@? ... null dec": jq succeeds on null, so interpolation
# printed the nulls and the `||` fallback never fired. Check the shape first.
jq -e '.decisions.total != null and .output_tokens != null' "$F" >/dev/null 2>&1 \
  || { printf '⛁ warming up'; exit 0; }

jq -r '
  def k: if . >= 1000 then "\(. / 1000 | floor)k" else "\(.)" end;
  [ "⛁ \(.repo)@\(.branch // "?")",
    "◆ \(.decisions.total) dec (\(.decisions.scoping)s/\(.decisions.inline)i/\(.decisions.gate)g)",
    "↑ \(.output_tokens | k) out · ctx \(.context_peak | k)",
    "⇢ \(.user_turns)p/\(.tool_calls)t",
    (if .commits > 0 or .dirty > 0 or .unpushed > 0
     then "⎇ \(.commits)c" + (if .dirty > 0 then " \(.dirty)~" else "" end)
                            + (if .unpushed > 0 then " \(.unpushed)↑unpushed" else "" end)
     else empty end)
  ] | join("  ")' "$F" 2>/dev/null || printf '⛁ —'
