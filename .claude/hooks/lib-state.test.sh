#!/usr/bin/env bash
# Tests for lib-state.sh's archivable_reasons(), focused on the session-live
# check (dotfiles#167), for state_lock/state_unlock (dotfiles#161), and for
# day_decisions (dotfiles#301).
#
# The dirty/unpushed/home checks predate this file and are exercised
# end-to-end by stop-continuity.test.sh and metrics-live.test.sh already;
# what's new and untested elsewhere is the claim-stamp liveness gate, so
# that's what this covers. Every case below starts from a worktree that is
# clean, pushed and homed -- reasons empty before the live check runs at
# all -- so a pass here isolates the new behavior from the old.
#
# Set AWK_PATH to a directory whose `awk` is another implementation (mawk,
# gawk, busybox) to check state_lock's meta parsing under it.
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# --- a clean, pushed, homed worktree ------------------------------------------
ORIGIN="$SCRATCH/origin.git"; git init -q --bare "$ORIGIN" >/dev/null 2>&1
WT="$SCRATCH/work"; gitq "$SCRATCH" init -q -b feature "$WT"
printf 'x\n' > "$WT/f"
gitq "$WT" add f
gitq "$WT" commit -q -m init
gitq "$WT" remote add origin "$ORIGIN"
gitq "$WT" push -q -u origin feature

# --- a fake HOOK_DIR: branch-home-gate.sh always says "home", claim-stamp.sh
# is swapped per case ------------------------------------------------------
FAKE="$SCRATCH/hooks"; mkdir -p "$FAKE"
cat > "$FAKE/branch-home-gate.sh" <<'EOF'
#!/bin/sh
echo "home: pr https://github.com/o/r/pull/1"
EOF
chmod +x "$FAKE/branch-home-gate.sh"

set_claim_stamp() {  # set_claim_stamp <read-output>
  cat > "$FAKE/claim-stamp.sh" <<EOF
#!/bin/sh
[ "\$1" = read ] || exit 0
cat <<'STAMPS'
$1
STAMPS
EOF
  chmod +x "$FAKE/claim-stamp.sh"
}

run_reasons() {  # run_reasons <self-sid>
  HOOK_DIR="$FAKE" bash -c '
    . "'"$HOOKS"'/lib-state.sh"
    archivable_reasons "'"$WT"'" feature "'"$1"'"
  '
}

check() {  # check <name> <self-sid> <want-contains|empty>
  name=$1; sid=$2; want=$3
  got=$(run_reasons "$sid")
  case "$want" in
    '') if [ -z "$got" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $name: want empty, got [$got]"; fi ;;
    *)  case "$got" in
          *"$want"*) pass=$((pass+1)) ;;
          *) fail=$((fail+1)); echo "FAIL $name: want to contain [$want], got [$got]" ;;
        esac ;;
  esac
}

# no claim-stamp.sh at all: behaves exactly as before this change (empty)
rm -f "$FAKE/claim-stamp.sh"
check "no claim-stamp.sh -> archivable" abcd1234 ""

# a live stamp belonging to someone else: blocks
set_claim_stamp "$(printf 'live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1')"
check "other session's fresh stamp -> session live" abcd1234 "session live"

# the caller's own stamp, fresh: does not block its own archival
check "own fresh stamp is excluded" deadbeef ""

# a stale stamp: does not block
set_claim_stamp "$(printf 'stale\tdeadbeef\thost-aa1\t180m\thttps://github.com/o/r/pull/1')"
check "stale stamp -> archivable" abcd1234 ""

# no card / no stamps at all (claim-stamp prints nothing): does not block
set_claim_stamp ""
check "no stamps -> archivable" abcd1234 ""

# no session id given (a sweep, not a session): a fresh stamp from anyone,
# including one that happens to share no sid, still blocks
set_claim_stamp "$(printf 'live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1')"
check "no self sid, fresh stamp -> session live" "" "session live"


# --- state_lock / state_unlock ------------------------------------------------
LOCKDIR="$SCRATCH/x.lock"
CASE="$SCRATCH/case.sh"

lock_check() {  # lock_check <name> <script-body-file-already-written> <want-exit>
  name=$1; want=$2
  bash "$CASE" >/dev/null 2>&1; got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else
    fail=$((fail+1)); echo "FAIL $name: want exit $want, got $got"
  fi
}

cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR"
EOF
lock_check "plain acquire succeeds" 0
rm -rf "$LOCKDIR"

cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR" && state_unlock && [ ! -d "$LOCKDIR" ]
EOF
lock_check "unlock releases (dir gone after)" 0
rm -rf "$LOCKDIR"

mkdir -p "$LOCKDIR"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$LOCKDIR/meta"
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR"
EOF
lock_check "contended acquire (live pid) fails" 1
rm -rf "$LOCKDIR"

# state_lock installs no trap of its own (trap overwrites, doesn't chain --
# see the PR #361 review thread): a caller's pre-existing EXIT trap must
# still fire after state_lock runs.
MARKER="$SCRATCH/marker"
cat > "$CASE" <<EOF
trap 'touch "$MARKER"' EXIT
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR"
EOF
rm -f "$MARKER"
lock_check "caller's own EXIT trap still fires after state_lock" 0
if [ -f "$MARKER" ]; then pass=$((pass+1)); else
  fail=$((fail+1)); echo "FAIL caller's own EXIT trap still fires after state_lock: marker missing"
fi
rm -rf "$LOCKDIR" "$MARKER"

mkdir -p "$LOCKDIR"
printf 'pid=999999999\nhostname=%s\n' "$(uname -n)" > "$LOCKDIR/meta"
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR" && grep -q "^pid=\$\$" "$LOCKDIR/meta"
EOF
lock_check "stale lock (dead pid, same host) is reclaimed" 0
rm -rf "$LOCKDIR"

# dotfiles#161: a kill between mkdir and the meta write leaves a lock dir
# with no meta at all -- no pid to check stale-reclaim's usual way. Age of
# the dir itself is the only signal left, so one older than
# STATE_LOCK_STALE_SECS must reclaim, and a dir that just appeared (another
# state_lock plausibly still mid-acquire) must not.
mkdir -p "$LOCKDIR"
AGE_CUTOFF=$(( $(date +%s) - 30 ))
AGE_TS=$(date -d "@$AGE_CUTOFF" +%Y%m%d%H%M.%S 2>/dev/null || date -r "$AGE_CUTOFF" +%Y%m%d%H%M.%S)
touch -t "$AGE_TS" "$LOCKDIR"
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR" && grep -q "^pid=\$\$" "$LOCKDIR/meta"
EOF
lock_check "meta-less lock dir aged past threshold is reclaimed" 0
rm -rf "$LOCKDIR"

mkdir -p "$LOCKDIR"
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR"
EOF
lock_check "fresh meta-less lock dir is not reclaimed" 1
rm -rf "$LOCKDIR"

# PR #379 review thread: if `: > "$ref"` succeeds but `touch -t` fails, the
# meta-less-reclaim path must not leak the "$dir.age.$$" reference file.
mkdir -p "$LOCKDIR"
cat > "$CASE" <<EOF
touch() { if [ "\$1" = "-t" ]; then return 1; fi; command touch "\$@"; }
. "$HOOKS/lib-state.sh"
state_lock "$LOCKDIR"
EOF
lock_check "touch -t failure on meta-less dir still fails" 1
if find "$SCRATCH" -maxdepth 1 -name "x.lock.age.*" | grep -q .; then
  fail=$((fail+1)); echo "FAIL touch -t failure leaks the age reference file"
else
  pass=$((pass+1))
fi
rm -rf "$LOCKDIR" "$SCRATCH"/x.lock.age.*


# --- day_decisions -----------------------------------------------------------
# The machine-wide decision store (dotfiles#301). CLAUDE_STATE_REPO points
# state_dir at a scratch tree so nothing here touches the real state repo, and
# so the fallback path (a machine without the repo) never gets picked up on a
# runner that happens to have /workspace/claude_prompts_scratch.
DAYREPO="$SCRATCH/state-repo"; mkdir -p "$DAYREPO/.git"
DAYF="$DAYREPO/state/global/metrics/day-decisions.json"
export CLAUDE_STATE_REPO="$DAYREPO"

day() {  # day <sid> <total> <junk> <now> <gap-seconds>
  bash -c '. "'"$HOOKS"'/lib-state.sh"; day_decisions "$@"' _ "$@"
}

dcheck() {  # dcheck <name> <want-total> <want-junk> <got-tsv>
  name=$1; want=$(printf '%s\t%s' "$2" "$3"); got=$4
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else
    fail=$((fail+1)); printf 'FAIL %s: want [%s], got [%s]\n' "$name" "$want" "$got"
  fi
}

# an empty store: this session's counts are the day's
dcheck "first call seeds the day" 7 1 "$(day sess-a 7 1 1000 10800)"

# a second session in the same day sums in
dcheck "a second session sums" 20 3 "$(day sess-b 13 2 1100 10800)"

# the same session again replaces its own contribution rather than adding to it:
# the hook fires on every prompt, so a running total would multiply
dcheck "same session is idempotent" 24 3 "$(day sess-a 11 1 1200 10800)"

# a gap under the limit keeps the day
dcheck "gap under the limit keeps the day" 25 3 "$(day sess-b 14 2 11000 10800)"

# a gap past the limit starts a fresh day: only the calling session is left
dcheck "gap past the limit resets" 4 0 "$(day sess-b 4 0 30000 10800)"
if [ "$(jq -r '.sessions | keys | join(",")' "$DAYF")" = "sess-b" ]; then
  pass=$((pass+1))
else
  fail=$((fail+1)); echo "FAIL reset drops the other sessions' contributions"
fi

# junk is carried, never subtracted from the total
dcheck "junk rides beside the total" 9 5 "$(day sess-c 5 5 30100 10800)"

# a lock held by a live process: prints the store as it stands, writes nothing
mkdir -p "$DAYF.lock"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$DAYF.lock/meta"
dcheck "contended lock writes nothing" 9 5 "$(day sess-d 99 0 30200 10800)"
rm -rf "$DAYF.lock"

# state_lock installs no trap of its own (#361), so day_decisions has to release
# the lock on its own way out: nothing may be left behind after a normal call.
if [ ! -d "$DAYF.lock" ]; then pass=$((pass+1)); else
  fail=$((fail+1)); echo "FAIL day_decisions left its lock dir behind"
fi

# and it must not arm a trap either -- a hook that already has one (stop-
# continuity.sh arms `trap restore_board EXIT`) would have it silently clobbered
got=$(bash -c '. "'"$HOOKS"'/lib-state.sh"; trap "echo CALLER_TRAP" EXIT
  day_decisions sess-e 1 0 30300 10800 >/dev/null' 2>&1)
if [ "$got" = "CALLER_TRAP" ]; then pass=$((pass+1)); else
  fail=$((fail+1)); printf "FAIL caller's EXIT trap clobbered: got [%s]\n" "$got"
fi

# The read has to happen after the lock is taken, not before (the review on
# #364). A stand-in state_lock writes another session's entry at the moment the
# lock is acquired: a day_decisions that had already snapshotted the file would
# overwrite that entry, where one that reads inside the lock folds both in.
rm -f "$DAYF"
got=$(bash -c '. "'"$HOOKS"'/lib-state.sh"
  state_lock() { jq -n "{last_prompt: 40000, sessions: {\"sess-x\": {total: 6, junk: 1}}}" > "'"$DAYF"'"; }
  state_unlock() { :; }
  day_decisions sess-y 2 0 40100 10800')
dcheck "the read happens inside the lock" 8 1 "$got"

# Two interleaved callers: the second finds the lock held, writes nothing, and
# once it is free lands its total on top of the first's rather than over it.
rm -f "$DAYF"
day sess-p 6 1 41000 10800 >/dev/null
mkdir -p "$DAYF.lock"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$DAYF.lock/meta"
dcheck "lock held: the second caller writes nothing" 6 1 "$(day sess-q 9 2 41100 10800)"
rm -rf "$DAYF.lock"
dcheck "lock free: the second caller lands on top" 15 3 "$(day sess-q 9 2 41200 10800)"

# no store at all and the lock unavailable: a usable pair, not empty output
rm -f "$DAYF"
mkdir -p "$DAYF.lock"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$DAYF.lock/meta"
dcheck "no store, no lock -> 0 0" 0 0 "$(day sess-r 3 0 41300 10800)"
rm -rf "$DAYF.lock"

# no metrics dir can be made (a file squats on its path): still a usable pair,
# not empty output -- PR B's caller splits this on a tab
BADREPO="$SCRATCH/bad-repo"; mkdir -p "$BADREPO/.git" "$BADREPO/state/global"
: > "$BADREPO/state/global/metrics"
dcheck "no metrics dir -> 0 0" 0 0 "$(CLAUDE_STATE_REPO="$BADREPO" day sess-s 3 0 41400 10800)"

unset CLAUDE_STATE_REPO

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
