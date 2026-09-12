#!/usr/bin/env bash
# Tests for pickup-list. Run: bash .local/bin/pickup-list.test.sh
# Set AWK_PATH to a directory whose `awk` is another implementation to run the
# same cases under it; CI does this for each.
#
# What matters: zero, one and two blocks each render right; a consumed block is
# gone; a block whose branch is level with main or whose PR merged is dropped;
# a block that cannot be checked is KEPT and says why, because dropping what we
# could not look at is exactly how work gets lost; newest first; --files gives
# /pickup the paths it needs to mark one consumed.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

RL="$(cd "$(dirname "$0")" && pwd)/pickup-list"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export TMPDIR="$S/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

SR="$S/state"; AUTO="$SR/state/global/log/auto"
mkdir -p "$AUTO" "$SR/.git"
export CLAUDE_STATE_REPO="$SR"

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# --- a fake gh: GH_MERGED lists the branches whose PR is merged --------------
BIN="$S/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/bin/sh
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: not logged in" >&2; exit 1; }
b=""
while [ $# -gt 0 ]; do [ "$1" = --head ] && { shift; b=$1; }; shift; done
for m in ${GH_MERGED:-}; do [ "$m" = "$b" ] && { echo '[{"number":1}]'; exit 0; }; done
echo '[]'
EOF
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH"

# --- a work repo with a main and some branches -------------------------------
ORIGIN="$S/origin.git"; WORK="$S/work"
git init -q --bare "$ORIGIN"
git init -q -b main "$WORK"
gitq "$WORK" remote add origin "$ORIGIN"
echo one > "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m base
gitq "$WORK" push -u origin main
for b in claude/alpha claude/beta claude/merged; do
  gitq "$WORK" checkout -b "$b" main
  echo "$b" >> "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m "$b"
done
gitq "$WORK" checkout -b claude/level main        # level with main: nothing ahead
gitq "$WORK" checkout main

# --- fixtures ----------------------------------------------------------------
# ckpt <slug> <branch> <worktree> <next> [consumed]
ckpt() {
  local f="$AUTO/2026-09-09-demo-$1.md"
  {
    printf '# Auto-checkpoint — demo @ `%s`\n\n' "$2"
    printf '**Verdict:** not archivable: worktree dirty\n\n'
    printf -- '- worktree `%s`\n' "$3"
    printf -- '- session `%s` · opus · started 2026-09-09T00:00:00Z\n\n' "$1"
    printf '## Resume\n\n'
    printf -- '- next: %s\n' "$4"
    printf -- '- link: https://github.com/o/demo/pull/1\n'
    printf -- '- model: opus\n'
    printf -- '- effort: high\n'
    [ -n "${5:-}" ] && printf -- '- consumed: %s\n' "$5"
    printf '\n## Commits this session\n\n- none\n'
  } > "$f"
  printf '%s' "$f"
}
# A checkpoint with no resume block at all: must never appear.
printf '# Auto-checkpoint — demo @ `claude/nothing`\n\n**Verdict:** archivable\n\n- worktree `%s`\n' \
  "$WORK" > "$AUTO/2026-09-09-demo-none.md"

run() { OUT=$("$RL" "$@" 2>&1); RC=$?; }
assert() { local m=$1; shift; if "$@"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $m"; fi; }
has()  { assert "$1: /$2/ in output" grep -qE "$2" <<<"$OUT" || printf '%s\n' "$OUT" | sed 's/^/    /'; }
hasnt() { assert "$1: /$2/ absent" bash -c '! grep -qE "$1" <<<"$2"' _ "$2" "$OUT"; }
eq()   { assert "$1: expected $2, got $3" test "$2" = "$3"; }

# --- zero blocks --------------------------------------------------------------
run
eq 'exit 0' 0 "$RC"
eq 'zero blocks prints none' 'Resume: none' "$OUT"

# --- one block ----------------------------------------------------------------
A=$(ckpt alpha claude/alpha "$WORK" "Wire the verdict into the checkpoint")
touch -t 202609090800 "$A"
run
has 'one row counted' '^Resume, showing 1 of 1$'
has 'table header' '^\| Branch \| Next step \| Age \| Model \| Notes \|$'
has 'branch cell' '\| `claude/alpha` \|'
has 'next step' 'Wire the verdict into the checkpoint'
has 'model and effort' 'opus · high'
has 'repo and worktree in notes' "demo · $WORK"

# --- two blocks, newest first --------------------------------------------------
B=$(ckpt beta claude/beta "$WORK" "Write the resume-list fixtures")
touch -t 202609091200 "$B"
run
has 'two rows counted' '^Resume, showing 2 of 2$'
eq 'newest first' 'claude/beta' \
  "$(grep -o '`claude/[a-z]*`' <<<"$OUT" | head -1 | tr -d '`')"

# --- a consumed block is gone ----------------------------------------------------
ckpt beta claude/beta "$WORK" "Write the resume-list fixtures" \
  "session abcd1234 at 2026-09-09T13:00:00Z" >/dev/null
run
has 'consumed block dropped' '^Resume, showing 1 of 1$'
hasnt 'consumed branch absent' 'claude/beta'

# --- level with main, and a merged PR, are both dropped ---------------------------
L=$(ckpt level claude/level "$WORK" "Nothing left ahead of main")
M=$(ckpt merged claude/merged "$WORK" "Its PR already merged")
GH_MERGED="claude/merged" run
hasnt 'branch level with main dropped' 'claude/level'
hasnt 'merged PR dropped' 'claude/merged'
has 'the live one survives' 'claude/alpha'
rm -f "$L" "$M"

# --- what cannot be checked is kept, and says so -----------------------------------
G=$(ckpt gone claude/gone "$S/not-here" "Worktree was thrown away")
run
has 'missing worktree kept' 'claude/gone'
has 'and named' 'worktree gone'
rm -f "$G"

GH_FAIL=1 run
has 'gh failure keeps the row' 'claude/alpha'
has 'and names it' 'PR state unverified \(gh\)'

# --- --brief caps and cuts ----------------------------------------------------------
long="A next step written well past the eighty character mark so that brief output has to cut it somewhere sensible"
P=$(ckpt long claude/alpha "$WORK" "$long")
run --brief
assert 'brief cuts the next step' test "$(grep -c "$long" <<<"$OUT")" -eq 0
run
has 'full output does not cut' "$long"
rm -f "$P"

# --- --files gives /pickup the path --------------------------------------------------
run --files
eq 'files: one line per block' 1 "$(grep -c '^' <<<"$OUT")"
has 'files: branch then path' "^claude/alpha	$AUTO/"
eq 'files: silent when empty' '' "$(rm -f "$A"; "$RL" --files)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
