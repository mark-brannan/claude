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
export METRICS_CONTEXT_LINES="100000 150000 200000"
export METRICS_CONTEXT_STEP=50000
STATE="$HOME/.claude/state/global"

# shellcheck source=lib-metrics-test-harness.sh
. "$(dirname "$HOOK")/lib-metrics-test-harness.sh"

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

# --- 1. two context lines, in order ------------------------------------------
TP="$SCRATCH/ctx.jsonl"; SID=ctx1
turn "$TP" 103000
out1=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
turn "$TP" 152000
out2=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
out3=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)

has  'first crossing names 100k'      '103k/100k' "$(msg "$out1")"
hasnt 'first crossing does not propose stopping' 'propose stopping' "$(msg "$out1")"
has  'second crossing names 150k'     '152k/150k' "$(msg "$out2")"
has  'second crossing proposes stopping' 'propose stopping' "$(msg "$out2")"
has  'first crossing shows one ⛁ glyph'  '⛁ 103k' "$(msg "$out1")"
has  'second crossing shows two ⛁ glyphs' '⛁⛁ 152k' "$(msg "$out2")"
t    'nothing fires a third time'     '' "$(msg "$out3")"

CROSS="$STATE/metrics/crossings/$SID.jsonl"
t 'both crossings are recorded, in order' \
  "$(printf '100000\n150000')" \
  "$(jq -r 'select(.kind == "context") | .at' "$CROSS" 2>/dev/null)"

# --- 2. a 40-minute gap starts a new sitting ---------------------------------
# The clock is wall-clock, so the way to put a session 61 minutes in is to
# write the state file the engine reads, which is what a resumed session's
# state actually looks like.
# The clock is machine-wide now, so putting a session 61 minutes in means
# writing the one shared file plus that session's own per-session state --
# the second only to keep the context line out of the way of the assertions.
SITF=$STATE/metrics/sitting.json
clock() {  # clock <minutes since sitting start> <minutes since last prompt>
  mkdir -p "$(dirname "$SITF")"
  jq -n --argjson ss "$(( $(date +%s) - $1 * 60 ))" \
        --argjson lp "$(( $(date +%s) - $2 * 60 ))" \
    '{sitting_start:$ss, last_prompt:$lp}' > "$SITF"
}
clock_clear() { rm -f "$SITF"; }
sitting() {  # sitting <session id> <minutes since sitting start> <minutes since last prompt>
  local n=$STATE/metrics/live/$1.nag.json
  mkdir -p "$(dirname "$n")"
  jq -n '{context_line:200000, time_line:0, time_line_sitting:0, gate_line:0,
          friction_tripped:false, since_nag:false,
          resume_ts:0, nag_pending:false}' > "$n"
  clock "$2" "$3"
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
# 0 when the file is not there at all: no clock is a clock at zero, and the
# assertions below are about a Stop never creating one.
sit_start() { jq -r '.sitting_start // 0' "$SITF" 2>/dev/null || true; \
              [ -f "$SITF" ] || printf 0; }

TPS="$SCRATCH/stopfirst.jsonl"; turn "$TPS" 1000
clock_clear
payload "$TPS" sfirst "$SCRATCH" Stop \
  | bash "$HOOK" stop 0 show >/dev/null 2>&1
t 'a Stop before any prompt does not start the clock' 0 "$(sit_start)"

payload "$TPS" sfirst "$SCRATCH" SubagentStop \
  | bash "$HOOK" subagentstop 0 show >/dev/null 2>&1
t 'nor does a SubagentStop' 0 "$(sit_start)"

out=$(payload "$TPS" sfirst "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
hasnt 'so the first prompt after them is minute zero' '⏱' "$(msg "$out")"
t 'and it is the prompt that starts the clock' yes \
  "$( [ "$(sit_start)" -gt 0 ] && echo yes || echo no )"

# An hour on the clock: a Stop must neither report it nor disturb it.
sitting quiet 61 10
before=$(sit_start)
out=$(payload "$TPS" quiet "$SCRATCH" Stop | bash "$HOOK" stop 0 show 2>&1)
hasnt 'a Stop past the line says nothing about sitting' '⏱ sitting' "$(msg "$out")"
t    'and leaves the clock exactly where it found it' "$before" "$(sit_start)"
out=$(payload "$TPS" quiet "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has  'the next prompt is what reports it' '⏱ sitting 1h00' "$(msg "$out")"

# --- 2c. one clock for the machine, one report per session -------------------
# Three chats open is still one person in one chair. sitting_start and
# last_prompt live in a single file under the state dir's metrics directory
# that any session's UserPromptSubmit advances; only time_line is per session,
# so each chat says a threshold once where its reader is looking.
TPM="$SCRATCH/multi.jsonl"; turn "$TPM" 1000
P() { payload "$TPM" "$1" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1; }
nag_field() { jq -r "$2" "$STATE/metrics/live/$1.nag.json" 2>/dev/null; }

clock_clear
P mA >/dev/null
started=$(sit_start)
t 'the first prompt anywhere starts the one clock' yes \
  "$( [ "${started:-0}" -gt 0 ] && echo yes || echo no )"
P mB >/dev/null
t 'a second session id does not start a second clock' "$started" "$(sit_start)"
t 'and no session keeps a clock of its own' '' \
  "$(cat "$STATE"/metrics/live/m[AB].nag.json | jq -r '.sitting_start // empty')"

# A prompt in either session is the same person still sitting: it advances the
# shared last_prompt, and both sessions read the same elapsed time back.
clock 61 10
outA=$(P mA)
has 'a prompt in one session reports the shared hour' '⏱ sitting 1h00' "$(msg "$outA")"
kept=$(sit_start)
outB=$(P mB)
has 'and the other session reports the same hour, not zero' '⏱ sitting 1h00' "$(msg "$outB")"
t   'neither prompt restarted the sitting' "$kept" "$(sit_start)"
t   'the second prompt advanced the shared last_prompt' yes \
  "$( [ "$(jq -r '.last_prompt' "$SITF")" -ge "$(( $(date +%s) - 5 ))" ] && echo yes || echo no )"

# The report is per session, so each says the hour once and only once.
t 'the line does not repeat in the session that said it' '' "$(msg "$(P mA)")"
t 'nor in the other one'                                 '' "$(msg "$(P mB)")"

# A session opened partway into someone else's sitting inherits the clock it
# walked in on. Wall-clock time cannot be advanced inside a test, so the ten
# minutes between mF's two prompts are expressed by rewriting the shared file
# -- which is exactly what the other session's prompts would have left there.
clock 50 5
outF1=$(P mF)
hasnt 'a session opened 50 minutes in says nothing at 50' '⏱' "$(msg "$outF1")"
t     'and does not restart the clock it walked in on' 0 "$(nag_field mF '.time_line')"
clock 61 5
outF2=$(P mF)
has 'and reports 1h00 at its next prompt' '⏱ sitting 1h00' "$(msg "$outF2")"
has 'with the stand-up verdict, not a wrap-up' 'stand up' "$(msg "$outF2")"

# A nag file written before the clock moved out of it carries a time_line
# with no sitting to belong to. Spend it rather than trust it: the sitting it
# was recorded in is one this machine has no record of.
clock 61 10
old=$STATE/metrics/live/mOld.nag.json
jq -n --argjson ss "$(( $(date +%s) - 900 ))" \
  '{context_line:200000, time_line:60, gate_line:0, friction_tripped:false,
    sitting_start:$ss, last_prompt:$ss, since_nag:false,
    resume_ts:0, nag_pending:false}' > "$old"
has 'a pre-move nag file does not suppress the new hour' '⏱ sitting 1h00' \
    "$(msg "$(P mOld)")"

# When the shared clock restarts, every session is free to speak again, not
# only the one whose prompt restarted it: a spent time_line belongs to the
# sitting it was recorded in, and that sitting is over. The per-session file
# carries that sitting's identity next to the line for exactly this.
clock 61 10
P mI >/dev/null
t 'the hour is spent in that session' '' "$(msg "$(P mI)")"
before_break=$(jq -r '.sitting_start' "$SITF")
clock 62 10   # a different sitting, an hour into itself
t 'which is a different sitting' no \
  "$( [ "$before_break" = "$(jq -r '.sitting_start' "$SITF")" ] && echo yes || echo no )"
has 'a restarted clock frees the other session to speak again' \
    '⏱ sitting 1h00' "$(msg "$(P mI)")"

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

# --- 3b. only "stop here" arms the Stop block --------------------------------
# "Stand up" asks for five minutes out of the chair and the same session back;
# it is not a wrap-up. Arming the block on it made every hour a demand for a
# resume block. Two hours is the sitting clock's actual verdict, and the only
# crossing on it that blocks. METRICS_STOP_HOUR=23 keeps the late-hour arm out
# of the way so what is under test is the crossing alone.
arm() {  # arm <session id> <minutes on the shared clock>
  clock "$2" 10
  payload "$TP3" "$1" "$REPO" | bash "$HOOK" prompt 0 >/dev/null 2>&1
  payload "$TP3" "$1" "$REPO" Stop | METRICS_STOP_HOUR=23 bash "$HOOK" stop 0 show 2>&1
}
o=$(arm arm1 61)
has 'the one-hour crossing is still reported' '⏱ sitting 1h00' \
    "$(msg "$(clock 61 10; payload "$TP3" armX "$REPO" | bash "$HOOK" prompt 0 2>&1)")"
t 'but it does not arm the Stop block' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
o=$(arm arm2 121)
t 'the two-hour crossing does' block "$(printf '%s' "$o" | jq -r '.decision // ""')"

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
has 'and the reason carries the crossing line' '⛁ 103k/100k' \
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

# --- 5. the ladder extends past the configured lines, forever ----------------
# dotfiles#132: NAG_CONTEXT_LINES stops at 200k by default, but a session that
# blows straight past it must keep getting a line every NAG_CONTEXT_STEP,
# not go quiet. A single jump to 320k crosses five rungs at once (100k, 150k,
# 200k, 250k, 300k) and the glyph count escalates with each: the fifth rung is
# capped at 5 ⛁ and switches to "(xN)".
TP5="$SCRATCH/ladder.jsonl"; SID5=ladder
turn "$TP5" 350000
out5=$(payload "$TP5" "$SID5" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'the ladder reaches past the last configured line' '350k/350k' "$(msg "$out5")"
has 'and the glyph count is capped, with the total after it' \
    '⛁⛁⛁⛁⛁\(x6\)' "$(msg "$out5")"
t 'six rungs cross in one jump, in order' \
  "$(printf '100000\n150000\n200000\n250000\n300000\n350000')" \
  "$(jq -r 'select(.kind == "context") | .at' "$STATE/metrics/crossings/$SID5.jsonl" 2>/dev/null)"

# --- 6. model injection only from the stop threshold up -----------------------
# Below NAG_CONTEXT_STOP_AT (150k default) the crossing is screen-only. At or
# above it, the first crossing offers a stopping point; every crossing after
# that says plainly it was already raised, instead of repeating the offer.
TP6="$SCRATCH/inject.jsonl"; SID6=inject
turn "$TP6" 103000
ctx6a=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'below the stop threshold, nothing reaches the model' '' "$ctx6a"

turn "$TP6" 152000
ctx6b=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
has 'the first crossing at/above the stop line offers to stop' \
    'a stopping point' "$ctx6b"

turn "$TP6" 260000
ctx6c=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
has  'a later crossing says it was already raised'  'Already raised at 150k' "$ctx6c"
hasnt 'and does not repeat the stopping-point offer' 'a stopping point'      "$ctx6c"

# A single call can cross more than one stop-eligible rung at once (a big
# tool result landing between prompts). That must still emit exactly one
# model line, not one per rung -- otherwise every rung but the first claims
# a distinct earlier occasion nobody acted on, when they all just fired now.
TP6b="$SCRATCH/inject2.jsonl"; SID6b=inject2
turn "$TP6b" 300000
ctx6d=$(payload "$TP6b" "$SID6b" "$SCRATCH" \
        | bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'one jump across three stop-eligible rungs still sends one line' \
  1 "$(printf '%s' "$ctx6d" | grep -c 'stopping point\|Already raised')"

# --- 7. the sitting line carries git state once #129 makes it safe to ---------
# dotfiles#132's third deferred item, reconciled now that #129 landed: a dirty
# or unpushed tree is exactly the fact the "stop here" verdict needs. A fresh
# repo, not $REPO -- that one already carries a leftover "dirty" file from the
# archivable tests above, and this is checking the exact count.
REPO7="$SCRATCH/repo7"; mkdir -p "$REPO7"
git -C "$REPO7" init -q -b feat/nags
git -C "$REPO7" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
TP7="$SCRATCH/sit7.jsonl"; turn "$TP7" 1000
: > "$REPO7/scratch-file"
o7=$(clock 61 10; payload "$TP7" sit7 "$REPO7" | bash "$HOOK" prompt 0 2>&1)
has 'the sitting line shows the dirty tree' '⎇ 1~' "$(msg "$o7")"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
