#!/usr/bin/env bash
# metrics-format.sh's fields, and a byte-for-byte parity check against the
# lib-metrics-fmt.jq defs they are taking over from (dotfiles#149 step 7).
# Parity is the whole point: the move out of jq must not change one glyph of
# what is on screen, and this is what says so.
#
# Run: bash .claude/hooks/metrics-format.test.sh
set -uo pipefail
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=metrics-format.sh
. "$HOOK_DIR/metrics-format.sh"

fail=0
eq() { # label expected actual
  if [ "$2" = "$3" ]; then printf 'ok   %s\n' "$1"
  else fail=1; printf 'FAIL %s\n  expected [%s]\n  actual   [%s]\n' "$1" "$2" "$3"; fi
}

eq "turns" '⇢ 3 ⚙ 41' "$(fmt_turns 3 41)"
eq "turns: zeros still print" '⇢ 0 ⚙ 0' "$(fmt_turns 0 0)"
eq "turns: missing args default to 0" '⇢ 0 ⚙ 0' "$(fmt_turns)"
eq "work: clean tree is empty" '' "$(fmt_work 0 0 0)"
eq "work: dirty only" '⎇ 1~' "$(fmt_work 0 1 0)"
eq "work: commits only" '⎇ 2c' "$(fmt_work 2 0 0)"
eq "work: unpushed warns" '⎇ 3↑unpushed  ← not safe to kill' "$(fmt_work 0 0 3)"
eq "work: all three" '⎇ 2c1~3↑unpushed  ← not safe to kill' "$(fmt_work 2 1 3)"

# fmt_work returns 0 on a clean tree: under `set -e` in a caller, a field
# with nothing to say must not read as a failure.
fmt_work 0 0 0 >/dev/null
eq "work: clean tree exits 0" 0 "$?"

# Parity. Each case is one live-metrics cache shape; the jq defs and the
# printf functions are handed the same numbers and must agree exactly.
if command -v jq >/dev/null 2>&1; then
  for c in '0 0 0 0 0' '3 41 0 1 0' '7 42 2 1 3' '1 59 5 0 0' '9 9 0 0 4'; do
    # shellcheck disable=SC2086
    set -- $c
    j=$(printf '{"user_turns":%s,"tool_calls":%s,"commits":%s,"dirty":%s,"unpushed":%s}\n' \
          "$1" "$2" "$3" "$4" "$5" \
        | jq -r -L "$HOOK_DIR" 'include "lib-metrics-fmt";
            turns + ((work // "") as $w | if $w == "" then "" else " " + $w end)')
    s=$(fmt_turns "$1" "$2")
    w=$(fmt_work "$3" "$4" "$5")
    [ -n "$w" ] && s="$s $w"
    eq "parity [$c]" "$j" "$s"
  done
else
  printf 'skip parity: no jq\n'
fi

[ "$fail" -eq 0 ] && printf '\nall passed\n'
exit "$fail"
