#!/usr/bin/env bash
# Tests for shift-run. Run: bash bin/shift-run.test.sh
# gh, the worker, work-item and card-id are all stubs; no network, no claude.
set -uo pipefail
SR="$(cd "$(dirname "$0")" && pwd)/shift-run"
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
mkdir -p "$S/bin"; export PATH="$S/bin:$PATH" GH_LOG="$S/gh.log" W_LOG="$S/w.log" S
pass=0; fail=0
ok() { if [ "$2" = 0 ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1"; fi; }
has() { grep -q -- "$2" "$1"; ok "$3" $?; }
lacks() { ! grep -q -- "$2" "$1"; ok "$3" $?; }

cat > "$S/issues.json" <<'J'
[{"number":9,"title":"Nine","labels":[{"name":"lane"}]},
 {"number":3,"title":"Three","labels":[{"name":"lane"}]},
 {"number":7,"title":"Held","labels":[{"name":"lane"},{"name":"needs-human"}]}]
J
cat > "$S/bin/gh" <<'G'
#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "issue list") cat "$S/issues.json" ;;
  "pr checks") exit "${CHECKS_RC:-0}" ;;
  "pr view") echo "${MERGEABLE:-MERGEABLE}" ;;
  "api graphql") echo "${OPEN_THREADS:-0}" ;;
  *) exit 0 ;;
esac
G
# The worker answers by phase, read off the prompt on stdin.
cat > "$S/bin/worker" <<'W'
#!/bin/sh
p=$(cat); echo "$p" | head -c 40 >> "$W_LOG"; echo >> "$W_LOG"
case "$p" in
  Work*\#3*) [ -n "$CODER_HALT" ] && { echo "SHIFT: halt which API?"; exit 0; }; echo "SHIFT: pr=30" ;;
  Work*\#9*) echo "SHIFT: pr=90" ;;
  Read*) echo "SHIFT: ok" ;;
  *"did not write"*) echo "SHIFT: ok" ;;
esac
W
printf '#!/bin/sh\necho abc123\n' > "$S/bin/cid"
printf '#!/bin/sh\necho "$*" >> "$S/card.log"\n' > "$S/bin/wi"
chmod +x "$S/bin/"*
export SHIFT_CARD_ID="$S/bin/cid" SHIFT_WORK_ITEM="$S/bin/wi"
export CODER_HALT=""
run() { : > "$GH_LOG"; : > "$W_LOG"; : > "$S/card.log"; bash "$SR" --repo o/r --label lane --worker "$S/bin/worker" "$@"; }

# dry run
run --dry-run > "$S/o"
has "$S/o" "worker: $S/bin/worker" "dry: names the worker"
has "$S/o" "would dispatch #3" "dry: lists 3"
has "$S/o" "would dispatch #9" "dry: lists 9"
lacks "$S/o" "#7" "dry: skips needs-human item"
if [ ! -s "$W_LOG" ]; then ok "dry: no worker ran" 0; else ok "dry: no worker ran" 1; fi
lacks "$GH_LOG" "merge" "dry: no merge"
if [ "$(grep 'would dispatch' "$S/o" | head -1 | grep -c '#3')" = 1 ]; then ok "dry: lowest number first" 0; else ok "dry: lowest number first" 1; fi

# full pass
run > "$S/o"; rc=$?
if [ $rc = 0 ]; then ok "pass: exit 0" 0; else ok "pass: exit 0" 1; fi
has "$S/o" "MERGED o/r#3 as PR #30" "pass: merged 3"
has "$GH_LOG" "pr merge 30 -R o/r --squash --delete-branch" "pass: squash merge"
if [ "$(wc -l < "$W_LOG")" = 6 ]; then ok "pass: 3 worker phases x 2 items" 0; else ok "pass: 3 worker phases x 2 items" 1; fi

# coder halts: label, comment, card; next item still merges
CODER_HALT=1 run > "$S/o"; rc=$?
if [ $rc = 1 ]; then ok "halt: exit 1" 0; else ok "halt: exit 1" 1; fi
has "$GH_LOG" "issue edit 3 -R o/r --add-label needs-human" "halt: label"
has "$GH_LOG" "issue comment 3" "halt: comment"
has "$S/card.log" "create --id abc123" "halt: card"
has "$GH_LOG" "pr merge 90" "halt: next item continues"
lacks "$GH_LOG" "pr merge 30" "halt: halted item not merged"

# gate failure
CHECKS_RC=1 run --limit 1 > "$S/o"; rc=$?
if [ $rc = 1 ]; then ok "gate: red checks halt" 0; else ok "gate: red checks halt" 1; fi
lacks "$GH_LOG" "pr merge" "gate: no merge on red"
OPEN_THREADS=2 run --limit 1 > "$S/o"; has "$GH_LOG" "needs-human" "gate: open threads halt"

# usage
bash "$SR" >/dev/null 2>&1; [ $? = 2 ]; ok "usage: no label is 2" $?
echo "pass=$pass fail=$fail"; [ "$fail" = 0 ]
