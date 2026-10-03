#!/usr/bin/env bash
# Tests for branch-home-gate.sh. Run: bash .claude/hooks/branch-home-gate.test.sh
# Set AWK_PATH to a directory whose `awk` is another implementation to run the
# same cases under it; CI does this for each.
#
# What matters: the quiet path really is quiet (default branch, detached HEAD,
# nothing ahead, no origin, not a repo); a PR, a work item or an open issue
# each count as a home, and a false substring match doesn't; nothing at all
# blocks once and only once per session; "cannot look" blocks rather than
# passing.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

HOOKS="$(cd "$(dirname "$0")" && pwd)"
GATE="$HOOKS/branch-home-gate.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export TMPDIR="$SCRATCH/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# --- a state repo whose items name no branch until a test writes one ----------
SR="$SCRATCH/claude_prompts_scratch"; mkdir -p "$SR/state/global"; gitq "$SR" init -q
ITEMS="$SR/state/global/items"
export CLAUDE_STATE_REPO="$SR"
export WORK_ITEM_BIN="$HOOKS/../../.local/bin/work-item"
# item <id> <brief> -- one agent item whose brief is the text; clear_items drops them all.
item() {
  mkdir -p "$ITEMS"
  printf '# Design\n\n## Brief\n%s\n\n## Log\n2026-10-03T05:00:00Z 1d68120b status=open owner=agent repo=- parent=- model=- effort=-\n2026-10-03T05:00:00Z 1d68120b status=ready\n' "$2" > "$ITEMS/$1.md"
}
clear_items() { rm -rf "$ITEMS"; }
item 1790000000aaaaaaaa 'Something else.'

# --- a fake gh whose answers come from the environment ------------------------
BIN="$SCRATCH/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/bin/sh
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: could not authenticate" >&2; exit 1; }
case "$1 ${2:-}" in
  "pr list")
    case " $* " in
      *" --head "*) printf '%s\n' "${GH_PRS:-[]}" ;;
      *)            printf '%s\n' "${GH_PRS_ALL:-[]}" ;;
    esac
    ;;
  "issue list") printf '%s\n' "${GH_ISSUES:-[]}" ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH"

# A PATH with the tools the gate needs and nothing else, so a test can take one
# tool away and watch the gate fail closed instead of quiet.
mkbin() {
  local d=$1; shift; mkdir -p "$d"
  local b p
  for b in sh dash bash git jq sed grep tr tail head cat awk sort cut wc \
           dirname basename timeout flock rm mkdir env date mktemp; do
    for skip in "$@"; do [ "$b" = "$skip" ] && continue 2; done
    p=$(command -v "$b" 2>/dev/null) && ln -sf "$p" "$d/$b"
  done
}
mkbin "$SCRATCH/nogh"            # no gh at all
mkbin "$SCRATCH/nojq" jq         # no jq either

# --- the repo under test ------------------------------------------------------
ORIGIN="$SCRATCH/origin.git"; WORK="$SCRATCH/work"
setup_repo() {  # setup_repo <branch|""> [commits-ahead]
  local branch=${1:-} ahead=${2:-1}
  rm -rf "$ORIGIN" "$WORK"
  git init -q --bare -b main "$ORIGIN"
  git init -q -b main "$WORK"
  gitq "$WORK" remote add origin "$ORIGIN"
  echo one > "$WORK/f"; gitq "$WORK" add -- f; gitq "$WORK" commit -m one
  gitq "$WORK" push -u origin main
  [ -n "$branch" ] || return 0
  gitq "$WORK" checkout -b "$branch"
  if [ "$ahead" -gt 0 ]; then
    echo two > "$WORK/g"; gitq "$WORK" add -- g; gitq "$WORK" commit -m two
  fi
  gitq "$WORK" push -u origin "$branch"
}

# --- payloads -----------------------------------------------------------------
stop_input() {  # stop_input <sid> [cwd] [stop_hook_active]
  jq -n --arg sid "$1" --arg cwd "${2:-$WORK}" --argjson a "${3:-false}" \
    '{session_id:$sid,cwd:$cwd,stop_hook_active:$a}'
}

# check <block|silent|other> <desc> <sid> [cwd] [active]
check() {
  local want=$1 desc=$2 got
  LAST=$(stop_input "$3" "${4:-$WORK}" "${5:-false}" | sh "$GATE" 2>&1)
  if [ -z "$LAST" ]; then got=silent
  elif [ "$(printf '%s' "$LAST" | jq -r '.decision // empty' 2>/dev/null)" = block ]; then got=block
  elif printf '%s' "$LAST" | jq -e . >/dev/null 2>&1; then got=other
  else got=invalid; fi
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL (want %s, got %s): %s\n  %s\n' "$want" "$got" "$desc" "$LAST"; fi
}
reason() { if grep -Eq -- "$2" <<<"$(jq -r '.reason // .systemMessage // empty' <<<"$LAST")"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL (message lacks /%s/): %s\n  %s\n' "$2" "$1" "$LAST"; fi; }
ok()     { if "${@:2}"; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n' "$1"; fi; }
rec_for() { printf '%s/claude-branch-home.%s' "$TMPDIR" "$1"; }

# --- the quiet path -----------------------------------------------------------
setup_repo ""
check silent 'on the default branch'            q1
check silent 'cwd is not a git repo'            q2 "$SCRATCH"
check silent 'cwd does not exist'               q3 "$SCRATCH/nope"

setup_repo claude/level 0
check silent 'branch level with origin/main'    q4

setup_repo claude/ahead
gitq "$WORK" checkout --detach
check silent 'detached HEAD'                    q5
gitq "$WORK" checkout claude/ahead

gitq "$WORK" remote remove origin
check silent 'no origin remote'                 q6
gitq "$WORK" remote add origin "$ORIGIN"

# --- a home ------------------------------------------------------------------
setup_repo claude/homed
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' check silent 'an open PR has this head' h1
export GH_PRS='[]'

# The store is local files, so it is read before gh is: an item is a home even
# when gh cannot answer at all.
item 1790000002aaaaaaaa 'It lives on `claude/homed`.'
GH_FAIL=1 check silent 'a work item names the branch' h2
item 1790000002aaaaaaaa 'Something else.'

# kanban.md is not read: a card there, with the store empty, is no home.
clear_items
printf -- '# Board\n\n## Claude'"'"'s\n- [ ] **Design lives on `claude/homed`** ([log](log/d.md))\n' > "$SR/state/global/kanban.md"
GH_FAIL=1 check block 'a kanban.md card is not a home' h2b
rm -f "$SR/state/global/kanban.md"
item 1790000000aaaaaaaa 'Something else.'

GH_ISSUES='[{"number":4,"title":"t","body":"the work is on claude/homed"}]' \
  check silent 'an open issue names the branch' h3

# A mergify stack PR's head is stack/<login>/<branch>/<slug>--<change-id>, not
# the branch name -- the exact --head lookup misses it, so this must fall
# back to the broad state-based match.
setup_repo claude/homed
GH_PRS_ALL='[{"url":"https://github.com/o/r/pull/9","headRefName":"stack/mark-brannan/claude/homed/record-rulings--ad4fbbdd"}]' \
  check silent 'a mergify stack PR has this head' h3b

# A card or issue naming a longer branch must not give a false home to its
# prefix: claude/homed-extra does not mean claude/homed has one.
setup_repo claude/homed
item 1790000004aaaaaaaa 'Design lives on `claude/homed-extra`.'
GH_FAIL=1 check block 'a work item for a longer branch is not a home' h4
item 1790000004aaaaaaaa 'Something else.'

setup_repo claude/homed
GH_ISSUES='[{"number":5,"title":"t","body":"the work is on claude/homed-extra"}]' \
  check block 'an open issue for a longer branch is not a home' h5

# --- no home ------------------------------------------------------------------
setup_repo claude/orphan
check block 'ahead, no PR, no card, no issue'   b1
reason 'names the branch'                        'claude/orphan'
reason 'says how far ahead'                      '1 commit\(s\) ahead of origin/main'
reason 'offers the PR'                           'open the PR'
reason 'offers a pointer card'                   '/card-write'
reason 'says it fires once'                      'once per session'
ok 'the block is recorded for the checkpoint'    grep -q '^blocked' "$(rec_for b1)"

check silent 'a second Stop in the same session' b1
check block  'a different session blocks again'  b2

# stop_hook_active suppresses the block even before the marker exists.
check silent 'the retry within a turn is quiet'  b3 "$WORK" true

# origin/HEAD, where it is set, is the base rather than the origin/main guess.
gitq "$WORK" symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/main
check block 'origin/HEAD is used as the base'    b4
reason 'names the base it measured against'      'ahead of origin/main'

# --- cannot look is not a pass ------------------------------------------------
GH_FAIL=1 check block 'gh failing blocks'        u1
reason 'says it could not verify'                'could not be verified'
reason 'still offers the ways out'               '/card-write'

LAST=$(stop_input u2 | PATH="$SCRATCH/nogh" /bin/sh "$GATE" 2>&1)
ok 'gh missing blocks'    [ "$(printf '%s' "$LAST" | jq -r .decision 2>/dev/null)" = block ]
reason 'says gh is not installed'                'not installed'

LAST=$(stop_input u3 | PATH="$SCRATCH/nojq" /bin/sh "$GATE" 2>&1)
ok 'jq missing blocks with valid JSON' [ "$(printf '%s' "$LAST" | jq -r .decision 2>/dev/null)" = block ]
LAST=$(stop_input u4 "$WORK" true | PATH="$SCRATCH/nojq" /bin/sh "$GATE" 2>&1)
ok 'jq missing on a retry is quiet'    [ -z "$LAST" ]

# --- --card: the machine-readable card, for claim-stamp.sh --------------------
card() { sh "$GATE" --card "${1:-$WORK}" 2>&1; }
cardis() { if [ "$(card "${3:-$WORK}")" = "$2" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s (want %s, got %s)\n' "$1" "$2" "$(card "${3:-$WORK}")"; fi; }

setup_repo claude/carded
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' \
  cardis 'a PR is the card'              'pr https://github.com/o/r/pull/7'
export GH_PRS='[]'
GH_ISSUES='[{"number":4,"title":"t","body":"work on claude/carded","url":"https://github.com/o/r/issues/4"}]' \
  cardis 'an issue is the card'          'issue https://github.com/o/r/issues/4'
cardis 'nothing is none'                 'none'
GH_FAIL=1 cardis 'a failed lookup says so' 'unverified: gh pr list failed (not authenticated here?)'

# A local work item is a home but not a card: a private file on one machine is
# not something a second machine can read a claim off.
item 1790000005aaaaaaaa 'Design lives on `claude/carded`.'
cardis 'a work item is not a card here' 'none'
item 1790000005aaaaaaaa 'Something else.'

setup_repo ""
cardis 'the default branch has no card'  'none'
cardis 'and neither does a non-repo'     'none' "$SCRATCH"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
