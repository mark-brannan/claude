#!/usr/bin/env bash
# Tests for pickup-list. Run: bash bin/pickup-list.test.sh
# What matters: newest is on top and --oldest reverses it; a taken item
# leaves the default view but stays findable, and takes its same-link
# siblings with it; the docket count reads the
# human-ruling items and nothing else; nothing is ever dropped for
# being uncheckable.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"
PL="$(cd "$(dirname "$0")" && pwd)/pickup-list"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
SR="$S/state"; PICKUP="$SR/state/global/pickup"; mkdir -p "$SR/.git" "$PICKUP"
export CLAUDE_STATE_REPO="$SR"

assert() { local m=$1; shift; if "$@"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $m"; fi; }
eq() { assert "$1: expected [$2], got [$3]" test "$2" = "$3"; }
item() {  # item <id> <updated> <status> <text>
  printf 'status: %s\nupdated: %s\nsession: x\nmodel: claude-sonnet-5\nbranch: r b (1 ahead, clean)\npr: none\nwhere: w\nprompt: %s\n---\n%s\n' \
    "$3" "$2" "$4" "$4" > "$PICKUP/$1.md"
}
ids() { sh "$PL" "$@" | grep -oE '^ +[0-9]{4}-[0-9-]+T[0-9-]+-[0-9a-f]+$' | tr -d ' '; }

eq 'an empty dir says so' 'Pickup: none' "$(sh "$PL")"

item 2026-09-01T10-00-aaaaaaaa 2026-09-01T10:00:00Z open "oldest work"
item 2026-09-02T10-00-bbbbbbbb 2026-09-02T10:00:00Z open "middle work"
item 2026-09-03T10-00-deadbeef 2026-09-03T10:00:00Z open "newest work"
eq 'newest first' '2026-09-03T10-00-deadbeef' "$(ids | head -1)"
eq '--oldest reverses' '2026-09-01T10-00-aaaaaaaa' "$(ids --oldest | head -1)"

sh "$PL" take 2026-09-02T10-00-bbbbbbbb >/dev/null
eq 'taken leaves the default view' '' "$(ids | grep bbbbbbbb || true)"
eq 'taken is still there with --closed' '2026-09-02T10-00-bbbbbbbb' "$(ids --closed | grep bbbbbbbb)"
eq 'taken is findable' '2026-09-02T10-00-bbbbbbbb' "$(ids find middle)"
eq 'status is written' taken "$(sed -n 's/^status: //p' "$PICKUP/2026-09-02T10-00-bbbbbbbb.md")"
sh "$PL" open 2026-09-02T10-00-bbbbbbbb >/dev/null
eq 'open puts it back' '2026-09-02T10-00-bbbbbbbb' "$(ids | grep bbbbbbbb)"
assert 'take of a missing id fails' bash -c "! sh '$PL' take nope 2>/dev/null"

# Taking one hand-off takes every open item naming the same link -- the
# body's link:, else the header's pr: -- so a second session cannot pick the
# same work up (card 179093046079e60170). Others, and closed ones, stay put.
L=https://github.com/o/r/pull/7
item 2026-09-04T10-00-11111111 2026-09-04T10:00:00Z open "link one"; printf 'link: %s\n' "$L" >> "$PICKUP/2026-09-04T10-00-11111111.md"
item 2026-09-04T11-00-22222222 2026-09-04T11:00:00Z open "link two"; sed -i "s|^pr: none|pr: $L|" "$PICKUP/2026-09-04T11-00-22222222.md"
item 2026-09-04T12-00-33333333 2026-09-04T12:00:00Z "done" "link done"; printf 'link: %s\n' "$L" >> "$PICKUP/2026-09-04T12-00-33333333.md"
item 2026-09-04T13-00-44444444 2026-09-04T13:00:00Z open "other link"; printf 'link: %s0\n' "$L" >> "$PICKUP/2026-09-04T13-00-44444444.md"
item 2026-09-04T14-00-55555555 2026-09-04T14:00:00Z open "my own"; printf 'link: %s\n' "$L" >> "$PICKUP/2026-09-04T14-00-55555555.md"
out=$(CLAUDE_CODE_SESSION_ID=55555555-0000 sh "$PL" take 2026-09-04T10-00-11111111)
assert 'take names the same-link item it also took' bash -c "printf '%s' '$out' | grep -qx 'taken 2026-09-04T11-00-22222222 (same link)'"
st() { sed -n 's/^status: //p' "$PICKUP/$1.md"; }
eq 'the same-link item (via pr:) is taken' taken "$(st 2026-09-04T11-00-22222222)"
eq 'a done same-link item stays done' "done" "$(st 2026-09-04T12-00-33333333)"
eq 'a different link is untouched' open "$(st 2026-09-04T13-00-44444444)"
eq "the taker's own same-link item stays open" open "$(st 2026-09-04T14-00-55555555)"
eq 'an item with no link takes only itself' 'taken 2026-09-01T10-00-aaaaaaaa' "$(sh "$PL" take 2026-09-01T10-00-aaaaaaaa)"
eq 'and its linkless neighbours stay open' open "$(st 2026-09-03T10-00-deadbeef)"
eq 'open releases only the one item' 'open 2026-09-04T10-00-11111111' "$(sh "$PL" open 2026-09-04T10-00-11111111)"
eq 'its sibling stays taken' taken "$(st 2026-09-04T11-00-22222222)"
rm -f "$PICKUP"/2026-09-04T1*.md
sh "$PL" open 2026-09-01T10-00-aaaaaaaa >/dev/null

for i in 1 2 3 4 5 6; do item "2026-09-1${i}T10-00-cccccc0$i" "2026-09-1${i}T10:00:00Z" open "filler $i"; done
eq 'default shows five' 5 "$(ids | wc -l | tr -d ' ')"
assert 'and says how many more' bash -c "sh '$PL' | grep -q ' more '"
eq '--all shows every open item' 9 "$(ids --all | wc -l | tr -d ' ')"
assert 'show prints the file' bash -c "sh '$PL' show 2026-09-03T10-00-deadbeef | grep -q '^prompt: newest work'"
printf 'status: open\nupdated: 2026-09-20T10:00:00Z\nsession: x\nmodel: m\nbranch: b\npr: none\nwhere: w\nuntil: 2026-10-15\nprompt: waits\n---\nwaits\n' > "$PICKUP/2026-09-20T10-00-0a0a0a0a.md"
assert 'show prints until:' bash -c "sh '$PL' show 2026-09-20T10-00-0a0a0a0a | grep -qx 'until: 2026-10-15'"
rm -f "$PICKUP/2026-09-20T10-00-0a0a0a0a.md"
assert 'show of a missing id fails' bash -c "! sh '$PL' show nope 2>/dev/null"

# --- work items are the cards ---------------------------------------------------
# items/ is the only source of cards: kanban.md is never read. The docket is
# the human-ruling items, nothing else; an agent item is a pickup candidate;
# take and open run through work-item claim/release, so the claim lands in
# the item's own log.
export TMPDIR="$S/tmp"; mkdir -p "$TMPDIR"
unset CI GITHUB_ACTIONS
I="$SR/state/global/items"
witem() { # id title owner status [brief]
  mkdir -p "$I"
  printf '# %s\n\n## Brief\n%s\n\n## Log\n2026-10-03T05:00:00Z 1d68120b status=open owner=%s repo=o/r parent=- model=opus effort=high\n2026-10-03T05:00:00Z 1d68120b status=%s\n' \
    "$2" "${5:-Do it.}" "$3" "$4" > "$I/$1.md"
}
assert 'no store, no docket line' bash -c "! sh '$PL' | grep -q '^Docket:'"
mkdir -p "$SR/state/global"
printf '# Board\n\n## Needs ruling\n\n- [ ] a card on the old board\n\n## Claude'"'"'s\n\n- [ ] **Old card** -- id: 1790836849aaaaaaaa\n' > "$SR/state/global/kanban.md"
assert 'a kanban.md is not read for the docket' bash -c "! sh '$PL' | grep -q '^Docket:'"
assert 'nor for pickup candidates' bash -c "! sh '$PL' --all | grep -q 'Old card'"
rm "$SR/state/global/kanban.md"

witem 1790836850aaaaaaaa 'Stored task' agent ready 'Do it ([x](https://example.invalid/card-1)).'
witem 1790836851aaaaaaaa 'Stored ruling' human-ruling ready
witem 1790836852aaaaaaaa 'Second ruling' human-ruling open
witem 1790836853aaaaaaaa 'Click work' human-click ready
witem 1790836854aaaaaaaa 'Not yet' agent open
assert 'an agent item is a pickup candidate' bash -c "sh '$PL' --all | grep -q '◆ Stored task'"
assert 'with its id beneath' bash -c "sh '$PL' --all | grep -q '^    1790836850aaaaaaaa$'"
assert 'an open (not ready) item is not a candidate' bash -c "! sh '$PL' --all | grep -q 'Not yet'"
assert 'a ruling is not a pickup candidate' bash -c "! sh '$PL' --all | grep -q 'Stored ruling'"
assert 'the docket counts the human-ruling items, not click work' bash -c "sh '$PL' | grep -q '^Docket: 2 awaiting an agora'"
assert 'take needs a session id' bash -c "! CLAUDE_CODE_SESSION_ID= sh '$PL' take 1790836850aaaaaaaa 2>/dev/null"
eq 'take on an item claims it through work-item' 'taken 1790836850aaaaaaaa' "$(sh "$PL" take 1790836850aaaaaaaa 1111111122223333)"
eq 'the claim is in the item log' 'status=claimed' "$(tail -1 "$I/1790836850aaaaaaaa.md" | cut -d' ' -f3)"
eq 'a taken item leaves the default view' '' "$(sh "$PL" --all | grep 'Stored task' || true)"
assert 'and shows its holder with --closed' bash -c "sh '$PL' --closed | grep 'Stored task' -A0 | grep -q 'taken by 11111111'"
assert 'a second session cannot take it' bash -c "! sh '$PL' take 1790836850aaaaaaaa 4444444455556666 2>/dev/null"
assert 'done refuses an item' bash -c "! sh '$PL' done 1790836850aaaaaaaa 2>/dev/null"
eq 'its holder opens it again' 'open 1790836850aaaaaaaa' "$(sh "$PL" open 1790836850aaaaaaaa 1111111122223333)"
assert 'and it is back in the view' bash -c "sh '$PL' --all | grep -q 'Stored task'"
assert 'a ruling item cannot be taken' bash -c "! sh '$PL' take 1790836851aaaaaaaa 1111111122223333 2>/dev/null"
assert 'a not-ready item cannot be taken' bash -c "! sh '$PL' take 1790836854aaaaaaaa 1111111122223333 2>/dev/null"
assert 'show reaches a ruling item' bash -c "sh '$PL' show 1790836851aaaaaaaa | grep -q 'Stored ruling'"
assert 'show reaches click work' bash -c "sh '$PL' show 1790836853aaaaaaaa | grep -q 'Click work'"
assert 'show of an unknown item fails' bash -c "! sh '$PL' show 1790836859aaaaaaaa 2>/dev/null"

# A store that cannot be read is named and exits 1, never "Pickup: none"
# (card 179101773919cb0a62). The pickup items themselves still list.
mkdir -p "$S/fakebin"; printf '#!/bin/sh\necho "python exploded" >&2\nexit 4\n' > "$S/fakebin/python3"; chmod +x "$S/fakebin/python3"
out=$(PATH="$S/fakebin:$PATH" sh "$PL" --all); rc=$?
eq 'a broken store exits 1' 1 "$rc"
assert 'and names the cause' bash -c "printf '%s' '$out' | grep -q 'Pickup: BROKEN STORE -- work-item list failed (exit 4): python exploded'"
assert 'and still lists the pickup items' bash -c "printf '%s' '$out' | grep -q 'newest work'"
assert 'show on a broken store names it, not "no item"' bash -c "PATH='$S/fakebin:$PATH' sh '$PL' show 1790836851aaaaaaaa 2>&1 >/dev/null | grep -q 'pickup-list show: BROKEN STORE -- work-item list failed (exit 4)'"
assert 'and fails' bash -c "! PATH='$S/fakebin:$PATH' sh '$PL' show 1790836851aaaaaaaa 2>/dev/null"
rm -rf "$I"
out=$(PATH="$S/fakebin:$PATH" sh "$PL" --all); rc=$?
eq 'no items/ at all is not a broken store' 0 "$rc"
assert 'and prints no error' bash -c "! printf '%s' '$out' | grep -q BROKEN"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
