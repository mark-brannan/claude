#!/usr/bin/env bash
# Tests for session-start-continuity.sh. Run: bash .claude/hooks/session-start-continuity.test.sh
# Set AWK_PATH to a directory whose `awk` is another implementation (mawk,
# original-awk) to check portability; CI runs it under all three.
#
# What matters: the board comes from `worklist --brief` and nowhere else; a
# hung worklist costs at most 6 s and never loses the rest of the brief; a
# missing worklist is named, not papered over; a card above the first heading
# is called out instead of silently dropped; the state-repo-missing message is
# unchanged. HOME and the state repo are both fakes under a scratch dir.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

HOOK="$(cd "$(dirname "$0")" && pwd)/session-start-continuity.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export HOME="$SCRATCH/home"; mkdir -p "$HOME/.local/bin" "$SCRATCH/bin"
unset CLAUDE_CODE_REMOTE

# git must not reach the network from a hook test; the pull is a courtesy.
printf '#!/bin/sh\nexit 0\n' > "$SCRATCH/bin/git"; chmod +x "$SCRATCH/bin/git"
export PATH="$SCRATCH/bin:$PATH"

STATE="$SCRATCH/state"; SD="$STATE/state/global"
export CLAUDE_STATE_REPO="$STATE"
reset_state() {
  rm -rf "$STATE"
  mkdir -p "$STATE/.git" "$SD/log/auto" "$SD/metrics/decisions"
  printf -- '- session abc — worked on the thing\n- next: more thing\n\n## Uncommitted at Stop\n M foo.sh\n\n## Other\n' \
    > "$SD/log/auto/2026-01-01-1200-abc.md"
  printf '{"ts":"%s","type":"gate"}\n{"ts":"%s","type":"scoping"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SD/metrics/decisions/x.jsonl"
  printf '# Board\n\n## Claude'"'"'s\n\n- [ ] Ordinary card https://example.invalid/1\n- [x] TICKED-CARD-TEXT https://example.invalid/2\n\n## Yours\n\n- [ ] LEGACY-SECTION-CARD https://example.invalid/3\n' \
    > "$SD/kanban.md"
}
# worklist_shim <body>   -- installs $HOME/.local/bin/worklist with the given sh body
worklist_shim() { printf '#!/bin/sh\n%s\n' "$1" > "$HOME/.local/bin/worklist"; chmod +x "$HOME/.local/bin/worklist"; }
no_worklist() { rm -f "$HOME/.local/bin/worklist"; }

# run  -- executes the hook, sets CTX (additionalContext) and ELAPSED (seconds)
run() {
  local out t0 t1
  t0=$(date +%s)
  out=$(printf '{"session_id":"t","hook_event_name":"SessionStart"}' | bash "$HOOK" 2>"$SCRATCH/stderr")
  t1=$(date +%s)
  ELAPSED=$((t1 - t0))
  CTX=$(printf '%s' "$out" | jq -r '.hookSpecificOutput | select(.hookEventName == "SessionStart") | .additionalContext' 2>/dev/null)
  RAW=$out
}
ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; [ -n "${2:-}" ] && printf '  %s\n' "$2"; }
has()    { if printf '%s' "$CTX" | grep -Fq -- "$2"; then ok; else bad "$1 (context lacks [$2])" "$(printf '%s' "$CTX" | head -20)"; fi; }
lacks()  { if printf '%s' "$CTX" | grep -Fq -- "$2"; then bad "$1 (context has [$2])"; else ok; fi; }
valid_json() { if [ -n "$CTX" ]; then ok; else bad "$1: no SessionStart additionalContext" "$RAW"; fi; }

# --- worklist present and fast -----------------------------------------------
reset_state
worklist_shim 'echo "as of 12:00Z (cached 3 min)"; echo "## Board"; echo "- WORKLIST-BOARD-LINE https://example.invalid/9"'
run
valid_json 'fast worklist'
has   'worklist output is the board'          'as of 12:00Z (cached 3 min)'
has   'worklist board line carried through'    'WORKLIST-BOARD-LINE'
lacks 'no kanban dump: ticked card absent'     'TICKED-CARD-TEXT'
lacks 'no kanban dump: legacy section absent'  'LEGACY-SECTION-CARD'
lacks 'old heading gone'                       'Open board items'
lacks 'no missing-worklist line'               'worklist not installed'
lacks 'no lint warning on a clean board'       'WARNING: kanban.md'
has   'checkpoints still printed'              'Where recent sessions left off'
has   'checkpoint session line'                'session abc'
has   'decision load still printed'            'Decision load, last 7 days'
has   'state repo line kept'                   "State repo: \`$STATE\`"
if [ "$ELAPSED" -le 3 ]; then ok; else bad "fast worklist took ${ELAPSED}s"; fi

# --- worklist missing ------------------------------------------------------
reset_state; no_worklist
run
valid_json 'missing worklist'
has   'names the gap'                          'worklist not installed -- live board view unavailable; this is not a clean state (run dotsync / cloud-session-setup.sh)'
lacks 'no dump as fallback'                    'TICKED-CARD-TEXT'
has   'rest of brief intact'                   'Decision load, last 7 days'

# --- worklist hangs --------------------------------------------------------
reset_state
worklist_shim 'echo "as of 12:00Z"; sleep 30; echo "NEVER-PRINTED"'
run
valid_json 'hung worklist'
if [ "$ELAPSED" -le 8 ]; then ok; else bad "hung worklist: hook took ${ELAPSED}s, cap is 8"; fi
has   'says it timed out'                      'did not return in 6 s'
has   'partial output kept'                    'as of 12:00Z'
lacks 'nothing after the kill'                 'NEVER-PRINTED'
has   'checkpoints survive the timeout'        'Where recent sessions left off'
has   'decision load survives the timeout'     'Decision load, last 7 days'

# --- worklist fails --------------------------------------------------------
reset_state
worklist_shim 'echo "no gh"; exit 2'
run
has   'nonzero exit named'                     'worklist --brief exited 2'
has   'its own failure line kept'              'no gh'

# --- worklist over budget is clipped ------------------------------------------
reset_state
worklist_shim 'echo "as of 12:00Z"; awk '"'"'BEGIN { for (i = 0; i < 400; i++) print "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" }'"'"
run
n=$(printf '%s' "$CTX" | wc -c)
if [ "$n" -lt 6000 ]; then ok; else bad "oversize worklist not clipped: context is $n bytes"; fi
has   'clipped output still starts with the stamp' 'as of 12:00Z'

# --- card above the first heading ----------------------------------------------
reset_state
worklist_shim 'echo "as of 12:00Z"'
printf -- '# Board\n\n- [ ] ORPHAN-CARD https://example.invalid/4\n\n## Claude'"'"'s\n\n- [ ] fine https://example.invalid/5\n' > "$SD/kanban.md"
run
has   'orphan card warned'                     "WARNING: kanban.md has a card above its first \`## \` heading"
reset_state
printf -- '# Board\n\nProse intro, not a card.\n\n## Claude'"'"'s\n\n- [ ] fine https://example.invalid/5\n' > "$SD/kanban.md"
run
lacks 'prose above heading is not a card'      'WARNING: kanban.md'
reset_state
printf -- '## Claude'"'"'s\n\n- [x] ticked https://example.invalid/6\n' > "$SD/kanban.md"
run
lacks 'ticked card under a heading: no orphan warning' 'WARNING: kanban.md'
rm -f "$SD/kanban.md"
run
lacks 'no kanban file: no warning'             'WARNING: kanban.md'

# --- state repo missing ----------------------------------------------------
rm -rf "$STATE"
worklist_shim 'echo "as of 12:00Z"'
run
valid_json 'state repo missing'
has   'existing message unchanged'             '## Continuity: state repo NOT available'
has   'names the fix'                          'mcp__Claude_Code_Remote__add_repo'
lacks 'worklist not run without a state repo'  'as of 12:00Z'

# --- no jq at all: silent, exit 0 -------------------------------------------
reset_state
mkdir -p "$SCRATCH/nojq"; for b in bash sh dirname cat mktemp head sed awk date; do ln -s "$(command -v $b)" "$SCRATCH/nojq/$b" 2>/dev/null; done
out=$(printf '{}' | PATH="$SCRATCH/nojq" bash "$HOOK" 2>&1); rc=$?
if [ -z "$out" ] && [ "$rc" -eq 0 ]; then ok; else bad "without jq should be silent and exit 0" "rc=$rc out=$out"; fi

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
