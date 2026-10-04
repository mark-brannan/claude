#!/usr/bin/env bash
# Tests for card-id. Run: bash bin/card-id.test.sh
# What matters: an id is epoch seconds then the session's eight hex, minted
# with nothing consulted; show resolves an item's id from any section and nothing else.
set -uo pipefail
CID="$(cd "$(dirname "$0")" && pwd)/card-id"
pass=0; fail=0
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
unset CLAUDE_CODE_SESSION_ID
export WORK_ITEM_DIR="$T/items"
ok() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }

now=$(date -u +%s)
a=$(sh "$CID" new 077c62eb-2979-4277-b798-0d0fd9e9bb8d); ok 'epoch seconds then the session hex' 1 "$(printf '%s' "$a" | grep -cE "^(${now}|$((now + 1)))077c62eb$")"
b=$(sh "$CID" new 077C62EB); ok 'the hex is lowercased' 077c62eb "${b#??????????}"
c=$(CLAUDE_CODE_SESSION_ID=d654192b-0000 sh "$CID" new); ok 'the session comes from the environment' d654192b "${c#??????????}"
ok 'no store is needed to make one' 18 "${#a}"
sh "$CID" new "" >/dev/null 2>&1; ok 'no session id refuses' 2 $?
sh "$CID" new zzzzzzzz >/dev/null 2>&1; ok 'a non-hex session refuses' 2 $?

mkdir -p "$T/items"
witem() { # id owner title brief
  printf '# %s\n\n## Brief\n%s\n\n## Log\n2026-10-03T05:00:00Z 1d68120b status=open owner=%s repo=o/global parent=- model=- effort=-\n2026-10-03T05:00:00Z 1d68120b status=ready\n' \
    "$3" "$4" "$2" > "$T/items/$1.md"
}
witem 1790000000aaaaaaaa agent Do 'Do it.'
witem 1790000000077c62eb human-ruling Q 'Ask.'
witem 1790000001aaaaaaaa human-click Stored 'Do it.'
ok 'show finds an agent item in its section' "Claude's" "$(sh "$CID" show 1790000000aaaaaaaa | cut -f1)"
ok 'show finds a ruling with its repo as the group' "global" "$(sh "$CID" show 1790000000077c62eb | cut -f2)"
ok 'show finds a click item in its owner'"'"'s section' "Human's" "$(sh "$CID" show 1790000001aaaaaaaa | cut -f1)"
ok 'show prints the item as a card' '- [ ] **Stored**: Do it. repo: o/global id: 1790000001aaaaaaaa' "$(sh "$CID" show 1790000001aaaaaaaa | cut -f3)"
sh "$CID" show 1790000000aaaaaaab >/dev/null 2>&1; ok 'an unknown id is not found' 1 $?
sh "$CID" show 179000000 >/dev/null 2>&1; ok 'a malformed id is refused' 2 $?
rm -rf "$T/items"
sh "$CID" show 1790000000aaaaaaaa >/dev/null 2>&1; ok 'no store, no item' 1 $?
printf '## Claude'"'"'s\n- [ ] **Old** id: 1790000000aaaaaaaa\n' > "$T/kanban.md"
sh "$CID" show 1790000000aaaaaaaa >/dev/null 2>&1; ok 'a kanban.md is not read' 1 $?

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
