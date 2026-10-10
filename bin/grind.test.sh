#!/usr/bin/env bash
# Tests for grind. Run: bash bin/grind.test.sh
#
# What matters: --dry-run lists every Ready (non-blocked) item and the exact
# command per item without spending anything; a real run parses cost/tokens
# out of the worker's JSON, prints the running-total/percent line, and pauses
# -- with the exact resume command -- on session budget, an outlier item cost,
# or the pause-every cadence; a carded or blocked worker is logged and not
# treated as a failure; a done or carded claim that GitHub does not bear out
# is UNVERIFIED, keeps its worktree and retries; the worker gets a permission
# mode that can run git and gh; --resume skips what a prior run already
# accounted for. gh and claude are both faked; no real `claude -p` is ever
# invoked.
set -uo pipefail

GRIND="$(cd "$(dirname "$0")" && pwd)/grind"
GRIND_WORK_ITEM="$(cd "$(dirname "$0")" && pwd)/work-item"
export GRIND_WORK_ITEM
pass=0; fail=0
S=$(mktemp -d); export S
cleanup() { rm -rf "$S"; }
trap cleanup EXIT

mkdir -p "$S/bin" "$S/home" "$S/state" "$S/repo" "$S/nogit"
export HOME="$S/home" XDG_STATE_HOME="$S/state" TMPDIR="$S/tmp"
mkdir -p "$TMPDIR"
export GH_LOG="$S/gh.log" CLAUDE_LOG="$S/claude.log"
: > "$GH_LOG"; : > "$CLAUDE_LOG"
export PATH="$S/bin:$PATH"

git -C "$S/repo" init -q
git -C "$S/repo" config user.email t@example.invalid
git -C "$S/repo" config user.name t
git -C "$S/repo" remote add origin https://github.com/o/alpha.git
git -C "$S/repo" commit -q --allow-empty -m init
# origin has main: only what a worker commits on top of it is on no remote.
git -C "$S/repo" update-ref refs/remotes/origin/main HEAD
cd "$S/repo" || exit 1

# --- canned Ready queue --------------------------------------------------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 20, "title": "Second item", "body": "do the second thing\n\nmodel: opus\neffort: high", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]},
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
  {"number": 9, "title": "Blocked item", "body": "not yet", "url": "https://github.com/o/alpha/issues/9", "labels": [{"name": "ready"}, {"name": "blocked"}]}
]
JSON

# What grind's verification asks gh for, canned. `pr list` answers the
# `done` check (a PR whose head is the item's branch), `issue view` the
# `carded` one (a comment added while the worker ran). Both are queried with
# a --jq filter, so the shim applies whatever filter grind passed to the
# canned document rather than second-guessing it.
# The far-future timestamp stands for "opened by the worker that just ran":
# grind's PR check is time-bounded, so a PR must post-date the worker's start.
cat > "$S/pr-list.json" <<'JSON'
[{"createdAt": "2999-01-01T00:00:00Z", "updatedAt": "2999-01-01T00:00:00Z", "state": "OPEN"}]
JSON
cat > "$S/issue-comments.json" <<'JSON'
{"comments": []}
JSON

cat > "$S/bin/gh" <<GH
#!/bin/sh
echo "\$*" >> "$GH_LOG"
filter=""; prev=""
for a in "\$@"; do
  [ "\$prev" = "--jq" ] && filter=\$a
  prev=\$a
done
[ -n "\$filter" ] || filter="."
case "\$1 \$2" in
  "issue list") cat "$S/ready.json" ;;
  "pr list")    jq -r "\$filter" "$S/pr-list.json" ;;
  "issue view") jq -r "\$filter" "$S/issue-comments.json" ;;
  "pr view")    f="$S/prview/\$(printf '%s' "\$3" | tr '/:' '__').json"; [ -f "\$f" ] && jq -r "\$filter" "\$f" ;;
  "api repos/"*"/sub_issues"*) f="$S/subs/\$(printf '%s' "\${2%%\?*}" | tr / _).json"; if [ "\$(cat "\$f" 2>/dev/null)" = FAIL ]; then exit 1; elif [ -f "\$f" ]; then cat "\$f"; else echo '[]'; fi ;;
  "api repos/"*"/issues/"*) if [ -f "$S/updated-at" ]; then cat "$S/updated-at"; else echo 2999-01-01T00:00:00Z; fi ;;
  "api user")   echo grind-me ;;
  *) echo "gh shim: unexpected \$*" >&2; exit 1 ;;
esac
GH
chmod +x "$S/bin/gh"

# fake worklist -- the bucket record grind reads its queue from, built at
# call time from the same canned files the gh shim serves: ready.json is the
# issue buckets (blocked label -> buckets.blocked), audit.json (when the --prs
# section has written it) the not_ready PRs, cards.json the ## Claude's cards.
cat > "$S/bin/worklist" <<WL
#!/bin/bash
echo "\$*" >> "$S/worklist.log"
ready=\$(jq -c '[.[] | select(.labels|map(.name)|index("blocked")|not) | {kind:"issue", repo:"o/alpha", number, title, url, body, labels:(.labels|map(.name))}]' "$S/ready.json")
blocked=\$(jq -c '[.[] | select(.labels|map(.name)|index("blocked")) | {kind:"issue", repo:"o/alpha", number, title, url, body, labels:(.labels|map(.name))}]' "$S/ready.json")
prs='[]'; [ -f "$S/audit.json" ] && prs=\$(jq -s -c '[.[] | select(.section == "unfinished" or .section == "stale-label") | {kind:"pr", repo:"o/alpha", number, title, url, isDraft:false, labels, author}]' "$S/audit.json")
cards='[]'; [ -f "$S/cards.json" ] && cards=\$(cat "$S/cards.json")
awaiting='[]'; [ -f "$S/awaiting-human.json" ] && awaiting=\$(cat "$S/awaiting-human.json")
repos='["o/alpha"]'
case "\$1" in
  -*) [ "\$PWD" = "$S/home/beta" ] && { repos='["o/beta"]'  # --here answers for the cwd
        ready=\$(jq -c '[.[] | select(.repo == null) | {kind:"issue", repo:"o/beta", number, title, url, body, labels:(.labels|map(.name))}]' "$S/ready-beta.json"); } ;;
  *) repos='["o/alpha","o/beta","o/gamma"]'
  ready=\$(jq -c -s '.[0] + [.[1][] | .repo = (.repo // "o/beta")]' <(printf '%s' "\$ready") <(jq -c '[.[] | {kind:"issue", repo, number, title, url, body, labels:(.labels|map(.name))}]' "$S/ready-beta.json")) ;; esac
jq -nc --argjson r "\$ready" --argjson b "\$blocked" --argjson p "\$prs" --argjson c "\$cards" --argjson ah "\$awaiting" --argjson repos "\$repos" \
  '{owner:"o", repos:\$repos, buckets:{awaiting_human:\$ah, queued:[], not_ready:\$p, ready:\$r, blocked:\$b, untriaged:[], stranded:[], rulings:[], humans:[], claudes:\$c}}'
# A broken store: the record on stdout, then the cause on stderr and exit 3,
# as the real worklist --json does.
[ -f "$S/worklist-broken" ] && { echo 'worklist: Board: BROKEN STORE -- work-item list failed (exit 4): python exploded; this is not an empty board' >&2; exit 3; }
exit 0
WL
chmod +x "$S/bin/worklist"

# fake claude -- reads the prompt from stdin (unused), writes canned
# stream-json lines read from $S/claude-replies/<n>.json for the current
# item (an assistant event followed by a result event, one per line, as the
# real worker now streams), defaulting to a flat two-line reply. grind reads
# claude's stdout line by line now, so the shim must emit newline-delimited
# JSON, never one blob.
mkdir -p "$S/claude-replies"
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
stage="$S/claude-stage/\$n"
[ -d "\$stage" ] && { mkdir -p .claude-staging && cp -r "\$stage"/. .claude-staging/; }
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"
# real git for everything except `push`, which is logged and turned into a
# no-op -- grind's staging move (#172) commits and pushes for real, and this
# suite has no reachable remote to push to.
REAL_GIT=$(command -v git)
export GIT_PUSH_LOG="$S/git-push.log"; : > "$GIT_PUSH_LOG"
cat > "$S/bin/git" <<GITSHIM
#!/bin/sh
skip_next=0; subcmd=""
for a in "\$@"; do
  if [ "\$skip_next" = 1 ]; then skip_next=0; continue; fi
  case "\$a" in
    -C) skip_next=1; continue ;;
    -*) continue ;;
  esac
  subcmd=\$a; break
done
if [ "\$subcmd" = push ]; then
  printf '%s\n' "\$*" >> "$GIT_PUSH_LOG"
  [ -z "\${GIT_PUSH_FAIL:-}" ]; exit
fi
# How many items the session file held when a worktree was removed: a removal
# before the item is recorded shows up as one short.
case " \$* " in *" worktree remove "*)
  f=\$(ls -t "$S"/state/grind/*.json 2>/dev/null | head -1)
  printf '%s\n' "\$(jq '.items | length' "\$f" 2>/dev/null)" >> "$S/wt-remove.log" ;;
esac
exec "$REAL_GIT" "\$@"
GITSHIM
chmod +x "$S/bin/git"
# reply <cost> <status> <n> -- writes the two-line stream-json shape above
# (one assistant usage event, one result event) to $S/claude-replies/<n>.json.
reply() {
  jq -nc '{type:"assistant", message:{usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}}}' \
    > "$S/claude-replies/$3.json"
  jq -nc --argjson cost "$1" --arg status "$2" \
    '{type:"result", total_cost_usd:$cost, usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}, result:("done work\nGRIND_STATUS: " + $status)}' \
    >> "$S/claude-replies/$3.json"
}

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
has()  { if grep -Eq -- "$2" <<<"$OUT"; then ok; else bad "$1 (missing /$2/)" "$OUT"; fi; }
lacks(){ if grep -Eq -- "$2" <<<"$OUT"; then bad "$1 (has /$2/)" "$OUT"; else ok; fi; }
eq()   { if [ "$2" = "$3" ]; then ok; else bad "$1: want [$2] got [$3]"; fi; }
assert() { local d=$1; shift; if "$@"; then ok; else bad "$d"; fi; }
# grind's records of GitHub items (items carrying home=) outlive a run on
# purpose; every test but the record's own starts without them, so an item
# grind looked at in an earlier test is not reordered behind untouched ones.
forget_records() {
  for d in "$S/home/.claude/state/global/items" "${WORK_ITEM_DIR:-}"; do
    [ -n "$d" ] && [ -d "$d" ] || continue
    grep -l ' home=' "$d"/*.md 2>/dev/null | xargs rm -f
  done
}
run() { rm -f "$S/claude-next"; [ -n "${KEEP_RECORDS:-}" ] || forget_records; OUT=$(sh "$GRIND" "$@" 2>&1); RC=$?; }
calls_claude() { wc -l < "$CLAUDE_LOG" | tr -d ' '; }
latest_session() { ls -t "$S/state/grind"/*.json 2>/dev/null | head -1; }

# --- --dry-run: lists Ready items, top (lowest number) first, blocked excluded ---
: > "$GH_LOG"
run --dry-run
eq 'exit 0' 0 "$RC"
eq 'no claude call in dry-run' 0 "$(calls_claude)"
has 'first item is the lower-numbered one' '^\[1/2\] o/alpha#5 -- First item$'
has 'second item follows' '^\[2/2\] o/alpha#20 -- Second item$'
lacks 'blocked item excluded' 'alpha#9'
has 'a worktree command is shown' 'git -C .* worktree add -b grind-5'
has 'the claude command is shown, with defaults; its budget is the item hard cap, 3x its soft cap' 'claude -p <issue o/alpha#5 body> --output-format stream-json --verbose --max-budget-usd 15.00 --model sonnet --effort medium'
assert 'dry-run wrote no state file' bash -c '! ls '"$S"'/state/grind/*.json >/dev/null 2>&1'

# --- --model and --effort are refused; the item carries them -------------------------
run --dry-run --model opus
eq 'a --model flag is refused' 2 "$RC"
has 'the refusal names the item fields' '`model:` and `effort:`'
run --dry-run --effort high
eq 'an --effort flag is refused' 2 "$RC"
run --dry-run --item-budget 2
has 'an item with fields runs on its own pair' 'alpha#20 body>.*--model opus --effort high'
has 'an item without fields gets the one default pair' 'alpha#5 body>.*--max-budget-usd 6.00 --model sonnet --effort medium'

# --- a real run: cost/tokens parsed, running total and percent printed ----------
rm -f "$S/claude-replies"/*.json
reply 1.00 "done" 1
reply 2.00 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 20 --pause-every 5
eq 'exit 0' 0 "$RC"
eq 'two claude invocations' 2 "$(calls_claude)"
has 'first item line: cost, tokens, running total, percent' '^o/alpha#5: First item -- sonnet, \$1\.00, 150 tokens -- running \$1\.00 / \$20\.00 -- 5%$'
has 'second item line: running total accumulates' '^o/alpha#20: Second item -- opus, \$2\.00, 150 tokens -- running \$3\.00 / \$20\.00 -- 15%$'
has 'queue exhausted, final tally' '^done: queue exhausted \(2 issue\)\. Running total \$3\.00 / \$20\.00\. 0 skipped\.$'
has 'INFO: session line names repo, count, model, caps' 'INFO  session grind-.* on o/alpha: 2 item\(s\) \(2 issue; finish-first\), item budget \$5\.00 \(scaled per item; hard 3x\), session \$20\.00, pause every 5'
eq 'the state file records each item'"'"'s own pair' 'sonnet/medium opus/high' "$(jq -r '[.items[] | "\(.model)/\(.effort)"] | join(" ")' "$(latest_session)")"
has 'INFO: item start line' 'INFO  \[1/2\] starting o/alpha#5 -- First item'
has 'INFO: worker line names the permission mode' 'INFO  worker running: .*--permission-mode bypassPermissions'
has 'INFO: worker exit line' 'INFO  worker exited 0 after [0-9]+s'
sess=$(latest_session)
eq 'two items recorded in state' 2 "$(jq '.items | length' "$sess")"

# --- the worker's permission mode lets it run git and gh -------------------------
# acceptEdits, the old default, denies every Bash call: a worker could edit
# files and then neither commit them nor open a PR, which is how run
# grind-20260912T210131Z spent $4.39 and produced nothing.
eq 'the default mode is bypassPermissions, not acceptEdits' 2 \
  "$(grep -c -- '--permission-mode bypassPermissions' "$CLAUDE_LOG")"
lacks 'acceptEdits is never passed by default' 'permission-mode acceptEdits'
# A headless worker that polls with Monitor or ScheduleWakeup spent $14 of a
# $15 cap on one item (claude#59); the flag removes both tools outright.
eq 'every worker is started without Monitor and ScheduleWakeup' 2 \
  "$(grep -c -- '--disallowedTools Monitor ScheduleWakeup' "$CLAUDE_LOG")"
: > "$CLAUDE_LOG"
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
run --session-budget 100 --pause-every 1 --permission-mode acceptEdits
assert '--permission-mode still overrides the default' \
  grep -q -- '--permission-mode acceptEdits' "$CLAUDE_LOG"

# --- the prompt contract names the branch and all three statuses -----------------
PROMPT=$(cat "$S/prompt.txt")
prompt_has() { if grep -Fq -- "$2" <<<"$PROMPT"; then ok; else bad "$1 (missing [$2])"; fi; }
prompt_has 'the issue body is the prompt' 'do the first thing'
prompt_has 'the contract names the item' 'Grind orchestration contract for o/alpha#5'
prompt_has 'it names the branch the worker is on' 'branch grind-5'
prompt_has 'it tells the worker to commit, push and open the PR' 'open the PR yourself with gh'
prompt_has 'done is offered' 'GRIND_STATUS: done'
prompt_has 'carded is offered' 'GRIND_STATUS: carded'
prompt_has 'blocked is offered' 'GRIND_STATUS: blocked'
prompt_has 'it warns that the claim is checked' 'records the item'

# --- heartbeat: shows a live, ~-marked token/cost estimate before the item
# finishes, accumulated from two assistant events; the final line still uses
# the exact total_cost_usd -----------------------------------------------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
echo '{"type":"assistant","message":{"usage":{"input_tokens":10000,"output_tokens":5000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000}}}'
sleep 0.3
echo '{"type":"assistant","message":{"usage":{"input_tokens":5000,"output_tokens":5000,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
sleep 2
echo '{"type":"result","total_cost_usd":0.90,"usage":{"input_tokens":15000,"output_tokens":10000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000},"result":"GRIND_STATUS: done"}'
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10 --heartbeat 1
eq 'exit 0' 0 "$RC"
has 'heartbeat line carries elapsed time, an input-side token count and ~$ estimate, labelled so -- both events accumulated, output left out (15000+20000+3000=38000 -> 38k)' \
  'still working on o/alpha#5 \([0-9]+m elapsed, ~38k input tokens, ~\$[0-9]+\.[0-9]{2} so far, input only\)'
has 'the final line still uses the exact total_cost_usd, not the estimate' '^o/alpha#5: First item -- sonnet, \$0\.90,'

# --- heartbeat: claude -p emits one assistant event per content block, and
# every block of one message repeats that message's identical usage -- three
# blocks of the same message must count once, not three times ------------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
echo '{"type":"assistant","message":{"id":"msg_1","usage":{"input_tokens":10000,"output_tokens":5000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000}}}'
sleep 0.3
echo '{"type":"assistant","message":{"id":"msg_1","usage":{"input_tokens":10000,"output_tokens":5000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000}}}'
sleep 0.3
echo '{"type":"assistant","message":{"id":"msg_1","usage":{"input_tokens":10000,"output_tokens":5000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000}}}'
sleep 2
echo '{"type":"result","total_cost_usd":0.30,"usage":{"input_tokens":10000,"output_tokens":5000,"cache_read_input_tokens":20000,"cache_creation_input_tokens":3000},"result":"GRIND_STATUS: done"}'
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10 --heartbeat 1
eq 'exit 0' 0 "$RC"
has 'heartbeat dedupes repeated blocks of the same message.id -- three identical 33000-input-token blocks count once, not 99000' \
  'still working on o/alpha#5 \([0-9]+m elapsed, ~33k input tokens, ~\$[0-9]+\.[0-9]{2} so far, input only\)'

# restore the multi-item ready queue and the reply-driven claude shim
cat > "$S/ready.json" <<'JSON'
[
  {"number": 20, "title": "Second item", "body": "do the second thing", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]},
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
  {"number": 9, "title": "Blocked item", "body": "not yet", "url": "https://github.com/o/alpha/issues/9", "labels": [{"name": "ready"}, {"name": "blocked"}]}
]
JSON
rm -f "$S/state/grind"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\${SPEND_GATE_USD:-} \${SPEND_GATE_HANDOFF:-}" >> "$S/claude-env.log"
echo "bg-disabled=\${CLAUDE_CODE_DISABLE_BACKGROUND_TASKS:-}" >> "$S/claude-bg.log"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
f=\$(ls -t "$S/state/grind"/*.json 2>/dev/null | head -1); [ -z "\$f" ] || cp "\$f" "$S/session-mid.json"
echo \$((n + 1)) > "$S/claude-next"
stage="$S/claude-stage/\$n"
[ -d "\$stage" ] && { mkdir -p .claude-staging && cp -r "\$stage"/. .claude-staging/; }
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"

# --- threshold lines: each fires once, even when one item crosses several ------
# Only two Ready items exist, so item 1 crosses 25%, item 2 jumps straight to
# 100% (and the budget-reached pause): 50% and 75% both announce on item 2.
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 5.00 "done" 1    # 25% of 20
reply 15.00 "done" 2   # +75% = 100% -> budget reached, 50% and 75% lines fire
: > "$CLAUDE_LOG"
run --session-budget 20 --pause-every 10
has '25% line on the first item' '\*\*\* 25% of session budget spent \(\$5\.00 / \$20\.00\) \*\*\*'
has '50% line also fires on the second item' '\*\*\* 50% of session budget spent \(\$20\.00 / \$20\.00\) \*\*\*'
has '75% line on the second item' '\*\*\* 75% of session budget spent \(\$20\.00 / \$20\.00\) \*\*\*'
eq 'no line printed twice' 1 "$(printf '%s\n' "$OUT" | grep -c '25% of session budget')"
has 'pauses when the session budget is reached' '^pause: session budget reached \(\$20\.00 / \$20\.00\)\.'
sess=$(latest_session)
has 'exact resume command printed' '^resume: grind --resume grind-'

# --- --resume skips already-processed items and keeps the same session file -----
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'exit 0' 0 "$RC"
eq 'no more items to run -- queue already exhausted' 0 "$(calls_claude)"
has 'says the queue is done' 'queue exhausted'
eq 'state file unchanged (still 2 items)' 2 "$(jq '.items | length' "$sess")"

# --- --resume refreshes session identity (pid, claude_session_id) in the
# state file, not just budgets/model/repo (#190): the original session's pid
# is long dead by the time --resume runs it from a fresh process, so the
# state file's diagnostics must reflect the resuming process, not the one
# that crashed. Two resumes, two different CLAUDE_SESSION_ID values -------------
export CLAUDE_SESSION_ID=resume-probe-before
run --resume "$session_id"
before_pid=$(jq -r '.lock.pid' "$sess")
before_claude_session=$(jq -r '.lock.claude_session_id' "$sess")
export CLAUDE_SESSION_ID=resume-probe-after
run --resume "$session_id"
after_pid=$(jq -r '.lock.pid' "$sess")
after_claude_session=$(jq -r '.lock.claude_session_id' "$sess")
unset CLAUDE_SESSION_ID
assert 'each --resume records the resuming process'"'"'s own pid, not a stale one' \
  bash -c "[ '$before_pid' != '$after_pid' ]"
eq 'the first resume picked up its own claude_session_id' 'resume-probe-before' "$before_claude_session"
eq 'the second resume refreshed claude_session_id again' 'resume-probe-after' "$after_claude_session"

# --- a worktree that cannot be created is a WARN, counted, and fails the run ----
# grind-5 already exists from earlier runs; checking it out elsewhere makes
# grind's branch -D and worktree add -b both fail for #5.
git -C "$S/repo" worktree add -q "$S/wt5" grind-5 >/dev/null 2>&1 \
  || git -C "$S/repo" worktree add -q -b grind-5 "$S/wt5" >/dev/null 2>&1
rm -f "$S/state/grind"/*.json
run --session-budget 100 --pause-every 10
eq 'exit 1 when an item was skipped' 1 "$RC"
has 'WARN line for the skip names the item and the branch' 'WARN  skipping o/alpha#5 -- could not create worktree .* on branch grind-5'
has 'the other item still runs' '^o/alpha#20: Second item --'
has 'tally counts the skip' 'queue exhausted .*\. .* 1 skipped\.$'
has 'ERR line at the end' 'ERR   1 item\(s\) skipped'

# same skip, but the run ends on the cadence pause instead of the queue: still exit 1
rm -f "$S/state/grind"/*.json
run --session-budget 100 --pause-every 1
eq 'exit 1 when a skip precedes a pause' 1 "$RC"
has 'the pause line still prints' '^pause: 1 items processed this run'
has 'ERR line after the pause' 'ERR   1 item\(s\) skipped'
git -C "$S/repo" worktree remove -f "$S/wt5" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-5 >/dev/null 2>&1

# --- outlier pause: one item costs more than twice the running median -----------
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 1.00 "done" 1
reply 3.00 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
has 'pauses on the outlier, not the budget' '^pause: o/alpha#20 cost \$3\.00, more than twice the running median \(\$1\.00\)'
eq 'only the second item ran before the pause' 2 "$(calls_claude)"

# equal-to-twice-median is not an outlier -- confirms a strict >, not >=.
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 1.00 "done" 1
reply 2.00 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
lacks 'exactly 2x median does not trip the outlier pause' '^pause: o/alpha#20 cost'
has 'runs to completion instead' '^done: queue exhausted'
eq 'the session file says the queue ran out, exit 0' 'queue-exhausted 0' "$(jq -r '"\(.ended.reason) \(.ended.exit)"' "$(latest_session)")"

# --- caps: soft and hard, per item and per run (claude#43) -----------------------
# What matters: an item's soft cap is --item-budget scaled by its model's price
# against Sonnet's and its effort weight, or its budget: when that is higher;
# its hard cap is 3x, the worker's --max-budget-usd, never cut (Solace on #47:
# soft stops, not hard ones). Dispatch stops only once spend reaches the run's
# soft budget, however big the next item's cap; nothing at the run level ends a
# worker. A cap flag on --resume wins over the session file and is written to
# it.
cp "$S/ready.json" "$S/ready.json.saved"
cat > "$S/ready.json" <<'JSON'
[{"number": 5, "title": "Sonnet medium", "body": "no fields", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
 {"number": 20, "title": "Opus high", "body": "model: opus\neffort: high\nbudget: $10", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]},
 {"number": 21, "title": "Sonnet low", "body": "effort: low", "url": "https://github.com/o/alpha/issues/21", "labels": [{"name": "ready"}]},
 {"number": 22, "title": "Budgeted", "body": "budget: 12\nbudget: tbd", "url": "https://github.com/o/alpha/issues/22", "labels": [{"name": "ready"}]}]
JSON
# caps_of <n> -> "soft $X hard $Y" off item #n's dry-run budget line
caps_of() {
  grep -A3 -E "^\[[0-9]+/[0-9]+\] o/alpha#$1 " <<<"$OUT" | grep -m1 'budget:' \
    | sed -E 's/.*soft (\$[0-9.]+) .*hard (\$[0-9.]+) \(its --max-budget-usd.*/soft \1 hard \2/'
}
rm -f "$S/state/grind"/*.json
run --dry-run
eq 'sonnet/medium: the item budget, hard 3x' 'soft $5.00 hard $15.00' "$(caps_of 5)"
eq 'opus/high: 2.5x the price, 2x the effort; its lower budget: loses; hard 3x, past the session' 'soft $25.00 hard $75.00' "$(caps_of 20)"
eq 'sonnet/low: half' 'soft $2.50 hard $7.50' "$(caps_of 21)"
eq 'a higher budget: wins; a later budget: that is not a number is no field' 'soft $12.00 hard $36.00' "$(caps_of 22)"
run --dry-run --session-budget 6
eq 'a small session cuts no item cap' 'soft $25.00 hard $75.00' "$(caps_of 20)"
run --dry-run --session-hard-budget 30
eq 'there is no run hard budget flag' 2 "$RC"
for flag in --item-budget --session-budget; do
  run --dry-run "$flag" abc
  eq "$flag abc is a usage error" 2 "$RC"
  has "and names the flag" "^grind: $flag abc is not a number of dollars$"
done
run --dry-run --pause-every x
eq 'a --pause-every that is not a count is a usage error' 2 "$RC"
# an item whose cap passes what is left of the soft budget still starts while
# spend is under it; each worker gets 3x its own soft cap, whatever is left
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 2.00 "done" 1
reply 5.00 "done" 2
: > "$CLAUDE_LOG"; : > "$S/claude-env.log"
run --session-budget 6 --pause-every 10
eq 'each worker gets its soft cap as the spend gate line, and the hand-off file (claude#69)' \
  '5.00 HANDOFF.md|25.00 HANDOFF.md' "$(paste -sd'|' "$S/claude-env.log")"
eq 'two workers ran: the opus item started with $4 of soft budget left' 2 "$(calls_claude)"
eq 'each worker gets 3x its soft cap, the session notwithstanding ($15, then $75)' '15.00 75.00' \
  "$(grep -oE -- '--max-budget-usd [0-9.]+' "$CLAUDE_LOG" | awk '{print $2}' | paste -sd' ' -)"
PROMPT=$(cat "$S/prompt.txt")
prompt_has 'the worker is told its soft cap as the stop' 'stop and report at ~$25.00'
prompt_has 'and its hard stop' 'Your hard stop is $75.00'
prompt_has 'and that past its soft cap only the hand-off write is left' 'Past ~$25.00 a hook denies every tool but one Write'
has 'dispatch stops once spend reaches the soft budget' '^pause: session budget reached \(\$7\.00 / \$6\.00\)\.'
eq 'the session file says why it ended' 'pause-budget 0' "$(jq -r '"\(.ended.reason) \(.ended.exit)"' "$(latest_session)")"
# --resume with cap flags applies them and records them
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 1.00 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
sess=$(latest_session); session_id=$(basename "$sess" .json)
eq 'the first run recorded its caps' '5 100 1' "$(jq -r '"\(.item_budget) \(.session_budget) \(.pause_every)"' "$sess")"
reply 1.00 "done" 1
reply 1.00 "done" 2
: > "$CLAUDE_LOG"
run --resume "$session_id" --item-budget 7 --session-budget 50 --pause-every 2
eq 'the resumed run applies --pause-every' 2 "$(calls_claude)"
eq 'and records the flags' '7 50 2' \
  "$(jq -r '"\(.item_budget) \(.session_budget) \(.pause_every)"' "$sess")"
eq 'and that the item budget was given' 1 "$(jq -r '.item_budget_set' "$sess")"
eq 'its workers run on the new item budget: opus/high at 3x $35' '105.00' \
  "$(grep -oE -- '--max-budget-usd [0-9.]+' "$CLAUDE_LOG" | awk 'NR == 1 {print $2}')"
# a resume that cannot write its caps back stops, saying so, before any spend
chmod a-w "$S/state/grind"
: > "$CLAUDE_LOG"
run --resume "$session_id" --item-budget 9
chmod u+w "$S/state/grind"
eq 'a resume that cannot record its caps exits 1' 1 "$RC"
has 'and says so' '^grind: cannot write the resumed caps to '
eq 'before any worker ran' 0 "$(calls_claude)"
eq 'and the file keeps the caps it had' '7 50 2' \
  "$(jq -r '"\(.item_budget) \(.session_budget) \(.pause_every)"' "$sess")"
mv "$S/ready.json.saved" "$S/ready.json"
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json

# --- --resume clears the last run's .ended once it holds the lock ---------------
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json "$S/session-mid.json"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
sess=$(latest_session)
eq 'first run paused on cadence' 'pause-cadence' "$(jq -r '.ended.reason' "$sess")"
run --resume "$(basename "$sess" .json)"
eq 'the resumed run started a worker' 2 "$(calls_claude)"
eq 'mid-run, the session file has no stale .ended' 'null' "$(jq -c '.ended' "$S/session-mid.json")"
assert 'and it ends with its own' test "$(jq -r '.ended.reason' "$sess")" != null

# --- carded: logged, not a failure, item still counted toward pause-every -------
# The card is verified: the issue gained a comment while the worker ran.
cat > "$S/issue-comments.json" <<'JSON'
{"comments": [{"createdAt": "2999-01-01T00:00:00Z"}]}
JSON
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 0.50 "carded" 1
reply 0.50 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 2
has 'carded item logged distinctly' '^carded: o/alpha#5 -- First item'
sess=$(latest_session)
eq 'carded status recorded' 'carded' "$(jq -r '.items[0].status' "$sess")"
has 'pauses on cadence after two items (one carded)' '^pause: 2 items processed this run'

# --- verification: a claim that does not check out is UNVERIFIED ----------------
# Run grind-20260912T210131Z reported "carded" twice and "done" once and left
# no card, no issue comment and no PR behind. Both claims are now checked.

# `done` with no PR on the item's branch
cat > "$S/pr-list.json" <<'JSON'
[]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'a done claim with no PR is UNVERIFIED, and says why' \
  '^UNVERIFIED: o/alpha#5 -- First item -- worker claimed success but no PR opened or pushed to on head branch grind-5, nor any other PR opened during the run \(\$0\.50, 150 tokens, running \$0.50 / \$100.00 -- 0%\); will retry on --resume'
lacks 'no success line for an unverified item' '^o/alpha#5: First item --'
assert 'gh was asked for a PR whose head is the item branch' \
  grep -q -- 'pr list --repo o/alpha --head grind-5 --state all' "$GH_LOG"
has 'the worktree is kept for inspection' 'WARN  keeping worktree .*grind-worktrees/alpha/5 on branch grind-5 for inspection'
assert 'and it really is still on disk' test -d "$TMPDIR/grind-worktrees/alpha/5"
sess=$(latest_session)
eq 'recorded as unverified' unverified "$(jq -r '.items[0].status' "$sess")"
eq 'its cost is still counted' 0.50 "$(jq -r '.items[0].cost' "$sess")"

# The worker handed its work to a background tool call and ended its turn
# (2026-10-04, public-issue-guard, $6.13): the item is unverified, and says so.
cat > "$S/pr-list.json" <<'JSON'
[]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json "$S/claude-bg.log"
{ jq -nc '{type:"assistant", message:{content:[{type:"tool_use",name:"Agent",input:{description:"port",prompt:"x",run_in_background:true}}],usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}}}'
  jq -nc '{type:"result", total_cost_usd:0.5, usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}, result:"It is running now.\nGRIND_STATUS: done"}'; } > "$S/claude-replies/1.json"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'a backgrounded worker with no PR is named, not just unverified' \
  '^UNVERIFIED: o/alpha#5 -- First item -- worker claimed success but worker used run_in_background'
assert "every worker runs with background tasks disabled" grep -q "bg-disabled=1" "$S/claude-bg.log"

# a PR left behind by an earlier attempt does not verify a fresh claim: the
# branch name is deterministic, so a stale PR is always sitting there on a
# retry, and without the time bound a worker that did nothing would pass.
cat > "$S/pr-list.json" <<'JSON'
[{"createdAt": "2001-01-01T00:00:00Z", "updatedAt": "2001-01-02T00:00:00Z", "state": "CLOSED"}]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'a stale PR from an earlier attempt does not verify this run' \
  '^UNVERIFIED: o/alpha#5 -- First item -- worker claimed success but no PR opened or pushed to on head branch grind-5'

# an open PR the worker pushed to during the run does verify, even though it
# was opened long before -- the case of a retry adding commits to its own PR
cat > "$S/pr-list.json" <<'JSON'
[{"createdAt": "2001-01-01T00:00:00Z", "updatedAt": "2999-01-01T00:00:00Z", "state": "OPEN"}]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'a pushed-to open PR verifies' '^o/alpha#5: First item -- sonnet, \$0\.50,'

# ...and --resume retries an unverified item, reusing the branch the kept
# worktree holds
cat > "$S/pr-list.json" <<'JSON'
[]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
sess=$(latest_session)
session_id=$(basename "$sess" .json)
cat > "$S/pr-list.json" <<'JSON'
[{"createdAt": "2999-01-01T00:00:00Z", "updatedAt": "2999-01-01T00:00:00Z", "state": "OPEN"}]
JSON
rm -f "$S/claude-replies"/*.json
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --resume "$session_id" --pause-every 1
eq 'an unverified item is retried on resume' 1 "$(calls_claude)"
has 'the retry, with a PR this time, is a plain success line' '^o/alpha#5: First item -- sonnet, \$0\.50,'

# --- .claude/ writes: staged content is moved into place and committed by
# grind itself before the PR-exists check runs (dotfiles#172 -- every write
# under .claude/ is refused inside the sandboxed worker, whatever the
# permission mode, so it stages under .claude-staging/ instead) ---------------
cat > "$S/pr-list.json" <<'JSON'
[{"createdAt": "2999-01-01T00:00:00Z", "updatedAt": "2999-01-01T00:00:00Z", "state": "OPEN"}]
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -rf "$S/claude-stage"; : > "$GIT_PUSH_LOG"
mkdir -p "$S/claude-stage/1/hooks"
echo 'echo staged' > "$S/claude-stage/1/hooks/example.test.sh"
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'the item still reports a plain success' '^o/alpha#5: First item -- sonnet, \$0\.50,'
has 'grind logs the move' 'moved staged \.claude/ files into place and pushed for o/alpha#5'
assert 'the staged file landed under .claude/ on the branch' \
  bash -c 'git -C "'"$S"'/repo" show grind-5:.claude/hooks/example.test.sh 2>/dev/null | grep -q "echo staged"'
assert 'nothing is left under .claude-staging/ on the branch' \
  bash -c '! git -C "'"$S"'/repo" show grind-5:.claude-staging >/dev/null 2>&1'
eq 'grind pushed exactly once for the staged files' 1 "$(wc -l < "$GIT_PUSH_LOG" | tr -d ' ')"
assert 'it pushes to the item branch by name -- grind-<n> has no upstream' \
  grep -q 'push -q origin HEAD:refs/heads/grind-5$' "$GIT_PUSH_LOG"
rm -rf "$S/claude-stage"

# a .claude-staging/<x> path that was itself already tracked (a stale leftover
# from before this move-and-commit logic, or a legacy force-add) must not
# survive the move as a permanently-stale tracked entry -- `git add .claude`
# alone never stages a deletion outside its own pathspec, so the fix stages
# both pathspecs (or an explicit `git rm -r .claude-staging`).
main_before=$(git -C "$S/repo" rev-parse HEAD)
mkdir -p "$S/repo/.claude-staging/hooks"
echo 'echo old' > "$S/repo/.claude-staging/hooks/example.test.sh"
git -C "$S/repo" add .claude-staging/hooks/example.test.sh
git -C "$S/repo" commit -q -m "test setup: legacy tracked .claude-staging path"
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -rf "$S/claude-stage"; : > "$GIT_PUSH_LOG"
mkdir -p "$S/claude-stage/1/hooks"
echo 'echo staged' > "$S/claude-stage/1/hooks/example.test.sh"
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'the item still reports a plain success (legacy tracked staging path)' '^o/alpha#5: First item -- sonnet, \$0\.50,'
assert 'the fresh staged content landed under .claude/ on the branch' \
  bash -c 'git -C "'"$S"'/repo" show grind-5:.claude/hooks/example.test.sh 2>/dev/null | grep -q "echo staged"'
assert 'the previously-tracked .claude-staging path does not survive the move as stale content' \
  bash -c '! git -C "'"$S"'/repo" show grind-5:.claude-staging/hooks/example.test.sh >/dev/null 2>&1'
rm -rf "$S/claude-stage"
# undo the legacy-tracked-path commit on the base branch so it doesn't leak
# into the scenarios that follow.
git -C "$S/repo" reset -q --hard "$main_before"

# An earlier attempt's unpushed commits are pushed as wip/ before a retry
# clears them; these scenarios each start from a clean slate instead.
forget_item5() {
  git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/alpha/5" >/dev/null 2>&1
  git -C "$S/repo" update-ref -d refs/remotes/origin/wip/grind-5 >/dev/null 2>&1
  git -C "$S/repo" branch -D grind-5 >/dev/null 2>&1; true
}
# a push that fails leaves the item unverified and its worktree kept: the
# worker's PR exists, but without the .claude/ change the item needed
forget_item5
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$GIT_PUSH_LOG"
mkdir -p "$S/claude-stage/1/hooks"
echo 'echo staged' > "$S/claude-stage/1/hooks/example.test.sh"
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
GIT_PUSH_FAIL=1 run --session-budget 100 --pause-every 1
has 'a failed staging push warns' 'could not move staged \.claude/ files into place and push them for o/alpha#5'
has 'and the item is UNVERIFIED, saying why' '^UNVERIFIED: o/alpha#5 -- First item -- worker claimed success but its staged \.claude/ files were never pushed'
has 'and its worktree is kept' 'keeping worktree .*grind-worktrees/alpha/5 on branch grind-5 for inspection'
# blocked keeps its status -- retrying it would only block again -- but the
# worktree holding the unpushed .claude/ change is still kept
forget_item5
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$GIT_PUSH_LOG"
reply 0.50 "blocked" 1
GIT_PUSH_FAIL=1 run --session-budget 100 --pause-every 1
has 'a blocked item with a failed staging push stays blocked' '^blocked: o/alpha#5 -- First item'
has 'and still keeps its worktree' 'keeping worktree .*grind-worktrees/alpha/5 on branch grind-5 for inspection'
rm -rf "$S/claude-stage"

# an item with nothing staged is unaffected -- no move, no extra push, no log line
forget_item5
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$GIT_PUSH_LOG"
reply 0.50 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
lacks 'no staging log line when nothing was staged' 'moved staged \.claude/ files'
eq 'no push logged either' 0 "$(wc -l < "$GIT_PUSH_LOG" | tr -d ' ')"

# `carded` with an untouched item store and no new comment on the issue. An
# item whose log is all in the past is not a new one: grind reads the log
# lines' timestamps, not the file's mtime.
export WORK_ITEM_DIR="$S/carded-items"
mkdir -p "$WORK_ITEM_DIR"
printf '# an old item\n\n## Brief\n\n## Log\n2001-01-01T00:00:00Z feedface status=open owner=agent\n' \
  > "$WORK_ITEM_DIR/17909840241dc56754.md"
cat > "$S/issue-comments.json" <<'JSON'
{"comments": [{"createdAt": "2001-01-01T00:00:00Z"}]}
JSON
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "carded" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'a carded claim with nothing written is UNVERIFIED, and says why' \
  '^UNVERIFIED: o/alpha#5 -- First item -- worker claimed success but no item created or logged and no new comment on the issue'
lacks 'not logged as carded' '^carded: o/alpha#5'

# an item logged during the run counts too, without any issue comment
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
printf '%s feedface note\n' "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$WORK_ITEM_DIR/17909840241dc56754.md"
echo '{"type":"result","total_cost_usd":0.50,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: carded"}'
GH
chmod +x "$S/bin/claude"
rm -f "$S/state/grind"/*.json
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'an item logged during the run verifies the card' '^carded: o/alpha#5 -- First item'
# so does a new item file
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
printf '# new\n\n## Brief\n\n## Log\n%s feedface status=open owner=human-ruling\n' "\$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$WORK_ITEM_DIR/17909850001a2b3c4d.md"
echo '{"type":"result","total_cost_usd":0.50,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: carded"}'
GH
chmod +x "$S/bin/claude"
rm -f "$S/state/grind"/*.json
rm -f "$WORK_ITEM_DIR/17909850001a2b3c4d.md" "$WORK_ITEM_DIR/17909840241dc56754.md"
printf '# an old item\n\n## Brief\n\n## Log\n2001-01-01T00:00:00Z feedface status=open owner=agent\n' \
  > "$WORK_ITEM_DIR/17909840241dc56754.md"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
has 'an item created during the run verifies the card' '^carded: o/alpha#5 -- First item'
unset WORK_ITEM_DIR

# --- blocked: a third status, logged, recorded, not retried ---------------------
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
reply 0.50 "blocked" 1
reply 0.50 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 2
has 'blocked item logged distinctly' '^blocked: o/alpha#5 -- First item \(\$0\.50, 150 tokens, running \$0.50 / \$100.00 -- 0%\)'
lacks 'a blocked item is not a failure' '^FAILED: o/alpha#5'
lacks 'nor an unverified claim -- blocked asserts nothing to check' '^UNVERIFIED: o/alpha#5'
sess=$(latest_session)
eq 'blocked status recorded' blocked "$(jq -r '.items[0].status' "$sess")"
eq 'the next item still runs' 2 "$(calls_claude)"
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'a blocked item is accounted for, not retried on resume' 0 "$(calls_claude)"

# --- pause-every cadence, exact count ---------------------------------------------
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 0.10 "done" 1
reply 0.10 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
eq 'stops after exactly one item' 1 "$(calls_claude)"
has 'pause names the cadence' 'pause every 1'

# --- done-ref matching is whole-entry, not substring (issue #5 vs #50) ----------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 5, "title": "Item five", "body": "b", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
  {"number": 50, "title": "Item fifty", "body": "b", "url": "https://github.com/o/alpha/issues/50", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 0.10 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 1
sess=$(latest_session)
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
rm -f "$S/claude-replies"/*.json
reply 0.10 "done" 1
run --resume "$session_id"
eq 'item 50 is not skipped as a substring match of done #5' 1 "$(calls_claude)"
has 'item 50 actually ran' '^o/alpha#50: Item fifty'

# --- --resume seeds running_total/costs from prior-run item costs ----------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 1, "title": "A", "body": "b", "url": "https://github.com/o/alpha/issues/1", "labels": [{"name": "ready"}]},
  {"number": 2, "title": "B", "body": "b", "url": "https://github.com/o/alpha/issues/2", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 15.00 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 20 --pause-every 1
has 'first run spends $15 of a $20 session budget' 'running \$15\.00 / \$20\.00'
sess=$(latest_session)
session_id=$(basename "$sess" .json)
rm -f "$S/claude-replies"/*.json
reply 15.00 "done" 1
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'resume runs the one remaining item' 1 "$(calls_claude)"
has 'running total continues from the seeded $15, not from $0' 'running \$30\.00 / \$20\.00'
has 'pauses on budget once the seeded total plus this item crosses it' '^pause: session budget reached \(\$30\.00 / \$20\.00\)\.'

# a session already at/over budget on resume pauses before spending anything
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 25.00 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 20 --pause-every 1
sess=$(latest_session)
session_id=$(basename "$sess" .json)
rm -f "$S/claude-replies"/*.json
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'no further spend once already over budget from a prior run' 0 "$(calls_claude)"
has 'pauses immediately using the seeded total' '^pause: session budget reached \(\$25\.00 / \$20\.00\)\.'

# --- a failed claude invocation with no PR behind it is recorded failed, at an
# estimated cost; --resume retries it -------------------------------------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 7, "title": "Flaky item", "body": "b", "url": "https://github.com/o/alpha/issues/7", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
cp "$S/pr-list.json" "$S/pr-list.saved"; echo '[]' > "$S/pr-list.json"
rm -f "$S/claude-replies"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
exit 1
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
has 'a failed invocation is logged as a failure, not a normal cost line' '^FAILED: o/alpha#7 .*did not complete \(no result event\); cost estimated'
lacks 'no cost line for the failed item' '^o/alpha#7: Flaky item --'
sess=$(latest_session)
eq 'the failed item is recorded failed, its cost marked estimated' 'failed true' "$(jq -r '.items[0] | "\(.status) \(.cost_estimated)"' "$sess")"
eq 'a worker that never named a session records worker_sid null' 'null' "$(jq -r '.items[0].worker_sid' "$sess")"
mv "$S/pr-list.saved" "$S/pr-list.json"

# restore the real claude shim and confirm --resume retries the failed item
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'the failed item retried on resume' 1 "$(calls_claude)"
has 'retried item now succeeds' '^o/alpha#7: Flaky item --'
eq 'the retry is recorded beside the failure' 'failed done' "$(jq -r '[.items[].status] | join(" ")' "$sess")"

# --- a worker that exits non-zero WITH a JSON result and no PR: cost kept, retried --
rm -f "$S/state/grind"/*.json
cp "$S/pr-list.json" "$S/pr-list.saved"; echo '[]' > "$S/pr-list.json"
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
echo '{"type":"result","is_error":true,"total_cost_usd":5.00,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"Budget exceeded"}'
exit 1
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
has 'logged as a failure' '^FAILED: o/alpha#7 .*will retry on --resume'
# The worker's exit status has to survive the subshell that runs it: under
# `set -e` a non-zero `wait` used to kill that subshell before it wrote the
# rc file, so grind reported `worker exited ` and then died on
# `[: Illegal number:` while deciding the item's status.
has 'the non-zero exit status reaches the exit line' 'INFO  worker exited 1 after [0-9]+s'
lacks 'no shell error from an empty exit status' 'Illegal number'
has 'the worker result text is on the FAILED line' '^FAILED: o/alpha#7 .*worker reported an error: Budget exceeded \('
sess=$(latest_session)
eq 'recorded in state as failed' failed "$(jq -r '.items[0].status' "$sess")"
eq 'its cost is kept' 5.00 "$(jq -r '.items[0].cost' "$sess")"
has 'running total includes the failed spend' 'running \$5\.00 / \$100\.00'
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'failed-with-cost item retried on resume' 1 "$(calls_claude)"
mv "$S/pr-list.saved" "$S/pr-list.json"

# --- a non-zero exit alone makes the item failed, unless GitHub bears the claim out --
# Nothing in the result event says anything went wrong here: `is_error` is
# absent and the worker even claims done. Only claude's exit status carries
# the failure, so this is the case that goes silently wrong the moment the
# rc file is lost. The claim is still checked first -- the cap can land after
# the push -- so with no PR behind it the item is failed.
rm -f "$S/state/grind"/*.json
cp "$S/pr-list.json" "$S/pr-list.saved"; echo '[]' > "$S/pr-list.json"
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
echo '{"type":"result","total_cost_usd":0.25,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
exit 3
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
has 'the exact exit status is reported' 'INFO  worker exited 3 after [0-9]+s'
lacks 'no shell error deciding the status' 'Illegal number'
has 'a non-zero exit with an unbacked claim is a failure' '^FAILED: o/alpha#7'
lacks 'not reported as a normal completed item' '^o/alpha#7: Flaky item --'
lacks 'failed, not unverified -- the error is the better diagnosis' 'UNVERIFIED'
has 'a failed item keeps its worktree' 'keeping worktree .*/7 on branch grind-7'
sess=$(latest_session)
eq 'recorded failed on exit status alone' failed "$(jq -r '.items[0].status' "$sess")"
mv "$S/pr-list.saved" "$S/pr-list.json"
rm -f "$S/state/grind"/*.json
run --session-budget 100 --pause-every 10
has 'a non-zero exit whose claim checks out is done' '^o/alpha#7: Flaky item --'
lacks 'and not failed' '^FAILED: o/alpha#7'

# restore the real claude shim
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"

# --- --repo naming a repo with no local checkout ---------------------------------
run --repo o/other
eq 'exit 1 when neither the cwd nor $HOME/other is a checkout of --repo' 1 "$RC"
has 'says where it looked' "no local checkout of o/other \(not the cwd, not $HOME/other\)"
has 'and that nothing is left in scope' 'no repo in scope has a local checkout'
run --repo o/alpha fam
eq 'exit 2 when --repo and a project are both given' 2 "$RC"
has 'and says they are two scopes' 'two scopes; pass one'

# --- a broken store: worklist --json exits 3 with the cause on stderr ----------------
touch "$S/worklist-broken"
run --dry-run
eq 'a broken store stops grind' 1 "$RC"
has 'and grind names the cause, not the record' '^grind: worklist --json failed: worklist: Board: BROKEN STORE -- work-item list failed'
rm -f "$S/worklist-broken"

# --- a project: one queue over every repo carrying the topic ---------------------
# The fake worklist answers a project name with two repos; beta's checkout is
# $HOME/beta (the cwd is alpha's), gamma has none and is dropped on one line.
git -C "$S/home" init -q beta && git -C "$S/home/beta" remote add origin https://github.com/o/beta.git \
  && git -C "$S/home/beta" -c user.email=t@example.invalid -c user.name=t commit -q --allow-empty -m init
cat > "$S/ready.json" <<'JSON'
[{"number": 5, "title": "Alpha item", "body": "alpha", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]}]
JSON
cat > "$S/ready-beta.json" <<'JSON'
[{"number": 5, "title": "Beta item", "body": "beta", "url": "https://github.com/o/beta/issues/5", "labels": [{"name": "ready"}]},
 {"number": 7, "title": "Gamma item", "body": "gamma", "url": "https://github.com/o/gamma/issues/7", "labels": [{"name": "ready"}], "repo": "o/gamma"}]
JSON
rm -f "$S/state/grind"/*.json
run --dry-run fam
eq 'a project dry-run exits 0' 0 "$RC"
grep -q '^fam --json --fresh$' "$S/worklist.log" && ok || bad 'worklist was called with the project name'
has 'the repo without a checkout is dropped, on one line' "^grind: no local checkout of o/gamma \(not the cwd, not $HOME/gamma\); it is out of this run$"
has 'alpha item cut from the cwd' "o/alpha#5 -- Alpha item"
has 'alpha worktree under its repo name' "git -C $S/repo worktree add -b grind-5 $TMPDIR/grind-worktrees/alpha/5"
has 'beta item cut from $HOME/beta' "git -C $S/home/beta worktree add -b grind-5 $TMPDIR/grind-worktrees/beta/5"
lacks 'gamma item never queued' 'o/gamma#7'
: > "$S/worklist.log"
cd "$S/nogit" && run --dry-run --repo o/beta; cd "$S/repo" || exit 1
eq '--repo from outside any checkout exits 0' 0 "$RC"
grep -q '^--here --json --fresh$' "$S/worklist.log" && ok || bad 'the record was fetched with --here'
has 'from the named repo checkout: its item is queued' '^\[1/1\] o/beta#5 -- Beta item$'
lacks 'and nothing from the cwd-less alpha' 'o/alpha#5'
run fam
eq 'a project run exits 0' 0 "$RC"
has 'the session line names the project' 'INFO  session grind-.* on project fam: 2 item\(s\)'
eq 'the state file records the project' fam "$(jq -r .project "$(latest_session)")"
eq 'both items recorded done' 'o/alpha#5=done o/beta#5=done' "$(jq -r '[.items[] | "\(.ref)=\(.status)"] | join(" ")' "$(latest_session)")"
assert 'beta worktree removed from beta checkout' bash -c '! git -C '"$S"'/home/beta worktree list | grep -q grind-worktrees'
: > "$CLAUDE_LOG"
run --resume "$(basename "$(latest_session)" .json)"
eq 'a resume takes the project from the session file' 0 "$RC"
has 'and finds both items already accounted for' '^done: queue exhausted'
eq 'so no worker ran' 0 "$(calls_claude)"
mkdir -p "$S/state/grind/locks/project_fam.lock"; jq -n '{pid: 999999, hostname: "elsewhere"}' > "$S/state/grind/locks/project_fam.lock/meta.json"
run fam
eq 'a project lock is keyed by the project, not a repo' 1 "$RC"
has 'and names the project' 'another grind is already running against project fam'
rm -rf "$S/state/grind/locks/project_fam.lock"
rm -f "$S/state/grind"/*.json

# --- a project grind takes each member repo's lock; one held elsewhere drops ---
# that repo from the run, and the rest of the family still runs.
mkdir -p "$S/state/grind/locks/o_beta.lock"
jq -n --argjson pid "$$" --arg host "$(uname -n)" '{pid:$pid, hostname:$host}' > "$S/state/grind/locks/o_beta.lock/meta.json"
run fam
eq 'a project run with one member held still exits 0' 0 "$RC"
has 'the held member is dropped, on one WARN line' "WARN  o/beta: another grind holds it \\(pid $$\\); it is out of this run"
eq 'only the free member is worked' 'o/alpha#5=done' "$(jq -r '[.items[] | "\(.ref)=\(.status)"] | join(" ")' "$(latest_session)")"
assert 'the other grind keeps its member lock' test -d "$S/state/grind/locks/o_beta.lock"
assert 'this run released the member lock it took' bash -c '[ ! -d "$1/state/grind/locks/o_alpha.lock" ]' _ "$S"
rm -f "$S/state/grind"/*.json
mkdir -p "$S/state/grind/locks/o_alpha.lock"; cp "$S/state/grind/locks/o_beta.lock/meta.json" "$S/state/grind/locks/o_alpha.lock/"
: > "$CLAUDE_LOG"
run fam
eq 'every member held: exit 1' 1 "$RC"
has 'and says so' 'every repo in project fam is held by another grind'
eq 'no worker ran' 0 "$(calls_claude)"
rm -rf "$S/state/grind/locks/o_alpha.lock" "$S/state/grind/locks/o_beta.lock" "$S/ready-beta.json"
rm -f "$S/state/grind"/*.json

# --- sub-issues: a parent is worked through its open Ready sub-issues ----------
# Each one is cut from its own repo's checkout: beta's is $HOME/beta (above),
# gamma has none. #13 is Ready on its own too and must be worked once, as
# #5's; #14 is not Ready and #15 is closed, so neither is worked; #6 has no
# sub-issues and is one unit, as ever.
sub() { jq -nc --arg r "$1" --argjson n "$2" --arg s "$3" --arg l "$4" \
  '{repository_url: "https://api.github.com/repos/\($r)", number: $n, title: "Sub \($n)", body: "sub \($n)",
    html_url: "https://github.com/\($r)/issues/\($n)", state: $s, labels: [{name: $l}]}'; }
mkdir -p "$S/subs"
{ sub o/beta 12 open ready; sub o/alpha 13 open ready; sub o/beta 14 open triage; sub o/alpha 15 closed ready; } \
  | jq -s . > "$S/subs/repos_o_alpha_issues_5_sub_issues.json"
sub o/gamma 3 open ready | jq -s . > "$S/subs/repos_o_alpha_issues_8_sub_issues.json"
echo FAIL > "$S/subs/repos_o_alpha_issues_9_sub_issues.json"  # gh api fails for #9
cat > "$S/ready.json" <<'JSON'
[{"number": 5, "title": "Two-repo parent", "body": "parent", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
 {"number": 6, "title": "No sub-issues", "body": "whole", "url": "https://github.com/o/alpha/issues/6", "labels": [{"name": "ready"}]},
 {"number": 8, "title": "Gamma parent", "body": "parent", "url": "https://github.com/o/alpha/issues/8", "labels": [{"name": "ready"}]},
 {"number": 9, "title": "Unreadable parent", "body": "parent", "url": "https://github.com/o/alpha/issues/9", "labels": [{"name": "ready"}]},
 {"number": 13, "title": "Sub 13", "body": "sub 13", "url": "https://github.com/o/alpha/issues/13", "labels": [{"name": "ready"}]}]
JSON
run --dry-run
eq 'a sub-issue dry-run exits 0' 0 "$RC"
has 'the beta sub-issue is an item, named for its parent' '\] o/beta#12 -- Sub 12 \(part of o/alpha#5\)$'
has 'cut from the beta checkout, under its repo name' "git -C $S/home/beta worktree add -b grind-12 $TMPDIR/grind-worktrees/beta/12$"
has 'the same-repo sub-issue is an item' '\] o/alpha#13 -- Sub 13 \(part of o/alpha#5\)$'
eq 'and is queued once, not again on its own' 1 "$(grep -c 'o/alpha#13 --' <<<"$OUT")"
lacks 'a parent with open sub-issues is not itself worked' 'o/alpha#(5|8) --'
lacks 'a sub-issue that is not Ready is not worked' 'o/beta#14'
lacks 'nor a closed one' 'o/alpha#15'
has 'an issue with no sub-issues is one unit, unchanged' "git -C $S/repo worktree add -b grind-6 $TMPDIR/grind-worktrees/alpha/6$"
has 'a sub-issue whose repo has no checkout is dropped, on the usual line' "no local checkout of o/gamma \(not the cwd, not $HOME/gamma\)"
lacks 'and never queued' 'o/gamma#3 --'
has 'an issue whose sub-issues cannot be read is skipped, loudly' 'WARN  skipping o/alpha#9 -- could not read its sub-issues$'
lacks 'and not worked whole' '\] o/alpha#9 --'
jq '[.[0]]' "$S/ready.json" > "$S/ready.json.tmp" && mv "$S/ready.json.tmp" "$S/ready.json"
jq '[.[0]]' "$S/subs/repos_o_alpha_issues_5_sub_issues.json" > "$S/subs/x" && mv "$S/subs/x" "$S/subs/repos_o_alpha_issues_5_sub_issues.json"
: > "$GH_LOG"
run
eq 'a sub-issue run exits 0' 0 "$RC"
eq 'the sub-issue is recorded done under its own ref' 'o/beta#12=done' "$(jq -r '[.items[] | "\(.ref)=\(.status)"] | join(" ")' "$(latest_session)")"
grep -q -- '^pr list --repo o/beta --head grind-12 ' "$GH_LOG" && ok || bad 'the done check reads the sub-issue repo' "$(cat "$GH_LOG")"
grep -qF 'The PR body says `Fixes o/beta#12` and `Part of o/alpha#5`.' "$S/prompt.txt" && ok || bad 'the prompt names the sub-issue and its parent' "$(cat "$S/prompt.txt")"
rm -rf "$S/subs"
rm -f "$S/state/grind"/*.json

# --- --policy cheapest-first: cheapest estimate first, across kinds -------------
cat > "$S/ready.json" <<'JSON'
[{"number": 2, "title": "Opus high", "body": "model: opus\neffort: high", "url": "https://github.com/o/alpha/issues/2", "labels": [{"name": "ready"}]},
 {"number": 3, "title": "Default pair", "body": "no pair", "url": "https://github.com/o/alpha/issues/3", "labels": [{"name": "ready"}]},
 {"number": 4, "title": "Haiku low", "body": "model: haiku\neffort: low", "url": "https://github.com/o/alpha/issues/4", "labels": [{"name": "ready"}]}]
JSON
run --dry-run --policy cheapest-first
eq 'a cheapest-first dry-run exits 0' 0 "$RC"
eq 'haiku/low, then the default pair, then opus/high' 'o/alpha#4 o/alpha#3 o/alpha#2' \
  "$(grep -oE '^\[[0-9]+/[0-9]+\] o/alpha#[0-9]+' <<<"$OUT" | sed 's/^[^ ]* //' | tr '\n' ' ' | sed 's/ $//')"
has 'and each item keeps its own pair' '--model haiku --effort low'
run --dry-run --policy cheapest
eq 'an unknown policy exits 2' 2 "$RC"
has 'and names all three' 'finish-first, start-first or cheapest-first'

# --- empty queue -----------------------------------------------------------------
cat > "$S/ready.json" <<'JSON'
[]
JSON
run
eq 'exit 0 on an empty queue' 0 "$RC"
has 'says nothing is ready' '^grind: nothing to work on o/alpha \(kinds: issue card\)$'

# --- not in a repo, no --repo given -----------------------------------------------
cd "$S/nogit" || exit 1
run
eq 'exit 1 outside a repo without --repo' 1 "$RC"
has 'says so' 'not in a GitHub repo'
cd "$S/repo" || exit 1

# --- single-flight lock: a clean run acquires and releases the lock dir ----
cat > "$S/ready.json" <<'JSON'
[
  {"number": 1, "title": "A", "body": "b", "url": "https://github.com/o/alpha/issues/1", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
rm -rf "$S/state/grind/locks"
rm -f "$S/claude-replies"/*.json
reply 0.10 "done" 1
: > "$CLAUDE_LOG"
lock_dir="$S/state/grind/locks/o_alpha.lock"
run --session-budget 100 --pause-every 10
eq 'exit 0 on a clean run' 0 "$RC"
assert 'lock directory released on clean exit' bash -c '! ls -d '"$S"'/state/grind/locks/*.lock >/dev/null 2>&1'
sess=$(latest_session)
eq 'lock diagnostics land in the state file: user' "$(id -un)" "$(jq -r '.lock.user' "$sess")"
eq 'lock diagnostics land in the state file: hostname' "$(uname -n)" "$(jq -r '.lock.hostname' "$sess")"
eq 'lock cleared current_item after the item finished' null "$(jq -r '.lock.current_item' "$sess")"
lock_tty=$(jq -r '.lock.tty' "$sess")
case $lock_tty in none|/dev/*) tty_ok=1 ;; *) tty_ok=0 ;; esac
eq 'lock tty is a device path or "none", never tty(1)'"'"'s "not a tty"' 1 "$tty_ok"
eq 'lock grind_rev is the rev of the repo holding the script' \
  "$(git -C "$(dirname "$GRIND")" rev-parse --short HEAD)" "$(jq -r '.lock.grind_rev' "$sess")"

# --- a held lock refuses a second grind, no work done -----------------------
mkdir -p "$lock_dir"
jq -n --argjson pid "$$" --arg host "$(uname -n)" \
  '{pid:$pid, hostname:$host, lock_acquired_at:"x"}' > "$lock_dir/meta.json"
rm -f "$S/state/grind"/*.json
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
eq 'exit 1 when another grind holds the lock' 1 "$RC"
has 'says another grind is running' 'another grind is already running against o/alpha'
eq 'no claude invocation while locked out' 0 "$(calls_claude)"
assert 'the lock-contention exit left no session file behind' bash -c '! ls "$1"/state/grind/*.json >/dev/null 2>&1' _ "$S"
rm -rf "$lock_dir"

# --- a stale lock (recorded pid is dead) is reclaimed, run proceeds ----------
mkdir -p "$lock_dir"
jq -n --arg host "$(uname -n)" \
  '{pid:999999999, hostname:$host, lock_acquired_at:"x"}' > "$lock_dir/meta.json"
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
reply 0.10 "done" 1
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
eq 'exit 0, the stale lock did not block the run' 0 "$RC"
has 'WARN about reclaiming the stale lock' 'WARN  reclaiming stale lock on o/alpha'
eq 'the item still ran' 1 "$(calls_claude)"
assert 'lock directory released again after this clean exit' bash -c '[ ! -d "'"$lock_dir"'" ]'
assert 'the rename-based reclaim leaves no quarantined .stale.* dir behind' \
  bash -c '! ls -d "'"$lock_dir"'".stale.* >/dev/null 2>&1'

# --- the card kind: a ## Claude's card whose link names this repo ---------------
# What matters: the card is queued after the issues (finish-first, and a
# card starts work), on a branch named from its bold name; only cards linking
# this repo are queued; --kind narrows the run and --prs is --kind pr; a
# keyless machine drops the pr kind by default but refuses it when asked; a
# verified card's item is marked done (and committed in the state repo), the
# other card's is not.
cat > "$S/cards.json" <<'JSON'
[{"kind":"card","section":"claudes","group":"global","text":"**alpha: tidy the widget** — the widget is untidy ([o/alpha](https://github.com/o/alpha)) id: 17909840241dc56754","name":"alpha: tidy the widget","link":"https://github.com/o/alpha","repo":"o/alpha"},
 {"kind":"card","section":"claudes","group":"global","text":"**beta: elsewhere** — not this repo ([o/beta](https://github.com/o/beta)) id: 17909840242aaaaaaa","name":"beta: elsewhere","link":"https://github.com/o/beta","repo":"o/beta"}]
JSON
cat > "$S/ready.json" <<'JSON'
[
  {"number": 20, "title": "Second item", "body": "do the second thing", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]},
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]}
]
JSON
# The items are files in a state repo, as on a real machine; work-item makes
# them, so the fixtures are the real format. The grind session is not the one
# that created them.
sr="$S/state-repo"; export WORK_ITEM_DIR="$sr/items"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
mkdir -p "$WORK_ITEM_DIR"; "$REAL_GIT" -C "$sr" init -q
mkitem() {  # mkitem <id> <title> <status after create: open|ready>
  CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" create --id "$1" --repo o/alpha \
    --brief "fixture (https://github.com/o/alpha)" "$2" >/dev/null || return 1
  [ "$3" = open ] || CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log "$1" status=ready
}
itemstatus() { "$GRIND_WORK_ITEM" fold "$1" | sed -n 's/^status=//p'; }
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
mkitem 17909840242aaaaaaa 'beta: elsewhere' ready
"$REAL_GIT" -C "$sr" add -- items && "$REAL_GIT" -C "$sr" commit -q -m fixtures
rm -f "$S/state/grind"/*.json
run --dry-run
eq 'dry-run exit 0' 0 "$RC"
has 'a keyless machine drops the pr kind by default, on one line' '^grind: pr kind skipped -- needs a signing key'
has 'issues first' '\[1/3\] o/alpha#5 -- First item'
has 'the card after them, by ref' '\[3/3\] card:alpha-tidy-the-widget -- alpha: tidy the widget'
has 'on a branch named from its bold name' 'worktree: git -C .* worktree add -b grind-card-alpha-tidy-the-widget'
lacks 'a card linking another repo is not queued' 'beta-elsewhere'
run --dry-run --kind card
has '--kind card queues only the card' '\[1/1\] card:alpha-tidy-the-widget'
lacks 'and no issue' 'o/alpha#5'
run --dry-run --prs
eq '--prs on a keyless machine still refuses' 1 "$RC"
has 'and says what the pr kind needs' '^grind: the pr kind needs a signing key'
run --dry-run --kind widget
eq 'an unknown kind is a usage error' 2 "$RC"
rm -f "$S/state/grind"/*.json; : > "$CLAUDE_LOG"
jq -c 'map(.url = "https://github.com/o/alpha/pull/1")' "$S/pr-list.json" > "$S/pr-list.url" && mv "$S/pr-list.url" "$S/pr-list.json"
run --kind card --pause-every 10
eq 'card run exit 0' 0 "$RC"
eq 'one worker for the one card' 1 "$(calls_claude)"
PROMPT=$(cat "$S/prompt.txt")
prompt_has 'the worker gets the card verbatim' '**alpha: tidy the widget** — the widget is untidy'
prompt_has 'framed as a card, not an issue' 'This item is a card from the agent'
prompt_has 'on its branch' 'grind-card-alpha-tidy-the-widget'
has 'the done line carries the card ref' '^card:alpha-tidy-the-widget: alpha: tidy the widget -- sonnet, \$0\.10'
eq 'the verified card is a done item' 'done' "$(itemstatus 17909840241dc56754)"
eq 'the other card is still ready' ready "$(itemstatus 17909840242aaaaaaa)"
has 'and grind said so' "INFO  marked card .alpha: tidy the widget. done in $WORK_ITEM_DIR"
eq 'its log reads claimed, then done, by one session' 'status=claimed status=done' \
  "$(awk '/^## Log/ {l=1; next} l && /status=(claimed|done)/ {print $3}' "$WORK_ITEM_DIR/17909840241dc56754.md" | paste -sd' ' -)"
assert 'and the done line cites the PR as evidence' grep -qE ' status=done evidence=https?://[^ ]+$' "$WORK_ITEM_DIR/17909840241dc56754.md"
eq 'the done is committed in the state repo' 'grind: worked card -- alpha: tidy the widget -> https://github.com/o/alpha/pull/1' "$("$REAL_GIT" -C "$sr" log -1 --format=%s)"
eq 'and the state repo is clean' '' "$("$REAL_GIT" -C "$sr" status --porcelain)"
assert 'and pushed' grep -q 'push -q origin HEAD$' "$GIT_PUSH_LOG"
eq 'the state file records the card ref' 'card:alpha-tidy-the-widget' "$(jq -r '.items[0].ref' "$(latest_session)")"
eq 'and the kinds' card "$(jq -r '.kinds' "$(latest_session)")"
# a card whose staged .claude/ files fail to push is UNVERIFIED and its item
# stays ready: an item marked done and then left unverified would never be
# queued again, since --resume reads the current queue
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$GIT_PUSH_LOG"
cp "$S/cards.json" "$S/cards.json.all"
jq -c 'map(select(.name | startswith("alpha")))' "$S/cards.json.all" > "$S/cards.json"
rm -f "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
# the shim that stages what it finds under claude-stage/<n>, as above
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\${SPEND_GATE_USD:-} \${SPEND_GATE_HANDOFF:-}" >> "$S/claude-env.log"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
stage="$S/claude-stage/\$n"
[ -d "\$stage" ] && { mkdir -p .claude-staging && cp -r "\$stage"/. .claude-staging/; }
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"
mkdir -p "$S/claude-stage/1/hooks"
echo 'echo staged' > "$S/claude-stage/1/hooks/example.test.sh"
GIT_PUSH_FAIL=1 run --kind card --pause-every 10
has 'a card with a failed staging push is UNVERIFIED' '^UNVERIFIED: card:alpha-tidy-the-widget -- alpha: tidy the widget -- worker claimed success but its staged \.claude/ files were never pushed'
eq 'and its item is still ready' ready "$(itemstatus 17909840241dc56754)"
lacks 'and grind did not say it marked it done' 'marked card'
rm -rf "$S/claude-stage"

# an item still `open` is walked open -> ready -> claimed -> done; a card with
# no id has no item to mark, so grind says so and the card stays queued
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -f "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' open
run --kind card --pause-every 10
eq 'an open item is retired too' 'done' "$(itemstatus 17909840241dc56754)"
eq 'through ready and claimed' 'status=open status=ready status=claimed status=done' \
  "$(awk '/^## Log/ {l=1; next} l && /status=/ {for (i = 3; i <= NF; i++) if ($i ~ /^status=/) print $i}' "$WORK_ITEM_DIR/17909840241dc56754.md" | paste -sd' ' -)"
# a card whose worker fails is claimed at dispatch and released back to ready
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -f "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
cp "$S/pr-list.json" "$S/pr-list.saved"; echo '[]' > "$S/pr-list.json"
run --kind card --pause-every 10
mv "$S/pr-list.saved" "$S/pr-list.json"
has 'an unbacked card claim is UNVERIFIED' '^UNVERIFIED: card:alpha-tidy-the-widget'
eq 'the card was claimed before the worker ran, then released' 'status=claimed status=ready' \
  "$(awk '/^## Log/ {l=1; next} l && /status=/ {for (i = 3; i <= NF; i++) if ($i ~ /^status=/) print $i}' "$WORK_ITEM_DIR/17909840241dc56754.md" | tail -2 | paste -sd' ' -)"
eq 'and the session file says the claim was let go' true "$(jq -r '.items[0].claim_released' "$(latest_session)")"
forget_card() { git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/alpha/card-alpha-tidy-the-widget" >/dev/null 2>&1
                git -C "$S/repo" branch -D grind-card-alpha-tidy-the-widget >/dev/null 2>&1; true; }
forget_card
# a blocked card is logged blocked, not handed back as ready, with grind's
# outcome on it; the next run leaves it be until someone else writes on it
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -f "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
reply 0.30 blocked 1
run --kind card --pause-every 10
eq 'a blocked card is blocked' blocked "$(itemstatus 17909840241dc56754)"
eq 'and names what unblocks it: a human line, since the worker cited nothing' human "$("$GRIND_WORK_ITEM" fold 17909840241dc56754 | sed -n 's/^until=//p')"
assert "with grind's outcome line on it" grep -q ' grind outcome=blocked run=grind-' "$WORK_ITEM_DIR/17909840241dc56754.md"
assert 'and its cost line' grep -qE ' cost tokens=150 usd=0\.30? by=grind$' "$WORK_ITEM_DIR/17909840241dc56754.md"
rm -f "$S/state/grind"/*.json
run --dry-run --kind card
has 'the next run skips it' '^card:alpha-tidy-the-widget -- SKIP: grind recorded blocked at .*, and nothing has changed since$'
# a blocked worker that cites an issue or PR names it as what unblocks the card
forget_card
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
jq -nc '{type:"result", total_cost_usd:0.30, usage:{input_tokens:100,output_tokens:50}, result:"Ruled already in o/alpha#94; nothing to build.\nGRIND_STATUS: blocked"}' > "$S/claude-replies/1.json"
run --kind card --pause-every 10
eq 'until= is the ref the worker cited' 'o/alpha#94' "$("$GRIND_WORK_ITEM" fold 17909840241dc56754 | sed -n 's/^until=//p')"
# a claim another live session holds is never taken over, and is found before
# any spend: no worker runs
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
rm -f "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
CLAUDE_CODE_SESSION_ID=0badc0de "$GRIND_WORK_ITEM" claim 17909840241dc56754
: > "$CLAUDE_LOG"
run --kind card --pause-every 10
eq 'an item another session holds stays claimed' claimed "$(itemstatus 17909840241dc56754)"
has 'and grind skips it, saying why' "WARN  skipping card:alpha-tidy-the-widget -- work-item refused the claim"
eq 'before any worker ran' 0 "$(calls_claude)"
# no work-item to claim with: refused before any spend
GRIND_WORK_ITEM="$S/no-such-work-item" run --kind card --pause-every 10
has 'a card with no work-item is skipped' "WARN  skipping card:alpha-tidy-the-widget -- no work-item to claim it with"
eq 'and no worker ran' 0 "$(calls_claude)"
jq -c 'map(.text |= sub(" id: [0-9a-f]+$"; ""))' "$S/cards.json" > "$S/cards.json.noid"; mv "$S/cards.json.noid" "$S/cards.json"
rm -f "$S/state/grind"/*.json
run --kind card --pause-every 10
has 'a card with no item id is skipped, saying so' 'WARN  skipping card:alpha-tidy-the-widget -- card has no id: <item id>'
eq 'before any worker ran' 0 "$(calls_claude)"
mv "$S/cards.json.all" "$S/cards.json"
# a card's pair (claude#43): the fields at the start of its brief, on the one
# line a card's text is; then its work-item rating, which wins field by field
# and is what cheapest-first plans with
rm -f "$S/state/grind"/*.json "$WORK_ITEM_DIR/17909840241dc56754.md"
mkitem 17909840241dc56754 'alpha: tidy the widget' ready
cp "$S/cards.json" "$S/cards.json.plain"
jq -c 'map(.text |= sub("— "; "— model: opus · effort: high "))' "$S/cards.json.plain" > "$S/cards.json"
run --dry-run --kind card
has 'model: and effort: at the start of a card brief set both' '<card card:alpha-tidy-the-widget text>.*--model opus --effort high'
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log 17909840241dc56754 model=haiku
run --dry-run --kind card
has 'the rated model wins over the text, and the text still gives the unrated effort' '<card card:alpha-tidy-the-widget text>.*--model haiku --effort high'
mv "$S/cards.json.plain" "$S/cards.json"
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log 17909840241dc56754 model=opus effort=high
run --dry-run --kind card
has 'a card rated opus/high in its log runs as opus/high' '<card card:alpha-tidy-the-widget text>.*--model opus --effort high'
run --dry-run --policy cheapest-first
has 'and under cheapest-first too' '<card card:alpha-tidy-the-widget text>.*--model opus --effort high'
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log 17909840241dc56754 model=haiku effort=low
run --dry-run --policy cheapest-first
has 'rated haiku/low, the card is planned first' '\[1/3\] card:alpha-tidy-the-widget'
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log 17909840241dc56754 budget=12
run --dry-run --kind card
has "a budget= on the card's log is its soft cap when higher" 'budget:   soft \$12\.00 .*hard \$36\.00'
unset WORK_ITEM_DIR GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL; rm -f "$S/cards.json"

# --- --prs -------------------------------------------------------------------------
# What matters here: only the two unfinished sections become items; every skip
# rule fires with its reason named; the run refuses outright without a signing
# key; the worker is put on the PR's own head branch and handed both briefs
# plus the one contract text; and neither "done" nor "blocked" is taken on
# trust -- done wants the label Mergify computes or a signed head that moved,
# blocked wants the fixup-hard label the contract's stop rule promises.
prroot="$S/prroot"; prrepo="$S/prrepo"; prorigin="$S/remote/o/alpha.git"
mkdir -p "$prroot/bin" "$prroot/hooks" "$prroot/skills/pickup" "$S/remote/o"
export GRIND_ROOT="$prroot"

# The real contract, read from the skill exactly as grind reads it in anger.
cp "$(cd "$(dirname "$GRIND")/.." && pwd)/skills/pickup/SKILL.md" \
   "$prroot/skills/pickup/SKILL.md"
cat > "$prroot/hooks/lib-state.sh" <<'LS'
branch_brief() { printf 'base: main (open PR)\nconflicts: yes\nrecommend: git merge origin/main   # fixture\n'; }
LS
cat > "$prroot/hooks/claim-stamp.sh" <<STAMP
#!/bin/sh
echo "\$*" >> "$S/stamp.log"
STAMP
cat > "$prroot/bin/pr-label-audit" <<AUDIT
#!/bin/sh
case " \$* " in *" --pr "*) echo "AUDIT BRIEF for \$3"; exit 0 ;; esac
cat "$S/audit.json"
AUDIT
chmod +x "$prroot/bin/pr-label-audit"

# newline-delimited objects plus the trailing summary, the shape
# pr-label-audit --json actually emits.
old() { date -u -d '9 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-9d +%Y-%m-%dT%H:%M:%SZ; }
fresh() { date -u +%Y-%m-%dT%H:%M:%SZ; }
audit_row() { # audit_row <n> <section> <verdict> <labels json> <author> <when>
  jq -nc --argjson n "$1" --arg s "$2" --arg v "$3" --argjson l "$4" --arg a "$5" --arg t "$6" \
    '{repo:"alpha", number:$n, title:("PR " + ($n|tostring)), url:("https://x/" + ($n|tostring)),
      owner:"o", author:$a, labels:$l, head_committed_at:$t, verdict:$v, section:$s}'
}
{ audit_row 30 unfinished conflicted '[]' solace "$(old)"
  audit_row 11 stale-label not-green '[]' solace "$(old)"
  audit_row 40 unfinished threads-open '["fixup-hard"]' solace "$(old)"
  audit_row 41 unfinished threads-open '["blocked"]' solace "$(old)"
  audit_row 42 unfinished conflicted '[]' 'dependabot[bot]' "$(old)"
  audit_row 43 unfinished conflicted '[]' 'release-please[bot]' "$(old)"
  audit_row 44 unfinished conflicted '[]' solace "$(fresh)"
  audit_row 45 unfinished conflicted '[]' solace "$(old)"
  audit_row 46 unfinished conflicted '[]' solace "$(fresh)"
  audit_row 50 green green '["awaiting-human"]' solace "$(old)"
  jq -nc '{repos_missing_fixup_hard:[]}'
} > "$S/audit.json"

# A real local origin so the orchestrator's fetch and worktree add are the
# ones under test, not a stub. cwd_repo strips the .git suffix, so the repo
# reads as .../o/alpha and its basename -- what pr-label-audit reports -- is
# alpha.
git init -q --bare "$prorigin"
git init -q -b main "$prrepo"
git -C "$prrepo" remote add origin "$prorigin"
git -C "$prrepo" config user.email t@example.invalid
git -C "$prrepo" config user.name t
git -C "$prrepo" commit -q --allow-empty -m init
git -C "$prrepo" push -q origin main
for n in 30 11 45 44; do
  git -C "$prrepo" branch -q "fix-$n" main
  git -C "$prrepo" push -q origin "fix-$n"
done
git -C "$prrepo" branch -q fix-45-held main

# gh, for --prs: pr view answers from one canned doc per PR, by whatever --jq
# filter grind passed, so the shim never second-guesses the query.
prview() { # prview <n> <label names json> <commits json>
  jq -n --arg b "fix-$1" --argjson l "$2" --argjson c "$3" \
    '{headRefName:$b, baseRefName:"main", labels:($l | map({name:.})), commits:$c}' > "$S/pr-$1.json"
}
for n in 30 11 40 41 42 43 45; do prview "$n" '[]' '[]'; done
# 44: a session pushed minutes ago. 46: the session pushed days ago and the
# fresh head is Mergify merging main in -- workable, whatever the head date says.
prview 44 '[]' "$(jq -nc --arg t "$(fresh)" '[{committedDate:$t, authors:[{login:"solace"}]}]')"
prview 46 '[]' "$(jq -nc --arg o "$(old)" --arg t "$(fresh)" '[{committedDate:$o, authors:[{login:"solace"}]}, {committedDate:$t, authors:[{login:"mergify[bot]"}]}]')"

cat > "$S/bin/gh" <<GH
#!/bin/sh
echo "\$*" >> "$GH_LOG"
filter=""; prev=""
for a in "\$@"; do [ "\$prev" = "--jq" ] && filter=\$a; prev=\$a; done
[ -n "\$filter" ] || filter="."
case "\$1 \$2" in
  "issue list") cat "$S/ready.json" ;;
  "pr list")    jq -r "\$filter" "$S/pr-list.json" ;;
  "issue view") jq -r "\$filter" "$S/issue-comments.json" ;;
  "api repos/"*"/sub_issues"*) f="$S/subs/\$(printf '%s' "\${2%%\?*}" | tr / _).json"; if [ "\$(cat "\$f" 2>/dev/null)" = FAIL ]; then exit 1; elif [ -f "\$f" ]; then cat "\$f"; else echo '[]'; fi ;;
  "api repos/"*"/issues/"*) if [ -f "$S/updated-at" ]; then cat "$S/updated-at"; else echo 2999-01-01T00:00:00Z; fi ;;
  "pr view")    jq -r "\$filter" "$S/pr-\$3.json" ;;
  "api user")   echo solace ;;
  "run rerun")  [ "\${GH_RERUN_FAIL:-0}" = 1 ] && exit 1; exit 0 ;;
  "pr edit"|"pr comment") exit 0 ;;
  "api repos/"*"/actions/runs/"*) printf '%s\n' "\${GH_RUN_ATTEMPT:-1}" ;;
  *) echo "gh shim: unexpected \$*" >&2; exit 1 ;;
esac
GH
chmod +x "$S/bin/gh"

cd "$prrepo" || exit 1
git config user.signingkey TESTKEY

# --- no signing key: refused before anything is cut ---------------------------------
git config --unset user.signingkey
run --prs --dry-run
eq 'no signing key is exit 1' 1 "$RC"
has 'and says which setting is empty' 'needs a signing key .*user\.signingkey is empty'
git config user.signingkey TESTKEY

# --- --prs --dry-run: the two unfinished sections only, lowest number first ---------
: > "$CLAUDE_LOG"
run --prs --dry-run
eq 'dry-run exits 0' 0 "$RC"
eq 'dry-run spends nothing' 0 "$(calls_claude)"
has 'stale-label PR is an item, lowest number first' '^\[1/9\] .*#11 -- \[not-green\] PR 11$'
has 'unfinished PR is an item, with its verdict' '^\[[0-9]+/9\] .*#30 -- \[conflicted\] PR 30$'
lacks 'a green, labelled PR is not an item' '#50'
has 'the checkout is onto the PR head branch, not a new one' 'git -C .* worktree add -B fix-11 .* origin/fix-11'
has 'the command names the briefs and the contract' 'claude -p <.*#11 briefs \+ fixup contract>.*--max-budget-usd 3.75 --model sonnet'

# --- every skip rule fires, with its reason ------------------------------------------
has 'fixup-hard is skipped'      '^\[[0-9]+/9\] .*#40 -- SKIP: labelled fixup-hard$'
has 'blocked is skipped'         '^\[[0-9]+/9\] .*#41 -- SKIP: labelled blocked$'
has 'dependabot is skipped'      '^\[[0-9]+/9\] .*#42 -- SKIP: opened by a bot'
has 'release-please is skipped'  '^\[[0-9]+/9\] .*#43 -- SKIP: opened by a bot'
has 'a head under 4h is skipped' '^\[[0-9]+/9\] .*#44 -- SKIP: head is less than 4h old$'
lacks 'a fresh head that is only a Mergify update is not' '#46 -- SKIP'
has 'and that PR is an item' '^\[[0-9]+/9\] .*#46 -- \[conflicted\] PR 46$'
lacks 'nothing is skipped without a reason' 'SKIP: *$'

# --- a branch a local worktree holds belongs to a live session -----------------------
lacks 'unheld branch is workable' '#45 -- SKIP'
git -C "$prrepo" worktree add -q --detach "$S/held" >/dev/null 2>&1
git -C "$S/held" checkout -q fix-45
run --prs --dry-run
has 'a worktree-held branch is skipped, by name' '#45 -- SKIP: a local worktree holds fix-45$'
git -C "$prrepo" worktree remove -f "$S/held" >/dev/null 2>&1

# --- the scheduler: finish-first works the fixups before anything new ----------
cat > "$S/cards.json" <<'JSON'
[{"kind":"card","section":"claudes","group":"global","text":"**alpha: a card** — text ([o/alpha](https://github.com/o/alpha))","name":"alpha: a card","link":"https://github.com/o/alpha","repo":"o/alpha"}]
JSON
rm -f "$S/state/grind"/*.json
run --dry-run
eq 'all kinds, dry-run, exit 0' 0 "$RC"
seq_of() { printf '%s\n' "$OUT" | grep -E '^\[[0-9]+/[0-9]+\]' | grep -oE '#[0-9]+|card:[a-z-]+' | tr '\n' ' '; }
eq 'finish-first: PRs by number, then issues, then the card' \
  '#11 #30 #40 #41 #42 #43 #44 #45 #46 #5 #20 card:alpha-a-card ' "$(seq_of)"
run --dry-run --policy start-first
eq 'start-first: issues, the card, then the PRs' \
  '#5 #20 card:alpha-a-card #11 #30 #40 #41 #42 #43 #44 #45 #46 ' "$(seq_of)"
run --dry-run --policy random
eq 'an unknown policy is a usage error' 2 "$RC"
run --dry-run --prs
eq '--prs is a filter over the same queue' '#11 #30 #40 #41 #42 #43 #44 #45 #46 ' "$(seq_of)"
rm -f "$S/cards.json"

# --- a not-green PR whose failing checks are all cancelled reruns instead of working ---
audit_row_cancelled() { # audit_row_cancelled <n> <run id> <when>
  jq -nc --argjson n "$1" --argjson rid "$2" --arg t "$3" \
    '{repo:"alpha", number:$n, title:("PR " + ($n|tostring)), url:("https://x/" + ($n|tostring)),
      owner:"o", author:"solace", labels:[], head_committed_at:$t, verdict:"not-green", section:"unfinished",
      failing_checks:[{name:"ci-gate / gate", url:("https://github.com/o/alpha/actions/runs/" + ($rid|tostring) + "/job/1")}],
      cancelled_only:true}'
}
cat > "$S/audit.json" <<J
$(audit_row_cancelled 60 9001 "$(old)")
J
prview 60 '[]' '[]'
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
: > "$CLAUDE_LOG"; : > "$GH_LOG"
run --prs --dry-run
has 'dry-run names the cancelled-only reason' '#60 -- SKIP: all checks are cancelled -- would rerun rather than work it$'
lacks 'dry-run never calls gh run rerun' 'run rerun'

: > "$GH_LOG"
GH_RUN_ATTEMPT=1 run --prs
eq 'exit 0 -- a cancelled-only skip is not a failure' 0 "$RC"
eq 'no worker spent on a cancelled-only PR' 0 "$(calls_claude)"
assert 'gh run rerun is called with the run id parsed from the check URL' \
  grep -Eq -- 'run rerun 9001 .*--failed' "$GH_LOG"
has 'the skip reason says the run was reran' 'WARN  skipping .*#60 -- all checks were cancelled -- reran run\(s\) 9001'

GH_RERUN_FAIL=1 GH_RUN_ATTEMPT=1 run --prs
eq 'a rerun that fails is still just a skip, not a run failure' 0 "$RC"
has 'the reason says nothing was eligible' 'WARN  skipping .*#60 -- all checks were cancelled, but nothing was eligible to rerun$'

: > "$GH_LOG"
GH_RUN_ATTEMPT=2 run --prs
eq 'a run already on its 2nd attempt is left alone, still just a skip' 0 "$RC"
eq 'no rerun call for a run already retried' 0 "$(grep -c 'run rerun' "$GH_LOG")"
has 'the reason says nothing was eligible, not that it reran' 'WARN  skipping .*#60 -- all checks were cancelled, but nothing was eligible to rerun$'

cat > "$S/audit.json" <<J
$(audit_row_cancelled 60 9001 "$(old)")
$(audit_row_cancelled 61 9002 "$(old)")
J
prview 61 '[]' '[]'
: > "$GH_LOG"
GH_RUN_ATTEMPT=1 run --prs
eq 'exit 0 -- both are skips, not failures' 0 "$RC"
eq 'still no worker spent, on either cancelled-only PR' 0 "$(calls_claude)"
eq 'only one PR is reran per pass' 1 "$(grep -c 'run rerun' "$GH_LOG")"
assert 'the first PR in the queue is the one reran' grep -Eq -- 'run rerun 9001 .*--failed' "$GH_LOG"
has 'the second PR is skipped for the per-pass cap, not reran' 'WARN  skipping .*#61 -- this pass already reran a PR$'

# --- a real --prs run: briefs plus one contract, on the PR own branch ----------------
cat > "$S/audit.json" <<J
$(audit_row 11 stale-label not-green '[]' solace "$(old)")
J
# --prs budget defaults, and flags that still override them; a resumed run
# keeps whether the item budget was given, so a pr item's cap does not fall
# back to the flat one
run --prs --dry-run
has 'default pr item budget is the $1 stop plus headroom, hard 3x' '^  budget: +soft \$1\.25 \(the worker.s stop\), hard \$3\.75 '
run --prs --dry-run --item-budget 3
has 'an explicit item budget wins' '^  budget: +soft \$3\.00 '
for ibs in 1 0; do
  jq -n --argjson ibs "$ibs" '{repo:"o/alpha", project:"", item_budget:3, item_budget_set:$ibs, session_budget:100,
    pause_every:3, prs:1, kinds:"pr", policy:"finish-first", items:[]}' > "$S/state/grind/grind-ibs$ibs.json"
done
run --resume grind-ibs1 --dry-run
has 'a resumed run keeps an item budget the session was given' '^  budget: +soft \$3\.00 '
run --resume grind-ibs0 --dry-run
has 'and the flat pr cap when it was not (an older file says nothing)' '^  budget: +soft \$1\.25 '
rm -f "$S/state/grind"/grind-ibs*.json
# a pr's budget: counts only where the account grind runs as wrote it: anyone
# may comment on a PR, and a stranger's budget: is not obeyed
cp "$S/pr-11.json" "$S/pr-11.saved"
jq '. + {author:{login:"solace"}, body:"", comments:[{author:{login:"solace"}, body:"budget: 4"}, {author:{login:"stranger"}, body:"budget: 9999"}]}' \
  "$S/pr-11.saved" > "$S/pr-11.json"
run --prs --dry-run
has 'your last comment sets the budget; a later stranger comment does not' '^  budget: +soft \$4\.00 '
jq '. + {author:{login:"stranger"}, body:"budget: 9999", comments:[]}' "$S/pr-11.saved" > "$S/pr-11.json"
run --prs --dry-run
has 'nor does a stranger-written PR body' '^  budget: +soft \$1\.25 '
mv "$S/pr-11.saved" "$S/pr-11.json"
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
reply 0.20 "done" 1
prview 11 '["awaiting-human"]' '[]'
: > "$CLAUDE_LOG"; : > "$S/claude-env.log"
run --prs
eq 'exit 0' 0 "$RC"
# The gate sits at the soft cap, a quarter past the contract's $1 stop: at $1
# the worker still needs Bash to label, comment and push (claude#69 review).
eq 'a pr worker gets its soft cap ($1.25) as the spend gate line' '1.25 HANDOFF.md' \
  "$(cat "$S/claude-env.log")"
has 'awaiting-human alone is enough to be done' '^.*#11: PR 11 -- sonnet, \$0\.20'
lacks 'and it is not unverified' 'UNVERIFIED'
PROMPT=$(cat "$S/prompt.txt")
prompt_has 'the GitHub brief is in the prompt'  'AUDIT BRIEF'
prompt_has 'the local brief is in the prompt'   'recommend: git merge origin/main'
prompt_has 'the contract is the skill section'  '## 6. The fixup contract'
prompt_has 'its stop rule came with it'         'label the PR `fixup-hard`'
prompt_has 'the worker is told the head branch' 'on fix-11 -- the PR'
prompt_has 'done is offered'                    'GRIND_STATUS: done'
prompt_has 'blocked is offered'                 'GRIND_STATUS: blocked'
prompt_has 'the worker is told the stop rule is its budget, not a kill' 'grind does not stop you at it'
prompt_has 'and that the gate closes past it, at the soft cap' 'Past ~$1.25 a hook denies every tool but one Write'
lacks 'no grind-N branch is ever made for a PR' 'grind-11'

# --- done with neither the label nor a signed head move is unverified ----------------
prview 11 '[]' '[]'
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
reply 0.20 "done" 1
run --prs
has 'an unbacked done claim is unverified' 'UNVERIFIED: .*#11 .*no awaiting-human label, and no signed commit'

# --- blocked without the fixup-hard label is unverified, not a clean give-up ---------
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
reply 0.20 "blocked" 1
run --prs
has 'a silent give-up is unverified' 'UNVERIFIED: .*#11 .*gave up without labelling the PR fixup-hard'
prview 11 '["fixup-hard"]' '[]'
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
reply 0.20 "blocked" 1
run --prs
has 'a labelled give-up is a clean blocked' '^blocked: .*#11 -- PR 11'
lacks 'and is not unverified' 'UNVERIFIED'

# --- the cap kills a fixup mid-wrap-up: grind carries out the stop rule for it -------
# grind-20260929T022433Z: both fixups hit the cap on the turn they were
# pushing, left no label and no comment, and were recorded failed with their
# worktrees deleted. The worker's own stop rule is grind's to finish.
capkill() { # capkill <n> <last assistant text>
  jq -nc --arg t "$2" '{type:"assistant", message:{id:"m1", content:[{type:"text", text:$t}], usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}}}' \
    > "$S/claude-replies/$1.json"
  jq -nc '{type:"result", subtype:"error_max_budget_usd", is_error:true, session_id:"5075db97-dead-beef", total_cost_usd:1.26, usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}, result:"Budget exceeded"}' \
    >> "$S/claude-replies/$1.json"
}
prview 11 '[]' '[]'
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json; : > "$GH_LOG"; : > "$S/stamp.log"
capkill 1 'Pushed the rebase. Budget is nearly spent; labelling fixup-hard next.'
run --prs
has 'a cap-killed fixup with no claim is failed' '^FAILED: .*#11 .*Budget exceeded'
assert 'grind labels it fixup-hard' grep -Eq -- '^pr edit 11 .*--add-label fixup-hard' "$GH_LOG"
assert 'and leaves the one comment' grep -Eq -- '^pr comment 11 ' "$GH_LOG"
assert 'quoting what the worker last said' grep -Eq -- '^> Pushed the rebase' "$GH_LOG"
assert 'the worker session claim stamp is released' grep -Eq -- '^release .*--scan 5075db97-dead-beef$' "$S/stamp.log"
has 'its worktree is kept' 'keeping worktree .*/pr-11 on branch fix-11'

# --- the cap lands after a claim GitHub bears out: that is a done fixup ------------------
prview 11 '["awaiting-human"]' '[]'
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json; : > "$GH_LOG"; : > "$S/stamp.log"
capkill 1 'All green.
GRIND_STATUS: done'
run --prs
has 'a verified claim outranks is_error' '^.*#11: PR 11 -- sonnet, \$1\.26'
lacks 'so it is not failed' '^FAILED'
assert 'and grind labels nothing' test "$(grep -c '^pr edit 11' "$GH_LOG")" = 0
assert 'the stamp is released on every exit, not only a failed one' grep -q 'release' "$S/stamp.log"

# --- the cap lands with no claim, but Mergify already finished the fixup: done ---------
# dotfiles#249's shape: the signed commit was on the PR and awaiting-human on
# it before the cap killed the worker mid-turn. The label is the same word a
# `done` claim is checked against, so the missing claim costs nothing.
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json; : > "$GH_LOG"; : > "$S/stamp.log"
capkill 1 'Pushing.'
run --prs
has 'awaiting-human outranks a missing claim' '^.*#11: PR 11 -- sonnet, \$1\.26'
lacks 'so it is not failed' '^FAILED'
sess=$(latest_session)
eq 'recorded done in state' 'done' "$(jq -r '.items[0].status' "$sess")"
assert 'and grind labels nothing' test "$(grep -c '^pr edit 11' "$GH_LOG")" = 0
assert 'the stamp is released all the same' grep -q 'release' "$S/stamp.log"
prview 11 '[]' '[]'

# --- the worker dies with no result event at all: stamp released, no label -------------
# #388's shape: killed mid-commit, nothing parseable to score. --resume retries
# it, so fixup-hard would turn that retry into a skip; the stamp goes anyway.
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json; : > "$GH_LOG"; : > "$S/stamp.log"
jq -nc '{type:"assistant", session_id:"5075db97-no-result", message:{id:"m1", content:[{type:"text", text:"Committing."}], usage:{input_tokens:100,output_tokens:50,cache_read_input_tokens:0,cache_creation_input_tokens:0}}}' \
  > "$S/claude-replies/1.json"
run --prs
has 'no result is recorded failed, and retried' '^FAILED: .*#11 .*did not complete \(no result event\); cost estimated.*will retry on --resume'
eq 'recorded with an estimated cost' 'failed true' "$(jq -r '.items[0] | "\(.status) \(.cost_estimated)"' "$(latest_session)")"
assert 'the stamp is released from the stream session id' grep -Eq -- '^release .*--scan 5075db97-no-result$' "$S/stamp.log"
assert 'no fixup-hard: --resume retries this' test "$(grep -c '^pr edit 11' "$GH_LOG")" = 0
has 'its worktree is kept' 'keeping worktree .*/pr-11 on branch fix-11'

# --- a local branch of the same name is never force-deleted --------------------------
# In --prs mode $branch is the PR's real head name, which a human may hold
# locally with unpushed commits. `git worktree add -B` resets it only when the
# checkout actually happens; a pre-emptive `git branch -D` would destroy it
# even on a run that never got that far.
cat > "$S/audit.json" <<J
$(audit_row 45 unfinished conflicted '[]' solace "$(old)")
J
git -C "$prrepo" branch -q -f fix-45 main
git -C "$prrepo" commit -q --allow-empty -m "unpushed work" 2>/dev/null
mine=$(git -C "$prrepo" rev-parse HEAD)
git -C "$prrepo" branch -q -f fix-45 "$mine"
git -C "$prorigin" update-ref -d refs/heads/fix-45   # make grind's fetch fail
rm -f "$S/claude-replies"/*.json "$S/state/grind"/*.json
run --prs
has 'an uncheckoutable PR is skipped, not fatal' 'could not check out fix-45'
# A --prs session with work, kept for the --resume test below: an empty
# queue writes no session file, so that test cannot make its own.
prs_session_file=$(latest_session); cp "$prs_session_file" "$S/prs-session.saved"
eq 'the local branch of the same name survives' "$mine" "$(git -C "$prrepo" rev-parse fix-45)"

# --- dotfiles#439: the backstop lands after the work is done --------------------------
# Run 20260929T022433Z: the worker pushed, opened its PR and said done, then the
# cap ended it with an error result. That is a done item: recorded done, its
# claim released, its worktree removed only after the record, nothing retried.
cp "$S/ready.json" "$S/ready.saved"; cp "$S/pr-list.json" "$S/pr-list.saved"
cat > "$S/ready.json" <<'JSON'
[{"number": 77, "title": "Capped item", "body": "b", "url": "https://github.com/o/alpha/issues/77", "labels": [{"name": "ready"}]}]
JSON
echo '[]' > "$S/pr-list.json"
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
b=\$("$REAL_GIT" rev-parse --abbrev-ref HEAD)
# named for the branch: two items' commits in one second would otherwise be one sha
"$REAL_GIT" commit -q --allow-empty -m "the work on \$b"
say() { jq -nc --arg t "\$1" --arg sid "\$2" '{type:"assistant", session_id:\$sid, message:{id:"m1", content:[{type:"text", text:\$t}], usage:{input_tokens:1000,output_tokens:3,cache_read_input_tokens:0,cache_creation_input_tokens:0}}}'; }
case \$(cat "$S/claude-mode") in
  donecap)
    "$REAL_GIT" push -q origin "HEAD:refs/heads/\$b"
    echo '[{"createdAt":"2999-01-01T00:00:00Z","updatedAt":"2999-01-01T00:00:00Z","state":"OPEN","url":"https://github.com/o/alpha/pull/99"}]' > "$S/pr-list.json"
    say "Pushed and opened the PR.
GRIND_STATUS: done" sess-donecap
    jq -nc '{type:"result", subtype:"error_max_budget_usd", is_error:true, session_id:"sess-donecap", total_cost_usd:2.50, usage:{input_tokens:1000,output_tokens:900,cache_read_input_tokens:0,cache_creation_input_tokens:0}}'
    exit 1 ;;
  noresult)
    echo half > half-done.txt   # an edit the cap lands before it is committed
    echo s3cr3t > .env.local    # one shaped like a secret
    echo k > Server.PEM          # in any case
    echo e > .envrc              # an rc file .env.* missed
    mkdir -p .aws && echo r > .aws/config   # and anything under .aws/
    echo tok > tokenizer.py      # and one that only sounds like it
    say "Committing." sess-noresult
    exit 1 ;;
  pushedcap)
    "$REAL_GIT" push -q origin "HEAD:refs/heads/\$b"   # as the contract asks, before the cap
    mkdir -p .aws; echo k > .aws/credentials; echo k > Service-Account.json
    say "Pushed." sess-pushedcap
    exit 1 ;;
esac
GH
chmod +x "$S/bin/claude"
echo donecap > "$S/claude-mode"
rm -f "$S/state/grind"/*.json "$S/wt-remove.log"; : > "$S/stamp.log"; : > "$CLAUDE_LOG"
run --kind issue --session-budget 100 --pause-every 10
sess=$(latest_session)
eq 'a capped worker whose PR is on GitHub is recorded done' 'done' "$(jq -r '.items[0].status' "$sess")"
has 'and reported done, not FAILED' '^o/alpha#77: Capped item -- sonnet, \$2\.50'
lacks 'nothing failed' '^FAILED'
eq 'at its exact cost' 'false' "$(jq -r '.items[0].cost_estimated' "$sess")"
assert 'its claim stamp is released, for an issue as for a fixup' grep -Eq -- '^release .*--scan sess-donecap$' "$S/stamp.log"
eq 'and the session file says so' 'true' "$(jq -r '.items[0].claim_released' "$sess")"
eq 'naming the worker session whose stamp it was' 'sess-donecap' "$(jq -r '.items[0].worker_sid' "$sess")"
eq 'its worktree was removed after the item was recorded, not before' '1' "$(tail -1 "$S/wt-remove.log" 2>/dev/null)"
assert 'and is gone' test ! -d "$TMPDIR/grind-worktrees/alpha/77"
: > "$CLAUDE_LOG"
run --resume "$(basename "$sess" .json)"
eq 'no retry is queued for it' 0 "$(calls_claude)"

# --- no result event at all: judged from GitHub, recorded, claim released -------------
cat > "$S/ready.json" <<'JSON'
[{"number": 78, "title": "Killed item", "body": "b", "url": "https://github.com/o/alpha/issues/78", "labels": [{"name": "ready"}]}]
JSON
echo '[]' > "$S/pr-list.json"; echo noresult > "$S/claude-mode"
rm -f "$S/state/grind"/*.json; : > "$S/stamp.log"; : > "$CLAUDE_LOG"
run --kind issue --session-budget 100 --pause-every 10
sess=$(latest_session)
has 'a worker with no result is FAILED, with an estimated cost' '^FAILED: o/alpha#78 .*no result event\); cost estimated'
eq 'and recorded, cost marked estimated, claim released' 'failed true true' \
  "$(jq -r '.items[0] | "\(.status) \(.cost_estimated) \(.claim_released)"' "$sess")"
assert 'the estimate is the heartbeat input-side one, not zero' \
  test "$(jq -r '.items[0].cost > 0' "$sess")" = true
assert 'its stamp is released from the stream session id' grep -Eq -- '^release .*--scan sess-noresult$' "$S/stamp.log"
assert 'its worktree is kept' test -d "$TMPDIR/grind-worktrees/alpha/78"

# --- claude#43: a stopped attempt keeps its work at the stop, and the retry resumes it ----
# Saved now, not on the next attempt: its commit and its uncommitted edit alike.
has 'the stop saves the attempt' 'INFO  saved the stopped attempt on o/alpha#78 to wip/grind-78; the retry resumes from it'
assert 'pushed as wip/grind-78' grep -q 'refs/heads/wip/grind-78' "$GIT_PUSH_LOG"
eq 'and recorded on the attempt' 'wip/grind-78' "$(jq -r '.items[0].wip_branch' "$sess")"
co=$(git -C "$TMPDIR/grind-worktrees/alpha/78" rev-parse --path-format=absolute --git-common-dir)   # the checkout grind cut from
eq 'the saved tip carries the uncommitted edit' 'half' "$(git --git-dir="$co" show origin/wip/grind-78:half-done.txt 2>/dev/null)"
eq 'in an unhooked snapshot commit on top of its own' \
  'grind: snapshot of o/alpha#78 at its stop (failed), for the retry to resume from|the work on grind-78' \
  "$(git --git-dir="$co" log --format=%s -n 2 origin/wip/grind-78 | paste -sd '|')"
saved_tip=$(git --git-dir="$co" rev-parse origin/wip/grind-78)
lacks_in_tree() { ! git --git-dir="$co" cat-file -e "origin/wip/grind-78:$1" 2>/dev/null; }
assert 'but not a new file shaped like a secret' lacks_in_tree .env.local
has 'which it names as held back' 'WARN  not saving .aws/config .env.local .envrc Server.PEM from o/alpha#78: shaped like a secret'
assert 'whatever its case' lacks_in_tree Server.PEM
assert 'an rc file that starts .env' lacks_in_tree .envrc
assert 'or anything under .aws/' lacks_in_tree .aws/config
eq 'while a file that only sounds like one is saved' 'tok' "$(git --git-dir="$co" show origin/wip/grind-78:tokenizer.py 2>/dev/null)"
: > "$GIT_PUSH_LOG"; echo donecap > "$S/claude-mode"
run --resume "$(basename "$sess" .json)"
has 'the retry resumes from it' 'INFO  resuming o/alpha#78 from the stopped attempt saved on wip/grind-78'
lacks 'with nothing left to push first' 'pushed the earlier attempt'
eq 'and records that' 'wip/grind-78' "$(jq -r '.items[1].resumed_from' "$sess")"
eq 'a first attempt resumed nothing' 'null' "$(jq -r '.items[0].resumed_from' "$sess")"
assert 'the worker is told what is already there' grep -q 'An earlier attempt at this item was stopped' "$S/prompt.txt"
assert 'commit by commit' grep -q 'grind: snapshot of o/alpha#78 at its stop' "$S/prompt.txt"
eq 'and its branch was cut from the saved tip' "$saved_tip" "$(git --git-dir="$co" rev-parse grind-78~1)"

# a save that fails at the stop warns and keeps the worktree; a retry whose
# push fails too clears nothing: the item waits, its worktree intact
cat > "$S/ready.json" <<'JSON'
[{"number": 79, "title": "Stuck item", "body": "b", "url": "https://github.com/o/alpha/issues/79", "labels": [{"name": "ready"}]}]
JSON
echo '[]' > "$S/pr-list.json"; echo noresult > "$S/claude-mode"
rm -f "$S/state/grind"/*.json
GIT_PUSH_FAIL=1 run --kind issue --session-budget 100 --pause-every 10
has 'a failed save at the stop warns' 'WARN  could not save the stopped attempt on o/alpha#79 to wip/grind-79; its worktree is the only copy'
eq 'and records no wip' 'null' "$(jq -r '.items[0].wip_branch' "$(latest_session)")"
kept=$(git -C "$TMPDIR/grind-worktrees/alpha/79" rev-parse HEAD)
: > "$CLAUDE_LOG"
GIT_PUSH_FAIL=1 run --resume "$(basename "$(latest_session)" .json)"
has 'a failed wip push skips the retry' 'WARN  skipping o/alpha#79 -- could not push the earlier attempt'
eq 'without running a worker' 0 "$(calls_claude)"
eq 'and the earlier attempt is untouched' "$kept" "$(git -C "$TMPDIR/grind-worktrees/alpha/79" rev-parse HEAD)"
# once the push goes through, the retry pushes the leftover and resumes from it
: > "$GIT_PUSH_LOG"; echo donecap > "$S/claude-mode"
run --resume "$(basename "$(latest_session)" .json)"
has 'the retry pushes what the failed save could not' 'INFO  pushed the earlier attempt.s unpushed commits on o/alpha#79 to wip/grind-79'
has 'and resumes from it' 'INFO  resuming o/alpha#79 from the stopped attempt saved on wip/grind-79'

# a worker that pushed its own branch before the cap left nothing unpushed,
# and the retry still resumes from its work rather than from scratch
cat > "$S/ready.json" <<'JSON'
[{"number": 80, "title": "Pushed item", "body": "b", "url": "https://github.com/o/alpha/issues/80", "labels": [{"name": "ready"}]}]
JSON
echo '[]' > "$S/pr-list.json"; echo pushedcap > "$S/claude-mode"
rm -f "$S/state/grind"/*.json
run --kind issue --session-budget 100 --pause-every 10
pushed_tip=$(git --git-dir="$co" rev-parse origin/grind-80)
has 'a pushed attempt is saved too' 'INFO  saved the stopped attempt on o/alpha#80 to wip/grind-80'
eq 'at the tip the worker pushed' "$pushed_tip" "$(git --git-dir="$co" rev-parse origin/wip/grind-80)"
has 'an .aws/ credentials file and a capitalised key are held back' 'WARN  not saving .aws/credentials Service-Account.json from o/alpha#80'
echo donecap > "$S/claude-mode"
run --resume "$(basename "$(latest_session)" .json)"
has 'and the retry resumes from it' 'INFO  resuming o/alpha#80 from the stopped attempt saved on wip/grind-80'

# --- a signal ends the run on the record, and lets the worker's claim go --------------
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > /dev/null
echo "\$*" >> "$CLAUDE_LOG"
echo '{"type":"assistant","session_id":"sess-signal","message":{"id":"m1","content":[],"usage":{"input_tokens":1,"output_tokens":1}}}'
sleep 3
GH
chmod +x "$S/bin/claude"
cat > "$S/ready.json" <<'JSON'
[{"number": 80, "title": "Interrupted item", "body": "b", "url": "https://github.com/o/alpha/issues/80", "labels": [{"name": "ready"}]}]
JSON
rm -f "$S/state/grind"/*.json; : > "$S/stamp.log"; : > "$CLAUDE_LOG"
sh "$GRIND" --kind issue --session-budget 100 --heartbeat 0 >/dev/null 2>&1 &
gpid=$!
for _ in $(seq 50); do [ -s "$CLAUDE_LOG" ] && break; sleep 0.1; done
sleep 0.5; kill -TERM "$gpid"; wait "$gpid"; grc=$?
eq 'a TERM exits 143' 143 "$grc"
eq 'and the session file says a signal ended it' 'signal 143' "$(jq -r '"\(.ended.reason) \(.ended.exit)"' "$(latest_session)")"
assert 'the in-flight worker claim is released' grep -Eq -- '^release .*--scan sess-signal$' "$S/stamp.log"
sleep 3

mv "$S/ready.saved" "$S/ready.json"; mv "$S/pr-list.saved" "$S/pr-list.json"
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"

# --- empty PR queue ------------------------------------------------------------------
jq -nc '{repos_missing_fixup_hard:[]}' > "$S/audit.json"
run --prs
has 'nothing to fix up says so' 'nothing to work on .* \(kinds: pr\)'
eq 'and exits 0' 0 "$RC"

# --- main itself is red: the whole --prs pass pauses, not just the queued PRs --------
jq -nc '{repos_base_red:["alpha"]}' > "$S/audit.json"
: > "$CLAUDE_LOG"
run --prs
eq 'exit 0 -- a red base is not a failure' 0 "$RC"
eq 'no worker spent' 0 "$(calls_claude)"
has 'the pass says why it paused' 'base branch is red.*skipping the pr kind'
jq -nc '{repos_missing_fixup_hard:[]}' > "$S/audit.json"

# --- --resume of a --prs session stays on the PR queue --------------------------------
# The UNVERIFIED line promises a retry on `grind --resume <id>`, with no
# --prs on it; the session file has to carry the mode or that retry would
# quietly work the Ready queue on the PR session's budget.
cp "$S/prs-session.saved" "$prs_session_file"
prs_session=$(basename "$prs_session_file" .json)
eq 'the session file records the mode' 1 "$(jq -r .prs "$S/state/grind/$prs_session.json")"
run --resume "$prs_session"
has 'resumed without --prs, it still reads the PR queue' 'nothing to work on .* \(kinds: pr\)'
eq 'the session file records the kinds' pr "$(jq -r .kinds "$S/state/grind/$prs_session.json")"
# A session file from before the field existed is an issue session.
jq 'del(.prs, .kinds)' "$S/state/grind/$prs_session.json" > "$S/state/grind/grind-old.json"
run --resume grind-old --prs
eq 'an issue session cannot be resumed as --prs' 1 "$RC"
has 'and says why' 'worked kinds \[issue\]; drop --prs/--kind'

unset GRIND_ROOT
cd "$S/repo" || exit 1
cat > "$S/bin/gh" <<GH
#!/bin/sh
echo "\$*" >> "$GH_LOG"
filter=""; prev=""
for a in "\$@"; do [ "\$prev" = "--jq" ] && filter=\$a; prev=\$a; done
[ -n "\$filter" ] || filter="."
case "\$1 \$2" in
  "issue list") cat "$S/ready.json" ;;
  "pr list")    jq -r "\$filter" "$S/pr-list.json" ;;
  "issue view") jq -r "\$filter" "$S/issue-comments.json" ;;
  "pr view")    f="$S/prview/\$(printf '%s' "\$3" | tr '/:' '__').json"; [ -f "\$f" ] && jq -r "\$filter" "\$f" ;;
  "api repos/"*"/sub_issues"*) f="$S/subs/\$(printf '%s' "\${2%%\?*}" | tr / _).json"; if [ "\$(cat "\$f" 2>/dev/null)" = FAIL ]; then exit 1; elif [ -f "\$f" ]; then cat "\$f"; else echo '[]'; fi ;;
  "api repos/"*"/issues/"*) if [ -f "$S/updated-at" ]; then cat "$S/updated-at"; else echo 2999-01-01T00:00:00Z; fi ;;
  "api user")   [ -f "$S/user-fail" ] && exit 1; echo grind-me ;;
  *) echo "gh shim: unexpected \$*" >&2; exit 1 ;;
esac
GH
chmod +x "$S/bin/gh"

# --- review band: pause dispatch while PRs awaiting a look pile up -----------------
# memory: review-band-five-to-ten (Solace, 2026-09-22); design rung 1b. Cap is
# read from worklist's own buckets.awaiting_human, the record grind already
# fetches -- no extra gh call needed to know the band is full. Base sandbox
# ($S/repo, no signing key), so the pr kind drops itself silently and only
# the one Ready issue queues -- exactly what makes "one claude call" legible.
cat > "$S/ready.json" <<'JSON'
[
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]}
]
JSON
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
echo "\$*" >> "$CLAUDE_LOG"
echo '{"type":"assistant","message":{"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}'
echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0},"result":"GRIND_STATUS: done"}'
GH
chmod +x "$S/bin/claude"
rm -f "$S/state/grind"/*.json "$S/state/grind"/band-paused-* "$S/claude-replies"/*.json
: > "$CLAUDE_LOG"

jq -nc '[range(0;10)|{number:(100+.)}]' > "$S/awaiting-human.json"
run --session-budget 100 --pause-every 10
eq 'exit 0' 0 "$RC"
eq 'no claude call: the band is already at ten' 0 "$(calls_claude)"
has 'says it is pausing, names the count and the repo' \
  '^grind: pausing -- 10 PR\(s\) awaiting your look on o/alpha \(band 5-10; resumes below 5\)$'
assert 'a band marker was written for this repo' test -f "$S/state/grind/band-paused-o_alpha"
assert 'the band pause left no session file behind' bash -c '! ls "$1"/state/grind/*.json >/dev/null 2>&1' _ "$S"

# Still ten, or a lighter eight: the marker holds the pause either way --
# resuming needs the count below five, not merely below ten.
run --session-budget 100 --pause-every 10
eq 'still paused at ten' 0 "$(calls_claude)"
jq -nc '[range(0;8)|{number:(100+.)}]' > "$S/awaiting-human.json"
run --session-budget 100 --pause-every 10
eq 'still paused at eight -- hysteresis holds the ten-triggered pause' 0 "$(calls_claude)"
has 'the repeat-hit line, not the first-hit one' \
  '^grind: paused -- 8 PR\(s\) awaiting your look on o/alpha \(resumes below 5\)$'
assert 'nor did the repeat pause' bash -c '! ls "$1"/state/grind/*.json >/dev/null 2>&1' _ "$S"

# Below five (strictly -- "resumes below 5" means four, not five): the
# marker clears and dispatch resumes.
jq -nc '[range(0;4)|{number:(200+.)}]' > "$S/awaiting-human.json"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
eq 'exit 0' 0 "$RC"
eq 'one claude call once the band drops below five' 1 "$(calls_claude)"
assert 'the band marker was cleared' test ! -f "$S/state/grind/band-paused-o_alpha"

# A mid-band count that never crossed ten sets no marker, and five-to-ten
# alone is not a floor on ordinary dispatch (it only holds a pause that
# already fired).
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
jq -nc '[range(0;7)|{number:(300+.)}]' > "$S/awaiting-human.json"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
eq 'a mid-band count dispatches -- no marker was ever set' 1 "$(calls_claude)"

# --dry-run never consults the band. Clear state first: a same-second
# session id would otherwise reuse the just-written state file and read the
# item dispatched above as already done.
rm -f "$S/state/grind"/*.json
jq -nc '[range(0;10)|{number:(100+.)}]' > "$S/awaiting-human.json"
run --dry-run
eq 'exit 0' 0 "$RC"
has 'dry-run still shows the plan' '\[1/1\] o/alpha#5'

rm -f "$S/awaiting-human.json" "$S/state/grind"/band-paused-* "$S/state/grind"/*.json "$S/claude-replies"/*.json

# --- a logged-out claude is refused before any worktree or state file -------
# The observed failure (2026-09-16): every item came back $0, 0 tokens,
# "OAuth session expired", three runs in a row, and grind said only "worker
# reported an error".
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":false,"authMethod":"none"}'; exit 0; }
echo "\$*" >> "$CLAUDE_LOG"
cat > "$S/prompt.txt"
echo '{"type":"result","is_error":true,"total_cost_usd":0,"usage":{},"result":"Failed to authenticate: OAuth session expired and could not be refreshed"}'
GH
chmod +x "$S/bin/claude"
rm -f "$S/state/grind"/*.json
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
eq 'exit 1 when claude is logged out' 1 "$RC"
has 'says how to fix it' 'claude is not logged in .*claude auth login'
eq 'no worker invocation' 0 "$(calls_claude)"
assert 'no state file written' bash -c '! ls '"$S"'/state/grind/*.json >/dev/null 2>&1'
run --dry-run
eq 'dry-run does not consult auth' 0 "$RC"

# --- grind's own record, and what it has already looked at ---------------------
# Run grind-20261003T134428Z: two workers ended their real answer with
# GRIND_STATUS: blocked, the interactive Stop hook made each say one more
# line, grind read that line, called both "claimed success" and would have
# paid for both again on --resume. What matters: the last status line
# anywhere in the worker's output is the claim; grind itself writes the
# outcome, cost and run on the item's work item in the private store (never
# on GitHub); a later run skips an item whose outcome is newer than its last
# real change and works untouched items first; a done claim backed by a PR
# opened in another repo during the run is verified.
cat > "$S/bin/claude" <<GH
#!/bin/sh
[ "\$1" = auth ] && { echo '{"loggedIn":true,"authMethod":"claude.ai"}'; exit 0; }
cat > "$S/prompt.txt"
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
reply="$S/claude-replies/\$n.json"
if [ -f "\$reply" ]; then cat "\$reply"; else
  echo '{"type":"result","total_cost_usd":0.10,"usage":{"input_tokens":100,"output_tokens":50},"result":"GRIND_STATUS: done"}'
fi
GH
chmod +x "$S/bin/claude"
# said <n> <cost> <message>... -- one assistant event per message, then a
# result whose text is the last message, as claude -p streams it.
said() {
  n=$1; c=$2; shift 2; : > "$S/claude-replies/$n.json"
  for m in "$@"; do
    jq -nc --arg t "$m" '{type:"assistant", message:{content:[{type:"text", text:$t}], usage:{input_tokens:100,output_tokens:50}}}' >> "$S/claude-replies/$n.json"
  done
  jq -nc --argjson c "$c" --arg t "$m" '{type:"result", total_cost_usd:$c, usage:{input_tokens:1000,output_tokens:234}, result:$t}' >> "$S/claude-replies/$n.json"
}
cat > "$S/ready.json" <<'JSON'
[
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
  {"number": 20, "title": "Second item", "body": "do the second thing", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]}
]
JSON
echo '[]' > "$S/pr-list.json"
rec="$S/rec-state"; export WORK_ITEM_DIR="$rec/items"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
mkdir -p "$WORK_ITEM_DIR"; "$REAL_GIT" -C "$rec" init -q; "$REAL_GIT" -C "$rec" commit -q --allow-empty -m init
home_of() { grep -l " home=$1\$" "$WORK_ITEM_DIR"/*.md 2>/dev/null | head -n 1; }
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json "$S/updated-at"; forget_records; : > "$CLAUDE_LOG"

# grind records on an item whose home= is the issue; it never makes one
mkhome() {
  CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" create --id "$2" --repo o/alpha \
    --brief "work on $1" "$1" >/dev/null
  CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log "$2" status=ready "home=$1" >/dev/null
}
# an issue with no work item whose home= it is gets none made
said 1 0.10 'Nothing to do.
GRIND_STATUS: blocked'
run --session-budget 100 --pause-every 1
has 'with no home item, grind says so' 'INFO  no work item has home=o/alpha#5; outcome not recorded'
assert 'and makes no item' test -z "$(home_of 'o/alpha#5')"
eq 'nor any item at all' 0 "$(find "$WORK_ITEM_DIR" -mindepth 1 | grep -c . || true)"
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$CLAUDE_LOG"
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/5" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-5 >/dev/null 2>&1
mkhome 'o/alpha#5' 1790985001aaaaaaa1
mkhome 'o/alpha#20' 1790985002aaaaaaa2
mkhome 'o/alpha#17' 1790985017aaaaaa17
# outcome 3: the status line is found though a later message has none
said 1 1.37 'Ruled already in dotfiles#94; nothing to build.
Left a comment on the issue saying so.
GRIND_STATUS: blocked' 'Landed in the pickup item at state/global/pickup/x.md'
KEEP_RECORDS=1 run --session-budget 100 --pause-every 1
has 'a status line before the hand-off line is the claim' '^blocked: o/alpha#5 -- First item \(\$1\.37, 1234 tokens'
lacks 'not a claimed success' 'UNVERIFIED: o/alpha#5'
rec_sess=$(basename "$(latest_session)" .json)

# outcome 1: the record, on the GitHub item's work item, in the store's form
f=$(home_of 'o/alpha#5')
assert "the issue's existing item is found by its home" test -n "$f"
LOG=$(cat "$f" 2>/dev/null)
OUT=$LOG
has 'the cost line, in the store form' ' cost tokens=1234 usd=1\.37 by=grind$'
has 'the outcome line: status, run and no PR' " grind outcome=blocked run=$rec_sess prs= said: "
has 'what the worker did, on one line, from the message with the status' 'said: Ruled already in dotfiles#94; nothing to build\. Left a comment on the issue saying so\.$'
lacks 'not the hand-off line' 'pickup item'
eq "its status is not moved: grind records outcomes, it does not run an issue item's state" ready "$("$GRIND_WORK_ITEM" fold "$(basename "$f" .md)" | sed -n 's/^status=//p')"
eq 'its cost folds' '1234 1.37' "$("$GRIND_WORK_ITEM" fold "$(basename "$f" .md)" | sed -n 's/^cost_tokens=//p; s/^cost_usd=//p' | paste -sd' ' -)"
eq 'and it is committed in the state repo' 'grind: blocked -- o/alpha#5' "$("$REAL_GIT" -C "$rec" log -1 --format=%s)"
assert 'grind posted nothing on GitHub' bash -c '! grep -Eq "(issue|pr) comment" "$GH_LOG"'

# --resume never retries a blocked item
: > "$CLAUDE_LOG"; rm -f "$S/claude-replies"/*.json
echo '[{"createdAt": "2999-01-01T00:00:00Z", "updatedAt": "2999-01-01T00:00:00Z", "state": "OPEN", "url": "https://github.com/o/alpha/pull/21"}]' > "$S/pr-list.json"
KEEP_RECORDS=1 run --resume "$rec_sess" --pause-every 1
has 'resume moves on to the untouched item' '^o/alpha#20: Second item'
lacks 'and never retries the blocked one' 'starting o/alpha#5'
echo '[]' > "$S/pr-list.json"

# outcome 2: a new run skips what grind looked at and nothing has changed since
echo 2001-01-01T00:00:00Z > "$S/updated-at"
rm -f "$S/state/grind"/*.json; : > "$CLAUDE_LOG"
KEEP_RECORDS=1 run --dry-run
has 'the dry run says why it skips' '^o/alpha#5 -- SKIP: grind recorded blocked at .* \(run '"$rec_sess"'\), and nothing has changed since$'
has 'and the other one too' '^o/alpha#20 -- SKIP: grind recorded done at'
KEEP_RECORDS=1 run --session-budget 100
has 'a real run skips both, on INFO lines' 'INFO  skipping o/alpha#5 -- grind recorded blocked'
eq 'and pays for neither' 0 "$(calls_claude)"
assert 'the GitHub item was asked when it last changed' grep -q 'api repos/o/alpha/issues/5 --jq .updated_at' "$GH_LOG"
# a line on the work item from anyone but grind is a change
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log "$(basename "$(home_of 'o/alpha#5')" .md)" triaged >/dev/null
KEEP_RECORDS=1 run --dry-run
has 'a human line on the item makes it workable again' '^\[1/1\] o/alpha#5 -- First item$'
# so is a change on GitHub; and an item grind never touched goes first
echo 2999-01-01T00:00:00Z > "$S/updated-at"
jq '. + [{"number": 30, "title": "Third item", "body": "untouched", "url": "https://github.com/o/alpha/issues/30", "labels": [{"name": "ready"}]}]' "$S/ready.json" > "$S/ready.tmp" && mv "$S/ready.tmp" "$S/ready.json"
KEEP_RECORDS=1 run --dry-run
has 'the untouched item first' '^\[1/3\] o/alpha#30 -- Third item$'
has 'then the changed ones, lowest number first' '^\[2/3\] o/alpha#5 -- First item$'
has 'a GitHub change makes an item workable again' '^\[3/3\] o/alpha#20 -- Second item$'

# outcome 4: done, with the PR in another repo, opened during the run
cat > "$S/ready.json" <<'JSON'
[{"number": 17, "title": "Cross-repo item", "body": "fix it in .github", "url": "https://github.com/o/alpha/issues/17", "labels": [{"name": "ready"}]}]
JSON
mkdir -p "$S/prview"
pv() { jq -nc --arg c "$2" --arg a "$3" --arg h "$4" --arg b "$5" '{createdAt:$c, author:{login:$a}, headRefName:$h, body:$b}' > "$S/prview/$1.json"; }
pv https___github.com_o_dotgithub_pull_47 2999-01-01T00:00:00Z grind-me fix-it 'Fixes it. Grind item: o/alpha#17'
pv https___github.com_o_alpha_pull_3 2001-01-01T00:00:00Z grind-me old 'Grind item: o/alpha#17'
pv https___github.com_o_dotgithub_pull_48 2999-01-01T00:00:00Z someone-else fix-it 'Grind item: o/alpha#17'
pv https___github.com_o_dotgithub_pull_49 2999-01-01T00:00:00Z grind-me unrelated 'Some other work entirely'
pv https___github.com_o_dotgithub_pull_50 2999-01-01T00:00:00Z grind-me grind-17 'no marker, but on the item branch'
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$CLAUDE_LOG"
said 1 0.80 'The fix belongs in o/dotgithub: opened https://github.com/o/dotgithub/pull/47 (see also https://github.com/o/alpha/pull/3).
GRIND_STATUS: done'
KEEP_RECORDS=1 run --session-budget 100 --pause-every 1
has 'a PR opened in another repo during the run verifies done' '^o/alpha#17: Cross-repo item -- sonnet, \$0\.80'
f=$(home_of 'o/alpha#17'); OUT=$(cat "$f" 2>/dev/null)
has 'the record names it, and only the PR opened during the run' ' grind outcome=done run=[^ ]+ prs=https://github\.com/o/dotgithub/pull/47 said: '
# a PR it merely mentions, opened before the run, is not its work
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
said 1 0.80 'Already in flight as https://github.com/o/alpha/pull/3.
GRIND_STATUS: done'
run --session-budget 100 --pause-every 1
has 'an old PR it names does not verify done' '^UNVERIFIED: o/alpha#17 -- Cross-repo item -- worker claimed success but no PR opened'
# a PR another account opened, or one with no tie to the item, is not its work
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
said 1 0.80 'Opened https://github.com/o/dotgithub/pull/48 and https://github.com/o/dotgithub/pull/49.
GRIND_STATUS: done'
KEEP_RECORDS=1 run --session-budget 100 --pause-every 1
has 'a PR by another account, or untied to the item, does not verify done' '^UNVERIFIED: o/alpha#17'
# a PR on the item's own branch needs no marker
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
said 1 0.80 'Opened https://github.com/o/dotgithub/pull/50.
GRIND_STATUS: done'
KEEP_RECORDS=1 run --session-budget 100 --pause-every 1
has 'a PR on the item branch verifies done' '^o/alpha#17: Cross-repo item -- sonnet'
# an account grind cannot read counts no named PR, and says so
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json; : > "$S/user-fail"
said 1 0.80 'Opened https://github.com/o/dotgithub/pull/47.
GRIND_STATUS: done'
KEEP_RECORDS=1 run --session-budget 100 --pause-every 1
rm -f "$S/user-fail"
has 'an unreadable account is a WARN' 'WARN  could not read the account grind runs as'
has 'and the item is unverified' '^UNVERIFIED: o/alpha#17'
# a failed or unverified outcome is not a skip marker: the next fresh run retries the item
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
fid=$(basename "$(home_of 'o/alpha#17')" .md)
CLAUDE_CODE_SESSION_ID=cafe0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log "$fid" grind outcome=unverified run=grind-x said: nothing >/dev/null
CLAUDE_CODE_SESSION_ID=feed0000-0000-0000-0000-000000000000 "$GRIND_WORK_ITEM" log "$fid" cost tokens=1 usd=0.1 by=grind >/dev/null
rm -f "$S/state/grind"/*.json
KEEP_RECORDS=1 run --dry-run
lacks 'an unverified outcome does not park the item' 'o/alpha#17 -- SKIP'
# a status mentioned mid-sentence is not a claim; a line that opens with one is
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
said 1 0.80 'Reading the issue; I will end with GRIND_STATUS: blocked if it is ruled.' 'Nothing ruled it. Opened nothing yet.'
run --session-budget 100 --pause-every 1
lacks 'a mid-sentence mention is no claim' '^blocked: o/alpha#17'
has 'so the item is a claimed success to verify' '^UNVERIFIED: o/alpha#17'
git -C "$S/repo" worktree remove -f "$TMPDIR/grind-worktrees/17" >/dev/null 2>&1; git -C "$S/repo" branch -D grind-17 >/dev/null 2>&1
rm -f "$S/state/grind"/*.json "$S/claude-replies"/*.json
said 1 0.80 'Ruled in dotfiles#94.
**GRIND_STATUS: blocked**' 'Landed in the pickup item.'
run --session-budget 100 --pause-every 1
has 'a bolded status line is a claim' '^blocked: o/alpha#17'
unset WORK_ITEM_DIR GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
