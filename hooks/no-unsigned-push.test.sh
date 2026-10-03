#!/usr/bin/env bash
# Tests for no-unsigned-push.sh. Run: bash hooks/no-unsigned-push.test.sh
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

# Sets $verdict / $hook_out for an arbitrary command + cwd pair.
run_hook_cmd() {
  hook_out=$(jq -nc --arg c "$1" --arg d "$2" '{tool_input:{command:$c},cwd:$d}' | sh "$HOOK")
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

# The repo actually being pushed is the one to check, not wherever the
# session's cwd happens to sit. cwd here is a clean repo; the command names
# a different, unsigned one via `-C` -- that one must be denied.
clean=$(setup)
dirty=$(setup)
git -C "$clean" switch -q -c feat
git -C "$clean" commit -q --allow-empty -m 'signed on feat'
git -C "$dirty" switch -q -c feat
unsigned_commit "$dirty" 'unsigned on feat'
run_hook_cmd "git -C $dirty push" "$clean"
check "git -C DIR push checks DIR, not cwd" "$verdict" deny

# Same, but cwd is the unsigned repo and the command's -C target is clean:
# must not deny on the cwd's unsigned commits.
run_hook_cmd "git -C $clean push" "$dirty"
check "git -C DIR push does not fall back to cwd's commits" "$verdict" silent

# A leading `cd DIR &&` before the push has the same effect.
run_hook_cmd "cd $dirty && git push" "$clean"
check "cd DIR && git push checks DIR, not cwd" "$verdict" deny
run_hook_cmd "cd $clean && git push" "$dirty"
check "cd DIR && git push does not fall back to cwd's commits" "$verdict" silent

# A `cd` after the push, or an unrelated `-C` before it, must not be read as
# the push's directory -- both would otherwise point the check at the wrong
# repo (or a nonexistent one) and fail open.
run_hook_cmd "git push && cd $dirty" "$clean"
check "a trailing cd after push is not the push's directory" "$verdict" silent
run_hook_cmd "git commit -C HEAD && git push" "$dirty"
check "an unrelated -C before push is not the push's -C" "$verdict" deny
run_hook_cmd "git -C $dirty push && git -C $clean status" "$clean"
check "a second -C after the push is not the push's -C" "$verdict" deny

# `cd /a || git push` must not swallow the `|| git push` into the directory
# it captures -- the push itself still runs (regardless of whether `cd`
# succeeded), so the stop class must treat `|` as a separator too.
run_hook_cmd "cd $dirty || git push" "$clean"
check "cd DIR || git push does not swallow the fallback into the path" "$verdict" deny

# A bare `cd` (no argument) goes to $HOME, same as the shell.
HOME_SAVE=$HOME
export HOME=$dirty
run_hook_cmd "cd && git push" "$clean"
check "bare cd checks \$HOME, not cwd" "$verdict" deny
export HOME=$HOME_SAVE

# -C gets the same ~/\$HOME expansion as a leading cd.
HOME_SAVE=$HOME
dirty_parent=$(dirname "$dirty")
export HOME=$dirty_parent
run_hook_cmd "git -C ~/$(basename "$dirty") push" "$clean"
check "git -C ~/DIR push expands the tilde" "$verdict" deny
export HOME=$HOME_SAVE

# grep's `^` anchors every line, so a `cd` opening a later line of a
# multi-line command must not be read as the push's directory either.
run_hook_cmd "git push
cd $dirty" "$clean"
check "a cd on a later line is not the push's directory" "$verdict" silent

# Several -C flags chain, as git does: `-C parent -C w` is parent/w.
run_hook_cmd "git -C $(dirname "$dirty") -C $(basename "$dirty") push" "$clean"
check "chained -C flags resolve like git's" "$verdict" deny

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
