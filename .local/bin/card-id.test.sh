#!/usr/bin/env bash
# Tests for card-id. Run: bash .local/bin/card-id.test.sh
# What matters: an id is epoch seconds then the session's eight hex, minted
# with nothing consulted; show resolves an id from any section and nothing else.
set -uo pipefail
CID="$(cd "$(dirname "$0")" && pwd)/card-id"
pass=0; fail=0
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
unset CLAUDE_CODE_SESSION_ID
export CARD_ID_BOARD="$T/kanban.md"
ok() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }

now=$(date -u +%s)
a=$(sh "$CID" mint 077c62eb-2979-4277-b798-0d0fd9e9bb8d); ok 'epoch seconds then the session hex' 1 "$(printf '%s' "$a" | grep -cE "^(${now}|$((now + 1)))077c62eb$")"
b=$(sh "$CID" mint 077C62EB); ok 'the hex is lowercased' 077c62eb "${b#??????????}"
c=$(CLAUDE_CODE_SESSION_ID=d654192b-0000 sh "$CID" mint); ok 'the session comes from the environment' d654192b "${c#??????????}"
ok 'no board is needed to mint' 18 "${#a}"
sh "$CID" mint "" >/dev/null 2>&1; ok 'no session id refuses' 2 $?
sh "$CID" mint zzzzzzzz >/dev/null 2>&1; ok 'a non-hex session refuses' 2 $?

printf '## Needs ruling\n### global\n- [ ] **Q** -- ask ([l](https://x.invalid/q)) id: 1790000000077c62eb\n\n## Claude'"'"'s\n- [ ] **Do** -- it\n      ([l](https://x.invalid/d)) id: 1790000000aaaaaaaa\n' > "$CARD_ID_BOARD"
ok 'show finds a folded card with its section' "Claude's" "$(sh "$CID" show 1790000000aaaaaaaa | cut -f1)"
ok 'show finds a ruling with its group' "global" "$(sh "$CID" show 1790000000077c62eb | cut -f2)"
sh "$CID" show 1790000000aaaaaaab >/dev/null 2>&1; ok 'an unknown id is not found' 1 $?
sh "$CID" show 179000000 >/dev/null 2>&1; ok 'a malformed id is refused' 2 $?

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
