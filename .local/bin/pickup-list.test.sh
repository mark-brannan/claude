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
S=$(mktemp -d); export S; trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export XDG_CACHE_HOME="$S/cache"
hard_cache="$XDG_CACHE_HOME/pickup-list/fixup-hard"
nohard() { rm -rf "$XDG_CACHE_HOME/pickup-list"; jq -nc '{data:{search:{nodes:[]}}}' > "$S/hard.json"; }
nohard
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
if [ "${1:-}" = api ]; then
  echo "$*" >> "$S/gh-api.log"
  [ "${GH_HARD_FAIL:-0}" = 1 ] && { echo "gh: search failed" >&2; exit 1; }
  [ "${GH_HARD_HANG:-0}" = 1 ] && { sleep 30; exit 1; }
  jqf=.
  while [ $# -gt 0 ]; do [ "$1" = --jq ] && { shift; jqf=$1; }; shift; done
  jq -r "$jqf" "$S/hard.json"
  exit 0
fi
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

# --- fixup-hard PRs come first -------------------------------------------------------
# The whole point of the row: it outranks every block, so it has to print above
# the table, not inside it -- and an empty search must leave the table untouched.
run
hasnt 'no hard PRs: no hard header' '^Hard --'
has 'no hard PRs: the listing is as it was' '^Resume, showing 1 of 1$'

cat > "$S/hard-two.json" <<'HARD'
{"data":{"search":{"nodes":[
  {"number":193,"url":"https://github.com/o/colregs/pull/193","title":"Give way in a crossing",
   "repository":{"nameWithOwner":"o/colregs"},
   "comments":{"nodes":[
     {"author":{"__typename":"User"},"body":"Conflicts across four files and the base moved twice.\nSpent $1.04."},
     {"author":{"__typename":"Bot"},"body":"**Claude finished @o's task in 1m 45s** -- View job"}]}},
  {"number":7,"url":"https://github.com/o/demo/pull/7","title":"No comment left behind",
   "repository":{"nameWithOwner":"o/demo"},"comments":{"nodes":[]}}]}}}
HARD
somehard() { rm -rf "$XDG_CACHE_HOME/pickup-list"; cp "$S/hard-two.json" "$S/hard.json"; }
somehard
run
has 'hard header' '^Hard -- a fixer gave up'
has 'hard ref and marker' 'o/colregs#193 \[hard\] Give way in a crossing'
has 'hard url' 'https://github.com/o/colregs/pull/193'
has 'first line of the comment' 'Conflicts across four files and the base moved twice\.$'
hasnt 'only the first line' 'Spent'
hasnt 'a review bot posting after the fixer does not displace the handover' 'Claude finished'
has 'a fixer that left no comment says so' 'no comment from the fixer'
assert 'hard block is above the table' \
  test "$(grep -n '^Hard --' <<<"$OUT" | cut -d: -f1)" -lt "$(grep -n '^Resume, showing' <<<"$OUT" | cut -d: -f1)"
has 'the listing itself is unchanged' '^Resume, showing 1 of 1$'
has 'and still has its row' '\| `claude/alpha` \|'

# The cache is the whole reason worklist can print this in the SessionStart
# brief: a fresh one costs no call at all, and a stalled search is abandoned
# rather than waited on.
: > "$S/gh-api.log"
run
eq 'a fresh cache makes no search call' 0 "$(grep -c . "$S/gh-api.log")"
has 'and still prints the hard block' '^Hard -- a fixer gave up'

nohard
GH_HARD_FAIL=1 run
hasnt 'a failed search prints no hard block' '^Hard --'
has 'and costs the listing nothing' '^Resume, showing 1 of 1$'
assert 'a failed search leaves no cache behind' test ! -f "$hard_cache"

nohard
t0=$(date +%s); GH_HARD_HANG=1 run; t1=$(date +%s)
assert "a stalled search is abandoned in $((t1 - t0)) s (limit 8)" test $((t1 - t0)) -le 8
has 'and the listing still prints' '^Resume, showing 1 of 1$'

# --brief is the SessionStart path: it shows what is in the cache and never
# waits on the search itself; a stale cache is refilled by a detached full run,
# so the brief after this one has the rows for free.
nohard
t0=$(date +%s); GH_HARD_HANG=1 run --brief; t1=$(date +%s)
assert "brief does not wait on a stalled search, returned in $((t1 - t0)) s" test $((t1 - t0)) -le 2
has 'the listing is all there is on a cold cache' '^Resume, showing 1 of 1$'
somehard
run --brief
hasnt 'a cold brief prints no block' '^Hard --'
i=0; while [ "$i" -lt 20 ] && [ ! -s "$hard_cache" ]; do sleep 0.5; i=$((i + 1)); done
assert 'and a detached run has refilled the cache behind it' test -s "$hard_cache"
: > "$S/gh-api.log"
run --brief
has 'so the next brief shows it' 'o/colregs#193 \[hard\]'
eq 'without a call of its own' 0 "$(grep -c . "$S/gh-api.log")"

nohard
: > "$S/gh-api.log"
run --files
hasnt 'files output stays machine-readable' 'Hard --'
eq 'and --files makes no search call' 0 "$(grep -c . "$S/gh-api.log")"

# --- --files gives /pickup the path --------------------------------------------------
run --files
eq 'files: one line per block' 1 "$(grep -c '^' <<<"$OUT")"
has 'files: branch then path' "^claude/alpha	$AUTO/"
eq 'files: silent when empty' '' "$(rm -f "$A"; "$RL" --files)"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
