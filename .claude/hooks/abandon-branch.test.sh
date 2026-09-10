#!/usr/bin/env bash
# Tests for abandon-branch.sh. Run: bash .claude/hooks/abandon-branch.test.sh
#
# Deletes on both sides when it can confirm the remote side, refuses in
# $HOME, and never deletes the local branch on an indeterminate remote check
# (network/auth failure, not a confirmed absence).
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HOOKS/abandon-branch.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

ORIGIN="$SCRATCH/origin.git"; WORK="$SCRATCH/work"
setup_repo() {  # setup_repo <branch> [pushed=1]
  local branch=$1 pushed=${2:-1}
  rm -rf "$ORIGIN" "$WORK"
  git init -q --bare -b main "$ORIGIN"
  git init -q -b main "$WORK"
  gitq "$WORK" remote add origin "$ORIGIN"
  echo one > "$WORK/f"; gitq "$WORK" add -- f; gitq "$WORK" commit -m one
  gitq "$WORK" push -u origin main
  gitq "$WORK" checkout -b "$branch"
  echo two > "$WORK/g"; gitq "$WORK" add -- g; gitq "$WORK" commit -m two
  [ "$pushed" = 1 ] && gitq "$WORK" push -u origin "$branch"
}

ok() { if "${@:2}"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n' "$1"; fi; }
no() { if "${@:2}"; then fail=$((fail+1)); printf 'FAIL: %s\n' "$1"; else pass=$((pass+1)); fi; }
says() { printf '%s' "$1" | grep -qF -- "$2"; }  # says <text> <substring>, use via ok/no

# --- deletes both sides when the remote is reachable --------------------------
setup_repo claude/gone
OUT=$(sh "$SCRIPT" -C "$WORK" 2>&1)
no  'the local branch is gone'  gitq "$WORK" rev-parse --verify claude/gone
ok  'HEAD is detached, work still reachable' \
    [ "$(git -C "$WORK" rev-parse --abbrev-ref HEAD)" = HEAD ]
ok  'the remote branch is gone' \
    [ -z "$(git -C "$WORK" ls-remote --heads origin claude/gone 2>/dev/null)" ]
ok  'it says what it did' says "$OUT" 'abandoned `claude/gone`'

# --- a branch that was never pushed: local half only, said plainly ------------
setup_repo claude/local 0
OUT=$(sh "$SCRIPT" -C "$WORK" claude/local 2>&1)
no  'the local branch is gone (never pushed)'  gitq "$WORK" rev-parse --verify claude/local
ok  'it says there was nothing on the remote' says "$OUT" 'not on the remote'

# --- an unreachable remote: kept, not deleted ----------------------------------
setup_repo claude/unreachable
gitq "$WORK" remote set-url origin "$SCRATCH/no-such-remote.git"
OUT=$(sh "$SCRIPT" -C "$WORK" 2>&1)
ok  'the local branch is kept on an indeterminate remote' \
    [ "$(git -C "$WORK" rev-parse --abbrev-ref HEAD)" = claude/unreachable ]
ok  'it says the remote could not be verified' says "$OUT" 'could not verify remote'

# --- refuses in $HOME ----------------------------------------------------------
setup_repo claude/athome
OUT=$(HOME="$WORK" sh "$SCRIPT" -C "$WORK" 2>&1)
ok  'it says why it refused' says "$OUT" 'refused'
ok  'the branch is untouched' gitq "$WORK" rev-parse --verify claude/athome

# --- refuses main/master, and a detached HEAD with no branch given ------------
setup_repo claude/x
OUT=$(sh "$SCRIPT" -C "$WORK" main 2>&1); RC=$?
ok  'refuses to abandon main' [ "$RC" -ne 0 ]
gitq "$WORK" checkout --detach
OUT=$(sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses a detached HEAD with no branch given' [ "$RC" -ne 0 ]

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
