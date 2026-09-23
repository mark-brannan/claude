#!/usr/bin/env bash
# Tests for no-persistent-polling.sh. Run: bash .claude/hooks/no-persistent-polling.test.sh
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/no-persistent-polling.sh"
pass=0
fail=0

# check_json <deny|allow> <description> <json payload>
# The hook builds its JSON with `jq -n`, which pretty-prints (space after
# the colon, one field per line), so a compact grep would miss it -- parse
# the field with jq instead of pattern-matching the raw text.
check_json() {
  local want=$1 desc=$2 json=$3 out got
  out=$(printf '%s' "$json" | bash "$HOOK" 2>&1)
  if printf '%s' "$out" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1; then
    got=deny
  else
    got=allow
  fi
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL (want %s, got %s): %s\n' "$want" "$got" "$desc"
    [ -n "$out" ] && printf '  hook output: %s\n' "$out"
  fi
}

# --- send_later is always blocked -----------------------------------------
check_json deny 'send_later, any server' \
  '{"tool_name":"mcp__symphony__send_later","tool_input":{}}'
check_json deny 'send_later, different server prefix' \
  '{"tool_name":"mcp__other-server__send_later","tool_input":{}}'

# --- create_trigger bound to an existing session is blocked ---------------
check_json deny 'create_trigger, no create_new_session_on_fire at all' \
  '{"tool_name":"mcp__symphony__create_trigger","tool_input":{}}'
check_json deny 'create_trigger, create_new_session_on_fire explicitly false' \
  '{"tool_name":"mcp__symphony__create_trigger","tool_input":{"create_new_session_on_fire":false}}'
check_json deny 'create_trigger, fresh session but persistent_session_id also set' \
  '{"tool_name":"mcp__symphony__create_trigger","tool_input":{"create_new_session_on_fire":true,"persistent_session_id":"abc123"}}'

# --- the valid fresh-trigger case is allowed --------------------------------
check_json allow 'create_trigger, create_new_session_on_fire true, no persistent_session_id' \
  '{"tool_name":"mcp__symphony__create_trigger","tool_input":{"create_new_session_on_fire":true}}'

# --- tools this hook does not gate ------------------------------------------
check_json allow 'subscribe_pr_activity is untouched by this hook' \
  '{"tool_name":"mcp__symphony__subscribe_pr_activity","tool_input":{}}'
check_json allow 'plain Bash call' \
  '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
check_json allow 'unrelated mcp tool' \
  '{"tool_name":"mcp__symphony__get_status","tool_input":{}}'

# --- fails closed when jq is unavailable ------------------------------------
# The hook's own header explains why: the settings.json matcher ends in
# `|| true`, so a non-zero exit here would be silently swallowed into an
# ALLOW. Simulate a PATH with no jq on it (cat still present, since the hook
# reads stdin with `$(cat)` before it ever checks for jq). bash is invoked by
# its full path, not left to PATH lookup, since PATH here holds only the
# stand-ins below.
BASH_BIN=$(command -v bash)
no_jq_dir=$(mktemp -d)
for t in cat printf; do
  p=$(command -v "$t") && ln -s "$p" "$no_jq_dir/$t"
done
no_jq_out=$(printf '%s' '{"tool_name":"mcp__symphony__send_later","tool_input":{}}' \
  | env -i PATH="$no_jq_dir" HOME="$HOME" "$BASH_BIN" "$HOOK" 2>&1)
rm -rf "$no_jq_dir"
if grep -q '"permissionDecision":"deny"' <<<"$no_jq_out"; then
  pass=$((pass + 1))
else
  fail=$((fail + 1))
  printf 'FAIL: jq-missing case did not deny\n  hook output: %s\n' "$no_jq_out"
fi

printf '%s\n' "no-persistent-polling: $pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
