#!/usr/bin/env bash
# Tests for grind-check. Run: bash bin/grind-check.test.sh
#
# One clean session reads all PASS; each failure mode of dotfiles#439 has a
# session file that trips exactly the row meant for it. gh is a stub serving
# canned files; git is real, against a local bare origin.
set -uo pipefail

CHECK="$(cd "$(dirname "$0")" && pwd)/grind-check"
pass=0; fail=0
S=$(mktemp -d); export S
trap 'rm -rf "$S"' EXIT
export HOME="$S/home" TMPDIR="$S/tmp" XDG_STATE_HOME="$S/xdg" GH_FIX="$S/fix" WORK_ITEM_DIR="$S/items"
export PATH="$S/bin:$PATH" GIT_CONFIG_NOSYSTEM=1
mkdir -p "$S/bin" "$HOME" "$TMPDIR/grind-worktrees" "$XDG_STATE_HOME/grind" "$WORK_ITEM_DIR" \
  "$GH_FIX"/{prs,prview,issues,comments,commits}

# --- gh stub: each question answered from a file under $GH_FIX, through the
# caller's own --jq filter. A file holding FAIL makes that call fail.
cat > "$S/bin/gh" <<'GH'
#!/bin/sh
filter=.; prev=""; repo=""; head=""
for a in "$@"; do
  case $prev in --jq) filter=$a ;; --repo) repo=$(printf '%s' "$a" | tr / _) ;; --head) head=$a ;; esac
  prev=$a
done
default=""
case "$1 $2" in
  "pr list") f=$GH_FIX/prs/${repo}__$head.json; default='[]' ;;
  "pr view") f=$GH_FIX/prview/${repo}__$3.json ;;
  "api repos/"*/comments) n=${2%/comments}; n=${n##*/}; r=$(printf '%s' "$2" | cut -d/ -f2,3 | tr / _)
                          f=$GH_FIX/comments/${r}__$n.json; default='[]' ;;
  "api repos/"*/issues/*) r=$(printf '%s' "$2" | cut -d/ -f2,3 | tr / _); f=$GH_FIX/issues/${r}__${2##*/}.json ;;
  "api repos/"*/commits/*) f=$GH_FIX/commits/${2##*/}.json ;;
  *) echo "gh stub: unexpected $*" >&2; exit 1 ;;
esac
if [ -f "$f" ]; then [ "$(cat "$f")" = FAIL ] && exit 1; jq -r "$filter" "$f"
elif [ -n "$default" ]; then printf '%s' "$default" | jq -r "$filter"
else exit 1; fi
GH
chmod +x "$S/bin/gh"

# --- a checkout of o/alpha with a bare origin whose path ends in o/alpha ----
git init -q --bare "$S/remotes/o/alpha"
git init -q -b main "$HOME/alpha"
g() { git -C "$HOME/alpha" -c user.email=t@example.invalid -c user.name=t -c commit.gpgsign=false "$@"; }
g remote add origin "$S/remotes/o/alpha"
g commit -q --allow-empty -m init
g push -q origin HEAD:refs/heads/main
branch_commit() {  # branch_commit <branch> [push] -> the new tip
  g branch -q "$1" main; g checkout -q "$1"; g commit -q --allow-empty -m "work on $1"
  [ "${2:-}" = push ] && g push -q origin "$1"
  g rev-parse HEAD; g checkout -q main
}
tip5=$(branch_commit grind-5 push)
branch_commit grind-9 >/dev/null
branch_commit grind-10 push >/dev/null
branch_commit grind-14 >/dev/null
g push -q origin grind-14:refs/heads/wip/grind-14
g update-ref -d refs/remotes/origin/wip/grind-14   # on origin, but not seen locally

# --- canned GitHub ------------------------------------------------------------
put() { mkdir -p "$(dirname "$GH_FIX/$1")"; printf '%s\n' "$2" > "$GH_FIX/$1"; }
for n in 5 6 7 8 9 10 12 14 21 22 23 24; do put "issues/o_alpha__$n.json" '{"number":'"$n"'}'; done
put issues/o_beta__12.json '{"number":12}'
for n in 30 31; do put "issues/o_alpha__$n.json" '{"number":'"$n"',"pull_request":{}}'; done
put prs/o_alpha__grind-5.json '[{"number":40,"state":"OPEN","createdAt":"2026-10-03T10:10:00Z","url":"u","headRefOid":"'"$tip5"'","labels":[]}]'
put prs/o_alpha__grind-card-fix-the-widget.json '[{"number":41,"state":"OPEN","createdAt":"2026-10-03T10:20:00Z","url":"u","headRefOid":"x","labels":[]}]'
put prs/o_alpha__grind-8.json '[{"number":42,"state":"OPEN","createdAt":"2026-10-03T10:30:00Z","url":"u","headRefOid":"x","labels":[]}]'
put prs/o_beta__grind-5.json '[{"number":7,"state":"OPEN","createdAt":"2026-10-03T10:12:00Z","url":"u","headRefOid":"x","labels":[]}]'
put prs/o_alpha__grind-7.json FAIL
put prview/o_alpha__30.json '{"number":30,"state":"OPEN","url":"u","headRefName":"feature-x","labels":[{"name":"awaiting-human"}],"commits":[{"oid":"c30","committedDate":"2026-09-01T00:00:00Z"}]}'
put prview/o_alpha__31.json '{"number":31,"state":"OPEN","url":"u","headRefName":"feature-y","labels":[],"commits":[{"oid":"c31","committedDate":"2026-10-03T10:40:00Z"}]}'
cat > "$WORK_ITEM_DIR/1790000000aaaaaaaa.md" <<'MD'
# Fix the widget

## Brief
Fix the widget ([link](https://github.com/o/alpha/issues/99)) id: 1790000000aaaaaaaa

## Log
2026-10-02T10:00:00Z 11111111 status=open owner=agent repo=o/alpha parent=- model=- effort=-
MD
cat > "$WORK_ITEM_DIR/1790000001bbbbbbbb.md" <<'MD'
# Tidy everything

## Brief
Tidy everything, anywhere id: 1790000001bbbbbbbb

## Log
2026-10-02T10:00:00Z 11111111 status=open owner=agent repo=- parent=- model=- effort=-
MD

# --- session fixtures: the clean one, and a jq patch of it per case ----------
SID=grind-20261003T100000Z
clean=$(jq -n --arg cwd "$HOME/alpha" '{
  repo: "o/alpha", project: "", item_budget: 5, session_budget: 20, pause_every: 3, prs: 0,
  kinds: "pr issue card", policy: "finish-first",
  items: [
    {ref: "o/alpha#5", status: "done", cost: 1.0, model: "sonnet", effort: "medium", cost_estimated: false, claim_released: true, wip_branch: null},
    {ref: "o/alpha#30", status: "done", cost: 0.8, model: "sonnet", effort: "medium", cost_estimated: false, claim_released: true, wip_branch: null},
    {ref: "card:fix-the-widget", status: "done", cost: 0.5, model: "sonnet", effort: "medium", cost_estimated: false, claim_released: true, wip_branch: null}
  ],
  lock: {pid: 4242, ppid: 1, hostname: "h", user: "u", tty: "none", invoked_cwd: $cwd, grind_rev: "abc1234",
         claude_session_id: "none", lock_acquired_at: "2026-10-03T10:00:01Z", last_heartbeat_at: "2026-10-03T10:59:00Z",
         current_item: null, current_item_started_at: null},
  ended: {at: "2026-10-03T11:00:00Z", reason: "queue-exhausted", exit: 0}}')
item() { printf '{"ref":"%s","status":"%s","cost":%s,"claim_released":true,"wip_branch":%s}' "$1" "$2" "$3" "${4:-null}"; }

# mk <case> <jq patch> -- a session dir of its own, so row 4's scan of
# earlier files sees only what the case puts there.
mk() { mkdir -p "$S/st/$1"; printf '%s' "$clean" | jq "$2" > "$S/st/$1/$SID.json"; }
run() { OUT=$("$CHECK" "$S/st/$1/$SID.json" --json 2>&1); RC=$?; }
verdict() { printf '%s' "$OUT" | jq -r --argjson n "$1" '.rows[] | select(.n == $n) | .verdict' 2>/dev/null; }
evidence() { printf '%s' "$OUT" | jq -r --argjson n "$1" '.rows[] | select(.n == $n) | .evidence' 2>/dev/null; }
ok()  { pass=$((pass + 1)); }
bad() { fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
eq()  { if [ "$2" = "$3" ]; then ok; else bad "$1: want [$2] got [$3]" "$OUT"; fi; }
# expect <case> <row> <verdict> <what>
expect() { run "$1"; eq "$4 (row $2)" "$3" "$(verdict "$2")"; }

t0=$(date +%s)

# --- the clean run: every row PASS, exit 0 ----------------------------------
mk clean .
run clean
eq 'clean: exit 0' 0 "$RC"
eq 'clean: 13 rows' 13 "$(printf '%s' "$OUT" | jq '.rows | length')"
eq 'clean: every row PASS' PASS "$(printf '%s' "$OUT" | jq -r '[.rows[].verdict] | unique | join(",")')"
TEXT=$("$CHECK" "$S/st/clean/$SID.json")
eq 'text output: a header and 13 rows' 14 "$(printf '%s\n' "$TEXT" | wc -l | tr -d ' ')"

# --- usage ----------------------------------------------------------------------
"$CHECK" >/dev/null 2>&1; eq 'no argument is a usage error' 2 $?
"$CHECK" grind-nope >/dev/null 2>&1; eq 'an unknown session is a usage error' 2 $?
cp "$S/st/clean/$SID.json" "$XDG_STATE_HOME/grind/"
"$CHECK" "$SID" >/dev/null 2>&1; eq 'a bare session id resolves under XDG_STATE_HOME' 0 $?

# --- an older file: no ended, no claim_released -> N/A, not FAIL -------------
mk old 'del(.ended) | .items |= map(del(.claim_released, .wip_branch, .cost_estimated, .model, .effort))'
expect old 1 N/A 'an old file has no ended field'
eq 'and nothing else fails on it' 0 "$RC"
case $(evidence 7) in *"not recorded (N/A)"*) ok ;; *) bad 'row 7 says claim_released is not recorded' "$OUT" ;; esac

# 1. ended
mk no-ended 'del(.ended)'
expect no-ended 1 FAIL 'a new-schema file with no ended record'
eq 'any FAIL exits 1' 1 "$RC"
mk ended-error '.ended.reason = "error" | .ended.exit = 1'
expect ended-error 1 FAIL 'a run that ended by error'
mk ended-cadence '.ended.reason = "pause-cadence"'
expect ended-cadence 1 PASS 'a cadence pause is a clean end'
mk ended-band '.ended.reason = "pause-band"'
expect ended-band 1 PASS 'a review-band pause is a clean end'
mk ended-odd '.ended.reason = "finished"'
expect ended-odd 1 FAIL 'a reason grind never writes'

# 2. spend: total 2.30; limit = session budget + a quarter of the item cap
mk overspent '.session_budget = 1'
expect overspent 2 FAIL '$2.30 over $1 + $1.25'
mk within-tolerance '.session_budget = 1.1'
expect within-tolerance 2 PASS '$2.30 within $1.10 + $1.25'
mk no-item-budget 'del(.item_budget)'
expect no-item-budget 2 PASS 'no item_budget: the pr cap stands in, not zero'
eq 'and row 3 still passes with that cap' PASS "$(verdict 3)"
case $(evidence 2) in *"pr cap stands in"*) ok ;; *) bad 'row 2 says the pr cap stood in' "$OUT" ;; esac

# 3. over twice the cap with nothing delivered
mk over-cap ".items += [$(item o/alpha#6 failed 10.5)]"
expect over-cap 3 FAIL 'a failed item at $10.50 against a $5 cap'
mk over-cap-done '.items[0].cost = 10.5'
expect over-cap-done 3 PASS 'a done item over the cap delivered something'

# 4. re-attempts
mk thrice ".items = [$(item o/alpha#5 failed 0), $(item o/alpha#5 failed 0)] + .items"
expect thrice 4 FAIL 'one ref attempted three times'
mk redone .
printf '%s' "$clean" | jq '.items = [.items[0]] | del(.ended)' > "$S/st/redone/grind-20261002T100000Z.json"
expect redone 4 FAIL 'an issue done in an earlier session, attempted again'
mk refixup .
printf '%s' "$clean" | jq '.items = [.items[1]]' > "$S/st/refixup/grind-20261002T100000Z.json"
expect refixup 4 PASS 'a PR done earlier may come back as a fixup'

# 5. done claims hold on GitHub now
mk done-no-pr ".items += [$(item o/alpha#12 "done" 0.3)]"
expect done-no-pr 5 FAIL 'a done issue with no PR on grind-12'
mk done-gh-down ".items += [$(item o/alpha#7 "done" 0.3)]"
expect done-gh-down 5 FAIL 'a gh lookup that fails is not a PASS'

# 6. a success recorded as a failure
mk false-fail ".items += [$(item o/alpha#8 failed 1.0)]"
expect false-fail 6 FAIL 'a failed issue whose branch got a PR in the run'
mk false-fail-pr ".items += [$(item o/alpha#31 failed 1.0)]"
expect false-fail-pr 6 FAIL 'a failed fixup whose head moved in the run'

# 7. claims released
mk unreleased '.items[0].claim_released = false'
expect unreleased 7 FAIL 'claim_released false'
mk stamp-left .
put comments/o_alpha__40.json '[{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=1791023400 machine=host-abc -->\n**Claimed**"}]'
expect stamp-left 7 FAIL 'a stamp written inside the run window is still on the PR'
put comments/o_alpha__40.json '[{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=1790000000 machine=host-abc -->\n**Claimed**"}]'
expect stamp-left 7 PASS 'a stamp from before the run is not the run'"'"'s'
mk stamp-sid '.items[0].worker_sid = "cafef00d-1234"'
put comments/o_alpha__40.json '[{"id":1,"body":"<!-- claim-stamp sid=cafef00d epoch=1790000000 machine=host-abc -->\n**Claimed**"}]'
expect stamp-sid 7 FAIL 'a stamp carrying the recorded worker sid, whatever its age'
put comments/o_alpha__40.json '[{"id":1,"body":"<!-- claim-stamp sid=deadbeef epoch=1791023400 machine=host-abc -->\n**Claimed**"}]'
expect stamp-sid 7 PASS 'with worker_sid recorded, another session'"'"'s stamp inside the window is not the run'"'"'s'
mk stamp-sid-null '.items |= map(.worker_sid = null)'
expect stamp-sid-null 7 FAIL 'a null worker_sid falls back to the window'
rm -f "$GH_FIX/comments/o_alpha__40.json"

# 8. stranded work: unpushed commits, a kept dirty worktree, a wip exemption
mk unpushed ".items += [$(item o/alpha#9 failed 0.6)]"
expect unpushed 8 FAIL "grind-9's commit is on no remote"
mk wip-on-origin ".items += [$(item o/alpha#14 failed 0.6 '"wip/grind-14"')]"
expect wip-on-origin 8 PASS 'the same, recorded as a wip branch that is on origin'
mk wip-missing ".items += [$(item o/alpha#14 failed 0.6 '"wip/grind-nope"')]"
expect wip-missing 8 FAIL 'a recorded wip branch that origin does not have'
g worktree add -q "$TMPDIR/grind-worktrees/10" grind-10
: > "$TMPDIR/grind-worktrees/10/half-done.txt"
mk dirty ".items += [$(item o/alpha#10 failed 0.6)]"
expect dirty 8 FAIL 'a kept worktree with uncommitted edits'

# 9. the right repo
mk wrong-repo ".items += [$(item o/beta#12 blocked 0.1)]"
expect wrong-repo 9 FAIL 'alpha#5'"'"'s branch opened a PR in beta during the run'
mk general-card ".items += [$(item card:tidy-everything blocked 0.1)]"
expect general-card 9 FAIL 'a general card that names no repo'
# No invoked_cwd on record: the reviewer's own cwd must not stand in for it.
git init -q "$HOME/beta" && git -C "$HOME/beta" remote add origin https://github.com/o/beta.git
mk no-cwd 'del(.lock.invoked_cwd)'
OUT=$(cd "$HOME/beta" && "$CHECK" "$S/st/no-cwd/$SID.json" --json 2>&1); RC=$?
eq 'run from a checkout of o/beta, row 9 does not search beta (row 9)' PASS "$(verdict 9)"
case $(evidence 9) in *beta*) bad 'row 9 searched the reviewer cwd' "$OUT" ;; *) ok ;; esac

# 10. the lock
mk lock-held .
mkdir -p "$S/st/lock-held/locks/o_alpha.lock"; echo '{"pid":4242}' > "$S/st/lock-held/locks/o_alpha.lock/meta.json"
expect lock-held 10 FAIL 'the lock dir still holds this run'"'"'s pid'
mk lock-other .
mkdir -p "$S/st/lock-other/locks/o_alpha.lock"; echo '{"pid":999}' > "$S/st/lock-other/locks/o_alpha.lock/meta.json"
expect lock-other 10 PASS 'a lock another run holds is not this one'"'"'s'
mk rev-unknown '.lock.grind_rev = "unknown"'
expect rev-unknown 10 FAIL 'grind_rev unknown'
mk tty-garbage '.lock.tty = "not a tty"'
expect tty-garbage 10 FAIL 'tty "not a tty"'

# 11. one broken dependency blocking every worker
mk wall ".items += [$(item o/alpha#21 blocked 0.25), $(item o/alpha#22 failed 0.26), $(item o/alpha#23 blocked 0.24)]"
expect wall 11 FAIL 'three cheap failures in a row in one repo'
mk no-wall ".items += [$(item o/alpha#21 blocked 0.25), $(item o/alpha#22 failed 0.26), .items[0], $(item o/alpha#23 blocked 0.24)]"
expect no-wall 11 PASS 'a success breaks the streak'

# 12. an empty run file
mk empty '.items = [] | del(.ended)'
expect empty 12 FAIL 'no items and no ended'

# 13. scratch files left by a run that died mid-item
mk mid-item .
: > "$S/st/mid-item/$SID.rc"
expect mid-item 13 FAIL 'a leftover .rc'
mk mid-write .
: > "$S/st/mid-write/$SID.json.tmp"
expect mid-write 13 FAIL 'a leftover .json.tmp from a record half written'

printf '%d passed, %d failed (%ss)\n' "$pass" "$fail" "$(( $(date +%s) - t0 ))"
[ "$fail" -eq 0 ]
