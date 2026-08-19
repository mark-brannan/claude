#!/usr/bin/env bash
# Regenerate metrics/metrics.json from the per-session files.
#
# Generated, never edited: two sessions pushing at once both regenerate the
# same derived file from conflict-free per-session inputs, so a rebase can
# always take "theirs" and re-run this. That is the collision handling --
# there is no merge to get wrong.
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"
command -v jq >/dev/null 2>&1 || exit 0

M="$(state_dir)/metrics"
[ -d "$M" ] || exit 0

# Prune live snapshots that Stop never came back for. A container reclaimed
# mid-session leaves its live file behind forever, and without this the
# rollup keeps counting that half-session's tokens in every future total.
# 14 days is well past any session that is still going to finish.
find "$M/live" -name '*.json' -mtime +14 -delete 2>/dev/null
# Globbing, not `ls`: with an unmatched pattern `ls` exits 2, and the old
# `|| exit 0` then aborted the rollup even when the other glob had matched.
# That is the normal case -- stop-continuity.sh deletes this session's live
# file immediately before calling here, so `live/` is usually empty and
# metrics.json was simply never regenerated.
shopt -s nullglob
files=( "$M"/sessions/*.json "$M"/live/*.json )
[ "${#files[@]}" -gt 0 ] || exit 0

# A finished session (sessions/) wins over its own live snapshot.
# shellcheck disable=SC2086
jq -s '
  map(select(.session_id != null))
  | group_by(.session_id)
  | map( (map(select(.ended_at != null and .last_event == null)) | last)
         // (sort_by(.updated_at // .ts // "") | last) )
  | sort_by(.started_at // "")
  | {generated_at: (max_by(.updated_at // .ts // "").updated_at // ""),
     sessions: .,
     totals: {
       sessions: length,
       output_tokens: (map(.output_tokens // 0) | add),
       tool_calls:   (map(.tool_calls // 0) | add),
       decisions:    (map(.decisions.total // 0) | add),
       gates:        (map(.decisions.gate // 0) | add)
     }}' "${files[@]}" > "$M/metrics.json.$$" 2>/dev/null \
  && mv -f "$M/metrics.json.$$" "$M/metrics.json" 2>/dev/null \
  || rm -f "$M/metrics.json.$$" 2>/dev/null
exit 0
