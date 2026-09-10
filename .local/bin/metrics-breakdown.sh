#!/bin/sh
# On-demand breakdown of one session's decision/friction triples and git-event
# counts -- the detail dotfiles#132 explicitly dropped from the nag display
# (⚖0[0/0/0], ⚡0[0/0/0], tool-call/git-event counts) rather than bring back.
# The data was never deleted: metrics-live.sh already caches it in
# metrics/live/<sid>.json and measure-git-events.sh already logs it to
# metrics/git-events/<sid>.jsonl. This just reads both, on request, from a
# terminal -- not the statusline, not a hook.
#
# Usage: metrics-breakdown.sh [session-id-prefix]
#   No argument: the most recently updated live cache.
set -u

HOOKS="${METRICS_HOOKS:-$HOME/.claude/hooks}"
[ -d "$HOOKS" ] || { echo "no hooks at $HOOKS" >&2; exit 1; }
# shellcheck source=.claude/hooks/lib-state.sh
. "$HOOKS/lib-state.sh"

LIVE="$(state_dir)/metrics/live"
GITEV="$(state_dir)/metrics/git-events"

# Excludes *.nag.json: metrics-live.sh's own crossing state, not the cache.
F=""
if [ $# -ge 1 ]; then
  for c in "$LIVE/$1"*.json; do
    case "$c" in *.nag.json) continue ;; esac
    [ -f "$c" ] && F="$c" && break
  done
else
  # shellcheck disable=SC2012,SC2045  # newest by mtime; a glob can't sort, and
  # session ids are hex, so `ls` output here needs no further quoting care
  for c in $(ls -t "$LIVE"/*.json 2>/dev/null); do
    case "$c" in *.nag.json) continue ;; esac
    F="$c"; break
  done
fi
[ -n "${F:-}" ] && [ -f "$F" ] || { echo "no live cache found (searched $LIVE)" >&2; exit 1; }

sid=$(basename "$F" .json)
echo "session $sid"
jq -r '
  "decisions ⚖\(.decisions.total // 0)[\(.decisions.scoping // 0)/\(.decisions.inline // 0)/\(.decisions.gate // 0)]  (scoping/inline/gate)",
  "friction  ⚡\(.friction.total // 0)[\(.friction.correction // 0)/\(.friction.override // 0)/\(.friction.rebuke // 0)]  (correction/override/rebuke)",
  "blocked   ⛔\(.blocked.total // 0)[\(.blocked.classifier // 0)/\(.blocked.rule // 0)/\(.blocked.user // 0)]  (classifier/rule/user)",
  "tool calls \(.tool_calls // 0)"
' "$F"

GF="$GITEV/$sid.jsonl"
if [ -f "$GF" ]; then
  echo "git events:"
  jq -r '.kind' "$GF" 2>/dev/null | sort | uniq -c | sort -rn | sed 's/^/  /'
else
  echo "git events: none logged"
fi
