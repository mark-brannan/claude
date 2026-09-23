#!/usr/bin/env bash
# Tests for no-update-branch.sh. Run: bash .claude/hooks/no-update-branch.test.sh
#
# The cases that matter are the false positives. This hook is documented in
# RUNBOOK.md and argued about in PR comments, so the command it denies will
# appear verbatim inside commit messages and `gh pr comment` bodies -- which
# is precisely how a substring-matching sibling hook blocked its own
# documentation twice in one session.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/no-update-branch.sh"
pass=0
fail=0

check() {
  local want=$1 desc=$2 json=$3 out got
  out=$(printf '%s' "$json" | bash "$HOOK" 2>&1)
  if grep -q '"permissionDecision": *"deny"' <<<"$out"; then
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

bash_input() { jq -n --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }

# --- must deny -------------------------------------------------------------
check deny 'rebase form' "$(bash_input 'gh pr update-branch 226 --rebase')"
check deny 'merge form' "$(bash_input 'gh pr update-branch 226')"
check deny 'with --repo' \
  "$(bash_input 'gh pr update-branch 226 --repo mark-brannan/dotfiles --rebase')"
check deny 'after a separator' \
  "$(bash_input 'git fetch origin && gh pr update-branch 226 --rebase')"
check deny 'absolute path invocation' "$(bash_input '/usr/bin/gh pr update-branch 226')"
check deny 'MCP tool form' \
  "$(jq -n '{tool_name:"mcp__github__update_pull_request_branch",tool_input:{pullNumber:226}}')"

# --- must deny: command substitution and subshells --------------------------
# An agent capturing output is the realistic shape here, not an attacker.
check deny 'command substitution' \
  "$(bash_input 'out=$(gh pr update-branch 226 --rebase 2>&1); echo "$out"')"
check deny 'subshell' "$(bash_input '(gh pr update-branch 226 --rebase)')"
check deny 'backtick substitution' "$(bash_input 'out=`gh pr update-branch 226`')"

# --- must allow: the documentation trap ------------------------------------
check allow 'mentioned in a commit message' \
  "$(bash_input 'git commit -m "never use gh pr update-branch --rebase here"')"
check allow 'mentioned in a PR comment body' \
  "$(bash_input "gh pr comment 226 --body 'do not run gh pr update-branch'")"
check allow 'mentioned in a heredoc-ish quoted string' \
  "$(bash_input 'printf "%s" "gh pr update-branch --rebase strips signatures"')"

# --- must allow: neighbouring gh commands ----------------------------------
check allow 'other pr subcommand' "$(bash_input 'gh pr view 226 --json mergeStateStatus')"
check allow 'pr checks' "$(bash_input 'gh pr checks 226')"
check allow 'the sanctioned remedy' "$(bash_input 'resign-branch.sh claude/foo')"
check allow 'word merely ending in gh' "$(bash_input 'high pr update-branch')"
check allow 'unrelated command' "$(bash_input 'git status')"
check allow 'empty command' "$(bash_input '')"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
