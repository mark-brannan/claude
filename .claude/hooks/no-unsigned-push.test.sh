#!/usr/bin/env bash
# Tests for no-unsigned-push.sh. Run: bash .claude/hooks/no-unsigned-push.test.sh
#
# Each case builds a bare origin and a clone signing with a throwaway SSH key,
# so "signed" means a real gpgsig header. Unsigned commits are made with
# -c commit.gpgsign=false. Global git config is ignored throughout.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/no-unsigned-push.sh"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
pass=0
fail=0
tmpdirs=()
trap 'rm -rf "${tmpdirs[@]}"' EXIT

check() {
  local desc=$1 got=$2 want=$3
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL: %s (want %q, got %q)\n' "$desc" "$want" "$got"
  fi
}

# Prints the clone's path: main pushed to origin, origin/HEAD set, signing on.
setup() {
  local t
  t=$(mktemp -d)
  tmpdirs+=("$t")
  ssh-keygen -q -t ed25519 -N '' -f "$t/key"
  git init -q --bare -b main "$t/origin.git"
  git clone -q "$t/origin.git" "$t/w" 2>/dev/null
  git -C "$t/w" config user.email test@example.com
  git -C "$t/w" config user.name Test
  git -C "$t/w" config gpg.format ssh
  git -C "$t/w" config user.signingkey "$t/key"
  git -C "$t/w" config commit.gpgsign true
  git -C "$t/w" commit -q --allow-empty -m root
  git -C "$t/w" push -q origin main
  git -C "$t/w" remote set-head origin main >/dev/null
  printf '%s' "$t/w"
}

unsigned_commit() { git -C "$1" -c commit.gpgsign=false commit -q --allow-empty -m "$2"; }

# Sets $verdict to allow / deny / silent and $hook_out to the raw output.
run_hook() {
  hook_out=$(jq -nc --arg d "$1" '{tool_input:{command:"git push"},cwd:$d}' | sh "$HOOK")
  case $hook_out in
    '') verdict=silent ;;
    *'"deny"'*) verdict=deny ;;
    *) verdict=allow ;;
  esac
}

# The bug: a pushed branch that merges a main carrying unsigned commits was
# denied for main's commits, which @{u}..HEAD counted as its own.
w=$(setup)
git -C "$w" switch -q -c feat
git -C "$w" commit -q --allow-empty -m 'feat work'
git -C "$w" push -q -u origin feat 2>/dev/null
git -C "$w" switch -q main
unsigned_commit "$w" 'unsigned on main'
git -C "$w" push -q origin main
git -C "$w" switch -q feat
git -C "$w" merge -q --no-edit main
run_hook "$w"
check "merged main's unsigned commits are not the branch's" "$verdict" silent

# The branch's own unsigned commit is still caught, and only it is named.
unsigned_commit "$w" 'unsigned on feat'
run_hook "$w"
check "own unsigned commit is denied" "$verdict" deny
check "deny names 1 commit, not main's" "$(printf '%s' "$hook_out" | grep -c '1 unsigned commit')" 1

# The remedy has the same trap: a rebase from the upstream replays main's
# commits as new, signed duplicates. The advised command must not.
target=$(printf '%s' "$hook_out" | grep -o 'git rebase -S --force-rebase [0-9a-f]*' | sed 's/.* //')
check "deny advises a rebase" "${target:+yes}" yes
check "deny says the push needs --force-with-lease" "$(printf '%s' "$hook_out" | grep -c 'force-with-lease')" 1
git -C "$w" rebase -S --force-rebase "${target:-HEAD}" >/dev/null 2>&1
check "advised rebase keeps main's commit, not a copy" "$(git -C "$w" merge-base --is-ancestor origin/HEAD HEAD && echo kept || echo copied)" kept
check "advised rebase leaves only the branch's two commits past main" "$(git -C "$w" rev-list --count HEAD --not origin/HEAD)" 2
run_hook "$w"
check "advised rebase re-signs the branch" "$verdict" silent

# No upstream: falls back to origin/HEAD.
w=$(setup)
git -C "$w" switch -q -c fresh
unsigned_commit "$w" 'unsigned, never pushed'
run_hook "$w"
check "no upstream, unsigned commit is denied" "$verdict" deny

# All signed: silent.
w=$(setup)
git -C "$w" switch -q -c clean
git -C "$w" commit -q --allow-empty -m signed
run_hook "$w"
check "signed branch passes" "$verdict" silent

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
