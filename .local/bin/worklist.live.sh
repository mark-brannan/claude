#!/usr/bin/env bash
# Live smoke for worklist: runs it against the real board and real GitHub.
# Local only (needs gh auth and the state repo); CI runs worklist.test.sh.
# Run: bash .local/bin/worklist.live.sh
set -uo pipefail
WL="$(cd "$(dirname "$0")" && pwd)/worklist"
fail=0
check() { # check <name> <worklist args...>
  name=$1; shift
  err=$(mktemp)
  out=$(sh "$WL" "$@" 2>"$err"); rc=$?
  if [ "$rc" -ne 0 ] || [ -s "$err" ]; then
    printf 'FAIL: %s (exit %s)\n' "$name" "$rc"; head -3 "$err"; fail=1
  elif [ "$1" = --json ] && ! printf '%s' "$out" | jq -e .buckets >/dev/null 2>&1; then
    printf 'FAIL: %s (no buckets in JSON)\n' "$name"; fail=1
  else
    printf 'ok: %s\n' "$name"
  fi
  rm -f "$err"
}
check 'full view' --fresh
check 'brief' --brief
check 'json' --fresh --json
exit "$fail"
