#!/bin/sh
# Blocks the end of a turn while the state repo's kanban.md carries an
# uncommitted change that breaks the board contract.
#
# Why: kanban-lint.sh already runs on every Edit/Write of a board, but a
# board can also change through a Bash heredoc, a sed, or a script, and
# stop-continuity.sh commits and pushes the state repo at every Stop. A bad
# card written at 23:59 is in git history by 00:00 with nobody having read
# it. So, in the pr-threads-gate.sh pattern, the turn is not allowed to end
# until the added lines pass the lint -- the same lint, --diff mode, so only
# what this session wrote is judged and history on the board is left alone.
#
# Blocks at most once per turn: the harness sets stop_hook_active on the
# retry, and a second block would only loop.
#
# GATE: no state repo here means nothing to gate (exit 0 -- a cloud session
# without the private clone is reported at SessionStart, not here). But a
# dirty board that cannot be linted -- kanban-lint.sh missing, awk gone,
# the lint itself failing -- blocks and says so. A gate that goes quiet
# when it cannot look is indistinguishable from one that looked and found
# nothing.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib-state.sh
. "$HERE/lib-state.sh"

# json_str() and block() come from lib-state.sh, sourced above.

payload=$(cat) || exit 0
if command -v jq >/dev/null 2>&1; then
  active=$(printf '%s' "$payload" | jq -r '.stop_hook_active // false' 2>/dev/null)
else
  active=false
  printf '%s' "$payload" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true' && active=true
fi
[ "$active" = true ] && exit 0

SR=$(state_repo) || exit 0
board=state/global/kanban.md
[ -n "$(git -C "$SR" status --porcelain -- "$board" 2>/dev/null)" ] || exit 0

LINT="$HERE/kanban-lint.sh"
[ -f "$LINT" ] || block "kanban-gate: $SR/$board has uncommitted changes and kanban-lint.sh is missing from $HERE, so they could not be linted. This gate fails closed: restore the hook, or revert the board (git -C $SR checkout -- $board), then end the turn again."

out=$(sh "$LINT" --diff "$SR" "$board" 2>&1); rc=$?
case $rc in
  0) exit 0 ;;
  1) block "kanban-gate: this turn cannot end yet. The uncommitted changes to $SR/$board break the board contract -- line number in the working copy, rule, and where that fact lives instead:
$out

Fix or delete each line named, then end the turn again; this gate fires once per turn. The board holds a question only the user can settle under ## Needs ruling, and agent rabbit-trails under ## Claude's; /card-write has the routing table for everything else. stop-continuity.sh will not commit the board while this lint fails." ;;
  *) block "kanban-gate: $SR/$board has uncommitted changes that could not be linted ($out). This gate fails closed: make the board lintable, or revert it (git -C $SR checkout -- $board), then end the turn again." ;;
esac
