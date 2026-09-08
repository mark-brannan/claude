#!/usr/bin/env bash
# Tests for prose-budget-edit.sh. Run: bash .claude/hooks/prose-budget-edit.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/prose-budget-edit.sh"
export PROSE_BUDGET="$HERE/../../.local/bin/prose-budget"
pass=0; fail=0

# check <context|silent> <description> <file path>
check() {
  local want=$1 desc=$2 file=$3 out got
  out=$(jq -n --arg f "$file" '{tool_name:"Edit",tool_input:{file_path:$f}}' | timeout 20 bash "$HOOK" 2>&1)
  if printf '%s' "$out" | grep -q '"additionalContext"'; then got=context; else got=silent; fi
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); else
    fail=$((fail + 1)); printf 'FAIL (want %s, got %s): %s\n' "$want" "$got" "$desc"
    [ -n "$out" ] && printf '  hook output: %s\n' "$out"
  fi
  LAST=$out
}

REPO=$(mktemp -d); git -C "$REPO" init -q -b main
printf '{"lines": {"README.md": 2}, "voice": {"scope": "tree"}}\n' > "$REPO/.prose-budgets.json"
printf 'a\nb\nc\n' > "$REPO/README.md"
printf 'a\n' > "$REPO/CLAUDE.md"
mkdir -p "$REPO/docs"; printf 'a seamless flow\n' > "$REPO/docs/x.md"
printf 'print(1)\n' > "$REPO/x.py"
printf '{"note": "a robust note"}\n' > "$REPO/data.json"
NOCONF=$(mktemp -d); printf 'a robust line\n' > "$NOCONF/README.md"
trap 'rm -rf "$REPO" "$NOCONF"' EXIT

check context 'file over its line budget'         "$REPO/README.md"
printf '%s' "$LAST" | grep -q 'README.md:3: lines' || { fail=$((fail + 1)); echo 'FAIL: context lacks the finding'; }
check context 'voice word in a docs file'         "$REPO/docs/x.md"
check silent  'clean file'                        "$REPO/CLAUDE.md"
check silent  'json outside any json_prose target' "$REPO/data.json"
check silent  'not markdown or json'              "$REPO/x.py"
check silent  'no config in the repo'             "$NOCONF/README.md"
check silent  'file does not exist'               "$REPO/missing.md"

BARE=$(mktemp -d); for t in bash sh cat git dirname timeout; do p=$(command -v $t) && ln -s "$p" "$BARE/$t"; done
out=$(jq -n --arg f "$REPO/README.md" '{tool_name:"Edit",tool_input:{file_path:$f}}' | PATH=$BARE bash "$HOOK" 2>&1)
if [ -z "$out" ]; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: without jq the hook should be silent, got: $out"; fi
rm -rf "$BARE"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
