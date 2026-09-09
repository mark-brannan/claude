#!/usr/bin/env bash
# Tests for pr-threads-gate.sh. Run: bash .claude/hooks/pr-threads-gate.test.sh
#
# What matters: silent when the session touched no PR, silent when every
# thread is resolved or the PR is closed, blocks once (and only once) with the
# thread ids when one is open, and blocks -- never goes quiet -- when the
# check itself could not run. gh is faked; each case picks a reply via GH_MODE.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/pr-threads-gate.sh"
RECORDER="$(cd "$(dirname "$0")" && pwd)/pr-ownership-context.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export HOME="$SCRATCH/home"; mkdir -p "$HOME/.claude/rules" "$SCRATCH/bin" "$SCRATCH/repo"
printf '## PR ownership\n- rules\n' > "$HOME/.claude/rules/code.md"

cat > "$SCRATCH/bin/gh" <<'GH'
#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view") printf 'https://github.com/o/r/pull/7\n'; exit 0 ;;
esac
case "${GH_MODE:-}" in
  open)     printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","reviewThreads":{"nodes":[{"id":"PRRT_a","isResolved":true,"path":"a.ts","comments":{"nodes":[{"author":{"login":"bot"},"body":"done"}]}},{"id":"PRRT_b","isResolved":false,"path":"b.ts","comments":{"nodes":[{"author":{"login":"coderabbitai"},"body":"Disable the pre-commit hook\\nsecond line"}]}}]}}}}}' ;;
  resolved) printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","reviewThreads":{"nodes":[{"id":"PRRT_a","isResolved":true,"path":"a.ts","comments":{"nodes":[]}}]}}}}}' ;;
  merged)   printf '{"data":{"repository":{"pullRequest":{"state":"MERGED","reviewThreads":{"nodes":[{"id":"PRRT_z","isResolved":false,"path":null,"comments":{"nodes":[]}}]}}}}}' ;;
  missing)  printf '{"data":{"repository":{"pullRequest":null}}}' ;;
  fail)     echo "gh: HTTP 401: Bad credentials" >&2; exit 1 ;;
  hang)     sleep 30 ;;
esac
GH
chmod +x "$SCRATCH/bin/gh"
export PATH="$SCRATCH/bin:$PATH" GH_LOG="$SCRATCH/gh.log"

stop_input() { jq -n --arg s "$1" --argjson a "${2:-false}" '{session_id:$s,stop_hook_active:$a,cwd:"/x"}'; }
record() { printf '%s\n' "$2" >> "$TMPDIR/claude-pr-threads.$1"; }
# check <block|silent> <desc> <mode> <json>
check() {
  local want=$1 desc=$2 json=$4 out got
  out=$(printf '%s' "$json" | GH_MODE=$3 sh "$HOOK" 2>&1)
  if [ -z "$out" ]; then got=silent
  elif [ "$(printf '%s' "$out" | jq -r '.decision' 2>/dev/null)" = block ]; then got=block
  else got=invalid; fi
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL (want %s, got %s): %s\n  %s\n' "$want" "$got" "$desc" "$out"; fi
  LAST=$out
}
reason() { if printf '%s' "$LAST" | jq -r '.reason' | grep -Eq -- "$2"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL (reason lacks /%s/): %s\n' "$2" "$1"; fi; }
no_reason() { if printf '%s' "$LAST" | jq -r '.reason' | grep -Eq -- "$2"; then fail=$((fail+1)); printf 'FAIL (reason has /%s/): %s\n' "$2" "$1"; else pass=$((pass+1)); fi; }

# --- nothing to check --------------------------------------------------------
check silent 'no record for session'   open "$(stop_input s0)"
check silent 'no session id'           open "$(jq -n '{stop_hook_active:false}')"
check silent 'empty payload'           open ''

# --- the recorder writes what the gate reads -----------------------------------
rec() { printf '%s' "$2" | sh "$RECORDER" >/dev/null; cat "$TMPDIR/claude-pr-threads.$1" 2>/dev/null | tail -1; }
bash_in() { jq -n --arg s "$1" --arg c "$2" '{session_id:$s,cwd:"/work/here",tool_name:"Bash",tool_input:{command:$c}}'; }
t() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }
t 'gh pr view N --repo'      "$(printf 'repo\to/r\t25')"  "$(rec r1 "$(bash_in r1 'gh pr view 25 --repo o/r --comments')")"
t 'gh pr checks -R'          "$(printf 'repo\to/r\t3')"   "$(rec r1 "$(bash_in r1 'gh pr checks 3 -R o/r')")"
t 'gh api pulls url'         "$(printf 'repo\to/r\t4')"   "$(rec r1 "$(bash_in r1 'gh api repos/o/r/pulls/4/comments')")"
t 'gh pr view no number'     "$(printf 'cwd\t/work/here')" "$(rec r1 "$(bash_in r1 'gh pr view --json url')")"
t 'gh pr N without repo'     "$(printf 'cwd\t/work/here')" "$(rec r1 "$(bash_in r1 'gh pr view 9')")"
t 'MCP pull_request_read'    "$(printf 'repo\to/r\t8')"   "$(rec r1 "$(jq -n '{session_id:"r1",tool_name:"mcp__github__pull_request_read",tool_input:{owner:"o",repo:"r",pullNumber:8}}')")"
t 'MCP without a PR number'  "$(printf 'repo\to/r\t8')"   "$(rec r1 "$(jq -n '{session_id:"r1",tool_name:"mcp__github__get_pull_request_review",tool_input:{owner:"o",repo:"r"}}')")"
t 'second call still records' "$(printf 'repo\to/r\t26')" "$(rec r1 "$(bash_in r1 'gh pr merge 26 --repo o/r')")"

# --- open thread blocks, once --------------------------------------------------
record s1 "$(printf 'repo\to/r\t25')"
check block 'open thread -> block'    open "$(stop_input s1)"
reason 'names the PR'                  'o/r#25 has 1 unresolved'
reason 'names the thread id'           'PRRT_b'
reason 'shows path, author, first line' 'b.ts  @coderabbitai: Disable the pre-commit hook$'
no_reason 'resolved thread not listed' 'PRRT_a'
reason 'gives the resolve mutation'    'resolveReviewThread'
reason 'one at a time'                 'never a loop'
check silent 'retry with stop_hook_active' open "$(stop_input s1 true)"

# --- quiet when there is nothing open ------------------------------------------
record s2 "$(printf 'repo\to/r\t25')"
check silent 'all resolved'            resolved "$(stop_input s2)"
record s3 "$(printf 'repo\to/r\t25')"
check silent 'merged PR ignored'       merged "$(stop_input s3)"

# --- cwd records resolve through gh pr view ------------------------------------
record s4 "$(printf 'cwd\t%s' "$SCRATCH/repo")"
record s4 "$(printf 'cwd\t%s' "$SCRATCH/repo")"
record s4 "$(printf 'repo\to/r\t7')"
: > "$GH_LOG"
check block 'cwd -> PR via gh pr view' open "$(stop_input s4)"
reason 'resolved to o/r#7'             'o/r#7 has'
t 'same PR queried once' 1 "$(grep -c 'api graphql' "$GH_LOG")"
record s5 "$(printf 'cwd\t%s/nope' "$SCRATCH")"
check silent 'cwd that no longer exists' open "$(stop_input s5)"

# --- cannot verify is loud ---------------------------------------------------
record s6 "$(printf 'repo\to/r\t25')"
check block 'gh fails -> block'        fail "$(stop_input s6)"
reason 'says it could not verify'      'Could not verify'
reason 'carries the gh error'          'Bad credentials'
record s7 "$(printf 'repo\to/r\t25')"
check block 'PR not found -> block'    missing "$(stop_input s7)"
reason 'says not found'                'not found'
record s8 "$(printf 'repo\to/r\t25')"
mkdir -p "$SCRATCH/nogh"; for b in jq cat tr sort head wc sed; do ln -s "$(command -v $b)" "$SCRATCH/nogh/$b"; done
out=$(stop_input s8 | PATH="$SCRATCH/nogh" GH_MODE=open /bin/sh "$HOOK" 2>&1); LAST=$out
if [ "$(printf '%s' "$out" | jq -r .decision 2>/dev/null)" = block ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: gh absent should block: $out"; fi
reason 'names gh as missing'           'gh is not installed'

# --- a fan-out over many PRs checks every one; none is skipped by count ---------
for i in 1 2 3 4 5 6 7 8; do record s9 "$(printf 'repo\to/r\t%s' "$i")"; done
: > "$GH_LOG"
check silent 'eight clean PRs -> silent' resolved "$(stop_input s9)"
t 'all eight queried' 8 "$(grep -c 'api graphql' "$GH_LOG")"
check block 'eight PRs, one open thread each -> block' open "$(stop_input s9)"
reason 'names the eighth PR'            'o/r#8 has 1 unresolved'
no_reason 'no count cap'                'not checked'

# --- a hung fetch is reported as unverified, not skipped ------------------------
if command -v timeout >/dev/null 2>&1; then
  record s10 "$(printf 'repo\to/r\t1')"
  out=$(stop_input s10 | PR_THREADS_GATE_TIMEOUT=1 GH_MODE=hang sh "$HOOK" 2>&1); LAST=$out
  if [ "$(printf '%s' "$out" | jq -r .decision 2>/dev/null)" = block ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: hung fetch should block: $out"; fi
  reason 'names the timeout'             'o/r#1: fetch timed out'
fi

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
