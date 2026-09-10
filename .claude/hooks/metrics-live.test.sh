#!/usr/bin/env bash
# Tests for the crossing engine in metrics-live.sh.
# Run: bash .claude/hooks/metrics-live.test.sh
#
# What matters is that the nag is edge-triggered: a line fires once when its
# counter first crosses, and then not again until the next line. Three
# properties, one per case in issue #111's Verification section:
#
#   crossing    a transcript that grows past 100k then past 150k produces
#               exactly two context lines, in that order, and the second one
#               says to propose stopping
#   the gap     a gap over 30 minutes between prompts starts a new sitting, so
#               the 60-minute line does not fire on a clock that began before
#               the gap -- and a short gap leaves that clock running
#   the clock    prompts own it outright: a Stop or a SubagentStop never starts
#               it, never moves it and never reads it out, so a session whose
#               first wired event is a Stop is sitting for zero minutes
#   the Stop    a Stop on an archivable session past the line blocks once with
#               one instruction, then passes with the resume-block message, and
#               every Stop after that carries only the block's age
#
# The transcripts are built here rather than committed: each one exists to hold
# a single usage number, and a fixture file would say less than the generator.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/metrics-live.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME" "$SCRATCH/bin"
export CLAUDE_STATE_REPO=""
STATE="$HOME/.claude/state/global"

t() {  # t <desc> <want> <got>
  if [ "$2" = "$3" ]; then pass=$((pass+1))
  else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi
}
has() {  # has <desc> <pattern> <text>
  if printf '%s' "$3" | grep -Eq -- "$2"; then pass=$((pass+1))
  else fail=$((fail+1)); printf 'FAIL (no /%s/): %s\n  in [%s]\n' "$2" "$1" "$3"; fi
}
hasnt() {
  if printf '%s' "$3" | grep -Eq -- "$2"; then
    fail=$((fail+1)); printf 'FAIL (has /%s/): %s\n  in [%s]\n' "$2" "$1" "$3"
  else pass=$((pass+1)); fi
}

# --- transcripts -------------------------------------------------------------
# One human turn plus one assistant turn carrying the context number. Appending
# another pair with a bigger number is how a session grows past a line.
turn() {  # turn <file> <context tokens>
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" \
    '{type:"queue-operation", operation:"enqueue", timestamp:$ts,
      sessionId:"t", content:"go on"}' >> "$1"
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" --argjson n "$2" \
    --arg u "req-$(wc -l < "$1" | tr -d ' ')" \
    '{type:"assistant", timestamp:$ts, requestId:$u,
      message:{model:"claude-opus-5", role:"assistant",
               content:[{type:"text", text:"ok"}],
               usage:{input_tokens:$n, output_tokens:10,
                      cache_read_input_tokens:0, cache_creation_input_tokens:0}}}' >> "$1"
}

payload() {  # payload <transcript> <session id> <cwd> [hook_event_name]
  jq -nc --arg tp "$1" --arg sid "$2" --arg cwd "$3" --arg h "${4:-}" \
    '{transcript_path:$tp, session_id:$sid, cwd:$cwd}
     + (if $h == "" then {} else {hook_event_name:$h} end)'
}

msg() { printf '%s' "$1" | jq -r '.systemMessage // ""' 2>/dev/null; }

# --- 1. two context lines, in order ------------------------------------------
TP="$SCRATCH/ctx.jsonl"; SID=ctx1
turn "$TP" 103000
out1=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
turn "$TP" 152000
out2=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
out3=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)

has  'first crossing names 100k'      'past 100k' "$(msg "$out1")"
hasnt 'first crossing does not propose stopping' 'propose stopping' "$(msg "$out1")"
has  'second crossing names 150k'     'past 150k' "$(msg "$out2")"
has  'second crossing proposes stopping' 'propose stopping' "$(msg "$out2")"
t    'nothing fires a third time'     '' "$(msg "$out3")"

CROSS="$STATE/metrics/crossings/$SID.jsonl"
t 'both crossings are recorded, in order' \
  "$(printf '100000\n150000')" \
  "$(jq -r 'select(.kind == "context") | .at' "$CROSS" 2>/dev/null)"

# --- 2. a 40-minute gap starts a new sitting ---------------------------------
# The clock is wall-clock, so the way to put a session 61 minutes in is to
# write the state file the engine reads, which is what a resumed session's
# state actually looks like.
sitting() {  # sitting <session id> <minutes since sitting start> <minutes since last prompt>
  local n=$STATE/metrics/live/$1.nag.json
  mkdir -p "$(dirname "$n")"
  jq -n --argjson ss "$(( $(date +%s) - $2 * 60 ))" \
        --argjson lp "$(( $(date +%s) - $3 * 60 ))" \
    '{context_line:200000, time_line:0, gate_line:0, friction_tripped:false,
      sitting_start:$ss, last_prompt:$lp, since_nag:false,
      resume_ts:0, nag_pending:false}' > "$n"
}

TP2="$SCRATCH/sit.jsonl"; turn "$TP2" 1000
sitting gap 61 40
out=$(payload "$TP2" gap "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
hasnt 'a 40 min gap resets the clock: no 60 min line' '⏱' "$(msg "$out")"

sitting nogap 61 10
out=$(payload "$TP2" nogap "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'a 10 min gap leaves the clock running' '⏱ sitting 1h00' "$(msg "$out")"
has 'the clock line carries the context'    'context 1k'     "$(msg "$out")"
has 'and one hour says stand up'            'stand up'       "$(msg "$out")"

out=$(payload "$TP2" nogap "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
t 'the 60 min line does not repeat' '' "$(msg "$out")"

sitting twohours 121 10
out=$(payload "$TP2" twohours "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'two hours names the exit' 'sitting 2h00 .* stop here, run /wrapup' "$(msg "$out")"

# --- 2b. the clock belongs to the prompt -------------------------------------
# $SCRATCH is not a git repo, so archivable() refuses and the Stop nag stays
# out of the way; what is under test here is only the clock.
sit_start() { jq -r '.sitting_start // 0' "$STATE/metrics/live/$1.nag.json" 2>/dev/null; }

TPS="$SCRATCH/stopfirst.jsonl"; turn "$TPS" 1000
payload "$TPS" sfirst "$SCRATCH" Stop \
  | bash "$HOOK" stop 0 show >/dev/null 2>&1
t 'a Stop before any prompt does not start the clock' 0 "$(sit_start sfirst)"

payload "$TPS" sfirst "$SCRATCH" SubagentStop \
  | bash "$HOOK" subagentstop 0 show >/dev/null 2>&1
t 'nor does a SubagentStop' 0 "$(sit_start sfirst)"

out=$(payload "$TPS" sfirst "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
hasnt 'so the first prompt after them is minute zero' '⏱' "$(msg "$out")"
t 'and it is the prompt that starts the clock' yes \
  "$( [ "$(sit_start sfirst)" -gt 0 ] && echo yes || echo no )"

# An hour on the clock: a Stop must neither report it nor disturb it.
sitting quiet 61 10
before=$(sit_start quiet)
out=$(payload "$TPS" quiet "$SCRATCH" Stop | bash "$HOOK" stop 0 show 2>&1)
hasnt 'a Stop past the line says nothing about sitting' '⏱ sitting' "$(msg "$out")"
t    'and leaves the clock exactly where it found it' "$before" "$(sit_start quiet)"
out=$(payload "$TPS" quiet "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has  'the next prompt is what reports it' '⏱ sitting 1h00' "$(msg "$out")"

# --- 3. Stop, archivable, past the line --------------------------------------
REPO="$SCRATCH/repo"; mkdir -p "$REPO"
git -C "$REPO" init -q -b feat/nags
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
cat > "$SCRATCH/bin/gh" <<'GH'
#!/bin/sh
echo 1
GH
chmod +x "$SCRATCH/bin/gh"
export PATH="$SCRATCH/bin:$PATH"

TP3="$SCRATCH/stop.jsonl"; turn "$TP3" 1000
S() { payload "$TP3" stop1 "$REPO" Stop \
      | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1; }

o1=$(S)
t   'the first Stop blocks'  block "$(printf '%s' "$o1" | jq -r '.decision // ""')"
has 'with one instruction'   '^Write the resume block: append a `## Resume` block' \
    "$(printf '%s' "$o1" | jq -r '.reason // ""')"

# The model answers the block by writing the checkpoint's resume block. The
# hook must find it on disk, not assume it from having asked.
CK="$STATE/log/auto"; mkdir -p "$CK"
printf '# ckpt\n\n## Resume\n\n- next: x\n' > "$CK/2026-09-09-repo-stop1.md"
o2=$(S)
t   'the second Stop does not block' '' "$(printf '%s' "$o2" | jq -r '.decision // ""')"
has 'and reports the resume block it found' \
    '^Archivable\. Resume block written [0-9]{2}:[0-9]{2} in 2026-09-09-repo-stop1\.md\. Next time: `/resume`\.$' \
    "$(msg "$o2" | head -1)"

o3=$(S)
t     'a later Stop does not block'  '' "$(printf '%s' "$o3" | jq -r '.decision // ""')"
has   'and carries only the age'     'Resume block 0m old' "$(msg "$o3")"
hasnt 'not the message again'        'Next time' "$(msg "$o3")"

# The block was ignored: no `## Resume` anywhere. Say so, do not claim one,
# and do not block again -- the late-hour arm is spent for the session.
S3() { payload "$TP3" stop3 "$REPO" Stop \
       | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1; }
o=$(S3); t 'blocks once' block "$(printf '%s' "$o" | jq -r '.decision // ""')"
o=$(S3)
t     'an unanswered block does not re-block' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
has   'and reports the block as missing' 'no `## Resume` block' "$(msg "$o")"
hasnt 'never claims it was written'      'Resume block written' "$(msg "$o")"
o=$(S3); t 'and stays quiet after' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"

# A crossing that arms the Stop is consumed by it, so the block reason has to
# carry the line -- otherwise the threshold that caused the block is never seen.
TP4="$SCRATCH/cross.jsonl"; turn "$TP4" 103000
o=$(payload "$TP4" stop4 "$REPO" Stop | METRICS_STOP_HOUR=23 bash "$HOOK" stop 0 show 2>&1)
t   'a context crossing at Stop blocks' block "$(printf '%s' "$o" | jq -r '.decision // ""')"
has 'and the reason carries the crossing line' '⛁ context 103k — past 100k' \
    "$(printf '%s' "$o" | jq -r '.reason // ""')"

# A dirty tree is not archivable, so nothing blocks however late it is.
: > "$REPO/dirty"
o4=$(payload "$TP3" stop2 "$REPO" Stop | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1)
t 'a dirty tree is never archivable' '' "$(printf '%s' "$o4" | jq -r '.decision // ""')"

# --- 4. the friction counter is the one line addressed to the model ----------
# The standing orders' capacity clause no longer carries its own trigger, so
# this line has to arrive as context, not as a systemMessage the model cannot
# see. Uses the committed contentious fixture rather than a hand-rolled one:
# the classifier that types a turn as a correction or a rebuke is what is
# being relied on here.
FIX="$(cd "$(dirname "$0")" && pwd)/fixtures/friction-contentious.jsonl"
if [ -f "$FIX" ]; then
  ctx=$(payload "$FIX" fric "$SCRATCH" \
        | METRICS_FRICTION_TURNS=200 bash "$HOOK" prompt 0 2>&1 \
        | jq -r '.hookSpecificOutput.additionalContext // ""')
  has 'the friction line reaches the model'  'corrections or rebukes' "$ctx"
  has 'and names the capacity rule'          'capacity rule'          "$ctx"
  ctx2=$(payload "$FIX" fric "$SCRATCH" \
         | METRICS_FRICTION_TURNS=200 bash "$HOOK" prompt 0 2>&1 \
         | jq -r '.hookSpecificOutput.additionalContext // ""')
  t 'and fires once, not every turn' '' "$ctx2"
else
  printf 'SKIP: %s is missing\n' "$FIX"
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
