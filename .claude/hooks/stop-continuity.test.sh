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
# GH_LOG, when set, records each call with its grandparent's argv -- the
# script that wanted the answer (branch-home-gate.sh --check vs --card).
if [ -n "${GH_LOG:-}" ]; then
  gp=$(ps -o ppid= -p $PPID 2>/dev/null | tr -d ' ')
  echo "$* <- $(ps -o args= -p "$gp" 2>/dev/null)" >> "$GH_LOG"
fi
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
# metrics-live.sh refuses a verdict older than its Stop sequence's start, so
# the record has to say when this one was reached.
at=$(jq -r '.verdict_at // empty' "$HOME/.claude/state/global/metrics/sessions/$SID.json")
assert "the metrics record stamps verdict_at in epoch seconds, got [$at]" \
  test "${at:-0}" -ge $(( $(date -u +%s) - 60 ))
has 'the worktree is recorded for resume-list' "^- worktree .$WORK.$" "$CKPT"

# --- outside any repo ---------------------------------------------------------------
# The 📦 notice now shows this verdict, so its reason has to read as one: there
# is no branch to name.
NOGIT="$S/nogit"; mkdir -p "$NOGIT"
NGSID=nogit000-1111-2222-3333
printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s"}' "$TP" "$NGSID" "$NOGIT" \
  | bash "$HOOK" >/dev/null 2>&1
eq 'not a git repo: the verdict says so' 'not archivable: not a git repo' \
  "$(jq -r .verdict "$HOME/.claude/state/global/metrics/sessions/$NGSID.json")"

# --- one gh round trip per Stop ---------------------------------------------------
# The verdict's home check and the pickup item's `pr:` lookup ask the same
# question. The answer travels through ARCHIVABLE_HOME_FILE (lib-state.sh);
# a variable set inside `$(archivable_reasons ...)` dies with the subshell,
# which is how the reuse silently never fired once (PR #388, design pass).
GH_LOG="$S/gh.log"; : > "$GH_LOG"
SID=ghlog000-1111-2222-3333 GH_LOG="$GH_LOG" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
# claim-stamp.sh's own `--card` lookup is a separate, deliberate call and is
# not counted here; the verdict's `--check` is what must run once.
eq 'the verdict asks gh for the head once per Stop' 1 \
  "$(grep -c -- '^pr list --head.*branch-home-gate.sh --check' "$GH_LOG")"
eq 'and the pickup item still learns the PR' 'pr: https://github.com/o/r/pull/7' \
  "$(grep '^pr: ' "$HOME"/.claude/state/global/pickup/*-ghlog000.md 2>/dev/null | head -1)"
assert 'the home file does not outlive the Stop' \
  bash -c "! ls '$TMPDIR'/claude-stop-home.* >/dev/null 2>&1"

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

# --- @{u} is main, the commit lives on a stack/ branch (mergify stack push) --------
gitq "$WORK" checkout -b claude/stacked main
gitq "$WORK" branch -u origin/main
echo seven >> "$WORK/f"; gitq "$WORK" add f; gitq "$WORK" commit -m stacked
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'on no remote branch: not archivable' 'not archivable: 1 commit(s) unpushed' "$(verdict)"
gitq "$WORK" push origin claude/stacked:refs/heads/stack/claude-stacked
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'pushed to stack/, @{u}=main: archivable' 'archivable' "$(verdict)"
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

# --- the pickup item: one per session, machine-written, body model-editable ---
# Written on every Stop from the transcript and git, so a session that ends
# any way at all leaves an item for /pickup. The body is the hand-off a model
# may write, and it survives the rewrite only because the hook overwrites
# nothing but the text it last wrote itself.
PICKD="$HOME/.claude/state/global/pickup"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
ITEM=$(ls "$PICKD"/*-"${SID:0:8}".md 2>/dev/null | head -1)
assert 'a pickup item was written' test -n "$ITEM"
sfield() { sed -n "s/^$1: //p" "$ITEM" | head -1; }
sbody() { awk 'f{print} /^---$/{f=1}' "$ITEM"; }
assert 'the id is the session start minute plus the short session id' \
  bash -c "basename '$ITEM' .md | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-${SID:0:8}\$'"
eq 'status opens' open "$(sfield status)"
eq 'the body defaults to the last prompt line' "$(sfield prompt)" "$(sbody)"
assert 'the prompt line is the transcript'"'"'s last human line' test -n "$(sfield prompt)"
eq 'the pushed branch with a PR records it' https://github.com/o/r/pull/7 "$(sfield pr)"
has 'branch state names ahead and clean' '^branch: work claude/work \(0 ahead, clean\)$' "$ITEM"

# A model edits the body: the next Stop keeps it.
printf 'status: open\nupdated: x\nsession: %s\nmodel: m\nbranch: b\npr: %s\nwhere: w\nprompt: %s\n---\nfinish the fixtures, then open the PR\n' \
  "$SID" "$(sfield pr)" "$(sfield prompt)" > "$ITEM"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'an edited body survives the rewrite' 'finish the fixtures, then open the PR' "$(sbody)"
eq 'a found PR is kept without a second lookup' https://github.com/o/r/pull/7 "$(sfield pr)"

# An until: header, written by a model, survives the rewrite like prompt: does;
# an item that never had one gets no until: line.
assert 'no until: line on an item that has none' bash -c "! grep -q '^until:' '$ITEM'"
printf 'until: a line in the body\n' >> "$ITEM"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'an until: line in the body is not hoisted into the header' '' "$(awk '/^---$/{exit} /^until:/' "$ITEM")"
sed -i '/^until: a line in the body$/d' "$ITEM"
sed -i 's|^\(where: .*\)$|\1\nuntil: https://github.com/o/r/issues/9|' "$ITEM"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'until: survives the rewrite' https://github.com/o/r/issues/9 "$(sfield until)"
eq 'the body is still intact beside until:' 'finish the fixtures, then open the PR' "$(sbody)"

# A done status is kept while the prompt is unchanged.
sed -i 's/^status: open$/status: done/' "$ITEM"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'status is kept while the prompt is unchanged' 'done' "$(sfield status)"

# A body that still reads as the hook left it follows the prompt; a new
# prompt reopens the item.
TP2="$S/pickup-transcript.jsonl"
{
  jq -c '.' "$TP" | head -3
  printf '{"type":"queue-operation","operation":"enqueue","content":"pick up the fixture work and finish it","timestamp":"2026-09-26T12:00:00.000Z"}\n'
} > "$TP2"
printf 'status: done\nupdated: x\nsession: %s\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: old prompt\n---\nold prompt\n' "$SID" > "$ITEM"
TP="$TP2" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
ITEM=$(ls "$PICKD"/*-"${SID:0:8}".md 2>/dev/null | head -1)
eq 'an untouched body follows the new prompt' 'pick up the fixture work and finish it' "$(sbody)"
eq 'a new prompt reopens the item' open "$(sfield status)"

# --- curia digests: a touched digest gets the floor ----------------------------
# The transcript names a curia (`confer <id>` here); the Stop hook stamps a
# floor block at the end of "Where this stands" -- model text above survives --
# and nothing else. Idempotent across Stops. The user's words are not its to
# write: roll.md is the curia-roll hook's, and the digest refers to it by stamp.
CURD="$HOME/.claude/state/global/curia/test-question"
mkdir -p "$CURD"
# The "Human's words" section is what the live digests still carry until the
# curia lint curates it out: the place the hook used to append quotes.
cat > "$CURD/digest.md" <<'EOF'
# Curia: test question

- id: `test-question`
- status: open

## Where this stands

Model text that must survive.

## Decided

## Human's words

Left from before the words log.
EOF
printf '\n### 20260926t110000z\n```\nwords\n```\n' > "$CURD/roll.md"
ROLL_BEFORE=$(cat "$CURD/roll.md")
TP3="$S/curia-transcript.jsonl"
{
  jq -c '.' "$TP" | head -3
  printf '{"type":"queue-operation","operation":"enqueue","content":"confer test-question please","timestamp":"2026-09-26T12:00:00.000Z"}\n'
} > "$TP3"
TP="$TP3" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
TH="$CURD/digest.md"
has 'the floor block is written' '^<!-- floor' "$TH"
has 'the floor carries last-touched and the session' "^- last touched: .* session ${SID:0:8} " "$TH"
has 'the floor carries the branch state' '^- branch: work claude/work \(0 ahead, clean\)' "$TH"
has 'model text above the floor survives' '^Model text that must survive\.$' "$TH"
assert 'the floor sits inside Where this stands' \
  bash -c "awk '/^## Where this stands/{f=1} /^## Decided/{exit} f&&/^<!-- floor/{ok=1} END{exit !ok}' '$TH'"
assert 'the user'"'"'s words are not copied into the digest' \
  bash -c "! grep -q 'confer test-question please' '$TH' && ! grep -q '(hook)' '$TH'"

# A second Stop rewrites, never duplicates.
TP="$TP3" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'one floor block after two Stops' 1 "$(grep -c '^<!-- floor' "$TH")"

# Reading a digest is not sitting on it: a session whose tool calls cat or ls
# the digest file, with no prompt naming the curia, leaves it untouched. Once
# bare `/curia` lists every curia (#403), every sitting would otherwise stamp
# every curia with its own floor.
TP5="$S/curia-transcript-cat.jsonl"
{
  jq -c '.' "$TP" | head -3
  printf '{"type":"queue-operation","operation":"enqueue","content":"what is open on the board?","timestamp":"2026-09-26T14:00:00.000Z"}\n'
  printf '{"type":"assistant","uuid":"a-cat","timestamp":"2026-09-26T14:00:01.000Z","message":{"role":"assistant","model":"m","content":[{"type":"tool_use","id":"t1","name":"Bash","input":{"command":"cat %s; ls %s"}},{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":"%s"}}]}}\n' \
    "$TH" "$CURD" "$TH"
} > "$TP5"
SID2=catsess0-1111-2222-3333
before=$(cat "$TH")
TP="$TP5" SID="$SID2" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
eq 'a cat/ls of the digest does not stamp it' "$before" "$(cat "$TH")"
assert 'no floor for the reading session' bash -c "! grep -q 'session ${SID2:0:8}' '$TH'"

# A curia not yet moved to digest.md still gets its floor on thread.md.
OLDD="$HOME/.claude/state/global/curia/old-question"
mkdir -p "$OLDD"
printf '# Curia: old question\n\n## Where this stands\n\nOld text.\n' > "$OLDD/thread.md"
TP6="$S/curia-transcript-old.jsonl"
{
  jq -c '.' "$TP" | head -3
  printf '{"type":"queue-operation","operation":"enqueue","content":"confer old-question","timestamp":"2026-09-26T15:00:00.000Z"}\n'
} > "$TP6"
TP="$TP6" GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' stop
has 'a thread.md-only curia still gets the floor' '^<!-- floor' "$OLDD/thread.md"
assert 'and no digest.md is invented beside it' bash -c "[ ! -e '$OLDD/digest.md' ]"
eq 'the words log roll.md is never written by the Stop hook' "$ROLL_BEFORE" "$(cat "$CURD/roll.md")"

# A named curia whose digest does not exist is skipped without a write.
assert 'no digest is invented for an unknown id' \
  bash -c "! ls '$HOME/.claude/state/global/curia' | grep -qv '^\(test\|old\)-question\$'"

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

# --- no flock: a Stop still commits and pushes the state repo ----------------
# macOS ships no flock, and a bare `flock -w 90 9 || exit 0` silently skipped
# everything below the checkpoint write on every Mac Stop. The push lock is
# state_lock_wait's mkdir now. A flock that fails -- as a missing one does --
# shadows the real one on Linux, so this proves the macOS path everywhere.
assert 'the hook never calls flock' bash -c '! grep -qE "^[^#]*\bflock\b" "$1"' _ "$HOOK"

cat > "$BIN/flock" <<'EOF'
#!/bin/sh
touch "${FLOCK_CALLED:-/dev/null}"; exit 127
EOF
chmod +x "$BIN/flock"
export FLOCK_CALLED="$S/flock-called"

SRORIGIN="$S/state-origin.git"; SREPO="$S/state-repo"
git init -q --bare "$SRORIGIN"
git init -q -b main "$SREPO"
gitq "$SREPO" remote add origin "$SRORIGIN"
mkdir -p "$SREPO/state/global"; echo seed > "$SREPO/state/global/.seed"
gitq "$SREPO" add state; gitq "$SREPO" commit -m seed
gitq "$SREPO" push -u origin main

GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' CLAUDE_STATE_REPO="$SREPO" stop
eq 'no flock: the state repo got the session commit' \
  "State: work session ${SID:0:8}" "$(git -C "$SRORIGIN" log -1 --format=%s main 2>/dev/null | sed 's/ (.*//')"
assert 'no flock: the fake flock was never called' test ! -e "$FLOCK_CALLED"
assert 'no flock: the push lock is released after the Stop' test ! -e "$TMPDIR/claude-state-push.lock.d"
rm -f "$BIN/flock"; unset FLOCK_CALLED

# --- a conflicting state-repo pull is backed out, never left mid-rebase ---------
# Upstream and this clone both add one path with different bytes: the Stop's
# own commit conflicts on `pull --rebase`, and a rebase left in place would
# wedge the clone for every later Stop.
SRCLONE="$S/state-clone"
git clone -q -b main "$SRORIGIN" "$SRCLONE" >/dev/null 2>&1
rel=state/global/both.txt
echo upstream > "$SRCLONE/$rel"
gitq "$SRCLONE" add "$rel"; gitq "$SRCLONE" commit -m upstream-conflict; gitq "$SRCLONE" push origin main
echo local > "$SREPO/$rel"
rm -f "$SREPO/state/global/.last-state-push"   # past the push debounce

# In the cloud the clone dies with the VM, so a failed push is a reason.
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' CLAUDE_STATE_REPO="$SREPO" CLAUDE_CODE_REMOTE=true stop
assert 'conflicting pull: no rebase left in progress' \
  test ! -d "$(git -C "$SREPO" rev-parse --absolute-git-dir)/rebase-merge"
assert 'conflicting pull: no apply-backend rebase left either' \
  test ! -d "$(git -C "$SREPO" rev-parse --absolute-git-dir)/rebase-apply"
assert 'conflicting pull: still on main' git -C "$SREPO" symbolic-ref -q HEAD
assert 'conflicting pull: the verdict says the push failed' \
  grep -qE 'state-repo push failed' "$SREPO/state/global/log/auto/"*"-work-${SID:0:8}.md"
eq 'conflicting pull: and so does the metrics record' \
  'not archivable: state-repo push failed' \
  "$(jq -r .verdict "$SREPO/state/global/metrics/sessions/$SID.json")"

# The local twin: the same failed push on a machine that keeps its clone. The
# commit is the promise there, and it held (ruled for dotfiles#149).
rm -f "$SREPO/state/global/.last-state-push"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' CLAUDE_STATE_REPO="$SREPO" stop
assert 'conflicting pull, local: the push really failed' \
  test "$(git -C "$SRORIGIN" log -1 --format=%s main)" = upstream-conflict
eq 'conflicting pull, local: the verdict stays archivable' archivable \
  "$(sed -n 's/^\*\*Verdict:\*\* //p' "$SREPO/state/global/log/auto/"*"-work-${SID:0:8}.md" | head -1)"
eq 'conflicting pull, local: and so does the metrics record' archivable \
  "$(jq -r .verdict "$SREPO/state/global/metrics/sessions/$SID.json")"

# --- the board's items/ are committed like any other state ------------------
# No lint stands between an item and the commit; on_exit still releases the
# push lock. (The push above still conflicts, so this checks the commit only.)
it=state/global/items/1790000000d654192b.md
mkdir -p "$SREPO/state/global/items"
printf -- '- [ ] an item https://example.invalid/8\n' > "$SREPO/$it"
GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' CLAUDE_STATE_REPO="$SREPO" stop
assert 'items/: a new item is committed' \
  git -C "$SREPO" cat-file -e HEAD:"$it"
assert 'items/: the push lock is released' test ! -e "$TMPDIR/claude-state-push.lock.d"

# --- a live metrics-live.sh holding the per-session lock never blocks Stop (#161) --
# Pre-create $LIVE/<sid>.lock with meta naming this test process's own pid, so
# state_lock sees a live holder on this host and refuses to reclaim it -- the
# same shape a concurrent metrics-live.sh nag read-modify-write would leave.
LIVE="$HOME/.claude/state/global/metrics/live"
mkdir -p "$LIVE/$SID.lock"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$LIVE/$SID.lock/meta"

GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]'
printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s"}' "$TP" "$SID" "$WORK" \
  | GH_PRS="$GH_PRS" timeout 10 bash "$HOOK" >/dev/null 2>&1
rc=$?
CKPT=$(ls "$AUTO"/*"${SID:0:8}".md 2>/dev/null | head -1)
assert 'a held live lock never blocks Stop' test "$rc" -ne 124
assert 'the checkpoint is still written when the lock is held' test -n "$CKPT"
rm -rf "$LIVE/$SID.lock"

# --- the incident: the checkpoint and the 📦 notice answer once (dotfiles#149) --
# Two Stop hooks ran in parallel: the notice counted every session's unpushed
# state-repo commits and computed its own verdict while this hook was still
# committing, so the checkpoint said "archivable" and the notice said "not:
# state repo N commit(s) unpushed". stop-sequence.py runs them in order and
# the notice reads this hook's verdict back. A parallel session's unpushed
# commit sits in the clone; the work branch is clean, pushed, and has a PR.
SEQ="$HOOKS/stop-sequence.py"
SRORIGIN2="$S/state-origin2.git"; SREPO2="$S/state-repo2"
git init -q --bare "$SRORIGIN2"
git init -q -b main "$SREPO2"
gitq "$SREPO2" remote add origin "$SRORIGIN2"
mkdir -p "$SREPO2/state/global/log/auto"; echo seed > "$SREPO2/state/global/.seed"
gitq "$SREPO2" add state; gitq "$SREPO2" commit -m seed
gitq "$SREPO2" push -u origin main
other() {  # other <n> -- a parallel session's state commit, not pushed
  echo "other $1" > "$SREPO2/state/global/log/auto/2026-10-02T09-00-other-par$1.md"
  gitq "$SREPO2" add state; gitq "$SREPO2" commit -m "State: work session par$1"
}
SID3=incident-0000-1111-2222
sequence() {  # sequence -- run the real Stop sequence; prints metrics-live's stdout
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","hook_event_name":"Stop"}' \
      "$TP" "$SID3" "$WORK" \
    | GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]' CLAUDE_STATE_REPO="$SREPO2" \
      METRICS_STOP_HOUR=24 METRICS_NIGHT_END_HOUR=0 python3 "$SEQ" 2>/dev/null
}
box() { printf '%s' "$1" | jq -r '.systemMessage // ""' 2>/dev/null | grep '📦'; }
ck_verdict() {
  sed -n 's/^\*\*Verdict:\*\* //p' "$SREPO2/state/global/log/auto/"*"-work-${SID3:0:8}.md" | head -1
}

# Debounced: a push went out a moment ago, so this Stop only commits locally,
# and the clone ends holding the other session's commit and this one's.
other 1
date -u +%s > "$SREPO2/state/global/.last-state-push"
out=$(sequence)
assert 'incident, debounced: the clone holds unpushed commits' \
  test "$(git -C "$SREPO2" rev-list --count '@{u}..HEAD')" -ge 2
eq 'incident, debounced: the checkpoint says archivable' archivable "$(ck_verdict)"
eq 'incident, debounced: and the 📦 line agrees' \
  "📦 archivable. (claude/work ${SID3:0:8})" "$(box "$out")"
assert 'incident, debounced: the 📦 line never names the state repo' \
  bash -c '! grep -q "state repo" <<<"$1"' _ "$(box "$out")"

# A push in the same Stop: the sentinel is gone, so this Stop pushes its own
# commit and the parallel session's with it, while the notice waits its turn.
other 2
rm -f "$SREPO2/state/global/.last-state-push"
out=$(sequence)
eq 'incident, pushed: origin got this Stop'"'"'s commit' "State: work session ${SID3:0:8}" \
  "$(git -C "$SRORIGIN2" log -1 --format=%s main | sed 's/ (.*//')"
assert 'incident, pushed: and the parallel session'"'"'s with it' \
  test -n "$(git -C "$SRORIGIN2" log --format=%s main --grep='session par2' -1)"
eq 'incident, pushed: the checkpoint says archivable' archivable "$(ck_verdict)"
eq 'incident, pushed: and the 📦 line agrees' \
  "📦 archivable. (claude/work ${SID3:0:8})" "$(box "$out")"
assert 'incident, pushed: the 📦 line never names the state repo' \
  bash -c '! grep -q "state repo" <<<"$1"' _ "$(box "$out")"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
