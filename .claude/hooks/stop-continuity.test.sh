#!/usr/bin/env bash
# Tests for the parts of stop-continuity.sh that dotfiles#110 added: the
# archive verdict line, the same verdict in the metrics record, and carrying a
# model-written resume block through the rewrite.
# Run: bash .claude/hooks/stop-continuity.test.sh
#
# What matters: `archivable` is said only when every condition holds; each
# reason is named, in the contract's order; a resume block survives a Stop,
# because the hook rewrites the whole checkpoint and eating the hand-off the
# model was told to write would be silent and total.
#
# The rest of the hook (metrics shape, the salvage commit, the state-repo
# push) is not covered here.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

HOOKS="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HOOKS/stop-continuity.sh"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export TMPDIR="$S/tmp"; mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export CLAUDE_STOP_COMMIT=off          # the salvage commit is not under test

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# A state dir that is deliberately NOT a git repo: state_is_repo is false, so
# the hook stops before the commit-and-push section and the verdict written by
# the salvage step is the one under test.
SD="$S/state"; mkdir -p "$SD/state/global"
export CLAUDE_STATE_REPO=""
export HOME="$S/home"
AUTO="$HOME/.claude/state/global/log/auto"

# --- a fake gh: GH_PRS is what `gh pr list` answers ---------------------------
BIN="$S/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/bin/sh
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: not logged in" >&2; exit 1; }
case "$1 ${2:-}" in
  "pr list")    printf '%s\n' "${GH_PRS:-[]}" ;;
  "issue list") printf '%s\n' "${GH_ISSUES:-[]}" ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH"

# --- the repo the session worked ----------------------------------------------
ORIGIN="$S/origin.git"; WORK="$S/work"
git init -q --bare "$ORIGIN"
git init -q -b main "$WORK"
gitq "$WORK" remote add origin "$ORIGIN"
echo one > "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m base
gitq "$WORK" push -u origin main
gitq "$WORK" checkout -b claude/work
echo two >> "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m work
gitq "$WORK" push -u origin claude/work

TP="$HOOKS/fixtures/friction-calm.jsonl"
SID=stopcont-0000-1111-2222
CKPT=""
stop() {  # stop -- run the hook and set $CKPT to the checkpoint it wrote
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s"}' "$TP" "$SID" "$WORK" \
    | bash "$HOOK" >/dev/null 2>&1
  CKPT=$(ls "$AUTO"/*"${SID:0:8}".md 2>/dev/null | head -1)
}
verdict() { sed -n 's/^\*\*Verdict:\*\* //p' "$CKPT" | head -1; }

assert() { local m=$1; shift; if "$@"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $m"; fi; }
eq() { assert "$1: expected [$2], got [$3]" test "$2" = "$3"; }
has() { assert "$1: /$2/ in $3" grep -qE "$2" "$3"; }

# --- everything in order: archivable --------------------------------------------
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
assert 'a checkpoint was written' test -n "$CKPT"
eq 'clean, pushed, PR: archivable' 'archivable' "$(verdict)"
eq 'the metrics record says the same' 'archivable' \
  "$(jq -r .verdict "$HOME/.claude/state/global/metrics/sessions/$SID.json")"
has 'the worktree is recorded for resume-list' "^- worktree .$WORK.$" "$CKPT"

# --- no PR and no pointer --------------------------------------------------------
stop
has 'no home is named' '^\*\*Verdict:\*\* not archivable: no PR and no pointer' "$CKPT"

# --- a dirty worktree, and unpushed commits, named in the contract's order ---------
echo three >> "$WORK/f"
gitq "$WORK" add f; gitq "$WORK" commit -m unpushed
echo four >> "$WORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'dirty before unpushed' 'not archivable: worktree dirty, 1 commit(s) unpushed' "$(verdict)"
gitq "$WORK" checkout -- f
gitq "$WORK" push

# --- a branch that was never pushed at all -------------------------------------
# No upstream means `rev-list @{u}..HEAD` fails rather than answering 0, so a
# fallback of 0 would call a clean, home-having branch archivable while every
# commit still lives only on local disk.
gitq "$WORK" checkout -b claude/never-pushed
echo five >> "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m local-only
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'never pushed is not archivable' \
  'not archivable: `claude/never-pushed` has no upstream (never pushed)' "$(verdict)"
gitq "$WORK" checkout claude/work

# --- a fresh branch, no upstream, zero commits ahead of main -----------------------
# branch-home-gate.sh already treats this as "nothing to strand"; the verdict
# should agree instead of flagging the same branch as never-pushed.
gitq "$WORK" checkout -b claude/fresh-review main
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'zero commits ahead, no upstream: archivable' 'archivable' "$(verdict)"
gitq "$WORK" checkout claude/work

# --- a detached HEAD, on and off a remote branch (#128/#143) -----------------------
# The carve-out lib-state.sh's unpushed_state owns: a commit that already lives
# on some remote branch is not stranded by being checked out detached, but one
# that lives nowhere else is exactly the case the verdict exists for.
gitq "$WORK" checkout --detach origin/claude/work
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'detached on a remote branch: archivable' 'archivable' "$(verdict)"
echo six >> "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m detached-only
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'detached off any remote branch: not archivable' \
  'not archivable: detached HEAD, no upstream to compare against' "$(verdict)"
gitq "$WORK" checkout claude/work

# --- "cannot verify" is never a pass ------------------------------------------------
GH_FAIL=1 stop
has 'unverified is not archivable' '^\*\*Verdict:\*\* not archivable: branch home unverified' "$CKPT"

# --- a resume block survives the rewrite ---------------------------------------------
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
printf '\n## Resume\n\n- next: Finish the resume-list fixtures\n- link: o/r#7\n- model: opus\n- effort: high\n' >> "$CKPT"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
has 'the heading survives' '^## Resume$' "$CKPT"
has 'next survives' '^- next: Finish the resume-list fixtures$' "$CKPT"
has 'effort survives' '^- effort: high$' "$CKPT"
eq 'exactly one resume block' 1 "$(grep -c '^## Resume$' "$CKPT")"
eq 'exactly one verdict line' 1 "$(grep -c '^\*\*Verdict:\*\* ' "$CKPT")"
assert 'the block did not swallow the rest of the file' grep -q '^## Commits this session$' "$CKPT"

# --- and so does a consumed marker, so the record of who took it stays --------------
sed -i 's/^- effort: high$/&\n- consumed: session abcd1234 at 2026-09-09T13:00:00Z/' "$CKPT"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
has 'consumed marker survives' '^- consumed: session abcd1234' "$CKPT"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
