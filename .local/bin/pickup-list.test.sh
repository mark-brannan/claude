#!/usr/bin/env bash
# Tests for pickup-list. Run: bash .local/bin/pickup-list.test.sh
# What matters: newest is on top and --oldest reverses it; a taken item
# leaves the default view but stays findable; the docket count reads the
# board's `## Needs ruling` and nothing else; nothing is ever dropped for
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

for i in 1 2 3 4 5 6; do item "2026-09-1${i}T10-00-cccccc0$i" "2026-09-1${i}T10:00:00Z" open "filler $i"; done
eq 'default shows five' 5 "$(ids | wc -l | tr -d ' ')"
assert 'and says how many more' bash -c "sh '$PL' | grep -q ' more '"
eq '--all shows every open item' 9 "$(ids --all | wc -l | tr -d ' ')"
assert 'show prints the file' bash -c "sh '$PL' show 2026-09-03T10-00-deadbeef | grep -q '^prompt: newest work'"
printf 'status: open\nupdated: 2026-09-20T10:00:00Z\nsession: x\nmodel: m\nbranch: b\npr: none\nwhere: w\nuntil: 2026-10-15\nprompt: waits\n---\nwaits\n' > "$PICKUP/2026-09-20T10-00-0a0a0a0a.md"
assert 'show prints until:' bash -c "sh '$PL' show 2026-09-20T10-00-0a0a0a0a | grep -qx 'until: 2026-10-15'"
rm -f "$PICKUP/2026-09-20T10-00-0a0a0a0a.md"
assert 'show of a missing id fails' bash -c "! sh '$PL' show nope 2>/dev/null"

# The docket count is the board's `## Needs ruling` open boxes, nothing else.
cat > "$SR/state/global/kanban.md" <<'EOF'
# Board

## Needs ruling

- [ ] one question
- [x] a ruled one
- [ ] another question

## Human's

- [ ] click work does not count
EOF
assert 'the docket counts open Needs-ruling boxes' bash -c "sh '$PL' | grep -q '^Docket: 2 awaiting an agora'"
rm "$SR/state/global/kanban.md"
assert 'no board, no docket line' bash -c "! sh '$PL' | grep -q '^Docket:'"

# --- cards on the board's `## Claude's` are pickup items too -----------------
# An example.invalid link is no GitHub card, so a take is the ledger alone -- the part a
# second run reads.
export TMPDIR="$S/tmp"; mkdir -p "$TMPDIR"
unset CI GITHUB_ACTIONS
CARD=https://example.invalid/card-1
cat > "$SR/state/global/kanban.md" <<EOF
# Board

## Needs ruling

### global
- [ ] a ruling ([x](https://example.invalid/ruling)) default: a undo: b until: c risk: d judgment: values

## Claude's

- [ ] **Card one** -- a card a session can take ([x]($CARD)) model: opus effort: high
EOF
assert 'a card is listed with pickup items' bash -c "sh '$PL' --all | grep -qxF '    $CARD'"
assert 'a ruling is not a pickup candidate' bash -c "! sh '$PL' --all | grep -q 'example.invalid/ruling'"
assert 'nor can it be taken' bash -c "! sh '$PL' take https://example.invalid/ruling 1111111122223333 2>/dev/null"
assert 'take of a card needs a session id' bash -c "! CLAUDE_CODE_SESSION_ID= sh '$PL' take '$CARD' 2>/dev/null"
eq 'take on a card claims it' "taken $CARD" "$(sh "$PL" take "$CARD" 1111111122223333)"
eq 'a second run sees it taken' '' "$(sh "$PL" --all | grep -F "$CARD" || true)"
assert 'and shows the holder with --closed' bash -c "sh '$PL' --closed | grep -q 'taken by 11111111'"
assert 'a second session cannot take it' bash -c "! sh '$PL' take '$CARD' 4444444455556666 2>/dev/null"
assert 'done refuses a card' bash -c "! sh '$PL' done '$CARD' 2>/dev/null"
sh "$PL" open "$CARD" >/dev/null
assert 'open releases it' bash -c "sh '$PL' --all | grep -qxF '    $CARD'"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
