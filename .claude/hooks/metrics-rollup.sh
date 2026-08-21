#!/usr/bin/env bash
# Regenerate metrics/metrics.json from the per-session files.
#
# Generated, never edited, and *never committed*: the state repo gitignores
# metrics.json. Per-session inputs are conflict-free by construction, but a
# committed rollup of them is not -- every Stop rewrote the one shared file,
# so any two sessions ending near each other collided on it and a human had
# to resolve a conflict in generated JSON. Untracked, the file is still here
# to read; each machine regenerates its own from whatever sessions it has.
# Reads that must not depend on a local rollup use the `jq -s` one-liners in
# metrics/README.md over sessions/*.json directly.
# (Decided 2026-08-20 after one such conflict; see the metrics README.)
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
# Interrupted writers leave `<id>.json.<pid>` temp files behind. The glob
# below never picks them up, so they are harmless to the rollup -- but they
# sat in the state repo as untracked clutter until someone noticed them.
find "$M/live" -name '*.json.*' -mtime +1 -delete 2>/dev/null
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
       gates:        (map(.decisions.gate // 0) | add),
       cache_churn_pct_avg: ([.[] | .cache_churn_pct | select(. != null)]
                              | if length > 0 then (add / length | round) else null end)
     }}' "${files[@]}" > "$M/metrics.json.$$" 2>/dev/null \
  && mv -f "$M/metrics.json.$$" "$M/metrics.json" 2>/dev/null \
  || rm -f "$M/metrics.json.$$" 2>/dev/null
exit 0
