#!/usr/bin/env bash
# Tests for grind. Run: bash .local/bin/grind.test.sh
#
# What matters: --dry-run lists every Ready (non-blocked) item and the exact
# command per item without spending anything; a real run parses cost/tokens
# out of the worker's JSON, prints the running-total/percent line, and pauses
# -- with the exact resume command -- on session budget, an outlier item cost,
# or the pause-every cadence; a carded worker is logged and not treated as a
# failure; --resume skips what a prior run already accounted for. gh and
# claude are both faked; no real `claude -p` is ever invoked.
set -uo pipefail

GRIND="$(cd "$(dirname "$0")" && pwd)/grind"
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
cd "$S/repo" || exit 1

# --- canned Ready queue --------------------------------------------------------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 20, "title": "Second item", "body": "do the second thing", "url": "https://github.com/o/alpha/issues/20", "labels": [{"name": "ready"}]},
  {"number": 5, "title": "First item", "body": "do the first thing", "url": "https://github.com/o/alpha/issues/5", "labels": [{"name": "ready"}]},
  {"number": 9, "title": "Blocked item", "body": "not yet", "url": "https://github.com/o/alpha/issues/9", "labels": [{"name": "ready"}, {"name": "blocked"}]}
]
JSON

cat > "$S/bin/gh" <<GH
#!/bin/sh
echo "\$*" >> "$GH_LOG"
case "\$1 \$2" in
  "issue list") cat "$S/ready.json" ;;
  *) echo "gh shim: unexpected \$*" >&2; exit 1 ;;
esac
GH
chmod +x "$S/bin/gh"

# fake claude -- reads the prompt from stdin (unused), writes canned
# stream-json lines read from $S/claude-replies/<n>.json for the current
# item (an assistant event followed by a result event, one per line, as the
# real worker now streams), defaulting to a flat two-line reply. grind reads
# claude's stdout line by line now, so the shim must emit newline-delimited
# JSON, never one blob.
mkdir -p "$S/claude-replies"
cat > "$S/bin/claude" <<GH
#!/bin/sh
cat > /dev/null
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
has()  { if printf '%s\n' "$OUT" | grep -Eq -- "$2"; then ok; else bad "$1 (missing /$2/)" "$OUT"; fi; }
lacks(){ if printf '%s\n' "$OUT" | grep -Eq -- "$2"; then bad "$1 (has /$2/)" "$OUT"; else ok; fi; }
eq()   { if [ "$2" = "$3" ]; then ok; else bad "$1: want [$2] got [$3]"; fi; }
assert() { local d=$1; shift; if "$@"; then ok; else bad "$d"; fi; }
run() { rm -f "$S/claude-next"; OUT=$(sh "$GRIND" "$@" 2>&1); RC=$?; }
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
has 'a worktree command is shown' 'git worktree add -b grind-5'
has 'the claude command is shown, with defaults' 'claude -p <issue o/alpha#5 body> --output-format stream-json --verbose --max-budget-usd 5 --model sonnet --effort medium'
assert 'dry-run wrote no state file' bash -c '! ls '"$S"'/state/grind/*.json >/dev/null 2>&1'

# --- --dry-run respects override flags -----------------------------------------
run --dry-run --model opus --effort high --item-budget 2
has 'overrides reach the command line' -- '--max-budget-usd 2 --model opus --effort high'

# --- a real run: cost/tokens parsed, running total and percent printed ----------
rm -f "$S/claude-replies"/*.json
reply 1.00 "done" 1
reply 2.00 "done" 2
: > "$CLAUDE_LOG"
run --session-budget 20 --pause-every 5
eq 'exit 0' 0 "$RC"
eq 'two claude invocations' 2 "$(calls_claude)"
has 'first item line: cost, tokens, running total, percent' '^o/alpha#5: First item -- sonnet, \$1\.00, 150 tokens -- running \$1\.00 / \$20\.00 -- 5%$'
has 'second item line: running total accumulates' '^o/alpha#20: Second item -- sonnet, \$2\.00, 150 tokens -- running \$3\.00 / \$20\.00 -- 15%$'
has 'queue exhausted, final tally' '^done: Ready queue exhausted\. Running total \$3\.00 / \$20\.00\. 0 skipped\.$'
has 'INFO: session line names repo, count, model, caps' 'INFO  session grind-.* on o/alpha: 2 Ready item\(s\), sonnet/medium, cap \$5\.00/item \$20\.00/session'
has 'INFO: item start line' 'INFO  \[1/2\] starting o/alpha#5 -- First item'
has 'INFO: worker line names the permission mode' 'INFO  worker running: .*--permission-mode acceptEdits'
has 'INFO: worker exit line' 'INFO  worker exited 0 after [0-9]+s'
has 'worker gets --permission-mode' '--permission-mode acceptEdits' 
sess=$(latest_session)
eq 'two items recorded in state' 2 "$(jq '.items | length' "$sess")"

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
cat > /dev/null
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
has 'heartbeat line carries elapsed time, a token count, and a ~$ estimate -- both assistant events accumulated (15000+10000+20000+3000=48000 -> 48k)' \
  'still working on o/alpha#5 \([0-9]+m elapsed, ~48k tokens, ~\$[0-9]+\.[0-9]{2} so far\)'
has 'the final line still uses the exact total_cost_usd, not the estimate' '^o/alpha#5: First item -- sonnet, \$0\.90,'

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
cat > /dev/null
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
has 'says the queue is done' 'Ready queue exhausted'
eq 'state file unchanged (still 2 items)' 2 "$(jq '.items | length' "$sess")"

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
has 'tally counts the skip' 'Ready queue exhausted\. .* 1 skipped\.$'
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
has 'runs to completion instead' '^done: Ready queue exhausted'

# --- carded: logged, not a failure, item still counted toward pause-every -------
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

# --- a failed claude invocation is not recorded as done; --resume retries it ------
cat > "$S/ready.json" <<'JSON'
[
  {"number": 7, "title": "Flaky item", "body": "b", "url": "https://github.com/o/alpha/issues/7", "labels": [{"name": "ready"}]}
]
JSON
rm -f "$S/state/grind"/*.json
rm -f "$S/claude-replies"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
cat > /dev/null
n=\$(cat "$S/claude-next" 2>/dev/null || echo 1)
echo "\$n \$*" >> "$CLAUDE_LOG"
echo \$((n + 1)) > "$S/claude-next"
exit 1
GH
chmod +x "$S/bin/claude"
: > "$CLAUDE_LOG"
run --session-budget 100 --pause-every 10
has 'a failed invocation is logged as a failure, not a normal cost line' '^FAILED: o/alpha#7'
lacks 'no cost line for the failed item' '^o/alpha#7: Flaky item --'
sess=$(latest_session)
eq 'failed item is not recorded in state' 0 "$(jq '.items | length' "$sess")"

# restore the real claude shim and confirm --resume retries the failed item
cat > "$S/bin/claude" <<GH
#!/bin/sh
cat > /dev/null
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
eq 'now recorded in state' 1 "$(jq '.items | length' "$sess")"

# --- a worker that exits non-zero WITH a JSON result: cost kept, item retried ------
rm -f "$S/state/grind"/*.json
cat > "$S/bin/claude" <<GH
#!/bin/sh
cat > /dev/null
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
sess=$(latest_session)
eq 'recorded in state as failed' failed "$(jq -r '.items[0].status' "$sess")"
eq 'its cost is kept' 5.00 "$(jq -r '.items[0].cost' "$sess")"
has 'running total includes the failed spend' 'running \$5\.00 / \$100\.00'
session_id=$(basename "$sess" .json)
: > "$CLAUDE_LOG"
run --resume "$session_id"
eq 'failed-with-cost item retried on resume' 1 "$(calls_claude)"

# restore the real claude shim
cat > "$S/bin/claude" <<GH
#!/bin/sh
cat > /dev/null
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

# --- --repo naming a repo the cwd is not a checkout of ---------------------------
run --repo o/other
eq 'exit 1 when cwd is not a checkout of --repo' 1 "$RC"
has 'says which repo it found' 'not a checkout of o/other \(found: o/alpha\)'

# --- empty queue -----------------------------------------------------------------
cat > "$S/ready.json" <<'JSON'
[]
JSON
run
eq 'exit 0 on an empty queue' 0 "$RC"
has 'says nothing is ready' '^grind: no Ready items on o/alpha$'

# --- not in a repo, no --repo given -----------------------------------------------
cd "$S/nogit" || exit 1
run
eq 'exit 1 outside a repo without --repo' 1 "$RC"
has 'says so' 'not in a GitHub repo'
cd "$S/repo" || exit 1

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
