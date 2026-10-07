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

# state_lock_wait is the portable `flock -w`: it gives up on a live holder
# after its budget, and takes a lock freed while it waits.
mkdir -p "$LOCKDIR"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$LOCKDIR/meta"
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock_wait "$LOCKDIR" 1
EOF
lock_check "state_lock_wait: live holder past the budget fails" 1
( sleep 1; rm -rf "$LOCKDIR" ) &
cat > "$CASE" <<EOF
. "$HOOKS/lib-state.sh"
state_lock_wait "$LOCKDIR" 5 && grep -q "^pid=\$\$" "$LOCKDIR/meta"
EOF
lock_check "state_lock_wait: a lock freed mid-wait is taken" 0
wait; rm -rf "$LOCKDIR"

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

# --- the home line comes back through a file, from inside $(...) ----------------
# Every caller captures archivable_reasons with $(...), so a variable it sets
# is lost; ARCHIVABLE_HOME_FILE is how stop-continuity.sh's pickup item reuses
# the gh answer instead of asking again (PR #388, design pass).
rm -f "$FAKE/claim-stamp.sh"
HF="$SCRATCH/home-line"
got=$(HOOK_DIR="$FAKE" ARCHIVABLE_HOME_FILE="$HF" bash -c '
  . "'"$HOOKS"'/lib-state.sh"
  r=$(archivable_reasons "'"$WT"'" feature abcd1234)
  printf "%s|%s" "$r" "$(cat "$ARCHIVABLE_HOME_FILE" 2>/dev/null)"')
if [ "$got" = "|home: pr https://github.com/o/r/pull/1" ]; then pass=$((pass+1))
else fail=$((fail+1)); echo "FAIL home line through file: got [$got]"; fi

# --- unpushed_state: a commit on a differently-named remote branch ------------
# `mergify stack push` leaves @{u} at origin/main and pushes to stack/<name>;
# counting @{u}..HEAD called that pushed commit unpushed.
STK="$SCRATCH/stack"; git clone -q "$ORIGIN" "$STK" >/dev/null 2>&1
gitq "$STK" checkout -q -b main origin/feature
gitq "$STK" push -q -u origin main
gitq "$STK" checkout -q -b local-stack
gitq "$STK" branch -q -u origin/main
printf 'y\n' > "$STK/g"; gitq "$STK" add g; gitq "$STK" commit -q -m stacked
ust() { bash -c '. "'"$HOOKS"'/lib-state.sh"; unpushed_state "$1" "$2"' _ "$@"; }
eq_ust() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $1: expected [$2], got [$3]"; fi; }
eq_ust "commit on no remote branch, @{u}=main: ahead 1" 'ahead 1' "$(ust "$STK" local-stack)"
gitq "$STK" push -q origin local-stack:refs/heads/wip/sid
eq_ust "same commit only on a wip/ salvage ref: still ahead 1" 'ahead 1' "$(ust "$STK" local-stack)"
gitq "$STK" push -q origin local-stack:refs/heads/stack/x
eq_ust "same commit on stack/x, @{u} still main: ahead 0" 'ahead 0' "$(ust "$STK" local-stack)"
gitq "$STK" branch -q --unset-upstream
eq_ust "no upstream, commit on a remote branch: safe" 'safe' "$(ust "$STK" local-stack)"

# --- decision_rate -----------------------------------------------------------
dr() { bash -c '. "'"$HOOKS"'/lib-state.sh"; decision_rate "$@"' _ "$@"; }
eq_ust "decision_rate: 3 in 1h10"      '3 decisions in 1h10 (2.6/h)' "$(dr 3 4200)"
eq_ust "decision_rate: singular"       '1 decision in 0h30 (2.0/h)'  "$(dr 1 1800)"
eq_ust "decision_rate: no clock, no line" ''                          "$(dr 3 0)"

# --- work_record: a pickup item and a card read into one record shape -------
# Fields: kind title status until claim model effort link id updated.
wr() { ( . "$HOOKS/lib-state.sh"; export WORK_CLAIMS=${WC:-}; work_record "$@" ) | tr '\037' '|'; }
WR="$SCRATCH/wr"; mkdir -p "$WR"
printf 'status: open\nupdated: 2026-09-09T10:00:00Z\nmodel: claude-sonnet-5\npr: https://github.com/o/r/pull/7\n---\n\nFinish the thing\nlink: https://github.com/o/r/issues/3\nmodel: Opus\neffort: high\n' \
  > "$WR/2026-09-09T10-00-abcd1234.md"
eq_ust "work_record: a pickup item, body's hand-off lines win" \
  'pickup|Finish the thing|open|||opus|high|https://github.com/o/r/issues/3|2026-09-09T10-00-abcd1234|2026-09-09T10:00:00Z' \
  "$(wr "$WR/2026-09-09T10-00-abcd1234.md")"
printf 'status: taken\nupdated: 2026-09-10T10:00:00Z\nmodel: claude-sonnet-5\npr: none\n---\n' > "$WR/2026-09-10T10-00-00000000.md"
eq_ust "work_record: a bare item falls back to the header's model, no link" \
  'pickup||taken|||sonnet|||2026-09-10T10-00-00000000|2026-09-10T10:00:00Z' \
  "$(wr "$WR/2026-09-10T10-00-00000000.md")"
eq_ust "work_record: a card with model, effort and until" \
  'card|Fix the gate|open|o/r#9 merges||opus|high|https://github.com/o/r/issues/8|https://github.com/o/r/issues/8|2026-09-11T00:00:00Z' \
  "$(wr '- [ ] **Fix the gate** -- see [o/r#8](https://github.com/o/r/issues/8) model: opus effort: high until: o/r#9 merges' 2026-09-11T00:00:00Z)"
eq_ust "work_record: a card without them leaves them empty, title from its link text" \
  'card|tidy the docs (log)|open|||||log/2026-09-01.md|log/2026-09-01.md|' \
  "$(wr '- [ ] tidy the docs ([log](log/2026-09-01.md))')"
eq_ust "work_record: a card with a live claim is taken, the holder named" \
  'card|Held|taken||abcd1234|||https://example.invalid/h|https://example.invalid/h|' \
  "$(WC=$(printf 'live\tabcd1234\thost-x\t3m\thttps://example.invalid/h\nlive\teeeeeeee\thost-y\t1m\thttps://example.invalid/other') wr '- [ ] **Held** ([x](https://example.invalid/h))')"
eq_ust "work_record: a stale claim leaves it open" 'open' \
  "$(WC=$(printf 'stale\tabcd1234\thost-x\t300m\thttps://example.invalid/h') wr '- [ ] **Held** ([x](https://example.invalid/h))' | cut -d'|' -f3)"
eq_ust "work_record: same field count for both kinds" '10 10' \
  "$(wr "$WR/2026-09-09T10-00-abcd1234.md" | awk -F'|' '{print NF}') $(wr '- [ ] **A** ([x](https://example.invalid/a))' | awk -F'|' '{print NF}')"

# --- the work-item store is the whole board ------------------------------------
# board_union, board_card and claude_cards read items/ and nothing else: a
# kanban.md beside it is never opened. An item's claim is its log's.
KI="$SCRATCH/ki"; mkdir -p "$KI/items"
printf '# Board\n\n## Claude'"'"'s\n\n- [ ] **Old** ([x](https://example.invalid/o)) id: 1790836860aaaaaaaa\n' > "$KI/kanban.md"
ki() { # id title owner repo status brief [log time] [holder]
  printf '# %s\n\n## Brief\n%s\n\n## Log\n%s 1d68120b status=open owner=%s repo=%s parent=- model=- effort=-\n%s %s status=%s\n' \
    "$2" "$6" "${7:-2026-10-03T05:00:00Z}" "$3" "$4" "${7:-2026-10-03T05:00:00Z}" "${8:-1d68120b}" "$5" > "$KI/items/$1.md"
}
ki 1790836861aaaaaaaa 'Old moved' agent - ready '**Old moved** -- an item id: 1790836861aaaaaaaa'
ki 1790836862aaaaaaaa 'Stored ruling' human-ruling o/colregs ready 'Decide it.'
ki 1790836863aaaaaaaa 'Blocked one' agent - blocked 'Waits.'
ki 1790836864aaaaaaaa 'Held one' agent - claimed 'Held.' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" abcd1234
ki 1790836865aaaaaaaa 'Stale hold' agent - claimed 'Let go.' 2026-09-01T00:00:00Z eeeeeeee
ki 1790836866aaaaaaaa 'Done one' agent - 'done' 'Over.'
ki 1790836867aaaaaaaa 'Click it' human-click - ready 'In the UI.'
WI="$HOOKS/../bin/work-item"
lsi() { WORK_ITEM_DIR=${LSI_DIR:-$KI/items} WORK_ITEM_BIN=$WI HOOK_DIR=/nonexistent sh -c '. "'"$HOOKS"'/lib-state.sh"; '"$1" _; }
eq_ust "items: claude_cards lists the agent's ready and claimed items, not blocked, done, rulings or click work" \
  '**Old moved**|**Held one**|**Stale hold**|' \
  "$(lsi 'claude_cards' | cut -f2- | sed -E 's/^(- \[ \] )?(\*\*[^*]+\*\*).*/\2/' | tr '\n' '|')"
eq_ust "items: a kanban.md card is not a candidate" '' "$(lsi 'claude_cards' | grep -F 'Old' | grep -v 'Old moved' || true)"
eq_ust "items: an item's updated is its newest log line" '2026-10-03T05:00:00Z' \
  "$(lsi 'claude_cards' | grep 'Old moved' | cut -f1)"
eq_ust "items: board_card finds a ruling item, grouped by its repo" 'Needs ruling|colregs|- [ ] **Stored ruling**: Decide it. repo: o/colregs id: 1790836862aaaaaaaa' \
  "$(lsi 'board_card 1790836862aaaaaaaa' | tr '\t' '|')"
eq_ust "items: board_card finds an agent item" "Claude's" "$(lsi 'board_card 0000000000aaaaaaaa; board_card 1790836861aaaaaaaa' | cut -f1)"
eq_ust "items: board_card does not find a kanban.md card" '' "$(lsi 'board_card 1790836860aaaaaaaa' || true)"
eq_ust "items: board_union is the items by section" \
  "## Needs ruling|### colregs|## Human's|## Claude's" \
  "$(lsi 'board_union' | grep '^##' | tr '\n' '|' | sed 's/|$//')"
eq_ust "items: a live holder's item is taken, by id" 'taken|abcd1234' \
  "$(lsi 'work_claims_load; claude_cards | grep "Held one" | work_records --cards' | cut -d "$(printf '\037')" -f3,5 | tr '\037' '|')"
eq_ust "items: a stale holder has let go" 'open|' \
  "$(lsi 'work_claims_load; claude_cards | grep "Stale hold" | work_records --cards' | cut -d "$(printf '\037')" -f3,5 | tr '\037' '|')"
eq_ust "items: no items/ is an empty board, not a kanban.md read" '' \
  "$(LSI_DIR=$SCRATCH/none lsi 'claude_cards; board_union')"
# A store that cannot be read is named in $ITEM_ROWS_ERR; an empty one is not
# (card 179101773919cb0a62). item_rows still returns 0, so a hook that only
# wants what is there carries on.
mkdir -p "$SCRATCH/emptyitems"
eq_ust "items: an empty items/ is healthy, not a broken store" 'rc=0 err=[]' \
  "$(LSI_DIR=$SCRATCH/emptyitems lsi 'item_rows >/dev/null; rc=$?; done_rows; echo "rc=$rc err=[$ITEM_ROWS_ERR]"')"
eq_ust "items: a missing work-item is a broken store, and item_rows still returns 0" 'rc=0 err=[work-item not found]' \
  "$(WORK_ITEM_DIR=$KI/items WORK_ITEM_BIN=/nonexistent HOOK_DIR=/nonexistent HOME=/nonexistent sh -c '. "'"$HOOKS"'/lib-state.sh"; item_rows >/dev/null; echo "rc=$? err=[$ITEM_ROWS_ERR]"')"
eq_ust "items: board_card finds a done item, under Done" 'Done' "$(lsi 'board_card 1790836866aaaaaaaa' | cut -f1)"
eq_ust "items: done_rows is the done items only" '1790836866aaaaaaaa' "$(lsi 'done_rows; printf "%s\n" "$DONE_ROWS"' | cut -f1)"
eq_ust "items: the default store is items/ in the state dir" 'yes' \
  "$(WORK_ITEM_DIR='' sh -c '. "'"$HOOKS"'/lib-state.sh"; [ "$(items_dir)" = "$(state_dir)/items" ] && echo yes')"

# --- ruling_readiness ----------------------------------------------------------
# Under sh as well as bash: worklist sources this file from /bin/sh. gh is
# faked: the reply for ref n is read from $RR/state.<n>, and every call logged.
RR="$SCRATCH/rr"; export RR; mkdir -p "$RR/bin"
cat > "$RR/bin/gh" <<'EOF'
#!/bin/sh
n=""; for a in "$@"; do case $a in n=*) n=${a#n=} ;; esac; done
echo "$n" >> "$RR/gh.log"
[ -f "$RR/state.$n" ] && cat "$RR/state.$n" || exit 1
EOF
chmod +x "$RR/bin/gh"
for sh_ in bash sh; do
  rr() { PATH="$RR/bin:$PATH" XDG_CACHE_HOME="$RR/cache.$sh_" RULING_TODAY=2026-10-01 \
           "$sh_" -c '. "'"$HOOKS"'/lib-state.sh"; ruling_readiness "$1"' _ "$1"; }
  : > "$RR/gh.log"
  eq_ust "$sh_: a date passed is ready"         ready   "$(rr 'x until: 2026-09-12 (2.2, before 1.8 risk: y')"
  eq_ust "$sh_: a date today is ready"          ready   "$(rr 'x until: 2026-10-01. risk: y')"
  eq_ust "$sh_: a date ahead is waiting"        waiting "$(rr 'x until: 2026-10-05 risk: y')"
  eq_ust "$sh_: a date inside words counts"     ready   "$(rr 'x until: M6 card, 2026-09-30 judgment: risk')"
  eq_ust "$sh_: an event in words is waiting"   waiting "$(rr 'x until: the next session rooted in dotfiles risk: z')"
  eq_ust "$sh_: a bare #n names no repo, words" waiting "$(rr 'x until: before #15 or #16 is picked up risk: z')"
  eq_ust "$sh_: no until: at all is ready"      ready   "$(rr 'x kind: tentative ADR settle: y')"
  eq_ust "$sh_: a field after until: is not read as its value" waiting "$(rr 'x until: next week risk: 2026-01-01 outage')"
  printf 'pr-open' > "$RR/state.1"; printf 'issue-open' > "$RR/state.2"
  printf 'issue-inflight' > "$RR/state.3"; printf 'issue-closed' > "$RR/state.4"
  eq_ust "$sh_: an open PR is ready"            ready   "$(rr 'x until: https://github.com/o/r/pull/1 risk: y')"
  eq_ust "$sh_: an open issue no PR closes is waiting" waiting "$(rr 'x until: [o/r#2](https://github.com/o/r/issues/2) risk: y')"
  eq_ust "$sh_: an issue an open PR closes is ready" ready "$(rr 'x until: o/r#3 risk: y')"
  eq_ust "$sh_: a closed issue is ready"        ready   "$(rr 'x until: o/r#4 risk: y')"
  eq_ust "$sh_: a link gh cannot answer is ready" ready "$(rr 'x until: o/r#5 risk: y')"
  printf 'pr-merged' > "$RR/state.2"
  eq_ust "$sh_: a cached state is reused within the TTL" waiting "$(rr 'x until: o/r#2 risk: y')"
  rr 'x until: o/r#5 risk: y' >/dev/null
  eq_ust "$sh_: gh asked once per ref, failures not cached" '1 2 3 4 5 5' "$(tr '\n' ' ' < "$RR/gh.log" | sed 's/ $//')"
  : > "$RR/gh.log"
  eq_ust "$sh_: cache-only takes a stale entry" waiting \
    "$(RULING_REF_TTL=0 RULING_REF_CACHE_ONLY=1 rr 'x until: o/r#2 risk: y')"
  eq_ust "$sh_: cache-only, no entry, ready"    ready   "$(RULING_REF_CACHE_ONLY=1 rr 'x until: o/r#6 risk: y')"
  eq_ust "$sh_: cache-only never calls gh"      ''      "$(cat "$RR/gh.log")"
  eq_ust "$sh_: past the TTL gh is asked again" ready   "$(RULING_REF_TTL=0 rr 'x until: o/r#2 risk: y')"
  rm -f "$RR"/state.*
done

# --- state_shard_path: per-session files split by the id's first two chars ---
SH="$SCRATCH/shard"; mkdir -p "$SH"
shp() { bash -c '. "$0/lib-state.sh"; state_shard_path "$@"' "$HOOKS" "$@"; }
eq_ust 'shard: a new file goes under the first two chars of the id' \
  "$SH/3f/3fa9-01.json" "$(shp "$SH" 3fa9-01.json 3fa9-01)"
eq_ust 'shard: the name need not start with the id' \
  "$SH/3f/2026-01-02-repo-3fa9.md" "$(shp "$SH" 2026-01-02-repo-3fa9.md 3fa9-01)"
: > "$SH/3fa9-01.json"
eq_ust 'shard: a file still at the flat path is used where it is' \
  "$SH/3fa9-01.json" "$(shp "$SH" 3fa9-01.json 3fa9-01)"
eq_ust 'shard: an empty id goes under _, never the dir itself' \
  "$SH/_/x.json" "$(shp "$SH" x.json '')"

# --- dirty_paths: the state repo's own state/ is the hooks' to commit ------
SR="$SCRATCH/state-repo"; gitq "$SCRATCH" init -q -b main "$SR"
mkdir -p "$SR/state/global/metrics"; : > "$SR/README"
gitq "$SR" add README; gitq "$SR" commit -q -m init
: > "$SR/state/global/metrics/live.json"
dp() { CLAUDE_STATE_REPO="$SR" bash -c '. "$0/lib-state.sh"; dirty_paths "$1"' "$HOOKS" "$1"; }
eq_ust 'dirty_paths: hook-written state/ in the state repo is not dirt' '' "$(dp "$SR")"
: > "$SR/notes.txt"
eq_ust 'dirty_paths: anything else in the state repo still is' '?? notes.txt' "$(dp "$SR")"
mkdir -p "$WT/state"; : > "$WT/state/x"
eq_ust 'dirty_paths: state/ in any other repo still is' '?? state/' "$(dp "$WT")"
rm -rf "$WT/state"

# --- buffered_state names what the state repo has not committed yet ----------
bs() { CLAUDE_STATE_REPO="$SR" bash -c '. "$0/lib-state.sh"; buffered_state "$1"' "$HOOKS" "$1"; }
rm -f "$SR/notes.txt"
mkdir -p "$SR/state/global/pickup"; : > "$SR/state/global/pickup/h.md"
eq_ust 'buffered_state: names the hand-off, counts the metrics' \
  '→ buffered in the state repo, not committed yet (the next Stop commits it): pickup/h.md, + 1 metrics file' \
  "$(bs "$SR")"
rm -f "$SR/state/global/pickup/h.md"; : > "$SR/state/global/metrics/two.json"
eq_ust 'buffered_state: metrics alone are a count' \
  '→ buffered in the state repo, not committed yet (the next Stop commits it): + 2 metrics files' \
  "$(bs "$SR")"
mkdir -p "$WT/state"; : > "$WT/state/x"
eq_ust 'buffered_state: silent outside the state repo' '' "$(bs "$WT")"
rm -rf "$WT/state" "$SR/state/global/metrics/two.json" "$SR/state/global/pickup"
gitq "$SR" add state/; gitq "$SR" commit -q -m state
eq_ust 'buffered_state: silent when state/ is committed' '' "$(bs "$SR")"

# --- verdict_explain names the dirty files when given the tree ---------------
ve() { CLAUDE_STATE_REPO="$SR" bash -c '. "$0/lib-state.sh"; verdict_explain "$@"' "$HOOKS" "$@"; }
: > "$WT/a"; : > "$WT/b"; : > "$WT/c"; : > "$WT/d"
eq_ust 'verdict_explain: names three files and counts the rest' \
  '→ worktree dirty: 4 uncommitted file(s) (a, b, c, +1 more). Normal mid-task: the agent commits them when the work lands. Archive the worktree only after that.' \
  "$(ve 'not archivable: worktree dirty' "$WT")"
rm -f "$WT/a" "$WT/b" "$WT/c" "$WT/d"
: > "$WT/my file"
eq_ust 'verdict_explain: a name with a space prints unquoted' \
  '→ worktree dirty: 1 uncommitted file(s) (my file). Normal mid-task: the agent commits them when the work lands. Archive the worktree only after that.' \
  "$(ve 'not archivable: worktree dirty' "$WT")"
rm -f "$WT/my file"
eq_ust 'verdict_explain: without the tree, no file list' \
  '→ worktree dirty: uncommitted files in this worktree. Normal mid-task: the agent commits them when the work lands. Archive the worktree only after that.' \
  "$(ve 'not archivable: worktree dirty')"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
