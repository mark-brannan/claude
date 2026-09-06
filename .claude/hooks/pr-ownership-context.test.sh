#!/usr/bin/env bash
# Tests for pr-ownership-context.sh. Run: bash .claude/hooks/pr-ownership-context.test.sh
#
# What matters: it fires on PR-shaped calls and nothing else, exactly once per
# session, emits valid JSON whatever the rules file contains, and says so out
# loud when the rules file or the heading is missing instead of going quiet.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/pr-ownership-context.sh"
pass=0
fail=0

SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export HOME="$SCRATCH/home"; mkdir -p "$HOME/.claude/rules"
cat > "$HOME/.claude/rules/code.md" <<'MD'
# Code

## Git

- git stuff, not wanted

## PR ownership: never a draft, never red

- **Never open a PR as a draft.** Quoted "text", a `backtick`, a	tab and a \backslash.
- **"Resolve conversation" is mine to do.**

### A board-only PR merges itself

Sub-heading stays inside the section.
MD
printf 'CRLF\r\n\fformfeed\n' >> "$HOME/.claude/rules/code.md"   # real control bytes, before the next ## heading is appended below
cat >> "$HOME/.claude/rules/code.md" <<'MD'

## Provisional until decided

- must not be injected
MD

# check <expect inject|silent> <description> <json input>
check() {
  local want=$1 desc=$2 json=$3 out got
  out=$(printf '%s' "$json" | sh "$HOOK" 2>&1)
  if [ -z "$out" ]; then got=silent
  elif printf '%s' "$out" | jq -e '.hookSpecificOutput.additionalContext' >/dev/null 2>&1; then got=inject
  else got=invalid-json
  fi
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL (want %s, got %s): %s\n' "$want" "$got" "$desc"
    [ -n "$out" ] && printf '  hook output: %s\n' "$out"
  fi
  LAST=$out
}
# context <description> <grep -E pattern that must match the injected text>
context() {
  if printf '%s' "$LAST" | jq -r '.hookSpecificOutput.additionalContext' | grep -Eq -- "$2"; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL (context lacks /%s/): %s\n' "$2" "$1"; fi
}
no_context() {
  if printf '%s' "$LAST" | jq -r '.hookSpecificOutput.additionalContext' | grep -Eq -- "$2"; then
    fail=$((fail + 1)); printf 'FAIL (context contains /%s/): %s\n' "$2" "$1"
  else pass=$((pass + 1)); fi
}

bash_input() { jq -n --arg s "$1" --arg c "$2" '{session_id:$s,tool_name:"Bash",tool_input:{command:$c}}'; }
mcp_input()  { jq -n --arg s "$1" --arg t "$2" '{session_id:$s,tool_name:$t,tool_input:{}}'; }

# --- fires, and on what ----------------------------------------------------
check inject 'gh pr view' "$(bash_input s1 'gh pr view 12 --comments')"
context 'section heading present'        '^## PR ownership'
# shellcheck disable=SC2016  # the backtick is data, not a command
context 'quotes/backticks/tab survive'   'Quoted "text", a `backtick`, a	tab and a \\backslash'
context 'sub-heading kept in section'    '^### A board-only PR'
context 'CR line survives as JSON'         '^CRLF.$'
context 'form-feed line survives as JSON'  'formfeed'
no_context 'next ## section excluded'    'must not be injected'
no_context 'earlier section excluded'    'git stuff'
context 'says where it came from'        'injected once per session by pr-ownership-context.sh'

check inject 'gh api graphql'   "$(bash_input s2 "gh api graphql -f query='{repository{pullRequest{reviewThreads}}}'")"
check inject 'gh api pulls'     "$(bash_input s3 'gh api repos/o/r/pulls/4/comments')"
check inject 'gh pr after &&'   "$(bash_input s4 'git push && gh pr checks --watch')"
check inject 'MCP pull_request_read'  "$(mcp_input s5 mcp__plugin_github_github__pull_request_read)"
check inject 'MCP review tool'        "$(mcp_input s6 mcp__github__create_pending_pull_request_review)"

# --- stays silent ------------------------------------------------------------
check silent 'gh issue'              "$(bash_input s7 'gh issue view 3')"
check silent 'git push alone'        "$(bash_input s7 'git push origin HEAD')"
check silent 'gh api unrelated'      "$(bash_input s7 'gh api user')"
check silent 'word ending in gh'     "$(bash_input s7 'high pr')"
check silent 'MCP non-PR github'     "$(mcp_input s7 mcp__github__search_repositories)"
check silent 'MCP other server'      "$(mcp_input s7 mcp__Trello__pull_request_read)"
check silent 'other tool'            "$(jq -n '{session_id:"s7",tool_name:"Read",tool_input:{file_path:"gh pr"}}')"
check silent 'empty payload'         ''

# --- once per session ----------------------------------------------------------
check inject 'first PR call in s8'   "$(bash_input s8 'gh pr view')"
check silent 'second PR call in s8'  "$(bash_input s8 'gh pr checks')"
check inject 'new session s9 fires'  "$(bash_input s9 'gh pr view')"
check inject 'no session_id: fires'  "$(jq -n '{tool_name:"Bash",tool_input:{command:"gh pr list"}}')"
check inject 'no session_id: again'  "$(jq -n '{tool_name:"Bash",tool_input:{command:"gh pr list"}}')"

# --- failure is loud, never silent ---------------------------------------------
sed -i 's/^## PR ownership.*/## Something else/' "$HOME/.claude/rules/code.md"
check inject 'heading missing -> note' "$(bash_input s10 'gh pr view')"
context 'names the missing heading'     "no '## PR ownership' heading"
rm "$HOME/.claude/rules/code.md"
check inject 'file missing -> note'    "$(bash_input s11 'gh pr view')"
context 'names the missing file'        'code.md is missing'

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
