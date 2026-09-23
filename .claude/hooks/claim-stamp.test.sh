#!/usr/bin/env bash
# Tests for claim-stamp.sh. Run: bash .claude/hooks/claim-stamp.test.sh
# Set AWK_PATH to a directory whose `awk` is another implementation to run the
# same cases under it; CI does this for each.
#
# `gh` is stubbed throughout, backed by a comment store on disk, so the tests
# exercise the real post/patch/delete sequencing without ever reaching GitHub.
# What matters: a claim writes exactly one stamp and patches it rather than
# posting a second; a second session is warned by name and age; a stale stamp
# is collected; release removes the label only when no stamp is left; and
# refresh is free -- no network at all -- when this session claimed nothing.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

HOOKS="$(cd "$(dirname "$0")" && pwd)"
CS="$HOOKS/claim-stamp.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export CLAUDE_STATE_REPO="$SCRATCH/nostate"
# The hook refuses to run under CI, and this suite runs under CI: clear the
# ambient signal so only the one case that sets it on purpose sees it.
unset CI GITHUB_ACTIONS

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# --- the gh stub: a comment store, not a canned answer ------------------------
# read_stamps pipes the comment list through `--jq`, and post reads its body
# from `--input -`, so a stub that only echoed fixtures would test none of the
# sequencing. This one keeps one file per comment and serves them back.
STORE="$SCRATCH/store"; mkdir -p "$STORE/comments"
export CLAIM_STORE="$STORE"
BIN="$SCRATCH/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'STUB'
#!/bin/sh
S=${CLAIM_STORE:?}
printf '%s\n' "$*" >> "$S/calls"
[ "${GH_FAIL:-0}" = 1 ] && exit 1
[ "${GH_FAIL_API:-0}" = 1 ] && [ "$1" = api ] && exit 1
case "$1" in
  pr) case " $* " in
        *" --head "*) printf '%s\n' "${GH_PRS:-[]}" ;;
        *)            printf '%s\n' "${GH_PRS_ALL:-[]}" ;;
      esac; exit 0 ;;
  issue) printf '%s\n' "${GH_ISSUES:-[]}"; exit 0 ;;
  api) shift ;;
  *) exit 1 ;;
esac
method=GET; path=; jqprog=
while [ $# -gt 0 ]; do
  case "$1" in
    -X) method=$2; shift 2 ;;
    --jq) jqprog=$2; shift 2 ;;
    --input) shift 2 ;;
    --paginate) shift ;;
    -f) printf '%s\n' "$2" >> "$S/labels"; shift 2 ;;
    *) path=$1; shift ;;
  esac
done
emit() { if [ -n "$jqprog" ]; then printf '%s' "$1" | jq -r "$jqprog"; else printf '%s' "$1"; fi; }
case "$method $path" in
  "GET "*/comments)
    emit "$(cat "$S"/comments/*.json 2>/dev/null | jq -s '.')" ;;
  "POST "*/comments)
    n=$(( $(cat "$S/next" 2>/dev/null || echo 100) + 1 )); printf '%s' "$n" > "$S/next"
    jq --argjson id "$n" '{id: $id, body: .body}' > "$S/comments/$n.json"
    emit "$(cat "$S/comments/$n.json")" ;;
  "PATCH "*/issues/comments/*)
    id=${path##*/}
    [ -f "$S/comments/$id.json" ] || exit 1
    jq --argjson id "$id" '{id: $id, body: .body}' > "$S/comments/$id.json.new"
    mv "$S/comments/$id.json.new" "$S/comments/$id.json"
    emit "$(cat "$S/comments/$id.json")" ;;
  "DELETE "*/issues/comments/*)
    id=${path##*/}; rm -f "$S/comments/$id.json" ;;
  "DELETE "*/labels/*)
    printf 'removed %s\n' "${path##*/}" >> "$S/labels" ;;
  *) exit 1 ;;
esac
STUB
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH"

# --- the repo under test ------------------------------------------------------
ORIGIN="$SCRATCH/origin.git"; WORK="$SCRATCH/work"
setup_repo() {  # setup_repo <branch|"">
  rm -rf "$ORIGIN" "$WORK"
  git init -q --bare -b main "$ORIGIN"
  git init -q -b main "$WORK"
  gitq "$WORK" remote add origin "$ORIGIN"
  echo one > "$WORK/f"; gitq "$WORK" add -- f; gitq "$WORK" commit -m one
  gitq "$WORK" push -u origin main
  [ -n "${1:-}" ] || return 0
  gitq "$WORK" checkout -b "$1"
  echo two > "$WORK/g"; gitq "$WORK" add -- g; gitq "$WORK" commit -m two
  gitq "$WORK" push -u origin "$1"
}

reset_store() { rm -rf "$STORE"; mkdir -p "$STORE/comments"; : > "$STORE/calls"; : > "$STORE/labels"; }
rec_for() { printf '%s/claude-claim-stamp.%s' "$TMPDIR" "$(printf '%s' "$1" | tr -c 'A-Za-z0-9_-' '_')"; }
bodies() { cat "$STORE"/comments/*.json 2>/dev/null | jq -r '.body'; }
ncomments() { ls "$STORE"/comments/*.json 2>/dev/null | wc -l | tr -d ' '; }
ncalls() { grep -c . "$STORE/calls" 2>/dev/null || true; }   # grep prints 0 itself

ok()   { if "${@:2}"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n' "$1"; fi; }
eq()   { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s (want %s, got %s)\n' "$1" "$3" "$2"; fi; }
has()  { if grep -Eq -- "$3" <<<"$2"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s (no /%s/ in): %s\n' "$1" "$3" "$2"; fi; }
hasnt(){ if grep -Eq -- "$3" <<<"$2"; then fail=$((fail+1)); printf 'FAIL: %s (unwanted /%s/ in): %s\n' "$1" "$3" "$2"; else pass=$((pass+1)); fi; }

export GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]'

# --- a claim on a branch whose card is a PR -----------------------------------
setup_repo claude/claimed
reset_store
out=$(sh "$CS" claim -C "$WORK" aaaaaaaa11112222)
eq  'one stamp is posted'                "$(ncomments)" 1
has 'the stamp names the session'        "$(bodies)" 'sid=aaaaaaaa'
has 'the stamp names the branch'         "$(bodies)" 'claude/claimed'
has 'the stamp carries an epoch'         "$(bodies)" 'epoch=[0-9]{10}'
has 'the machine is a hash, not a name'  "$(bodies)" 'machine=host-'
hasnt 'and not the real hostname'        "$(bodies)" "$(hostname 2>/dev/null || echo __nohost__)"
eq  'an uncontested claim says nothing'  "$out" ''
has 'the label is added'                 "$(cat "$STORE/labels")" 'labels\[\]=claimed'
ok  'a record is written'                test -f "$(rec_for aaaaaaaa11112222)"

# Re-claiming from the same session patches; it must never leave a trail.
sh "$CS" claim -C "$WORK" aaaaaaaa11112222 >/dev/null
eq  'the same session patches its stamp' "$(ncomments)" 1

# --- a second session is warned, by name and by age ---------------------------
out=$(sh "$CS" claim -C "$WORK" bbbbbbbb33334444)
has 'the second session is warned'       "$out" 'session `aaaaaaaa`'
has 'the warning gives an age'           "$out" 'minute\(s\) ago'
has 'the warning names the branch'       "$out" 'claude/claimed'
eq  'and it stamps too -- both are real' "$(ncomments)" 2

# --- release ------------------------------------------------------------------
: > "$STORE/labels"
sh "$CS" release -C "$WORK" bbbbbbbb33334444
eq  'release deletes its own stamp'      "$(ncomments)" 1
has 'the survivor is the other session'  "$(bodies)" 'sid=aaaaaaaa'
eq  'the label stays while a stamp does' "$(cat "$STORE/labels")" ''
ok  'the record is gone'                 test ! -f "$(rec_for bbbbbbbb33334444)"

sh "$CS" release -C "$WORK" aaaaaaaa11112222
eq  'the last release clears the card'   "$(ncomments)" 0
has 'and only then removes the label'    "$(cat "$STORE/labels")" 'removed claimed'

# --- a stale stamp is collected, not warned about -----------------------------
reset_store
printf '{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=1 machine=host-000000 -->"}' \
  > "$STORE/comments/1.json"
out=$(sh "$CS" claim -C "$WORK" ccccccccc5556666)
eq  'the stale stamp is deleted'         "$(ncomments)" 1
has 'the survivor is the new claim'      "$(bodies)" 'sid=cccccccc'
eq  'a stale holder is not warned about' "$out" ''

# A stamp just inside the threshold is a live claim, not garbage.
reset_store
printf '{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=%s machine=host-000000 -->"}' \
  "$(( $(date -u +%s) - 60 ))" > "$STORE/comments/1.json"
out=$(sh "$CS" claim -C "$WORK" dddddddd77778888)
has 'a fresh holder is warned about'     "$out" 'session `deadbeef`'
eq  'and its stamp is left alone'        "$(ncomments)" 2

# CLAIM_STALE_SECS is a knob, not a constant -- the threshold is proposed,
# not ruled (dotfiles#287), so it has to be movable without an edit.
reset_store
printf '{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=%s machine=host-000000 -->"}' \
  "$(( $(date -u +%s) - 60 ))" > "$STORE/comments/1.json"
out=$(CLAIM_STALE_SECS=30 sh "$CS" claim -C "$WORK" eeeeeeee99990000)
eq  'a lower threshold collects it'      "$(ncomments)" 1

# --- refresh ------------------------------------------------------------------
reset_store
sh "$CS" claim -C "$WORK" ffffffffaaaabbbb >/dev/null
before=$(bodies)
: > "$STORE/calls"
sh "$CS" refresh -C "$WORK" ffffffffaaaabbbb
eq  'refresh inside the debounce is free' "$(ncalls)" 0
eq  'and changes nothing'                 "$(bodies)" "$before"

: > "$STORE/calls"
CLAIM_REFRESH_SECS=0 sh "$CS" refresh -C "$WORK" ffffffffaaaabbbb
ok  'past the debounce it patches'        test "$(ncalls)" -gt 0
eq  'still exactly one stamp'             "$(ncomments)" 1

: > "$STORE/calls"
sh "$CS" refresh -C "$WORK" 99999999ccccdddd
eq  'refresh without a record is free'    "$(ncalls)" 0

# --scan: releasing without a record. Off by default because the Stop hook
# releases on every archivable turn and must not pay a card lookup to learn
# that this session never claimed anything.
reset_store
printf '{"id":1,"body":"<!-- claim-stamp sid=abcd0000 epoch=%s machine=host-000000 -->"}' \
  "$(date -u +%s)" > "$STORE/comments/1.json"
: > "$STORE/calls"
sh "$CS" release -C "$WORK" abcd000012345678
eq  'release without a record is free'    "$(ncalls)" 0
eq  'and leaves the stamp alone'          "$(ncomments)" 1
sh "$CS" release -C "$WORK" --scan abcd000012345678
eq  '--scan finds it by its marker'       "$(ncomments)" 0

# --- a Stop release is provisional; the next working turn re-claims ------------
# Stop releases on every archivable turn. A session that then takes another
# turn is holding the branch again with no stamp to show it -- the exact
# blind spot this hook exists to close -- so refresh re-claims, once.
setup_repo claude/resumed
reset_store
sh "$CS" claim -C "$WORK" cafe0000aaaabbbb
sh "$CS" release -C "$WORK" cafe0000aaaabbbb
eq  'the Stop release deletes the stamp'   "$(ncomments)" 0
ok  'and leaves a tombstone'               test -f "$(rec_for cafe0000aaaabbbb).released"
: > "$STORE/calls"
sh "$CS" refresh -C "$WORK" cafe0000aaaabbbb
eq  'refresh after it re-claims'           "$(ncomments)" 1
ok  'the record is back'                   test -f "$(rec_for cafe0000aaaabbbb)"
ok  'the tombstone is gone'                test ! -f "$(rec_for cafe0000aaaabbbb).released"
sh "$CS" release -C "$WORK" --scan cafe0000aaaabbbb
eq  'a --scan release is final'            "$(ncomments)" 0
ok  'and leaves no tombstone'              test ! -f "$(rec_for cafe0000aaaabbbb).released"
: > "$STORE/calls"
sh "$CS" refresh -C "$WORK" cafe0000aaaabbbb
eq  'so the next refresh is free'          "$(ncalls)" 0

# --- nothing to claim ---------------------------------------------------------
reset_store
setup_repo ""                       # on main: no branch card, no lookup
sh "$CS" claim -C "$WORK" 11111111eeeeffff
eq  'the default branch is a no-op'       "$(ncomments)" 0
eq  'and costs no network'                "$(ncalls)" 0

setup_repo claude/uncarded
reset_store
GH_PRS='[]' GH_PRS_ALL='[]' GH_ISSUES='[]' sh "$CS" claim -C "$WORK" 22222222eeeeffff
eq  'a branch with no card is a no-op'    "$(ncomments)" 0

# --- it never runs under CI ---------------------------------------------------
setup_repo claude/ci
reset_store
GITHUB_ACTIONS=true sh "$CS" claim -C "$WORK" 33333333eeeeffff
eq  'GITHUB_ACTIONS stamps nothing'       "$(ncomments)" 0
CLAUDE_CLAIM_STAMP=off sh "$CS" claim -C "$WORK" 33333333eeeeffff
eq  'the off switch stamps nothing'       "$(ncomments)" 0

# --- it is a convenience, so it never fails -----------------------------------
# A PATH holding every tool the script needs except gh -- an empty PATH would
# only prove that `dirname` is missing.
NOGH="$SCRATCH/nogh"; mkdir -p "$NOGH"
for b in sh dash bash git jq sed grep tr head cat awk cut wc dirname basename \
         timeout rm mkdir env date mktemp hostname uname sha256sum ls printf; do
  p=$(command -v "$b" 2>/dev/null) && ln -sf "$p" "$NOGH/$b"
done

setup_repo claude/failing
reset_store
GH_FAIL=1 sh "$CS" claim -C "$WORK" 44444444eeeeffff; rc=$?
eq  'gh failing still exits 0'            "$rc" 0
PATH="$NOGH" /bin/sh "$CS" claim -C "$WORK" 55555555eeeeffff; rc=$?
eq  'no gh at all still exits 0'          "$rc" 0

# --- read ---------------------------------------------------------------------
setup_repo claude/readable
reset_store
sh "$CS" claim -C "$WORK" 66666666eeeeffff >/dev/null
printf '{"id":9,"body":"<!-- claim-stamp sid=deadbeef epoch=1 machine=host-000000 -->"}' \
  > "$STORE/comments/9.json"
out=$(sh "$CS" read -C "$WORK")
has 'read reports the live claim'         "$out" 'live.*66666666'
has 'read reports the stale one'          "$out" 'stale.*deadbeef'
out=$(GH_FAIL_API=1 sh "$CS" read -C "$WORK"; echo "rc=$?")
has 'a failed stamp read says unverified'  "$out" '^unverified: .*pull/7'
hasnt 'and reports no stamp as live'      "$out" 'live|stale'
has 'and still exits 0'                   "$out" 'rc=0'
out=$(GH_FAIL=1 sh "$CS" read -C "$WORK")
has 'a failed card lookup says unverified' "$out" '^unverified'
setup_repo main
eq  'a branch with no card says so'       "$(sh "$CS" read -C "$WORK")" 'no card'

# --- the SessionStart entry point ---------------------------------------------
setup_repo claude/session
reset_store
payload() { jq -n --arg s "$1" --arg c "$WORK" '{session_id:$s,cwd:$c,source:"startup"}'; }
out=$(payload 7777777700001111 | sh "$CS" session-start)
eq  'an uncontested start says nothing'   "$out" ''
eq  'but it still claims'                 "$(ncomments)" 1

out=$(payload 8888888800001111 | sh "$CS" session-start)
ok  'a contested start emits valid JSON'  test -n "$out"
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')
has 'addressed to SessionStart'  "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.hookEventName')" 'SessionStart'
has 'the context names the holder'        "$ctx" 'session `77777777`'
has 'and points at the card'              "$ctx" 'github.com/o/r/pull/7'

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
