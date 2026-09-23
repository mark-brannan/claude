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
# The salvage commit's destination (dotfiles#285: a `wip/<session>` ref, never
# the branch the session's PR is on) and its refusals (dotfiles#196: CI, stale
# base, revert of the branch's own work; dotfiles#280: a stale untracked
# leftover from before the checkout synced) are covered near the bottom, in a
# throwaway repo of their own. The rest of the hook -- metrics shape, the
# state-repo push -- is not covered here.
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

# =============================================================================
# sc_salvage: the auto-commit at Stop (dotfiles#196)
# =============================================================================
# Everything above ran with CLAUDE_STOP_COMMIT=off. These use a throwaway repo
# of their own, pushed to a bare origin, so a commit made here can't leak into
# the verdict fixtures above. `hookpath` is the branch's own work: base has
# it one way, the branch changed it, and the failure mode under test is the
# base version coming back over it.
SORIGIN="$S/salvage-origin.git"; SWORK="$S/salvage-work"
git init -q --bare "$SORIGIN"
git init -q -b main "$SWORK"
git -C "$SWORK" config user.name t; git -C "$SWORK" config user.email t@example.invalid
# The salvage commit forces commit.gpgsign=true, so the fixture needs a key it
# can actually sign with; ssh signing needs no gpg agent.
ssh-keygen -q -t ed25519 -N "" -C t -f "$S/sign" </dev/null
git -C "$SWORK" config gpg.format ssh
git -C "$SWORK" config user.signingkey "$S/sign.pub"
gitq "$SWORK" remote add origin "$SORIGIN"
echo base > "$SWORK/f"; echo 'guard: no' > "$SWORK/hookpath"
gitq "$SWORK" add f hookpath; gitq "$SWORK" commit -m base
gitq "$SWORK" push -u origin main
gitq "$SWORK" remote set-head origin main
gitq "$SWORK" checkout -b claude/salvage
echo work >> "$SWORK/f"; echo 'guard: yes' > "$SWORK/hookpath"
gitq "$SWORK" add f hookpath; gitq "$SWORK" commit -m work
gitq "$SWORK" push -u origin claude/salvage

stop_salvage() {  # stop_salvage [VAR=value ...] -- run the hook with the salvage commit on
  # GITHUB_ACTIONS and CI are unset first: this suite runs under Actions, and
  # the hook's CI refusal would otherwise win every case below. The CI case
  # sets them back on purpose, as arguments.
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s"}' "$TP" "$SID" "$SWORK" \
    | env -u GITHUB_ACTIONS -u CI CLAUDE_STOP_COMMIT=on "$@" bash "$HOOK" >/dev/null 2>&1
  CKPT=$(ls "$AUTO"/*"${SID:0:8}".md 2>/dev/null | head -1)
}
WIP="wip/$SID"
snapshot() {
  before_local=$(git -C "$SWORK" rev-parse HEAD)
  before_origin=$(git -C "$SORIGIN" rev-parse claude/salvage)
  before_wip=$(git -C "$SORIGIN" rev-parse "$WIP" 2>/dev/null || echo none)
}
untouched() {  # untouched <label> <expected porcelain> -- nothing committed or pushed
  eq "$1: local HEAD untouched" "$before_local" "$(git -C "$SWORK" rev-parse HEAD)"
  eq "$1: origin untouched" "$before_origin" "$(git -C "$SORIGIN" rev-parse claude/salvage)"
  eq "$1: the wip ref untouched" "$before_wip" \
    "$(git -C "$SORIGIN" rev-parse "$WIP" 2>/dev/null || echo none)"
  eq "$1: the edit is still sitting there, uncommitted" "$2" "$(git -C "$SWORK" status --porcelain)"
}
# salvaged <label> <expected porcelain> -- the commit went to the wip ref and
# nowhere near the branch the session (and its PR) is on (dotfiles#285).
salvaged() {
  eq "$1: the branch head is unchanged locally" "$before_local" "$(git -C "$SWORK" rev-parse HEAD)"
  eq "$1: the branch head is unchanged on origin" "$before_origin" \
    "$(git -C "$SORIGIN" rev-parse claude/salvage)"
  assert "$1: origin has the wip ref" \
    git -C "$SORIGIN" rev-parse -q --verify "$WIP" >/dev/null
  eq "$1: the wip commit sits on the branch head" "$before_local" \
    "$(git -C "$SWORK" rev-parse "$WIP^")"
  eq "$1: the files are still in the working tree" "$2" "$(git -C "$SWORK" status --porcelain)"
  assert "$1: no wip: commit reached the branch" \
    test -z "$(git -C "$SORIGIN" log --oneline --grep='^wip: session' claude/salvage)"
}

# --- happy path: dirty tree, HEAD even with @{u} -> salvaged to the wip ref ------
# The failure this replaces: the same commit went onto the session's branch and
# was pushed to the open PR (dotfiles#177, #196, #280).
snapshot; echo dirty >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'salvage happy path: salvaged to the wip ref and pushed' \
  "salvaged to .$WIP. and pushed it" "$CKPT"
salvaged 'salvage happy path' ' M f'
eq 'the wip commit carries the uncommitted content' 'dirty' \
  "$(git -C "$SORIGIN" show "$WIP:f" | tail -1)"
# The signature itself, not %G?: verifying an ssh signature would need an
# allowedSignersFile this fixture has no reason to carry.
eq 'the salvage commit is signed' 'gpgsig' \
  "$(git -C "$SWORK" cat-file -p "$WIP" | awk '/^gpgsig/{print "gpgsig"; exit}')"
# A second Stop in the same session: the ref moves on, still off the branch.
snapshot; echo dirtier >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
salvaged 'a second Stop' ' M f'
eq 'the second Stop superseded the first on the wip ref' 'dirtier' \
  "$(git -C "$SORIGIN" show "$WIP:f" | tail -1)"
gitq "$SWORK" checkout -- f

# --- no signing key: refused rather than pushed unsigned (dotfiles#183) ----------
# A cloud session has no key. Unsigned is how the salvage commit kept landing
# unsigned commits on open pull requests, so the commit must fail instead.
snapshot; git -C "$SWORK" config --unset gpg.format
git -C "$SWORK" config --unset user.signingkey; echo unsigned-edit >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'no signing key: refused' 'refused: commit failed .hook or signing.' "$CKPT"
untouched 'no signing key' ' M f'
git -C "$SWORK" config gpg.format ssh
git -C "$SWORK" config user.signingkey "$S/sign.pub"
git -C "$SWORK" checkout -q -- f

# --- under CI: refused before anything else is looked at --------------------------
# The shared PR reviewer is Claude Code inside GitHub Actions with these hooks
# seeded; its checkout is dirty by construction. Nothing a bot has is ours.
snapshot; echo ci-edit >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage GITHUB_ACTIONS=true
has 'GITHUB_ACTIONS: refused' 'refused: running under CI' "$CKPT"
untouched 'GITHUB_ACTIONS' ' M f'
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage CI=1
has 'CI: refused' 'refused: running under CI' "$CKPT"
untouched 'CI' ' M f'
gitq "$SWORK" checkout -- f

# --- a revert of the branch's own work: refused, files named ---------------------
# claude-code-action's restore, or a tool writing from a stale copy: the
# branch changed hookpath, and now base's version is back over it.
snapshot; git -C "$SWORK" show origin/main:hookpath > "$SWORK/hookpath"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'revert to base: refused and the file is named' \
  'refused: the working tree puts .origin/main..s version back over this branch.s changes to: hookpath' "$CKPT"
untouched 'revert to base' ' M hookpath'
# ... even when a real edit rides along with it: the revert still wins.
echo more >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'revert plus a real edit: still refused' 'that is a revert, not new work' "$CKPT"
untouched 'revert plus a real edit' $' M f\n M hookpath'
gitq "$SWORK" checkout -- f hookpath
# A file the branch never changed, put back to base's content, is not a
# revert of anything -- it is simply unchanged, and the tree is not dirty.
# A file the branch changed, edited to something that is neither version,
# is new work and commits.
snapshot; echo 'guard: yes, differently' > "$SWORK/hookpath"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'a real edit to a branch-changed file: salvaged' "salvaged to .$WIP. and pushed it" "$CKPT"
salvaged 'a real edit to a branch-changed file' ' M hookpath'
gitq "$SWORK" checkout -- hookpath

# --- an untracked path base once had: refused, not committed (dotfiles#280) ------
# A worktree created before an upstream commit deleted a tracked file carries
# it on disk as an untracked leftover for the rest of the worktree's life.
# Give the branch's own history a commit that added stale.txt (so HEAD's
# ancestry has it, same as inheriting it from old main) and a later one that
# removed it (so HEAD's own tree is clean, same as after a rebase past the
# upstream deletion) -- then put the bytes back by hand: exactly what a
# stale leftover looks like on disk, whatever operation actually produced it.
gitq "$SWORK" checkout claude/salvage
echo history > "$SWORK/stale.txt"
gitq "$SWORK" add stale.txt; gitq "$SWORK" commit -m "add stale.txt"
gitq "$SWORK" rm -q stale.txt; gitq "$SWORK" commit -m "remove stale.txt"
gitq "$SWORK" push origin claude/salvage
echo history > "$SWORK/stale.txt"   # the stale leftover: untracked, on disk

snapshot; echo dirty >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'stale untracked leftover: refused, path named' \
  'refused: untracked path\(s\) were tracked .* stale\.txt' "$CKPT"
untouched 'stale untracked leftover' $' M f\n?? stale.txt'

# ... a genuinely new untracked file, never tracked anywhere, still commits.
rm -f "$SWORK/stale.txt"
gitq "$SWORK" checkout -- f
echo brand-new > "$SWORK/new-file.txt"
snapshot
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'a genuinely new untracked file: salvaged' "salvaged to .$WIP. and pushed it" "$CKPT"
salvaged 'a genuinely new untracked file' '?? new-file.txt'
eq 'the new file is on the wip ref' 'brand-new' "$(git -C "$SORIGIN" show "$WIP:new-file.txt")"
rm -f "$SWORK/new-file.txt"

# ... the branch's own add-delete-recreate of the same path: path history looks
# identical to the stale-leftover case above, but the bytes are new -- this is
# the session's own work, not dotfiles#280's upstream-deletion leftover, and
# the content check is what tells them apart.
echo 'new content, not history' > "$SWORK/stale.txt"
snapshot
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'recreate with new content: salvaged, not refused' \
  "salvaged to .$WIP. and pushed it" "$CKPT"
salvaged 'recreate with new content' '?? stale.txt'
eq 'the recreated file carries the new content, not the old' \
  'new content, not history' "$(git -C "$SORIGIN" show "$WIP:stale.txt")"
rm -f "$SWORK/stale.txt"

# --- HEAD behind @{u}: refused, not committed, not pushed (dotfiles#196) ---------
# Simulate the remote moving on without this checkout -- a hand re-push, a
# second session, anything -- by pushing a new commit straight to origin from
# a scratch clone.
CLONE="$S/salvage-clone"
git clone -q "$SORIGIN" "$CLONE" >/dev/null 2>&1
gitq "$CLONE" checkout claude/salvage
echo newer >> "$CLONE/f"; gitq "$CLONE" add f; gitq "$CLONE" commit -m newer-upstream
gitq "$CLONE" push origin claude/salvage

snapshot; echo stale-edit >> "$SWORK/f"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop_salvage
has 'behind @{u}: refused' \
  'refused: .claude/salvage. is 1 commit\(s\) behind .origin/claude/salvage.' "$CKPT"
untouched 'behind @{u}' ' M f'

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
