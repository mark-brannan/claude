#!/usr/bin/env bash
# Tests for no-prose-gate.sh. Run: bash hooks/no-prose-gate.test.sh
#
# What matters: it blocks a closing permission question once, never a real
# choice or a statement, never a turn that used AskUserQuestion, and never
# twice in a turn. Its reason routes to a ruling card, not an issue.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/no-prose-gate.sh"
pass=0
fail=0
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

human()  { jq -cn --arg t "$1" '{type:"user",message:{role:"user",content:$t}}'; }
said()   { jq -cn --arg t "$1" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}'; }
asked()  { jq -cn '{type:"assistant",message:{content:[{type:"tool_use",name:"AskUserQuestion",input:{}}]}}'; }
result() { jq -cn '{type:"user",message:{content:[{type:"tool_result",content:"ok"}]}}'; }

# check <block|silent> <description> <stop_hook_active> <last_assistant_message> -- transcript lines on stdin
check() {
  local want=$1 desc=$2 active=$3 msg=$4 tp="$SCRATCH/t.$RANDOM.jsonl" out got
  cat > "$tp"
  out=$(jq -cn --arg tp "$tp" --argjson a "$active" --arg m "$msg" \
    '{transcript_path:$tp, stop_hook_active:$a} + (if $m == "" then {} else {last_assistant_message:$m} end)' | sh "$HOOK" 2>&1)
  if [ -z "$out" ]; then got=silent
  elif printf '%s' "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then got=block
  else got="invalid: $out"
  fi
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); printf 'FAIL (want %s, got %s): %s\n' "$want" "$got" "$desc"; fi
  LAST=$out
}
# Process substitution, not a pipe: check must run in this shell to count.
ends() { check "$2" "$3" false '' < <(human 'fix the hook'; result; said "$1"); }

# --- blocks: the permission-to-proceed shapes -------------------------------
ends 'Tests pass. Want me to push and open the PR?' block 'want me to'
ends 'Shall I write that card?'                       block 'shall I'
ends 'Diff above. Proceed?'                           block 'proceed'
ends 'That is the plan. Go?'                          block 'go'
ends 'Green and resolved. Merge it?'                  block 'merge it'
ends 'Want it added now?'                             block 'want it'
ends "$(printf 'Done.\n\n**Want me to rebase #196 now?**\n')" block 'last line, bold, trailing blank'

# --- the reason routes to a ruling card and is valid JSON -------------------
ends 'Want me to push?' block 'reason probe'
reason=$(jq -r '.reason' <<<"$LAST")
grep -q 'ruling card' <<<"$reason" && pass=$((pass + 1)) || { fail=$((fail + 1)); echo 'FAIL: reason does not name a ruling card'; }
grep -qi 'needs-ruling. issue\|file .* issue' <<<"$reason" && { fail=$((fail + 1)); echo 'FAIL: reason still routes to an issue'; } || pass=$((pass + 1))
grep -qF '"Want me to push?"' <<<"$reason" && pass=$((pass + 1)) || { fail=$((fail + 1)); echo 'FAIL: reason does not quote the line'; }

# --- silent: choices, statements, questions that are not permission ---------
ends 'Which do you want: A, or B?'                    silent 'a real choice'
ends 'Where should the card go?'                      silent 'go mid-sentence'
ends 'Pushed; PR is up.'                              silent 'statement'
ends 'Want me to push? Done anyway, it is pushed.'    silent 'question not last'

# --- AskUserQuestion this turn, and earlier turns ---------------------------
check silent 'AskUserQuestion this turn' false '' < <(human 'go'; asked; result; said 'Want me to push?')
check block 'AskUserQuestion only in an earlier turn' false '' < <(human 'a'; asked; result; said 'ok'; human 'b'; said 'Want me to push?')

# --- once per turn, payload message wins, missing input stays quiet ---------
check silent 'stop_hook_active retry' true '' < <(human 'go'; said 'Want me to push?')
check block 'last_assistant_message preferred' false 'Proceed?' < <(human 'go'; said 'Pushed.')
out=$(printf '{"transcript_path":"%s/none.jsonl"}' "$SCRATCH" | sh "$HOOK")
[ -z "$out" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo 'FAIL: missing transcript should be silent'; }
out=$(printf '' | sh "$HOOK")
[ -z "$out" ] && pass=$((pass + 1)) || { fail=$((fail + 1)); echo 'FAIL: empty payload should be silent'; }

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
