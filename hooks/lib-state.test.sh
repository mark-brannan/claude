#!/usr/bin/env bash
# Tests for the lib-state.sh functions that have no Python twin: work_record
# and the work-item store, and ruling_readiness -- plus the shell-only mechanics of the
# functions that do: state_lock arming no trap of its own and leaking no
# age-reference file, and archivable_reasons handing its home line back
# through ARCHIVABLE_HOME_FILE.
#
# The ported functions' cases (state_repo, state_dir, state_shard_path, the
# locks, unpushed_state, dirty_paths, archivable_reasons, decision_rate) are
# lib/state.test.py's, and lib/state-parity.test.py holds this file's
# versions of them equal to lib/state.py's.
#
# Set AWK_PATH to a directory whose `awk` is another implementation (mawk,
# gawk, busybox) to run the awk-heavy readers under it.
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

# --- a fake HOOK_DIR: branch-home-gate.py always says "home" -----------------
FAKE="$SCRATCH/hooks"; mkdir -p "$FAKE"
cat > "$FAKE/branch-home-gate.py" <<'EOF'
print("home: pr https://github.com/o/r/pull/1")
EOF
chmod +x "$FAKE/branch-home-gate.py"

eq_ust() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $1: expected [$2], got [$3]"; fi; }


# --- state_lock: the shell-only mechanics --------------------------------------
LOCKDIR="$SCRATCH/x.lock"
CASE="$SCRATCH/case.sh"

lock_check() {  # lock_check <name> <script-body-file-already-written> <want-exit>
  name=$1; want=$2
  bash "$CASE" >/dev/null 2>&1; got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else
    fail=$((fail+1)); echo "FAIL $name: want exit $want, got $got"
  fi
}

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


# --- the home line comes back through a file, from inside $(...) ----------------
# Every caller captures archivable_reasons with $(...), so a variable it sets
# is lost; ARCHIVABLE_HOME_FILE is how a shell caller reuses the gh answer
# instead of asking again (PR #388, design pass). stop-continuity.py takes it
# from lib/state.py's archivable() return instead.
HF="$SCRATCH/home-line"
got=$(HOOK_DIR="$FAKE" ARCHIVABLE_HOME_FILE="$HF" bash -c '
  . "'"$HOOKS"'/lib-state.sh"
  r=$(archivable_reasons "'"$WT"'" feature abcd1234)
  printf "%s|%s" "$r" "$(cat "$ARCHIVABLE_HOME_FILE" 2>/dev/null)"')
if [ "$got" = "|home: pr https://github.com/o/r/pull/1" ]; then pass=$((pass+1))
else fail=$((fail+1)); echo "FAIL home line through file: got [$got]"; fi

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

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
