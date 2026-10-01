#!/usr/bin/env bash
# Tests for issue-door.sh. Run: bash .claude/hooks/issue-door.test.sh
#
# Why the guard exists: twice an agent filed a batch of duplicate issues on
# a plan the human had approved once, with the batch buried in it (languette#3
# to #9 was the second time). Prose in CLAUDE.md said "file only on an
# explicit yes" and a hand-off prompt overrode it. The human's ruling: no
# agent creates more than one or two without a human in the loop *during*
# creation, and the door must cost the human nothing. So the human's own turn
# is the door: UserPromptSubmit opens it, one identifier write spends it.
#
# What matters: reads, comments and edits are never touched; a create,
# transfer or delete passes once per human turn and is denied after; two in
# one call or one in a loop are denied even with the door open.
# AWK_PATH, as in the other lib-shell-words suites, is a directory whose
# `awk` is the implementation under test.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

HOOK="$(cd "$(dirname "$0")" && pwd)/issue-door.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export TMPDIR="$SCRATCH"

bash_in() { jq -nc --arg c "$1" '{session_id:"s1",tool_name:"Bash",tool_input:{command:$c}}'; }
mcp_in() { jq -nc --arg t "$1" --argjson i "$2" '{session_id:"s1",tool_name:$t,tool_input:$i}'; }
open_door() { printf '{"session_id":"s1","prompt":"yes, file it"}' | sh "$HOOK" prompt; }
shut_door() { rm -f "$TMPDIR/claude-issue-door.s1"; }

# check <allow|deny> <description> <json>
check() {
  local out got
  out=$(printf '%s' "$3" | sh "$HOOK" 2>&1)
  if [ -z "$out" ]; then got=allow
  elif [ "$(jq -r '.hookSpecificOutput.permissionDecision' <<<"$out" 2>/dev/null)" = deny ]; then got=deny
  else got="invalid: $out"
  fi
  if [ "$got" = "$1" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); printf 'FAIL (want %s, got %s): %s\n' "$1" "$got" "$2"; fi
}

# Never identifier writes: always allowed, door shut.
shut_door
check allow 'issue view'            "$(bash_in 'gh issue view 12 -R o/r')"
check allow 'issue list'            "$(bash_in 'gh issue list --state open')"
check allow 'issue comment'         "$(bash_in 'gh issue comment 12 --body "progress"')"
check allow 'issue edit'            "$(bash_in 'gh issue edit 12 --add-label x')"
check allow 'pr create'             "$(bash_in 'gh pr create --title t --body "fixes the issue create path"')"
check allow 'api GET issues'        "$(bash_in 'gh api repos/o/r/issues')"
check allow 'api -X GET -f'         "$(bash_in 'gh api -X GET repos/o/r/issues -f state=open')"
check allow 'api issue comment'     "$(bash_in 'gh api repos/o/r/issues/12/comments -f body=hi')"
check allow 'named, not run'        "$(bash_in 'echo "run gh issue create later" > note.md')"
check allow 'grep for it'           "$(bash_in 'grep -n "gh issue create" CLAUDE.md')"
check allow 'other tool'            "$(mcp_in Read '{"file_path":"/x"}')"
check allow 'mcp issue_write update' "$(mcp_in mcp__github__issue_write '{"method":"update","issue_number":3}')"

# Identifier writes with the door shut: denied.
check deny 'issue create, door shut'   "$(bash_in 'gh issue create --title t --body b')"
check deny 'issue new alias'           "$(bash_in 'gh issue new -t t -b b')"
check deny 'issue transfer'            "$(bash_in 'gh issue transfer 4 o/other')"
check deny 'issue delete'              "$(bash_in 'gh issue delete 4 --yes')"
check deny 'env prefix'                "$(bash_in 'GH_REPO=o/r gh issue create -t t -b b')"
check deny 'after cd &&'               "$(bash_in 'cd /w && gh issue create -t t -b b')"
check deny 'path to gh'                "$(bash_in '/usr/bin/gh issue create -t t -b b')"
check deny 'brace group'               "$(bash_in '{ gh issue create -t t -b b; }')"
check allow 'not gh, ends in gh'       "$(bash_in 'ugh issue create')"
check deny 'inside sh -c'              "$(bash_in 'sh -c "gh issue create -t t -b b"')"
check deny 'inside eval'               "$(bash_in 'eval "gh issue transfer 4 o/x"')"
check deny 'in $(...)'                 "$(bash_in 'url=$(gh issue create -t t -b b)')"
check deny 'api POST -f'               "$(bash_in 'gh api repos/o/r/issues -f title=t')"
check deny 'api -X POST --input'       "$(bash_in 'gh api -X POST repos/o/r/issues --input body.json')"
check deny 'graphql createIssue'       "$(bash_in "$(printf 'gh api graphql -f query=%s' "'mutation { createIssue(input:{}) { issue { id } } }'")")"
check deny 'graphql, query on its own line' "$(bash_in "$(printf 'gh api graphql -F query=@- <<EOF\nmutation {\n  transferIssue(input:{}) { issue { id } }\n}\nEOF')")"
check deny 'mcp create_issue'          "$(mcp_in mcp__github__create_issue '{"owner":"o","repo":"r","title":"t"}')"
check deny 'mcp issue_write create'    "$(mcp_in mcp__plugin_github_github__issue_write '{"method":"create","title":"t"}')"

# One per human turn: the turn opens it, the first write spends it.
open_door
check allow 'first create this turn'   "$(bash_in 'gh issue create -t t -b b')"
check deny  'second create, same turn' "$(bash_in 'gh issue create -t t2 -b b')"
open_door
check allow 'next turn, mcp create'    "$(mcp_in mcp__github__create_issue '{"title":"t"}')"
check deny  'and then a transfer'      "$(bash_in 'gh issue transfer 4 o/other')"

# Never a batch, door or no door; a denied batch does not spend the door.
open_door
check deny  'two in one call'          "$(bash_in 'gh issue create -t a -b b; gh issue create -t c -b d')"
check deny  'create and transfer'      "$(bash_in 'gh issue create -t a -b b && gh issue transfer 4 o/x')"
check deny  'for loop'                 "$(bash_in 'for t in a b c; do gh issue create -t "$t" -b x; done')"
check deny  'while loop'               "$(bash_in 'while read t; do gh issue create -t "$t" -b x; done < list')"
check deny  'xargs'                    "$(bash_in 'cat list | xargs -I{} gh issue create -t {} -b x')"
check allow 'loop closed before the create' "$(bash_in 'for f in a b; do echo "$f"; done; gh issue create -t one -b b')"
check deny  'inner loop closed, outer still open' "$(bash_in 'for t in a b; do for s in x y; do :; done; gh issue create -t "$t" -b b; done')"
check deny  'loop opened after then'    "$(bash_in 'if true; then for t in a b; do gh issue create -t "$t" -b b; done; fi')"
open_door
check allow 'door survived the denials' "$(bash_in 'gh issue create -t one -b b')"
open_door
check allow 'loop word in the title'   "$(bash_in 'gh issue create --title "Retry for uploads while offline" -b b')"
open_door
check deny  'until loop'               "$(bash_in 'until false; do gh issue create -t t -b x; done')"
check deny  'find -exec'               "$(bash_in 'find . -name "*.md" -exec gh issue create -F {} \;')"
check deny  'parallel'                 "$(bash_in 'parallel gh issue create -t {} -b x ::: a b')"

# Another session's turn does not open this one's door.
shut_door
printf '{"session_id":"s2","prompt":"go"}' | sh "$HOOK" prompt
check deny 'other session opened its own door' "$(bash_in 'gh issue create -t t -b b')"

# The deny reason is valid JSON and says what to do.
reason=$(bash_in 'gh issue create -t t -b b' | sh "$HOOK" | jq -r '.hookSpecificOutput.permissionDecisionReason')
case $reason in *'wait for their yes'*) pass=$((pass + 1)) ;; *) fail=$((fail + 1)); echo "FAIL: reason lacks the next step: $reason" ;; esac

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
