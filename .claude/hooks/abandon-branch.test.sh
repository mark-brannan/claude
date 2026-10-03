#!/usr/bin/env bash
# Tests for abandon-branch.sh. Run: bash .claude/hooks/abandon-branch.test.sh
#
# Deletes on both sides when it can confirm the remote side, refuses in
# $HOME, refuses the branch of an open PR, and never deletes the local
# branch on an indeterminate remote check (network/auth failure, not a
# confirmed absence).
#
# `gh` is stubbed on PATH throughout -- no test here reaches the network,
# and a test that did would pass or fail on whatever PRs happened to be
# open. The default stub reports no open PRs at all, as
# no-delete-stacked-base.test.sh's does.
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HOOKS/abandon-branch.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

STUB_DIR="$SCRATCH/stub"; mkdir -p "$STUB_DIR"
# GH_PRS holds the JSON array the stub prints; GH_FAIL nonzero makes it exit
# nonzero (an unreadable PR list) instead. Default: no open PRs anywhere.
cat > "$STUB_DIR/gh" <<'STUB'
#!/bin/sh
[ -n "${GH_FAIL:-}" ] && exit 1
printf '%s\n' "${GH_PRS:-[]}"
STUB
chmod +x "$STUB_DIR/gh"
export GH_PRS='[]'
PATH="$STUB_DIR:$PATH"

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
says() { grep -qF -- "$2" <<<"$1"; }  # says <text> <substring>, use via ok/no

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

# --- refuses the base branch of an open PR --------------------------------
setup_repo claude/based
OUT=$(GH_PRS='[{"number":1,"title":"stacked change","baseRefName":"claude/based","headRefName":"claude/stacked-one"}]' \
      sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses when an open PR is based on it' [ "$RC" -ne 0 ]
ok  'it says why it refused' says "$OUT" 'refused'
ok  'it names the PR' says "$OUT" '#1'
ok  'the local branch is untouched' gitq "$WORK" rev-parse --verify claude/based
ok  'the remote branch is untouched' \
    [ -n "$(git -C "$WORK" ls-remote --heads origin claude/based 2>/dev/null)" ]

# --- refuses the head branch of an open PR ---------------------------------
setup_repo claude/headed
OUT=$(GH_PRS='[{"number":2,"title":"the change itself","baseRefName":"main","headRefName":"claude/headed"}]' \
      sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses when it is itself an open PR head' [ "$RC" -ne 0 ]
ok  'it names the PR' says "$OUT" '#2'
ok  'the local branch is untouched' gitq "$WORK" rev-parse --verify claude/headed

# --- fails closed: gh missing -----------------------------------------------
# A PATH with only git and sh symlinked in, so gh is genuinely unresolvable
# rather than just absent from the stub dir (the system's real gh, if any,
# would otherwise still be found on the rest of PATH).
NOGH_DIR="$SCRATCH/nogh-bin"; mkdir -p "$NOGH_DIR"
ln -s "$(command -v git)" "$NOGH_DIR/git"
ln -s "$(command -v sh)" "$NOGH_DIR/sh"
ln -s "$(command -v dirname)" "$NOGH_DIR/dirname"
setup_repo claude/nogh
OUT=$(PATH="$NOGH_DIR" sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses without gh on PATH' [ "$RC" -ne 0 ]
ok  'it says it could not check' says "$OUT" 'could not check open PRs'
ok  'the branch is untouched' gitq "$WORK" rev-parse --verify claude/nogh

# --- fails closed: the PR list could not be read ----------------------------
setup_repo claude/ghfails
OUT=$(GH_FAIL=1 sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses when the PR list is unreadable' [ "$RC" -ne 0 ]
ok  'it says it could not check' says "$OUT" 'could not check open PRs'
ok  'the branch is untouched' gitq "$WORK" rev-parse --verify claude/ghfails

# --- fails closed: a list long enough to have been truncated ---------------
setup_repo claude/many
OUT=$(GH_PRS="$(jq -nc '[range(1000) | {number: ., title: "t", baseRefName: "main", headRefName: "x\(.)"}]')" \
      sh "$SCRIPT" -C "$WORK" 2>&1); RC=$?
ok  'refuses when the PR list may be truncated' [ "$RC" -ne 0 ]
ok  'the branch is untouched' gitq "$WORK" rev-parse --verify claude/many

# --- a never-pushed branch needs no PR check: gh down, still deleted ---------
setup_repo claude/localonly 0
OUT=$(GH_FAIL=1 sh "$SCRIPT" -C "$WORK" claude/localonly 2>&1)
no  'the local-only branch is gone with gh down' gitq "$WORK" rev-parse --verify claude/localonly

# --- no open PR: the delete proceeds as before ------------------------------
setup_repo claude/clear
OUT=$(GH_PRS='[{"number":9,"title":"unrelated","baseRefName":"main","headRefName":"claude/elsewhere"}]' \
      sh "$SCRIPT" -C "$WORK" 2>&1)
no  'the local branch is gone (no matching PR)'  gitq "$WORK" rev-parse --verify claude/clear
ok  'it says what it did' says "$OUT" 'abandoned `claude/clear`'

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
