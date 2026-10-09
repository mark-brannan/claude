#!/usr/bin/env bash
# Tests for the crossing engine in metrics-live.sh.
# Run: bash hooks/metrics-live.test.sh
#
# What matters is that the nag is edge-triggered: a line fires once when its
# counter first crosses, and then not again until the next line. Three
# properties, one per case in issue #111's Verification section:
#
#   crossing    a transcript that grows past 100k then past 150k produces
#               exactly two context lines, in that order, and the second one
#               trips the 💸 reason
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
# Pin an interactive entrypoint: a grind worker runs this suite under claude -p,
# and its inherited sdk-cli would skip every blocking-Stop case.
export CLAUDE_CODE_ENTRYPOINT=cli

HOOK="$(cd "$(dirname "$0")" && pwd)/metrics-live.sh"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME" "$SCRATCH/bin"
export CLAUDE_STATE_REPO=""
export METRICS_CONTEXT_LINES="100000 150000 200000"
export METRICS_CONTEXT_STEP=50000
# Daylight, whatever the wall clock says: the suite runs at night too, and the
# bedtime question would otherwise land on the first prompt of every case.
# The night-side cases set their own hours per invocation.
export METRICS_STOP_HOUR=24 METRICS_NIGHT_END_HOUR=0
STATE="$HOME/.claude/state/global"

# shellcheck source=lib-metrics-test-harness.sh
. "$(dirname "$HOOK")/lib-metrics-test-harness.sh"

# The 📦 verdict is stop-continuity.py's, read back from the metrics record
# (stop-sequence.py runs that hook first). Plant what its set_verdict would
# have written; the git checks behind a verdict are stop-continuity.test.py's.
plant() {  # plant <sid> [verdict] [verdict_at]
  # Flat, as a record written before the shard split: the reader must find it.
  mkdir -p "$STATE/metrics/sessions"
  jq -nc --arg v "${2:-archivable}" --argjson at "${3:-$(date -u +%s)}" \
    '{verdict: $v, verdict_at: $at}' > "$STATE/metrics/sessions/$1.json"
}

t() {  # t <desc> <want> <got>
  if [ "$2" = "$3" ]; then pass=$((pass+1))
  else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi
}
has() {  # has <desc> <pattern> <text>
  if grep -Eq -- "$2" <<<"$3"; then pass=$((pass+1))
  else fail=$((fail+1)); printf 'FAIL (no /%s/): %s\n  in [%s]\n' "$2" "$1" "$3"; fi
}
hasnt() {
  if grep -Eq -- "$2" <<<"$3"; then
    fail=$((fail+1)); printf 'FAIL (has /%s/): %s\n  in [%s]\n' "$2" "$1" "$3"
  else pass=$((pass+1)); fi
}

# --- 1. context rungs are counted, never spoken ------------------------------
# Ruled on dotfiles#137, 2026-09-22: one notice per event, and that notice is
# the block. A context crossing moves the block's ⛁ cluster and prints no
# line of its own -- least of all one naming the rung, which reused the a/b
# shape the block spends on output_tokens/context_peak.
TP="$SCRATCH/ctx.jsonl"; SID=ctx1
turn "$TP" 103000
out1=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
turn "$TP" 152000
payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
out2=$(payload "$TP" "$SID" "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)

t     'a crossing on a prompt says nothing at all' '' "$(msg "$out1")"
has   'the block counts both rungs'          '^⛁⛁ ' "$(msg "$out2")"
hasnt 'and never names the rung it crossed'  '/(100|150)k' "$(msg "$out2")"

hasnt 'no threshold line rides in front of it' 'still room' "$(msg "$out2")"
has   'the stop rung still reaches the verdict' '— 💸$' "$(msg "$out2")"
hasnt 'and the tail carries no words'          'propose|stopping' "$(msg "$out2")"

# A tool hook inside a sub-agent carries agent_id but reads the PARENT's
# transcript: it must say nothing, and must not consume the parent's crossing.
TPA="$SCRATCH/agent.jsonl"; turn "$TPA" 152000
outa=$(payload "$TPA" agent1 "$SCRATCH" PostToolUse \
  | jq -c '. + {agent_id:"a1b2c3", agent_type:"Explore"}' \
  | bash "$HOOK" posttooluse 0 show 2>&1)
t     'a tool hook inside a sub-agent is silent' '' "$outa"
outp=$(payload "$TPA" agent1 "$SCRATCH" PostToolUse | bash "$HOOK" posttooluse 0 show 2>&1)
has   'and the parent still gets its block afterwards' '^⛁⛁ ' "$(msg "$outp")"

CROSS="$STATE/metrics/crossings/${SID:0:2}/$SID.jsonl"
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
  local n=$STATE/metrics/live/${1:0:2}/$1.nag.json
  mkdir -p "$(dirname "$n")"
  jq -n '{context_line:200000, time_line:0, time_line_sitting:0,
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
has 'a 10 min gap leaves the clock running' '⏱ 1h0[0-9]' "$(msg "$out")"
hasnt 'the hour line gives no instruction'  'stand up|stop here|/wrapup|offer' "$(msg "$out")"

out=$(payload "$TP2" nogap "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
t 'the 60 min line does not repeat' '' "$(msg "$out")"

sitting twohours 121 10
out=$(payload "$TP2" twohours "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has   'two hours names the elapsed time'  '⏱ 2h01' "$(msg "$out")"
hasnt 'and gives no instruction either'   'stop here|/wrapup' "$(msg "$out")"

# --- 2b. the clock belongs to the prompt -------------------------------------
# No verdict is planted for these sessions, so archivable() refuses and the
# Stop nag stays out of the way; what is under test here is only the clock.
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
has  'the next prompt is what reports it' '⏱ 1h0[0-9]' "$(msg "$out")"

# --- 2c. one clock for the machine, one report per session -------------------
# Three chats open is still one person in one chair. sitting_start and
# last_prompt live in a single file under the state dir's metrics directory
# that any session's UserPromptSubmit advances; only time_line is per session,
# so each chat says a threshold once where its reader is looking.
TPM="$SCRATCH/multi.jsonl"; turn "$TPM" 1000
P() { payload "$TPM" "$1" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1; }
nag_field() { jq -r "$2" "$STATE/metrics/live/${1:0:2}/$1.nag.json" 2>/dev/null; }

clock_clear
P mA >/dev/null
started=$(sit_start)
t 'the first prompt anywhere starts the one clock' yes \
  "$( [ "${started:-0}" -gt 0 ] && echo yes || echo no )"
P mB >/dev/null
t 'a second session id does not start a second clock' "$started" "$(sit_start)"
t 'and no session keeps a clock of its own' '' \
  "$(cat "$STATE"/metrics/live/m[AB]/m[AB].nag.json | jq -r '.sitting_start // empty')"

# A prompt in either session is the same person still sitting: it advances the
# shared last_prompt, and both sessions read the same elapsed time back.
clock 61 10
outA=$(P mA)
has 'a prompt in one session reports the shared hour' '⏱ 1h0[0-9]' "$(msg "$outA")"
kept=$(sit_start)
outB=$(P mB)
has 'and the other session reports the same hour, not zero' '⏱ 1h0[0-9]' "$(msg "$outB")"
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
has 'and reports 1h00 at its next prompt' '⏱ 1h0[0-9]' "$(msg "$outF2")"

# A nag file written before the clock moved out of it carries a time_line
# with no sitting to belong to. Spend it rather than trust it: the sitting it
# was recorded in is one this machine has no record of.
clock 61 10
old=$STATE/metrics/live/mO/mOld.nag.json
mkdir -p "${old%/*}"
jq -n --argjson ss "$(( $(date +%s) - 900 ))" \
  '{context_line:200000, time_line:60, friction_tripped:false,
    sitting_start:$ss, last_prompt:$ss, since_nag:false,
    resume_ts:0, nag_pending:false}' > "$old"
has 'a pre-move nag file does not suppress the new hour' '⏱ 1h0[0-9]' \
    "$(msg "$(P mOld)")"

# A live cache still at the flat path (written before the shard split) must
# not stop the nag file landing in its own shard.
mkdir -p "$STATE/metrics/live"; printf '{}\n' > "$STATE/metrics/live/flatLive.json"
P flatLive >/dev/null
t 'a flat live cache: the nag file is still written, in its shard' yes \
  "$([ -f "$STATE/metrics/live/fl/flatLive.nag.json" ] && echo yes || echo no)"

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
    '⏱ 1h0[0-9]' "$(msg "$(P mI)")"

# --- 3. Stop, archivable, past the line --------------------------------------
REPO="$SCRATCH/repo"; mkdir -p "$REPO"
git -C "$REPO" init -q -b feat/nags
git -C "$REPO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
# A real upstream, pushed and clean -- these tests are about the sitting
# clock and the Stop block, not about unpushed work. The verdict itself is
# planted per session (plant, above), as stop-continuity.py would write it.
git init -q --bare "$SCRATCH/repo.git"
git -C "$REPO" remote add origin "$SCRATCH/repo.git"
git -C "$REPO" push -q -u origin feat/nags
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
# crossing on it that blocks. METRICS_STOP_HOUR=24 is an hour the clock never
# reaches, which keeps the late-hour arm out
# of the way so what is under test is the crossing alone.
arm() {  # arm <session id> <minutes on the shared clock>
  clock "$2" 10
  payload "$TP3" "$1" "$REPO" | bash "$HOOK" prompt 0 >/dev/null 2>&1
  plant "$1"
  payload "$TP3" "$1" "$REPO" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1
}
o=$(arm arm1 61)
has 'the one-hour crossing is still reported' '⏱ 1h0[0-9]' \
    "$(msg "$(clock 61 10; payload "$TP3" armX "$REPO" | bash "$HOOK" prompt 0 2>&1)")"
t 'but it does not arm the Stop block' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
o=$(arm arm2 121)
t 'the two-hour crossing does' block "$(printf '%s' "$o" | jq -r '.decision // ""')"

S() { plant stop1; payload "$TP3" stop1 "$REPO" Stop \
      | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1; }

# A headless session (claude -p reports entrypoint sdk-cli) is never asked for
# a hand-off; the same Stop in an interactive entrypoint still is.
o=$(plant stop1h; payload "$TP3" stop1h "$REPO" Stop \
    | CLAUDE_CODE_ENTRYPOINT=sdk-cli METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1)
t 'a headless Stop is not asked for a hand-off' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"

o1=$(S)
t   'the first Stop blocks'  block "$(printf '%s' "$o1" | jq -r '.decision // ""')"
has 'saying what the body holds' \
    '^Write the hand-off: replace the body .* next step, then link:, model: and effort: lines' \
    "$(printf '%s' "$o1" | jq -r '.reason // ""')"
hasnt 'without leaning on a skill' '/wrapup' "$(printf '%s' "$o1" | jq -r '.reason // ""')"
hasnt 'and nothing about the session ending' 'last of the session' \
    "$(printf '%s' "$o1" | jq -r '.reason // ""')"

# A wrap-up that already wrote its hand-off is never blocked: the forced turn
# after the closing message is what made the model, not the user, speak last
# (dotfiles#391). The arm is spent and the hand-off on disk is reported.
CK="$STATE/log/auto"; mkdir -p "$CK"
PK="$STATE/pickup"; mkdir -p "$PK"
handoff() {  # handoff <sid> -- a pickup item whose body was edited past the default
  printf 'status: open\nupdated: x\nsession: %s\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: p\n---\nnext: x\nlink: https://github.com/o/r/pull/7\nmodel: sonnet\neffort: medium\n' \
    "$1" > "$PK/2026-09-09T10-00-$1.md"
}
# An unedited item (body still the prompt line) is no hand-off, so the Stop
# blocks. The notice names each item by file and state; the reason gives the
# model the full path. Neither restates what the body should hold.
printf 'status: open\nupdated: x\nsession: stopn\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: p\n---\np\n' \
  > "$PK/2026-09-09T09-00-stopn.md"
o=$(plant stopn; payload "$TP3" stopn "$REPO" Stop | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1)
t   'an unedited pickup item still blocks' block "$(printf '%s' "$o" | jq -r '.decision // ""')"
has 'the notice names the item, without its directory, as unwritten' \
    '^📄 2026-09-09T09-00-stopn\.md \(p\)$' "$(msg "$o")"
has 'the notice still carries the metrics block' '^» ' "$(msg "$o")"
has 'the reason gives the model the full path' \
    'Item: `/.*/pickup/2026-09-09T09-00-stopn\.md`\. Then answer in one line' \
    "$(printf '%s' "$o" | jq -r '.reason // ""')"
hasnt 'and no item lines in the reason' '📄' "$(printf '%s' "$o" | jq -r '.reason // ""')"
has "and keeps the last word the user's" 'no summary, no question, nothing new\.$' \
    "$(printf '%s' "$o" | jq -r '.reason // ""')"
printf 'status: open\nprompt: p\n---\nnext: x\n' > "$PK/2026-09-09T11-00-stopm.md"
printf 'status: open\nprompt: p\n---\np\n' > "$PK/2026-09-09T12-00-stopm.md"
o=$(plant stopm; payload "$TP3" stopm "$REPO" Stop | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1)
t 'two items for one session are each listed with their state' \
  '📄 2026-09-09T11-00-stopm.md (saved HH:MM: ? · ? · ?)|📄 2026-09-09T12-00-stopm.md (p)' \
  "$(msg "$o" | grep '^📄' | sed -E 's/saved [0-9]{2}:[0-9]{2}/saved HH:MM/' | paste -sd'|')"
has 'an item-less Stop says there is none' '^📄 no pickup item for stop1$' "$(msg "$o1")"
has 'and tells the model where a new one goes' 'none exists yet in /.*/pickup/\.' \
    "$(printf '%s' "$o1" | jq -r '.reason // ""')"

handoff stop0
S0() { plant stop0; payload "$TP3" stop0 "$REPO" Stop \
       | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1; }
o=$(S0); o1s=$o
t     'an armed Stop with the block on disk does not block' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
has   'and lists the item with its saved time, link, model and effort' \
      '^📄 2026-09-09T10-00-stop0\.md \(saved [0-9]{2}:[0-9]{2}: o/r/pull/7 · sonnet · medium\)$' "$(msg "$o")"
hasnt 'and no longer says the hand-off was found' 'Hand-off already written|Next time' "$(msg "$o")"
o=$(S0)
t     'the next Stop does not block either' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
hasnt 'and carries no age line' 'Hand-off .* old' "$(msg "$o")"
t     'and the saved time does not move between Stops' \
      "$(msg "$o1s" | grep -o 'saved [0-9:]*')" "$(msg "$o" | grep -o 'saved [0-9:]*')"
# The saved time follows the body: back-date the stamp, an unchanged body keeps
# it, an edited body restamps it.
NF0="$STATE/metrics/live/st/stop0.nag.json"
jq '.resume_ts = 1000000000' "$NF0" > "$NF0.x" && mv "$NF0.x" "$NF0"
o=$(S0)
t     'an unchanged body keeps its saved time' 'yes' \
      "$([ "$(nag_field stop0 .resume_ts)" = 1000000000 ] && echo yes || echo no)"
printf 'later: edited\n' >> "$PK/2026-09-09T10-00-stop0.md"
o=$(S0)
t     'an edited body restamps its saved time' 'yes' \
      "$([ "$(nag_field stop0 .resume_ts)" -gt 1000000000 ] && echo yes || echo no)"

# The model answers the block by editing its pickup item's body. The hook
# must find it on disk, not assume it from having asked.
handoff stop1
o2=$(S)
t   'the second Stop does not block' '' "$(printf '%s' "$o2" | jq -r '.decision // ""')"
has 'and lists the item as saved' \
    '^📄 2026-09-09T10-00-stop1\.md \(saved [0-9]{2}:[0-9]{2}: ' "$(msg "$o2")"

o3=$(S)
t     'a later Stop does not block'  '' "$(printf '%s' "$o3" | jq -r '.decision // ""')"
hasnt 'and carries no age line'      'Hand-off .* old|Next time' "$(msg "$o3")"

# The block was ignored: no edited body anywhere. Say so, do not claim one,
# and do not block again -- the late-hour arm is spent for the session.
S3() { plant stop3; payload "$TP3" stop3 "$REPO" Stop \
       | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1; }
o=$(S3); t 'blocks once' block "$(printf '%s' "$o" | jq -r '.decision // ""')"
o=$(S3)
t     'an unanswered block does not re-block' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"
has   'and the item line says there is none' '^📄 no pickup item for stop3$' "$(msg "$o")"
hasnt 'never claims it was saved'        'saved ' "$(msg "$o")"
o=$(S3); t 'and stays quiet after' '' "$(printf '%s' "$o" | jq -r '.decision // ""')"

# A context crossing still arms the Stop. It no longer speaks on the way: the
# reason carries the resume instruction, and the metrics land in the block on
# the next Stop, which is the one that passes.
TP4="$SCRATCH/cross.jsonl"; turn "$TP4" 103000
plant stop4
o=$(payload "$TP4" stop4 "$REPO" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)
t   'a context crossing at Stop blocks' block "$(printf '%s' "$o" | jq -r '.decision // ""')"
hasnt 'and the reason carries no threshold line' '⛁' \
    "$(printf '%s' "$o" | jq -r '.reason // ""')"

# A dirty tree is not archivable, so nothing blocks however late it is.
: > "$REPO/dirty"
plant stop2 'not archivable: worktree dirty'
o4=$(payload "$TP3" stop2 "$REPO" Stop | METRICS_STOP_HOUR=0 bash "$HOOK" stop 0 show 2>&1)
t 'a dirty tree is never archivable' '' "$(printf '%s' "$o4" | jq -r '.decision // ""')"

# --- 3c. order: the block first, the archival verdict after it ---------------
# dotfiles#149 step 4's whole point, minus the context line #137 removed. The
# nag bucket still prints ahead of the block -- the sitting and gate lines
# feed it -- but no producer of it co-occurs with a Stop, so what is left to
# pin here is the block against the archival tail. Own repo so this does not
# depend on section 3's ordering or its dirty-tree flip above.
REPOO="$SCRATCH/repoo"; mkdir -p "$REPOO"
git -C "$REPOO" init -q -b feat/order
git -C "$REPOO" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git init -q --bare "$SCRATCH/repoo.git"
git -C "$REPOO" remote add origin "$SCRATCH/repoo.git"
git -C "$REPOO" push -q -u origin feat/order

TPO="$SCRATCH/order.jsonl"; turn "$TPO" 103000
plant orderx
oO1=$(payload "$TPO" orderx "$REPOO" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)
t 'order setup: the first Stop blocks' block "$(printf '%s' "$oO1" | jq -r '.decision // ""')"

handoff orderx

# Second Stop: also crosses 150k while confirming the hand-off, so a
# nag, the block, and the archival tail all fire together -- no re-block.
turn "$TPO" 152000
plant orderx
oO2=$(payload "$TPO" orderx "$REPOO" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)
t 'order: the confirming Stop does not re-block' '' "$(printf '%s' "$oO2" | jq -r '.decision // ""')"
msgO2=$(msg "$oO2")
status_at=$(printf '%s\n' "$msgO2" | grep -n '— ' | head -1 | cut -d: -f1)
block_at=$(printf '%s\n' "$msgO2" | grep -n '⇢ ' | head -1 | cut -d: -f1)
arch_at=$(printf '%s\n' "$msgO2" | grep -n '📦' | head -1 | cut -d: -f1)
t 'both sections are present' yes \
  "$( [ -n "$status_at" ] && [ -n "$block_at" ] && [ -n "$arch_at" ] && echo yes || echo no )"
t 'the block opens the message, no line in front of it' 1 "${status_at:-0}"
t 'the archival verdict renders after the block' yes \
  "$( [ "${block_at:-0}" -lt "${arch_at:-0}" ] 2>/dev/null && echo yes || echo no )"
has 'and reports the hand-off it found' '^📄 .*\(saved ' "$msgO2"

# --- 4. the friction counter is the one line addressed to the model ----------
# The standing orders' capacity clause no longer carries its own trigger, so
# this line has to arrive as context, not as a systemMessage the model cannot
# see. Uses the committed contentious fixture rather than a hand-rolled one:
# the classifier that types a turn as a correction or a rebuke is what is
# being relied on here.
FIX="$(cd "$(dirname "$0")" && pwd)/fixtures/friction-contentious.jsonl"
if [ -f "$FIX" ]; then
  ctx=$(payload "$FIX" fric "$SCRATCH" \
        | METRICS_FRICTION_TURNS=200 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 \
        | jq -r '.hookSpecificOutput.additionalContext // ""')
  has 'the friction line reaches the model'  'corrections or rebukes' "$ctx"
  has 'and names the capacity rule'          'capacity rule'          "$ctx"
  ctx2=$(payload "$FIX" fric "$SCRATCH" \
         | METRICS_FRICTION_TURNS=200 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 \
         | jq -r '.hookSpecificOutput.additionalContext // ""')
  t 'and fires once, not every turn' '0' \
    "$(printf '%s' "$ctx2" | grep -c 'corrections or rebukes' | tr -d ' ')"

  scr=$(msg "$(payload "$FIX" fric2 "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)")
  has 'friction past its nag threshold trips the reason cluster' \
    '— [^ ]*⚡' "$scr"

else
  printf 'SKIP: %s is missing\n' "$FIX"
fi

# --- 4b. friction with work in flight ----------------------------------------
# dotfiles#194: the friction counter answers a sitting clock's "land it, not
# stop and talk" logic the same way #192 gated the sitting clock -- mirrors
# section 6b2's in-flight setup (a dirty scratch git repo as cwd) rather than
# a hand-rolled fixture, since in_flight() is what is being relied on here.
if [ -f "$FIX" ]; then
  FWT="$SCRATCH/fricflight"; mkdir -p "$FWT"
  git -C "$FWT" init -q 2>/dev/null
  git -C "$FWT" checkout -q -b feature 2>/dev/null || true
  : > "$FWT/dirty.txt"

  fctx1=$(payload "$FIX" fricflight "$FWT" \
          | METRICS_FRICTION_TURNS=200 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 \
          | jq -r '.hookSpecificOutput.additionalContext // ""')
  has 'with work in flight the friction line says land it, not apply the rule' \
      'with work in flight.*Do not raise capacity or offer a stopping point yet' "$fctx1"
  hasnt 'and does not carry the ordinary capacity-rule wording yet' \
      'Apply the capacity rule from the standing orders, once' "$fctx1"

  fctx2=$(payload "$FIX" fricflight "$FWT" \
          | METRICS_FRICTION_TURNS=200 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 \
          | jq -r '.hookSpecificOutput.additionalContext // ""')
  has 'and a second call still says it -- unspent, not fired-once' \
      'with work in flight' "$fctx2"

  # ...and once the work lands, the unspent capacity-rule line fires --
  # same "leaves the rung unspent" shape as the sitting clock's #192 gate.
  git -C "$FWT" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
  rm -f "$FWT/dirty.txt"
  fctx3=$(payload "$FIX" fricflight "$FWT" \
          | METRICS_FRICTION_TURNS=200 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 \
          | jq -r '.hookSpecificOutput.additionalContext // ""')
  has 'and once the work lands the ordinary capacity-rule line fires' \
      'Apply the capacity rule from the standing orders, once' "$fctx3"
  hasnt 'with the in-flight wording gone' 'with work in flight' "$fctx3"
else
  printf 'SKIP: %s is missing\n' "$FIX"
fi

# --- 5. the ladder extends past the configured lines, forever ----------------
# dotfiles#132: NAG_CONTEXT_LINES stops at 200k by default, but a session that
# blows straight past it must keep counting every NAG_CONTEXT_STEP, not go
# quiet. A single jump to 350k crosses six rungs at once (100k through 350k)
# and the glyph count escalates with each: past the fifth it caps at 5 ⛁
# and switches to "(xN)".
TP5="$SCRATCH/ladder.jsonl"; SID5=ladder
turn "$TP5" 350000
payload "$TP5" "$SID5" "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
out5=$(payload "$TP5" "$SID5" "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)
has 'the ladder reaches past the last configured line' '/350k' "$(msg "$out5")"
has 'and the glyph count is capped, with the total after it' \
    '⛁⛁⛁⛁⛁\(x6\)' "$(msg "$out5")"
t 'six rungs cross in one jump, in order' \
  "$(printf '100000\n150000\n200000\n250000\n300000\n350000')" \
  "$(jq -r 'select(.kind == "context") | .at' "$STATE/metrics/crossings/${SID5:0:2}/$SID5.jsonl" 2>/dev/null)"

# --- 6. model injection rides its own context ladder -------------------------
# Below the first rung, nothing reaches the model. At or above it, the prompt
# that crosses a rung offers a stopping point, a later rung says it was
# already raised, and the prompts in between say nothing at all
# (dotfiles#282: the injection is edge-triggered, like the screen line).
TP6="$SCRATCH/inject.jsonl"; SID6=inject
turn "$TP6" 103000
ctx6a=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'below the first model rung, nothing reaches the model' '' "$ctx6a"

turn "$TP6" 152000
ctx6b=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
has 'the first crossing at/above the stop line offers to stop' \
    'a stopping point' "$ctx6b"

turn "$TP6" 260000
ctx6c=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
has  'a later crossing names the rung last offered'  'last offered at 125k' "$ctx6c"
hasnt 'and does not repeat the stopping-point offer' 'a stopping point'      "$ctx6c"

# dotfiles#282: a prompt that crosses no new rung carries no context line.
turn "$TP6" 261000
ctx6c2=$(payload "$TP6" "$SID6" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'and the next prompt over the same rung says nothing' '' "$ctx6c2"

# A single call can cross more than one stop-eligible rung at once (a big
# tool result landing between prompts). That must still emit exactly one
# model line, not one per rung -- otherwise every rung but the first claims
# a distinct earlier occasion nobody acted on, when they all just fired now.
TP6b="$SCRATCH/inject2.jsonl"; SID6b=inject2
turn "$TP6b" 300000
ctx6d=$(payload "$TP6b" "$SID6b" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'one jump across three stop-eligible rungs still sends one line' \
  1 "$(printf '%s' "$ctx6d" | grep -c 'stopping point\|last offered')"

# --- 6b. model injection: sitting clock, mirrors section 6 --------------------
# Same shape as the context ladder, on the sitting clock; a restart of the
# clock clears the injection with it.
SID6e=sitmodel
sitting "$SID6e" 40 10
out6e=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
t 'below the first sitting rung, nothing reaches the model' '' "$(ctx "$out6e")"

clock 61 10
out6f=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'the first sitting crossing is the time, the pickup and a pointer' \
    '^Sitting 1h01 at this machine, past 1h00\. Write the single next step .*pickup item.*without showing it\. Standing orders: "At a sitting rung"\.$' "$(ctx "$out6f")"
has 'and names the pickup item by this session'"'"'s short id' \
    "pickup/\*-${SID6e:0:8}\.md" "$(ctx "$out6f")"
# The pointer is only as good as its target: an edit to the orders that
# drops the bold lead fails here, not silently in a session.
anchor=$(ctx "$out6f" | sed -n 's/.*Standing orders: "\([^"]*\)".*/\1/p')
ORDERS="$(dirname "$HOOK")/../CLAUDE.md"
t 'and the standing orders still carry that bold lead' 1 \
  "$(grep -cF "**$anchor" "$ORDERS")"
hasnt 'and never offers a break or asks' 'offer a break|Offer one|\?' "$(ctx "$out6f")"

clock 121 10
out6g=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'a later sitting crossing shapes the stop again at the new rung' \
    'Sitting 2h01 at this machine, past 2h00\. Write the single next step' "$(ctx "$out6g")"
hasnt 'with no "last offered" repeat line' 'last offered' "$(ctx "$out6g")"

# dotfiles#282: still past 2h, no new rung -- silence, not a re-nag.
clock 125 10
out6g2=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
t 'and the next prompt inside the same rung says nothing' '' "$(ctx "$out6g2")"

clock 5 2
out6h=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
t 'a sitting-clock restart resets the model side too' '' "$(ctx "$out6h")"

clock 61 10
out6i=$(payload "$TP2" "$SID6e" "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
has 'so the next real crossing shapes a stop again' \
    'past 1h00\. Write the single' "$(ctx "$out6i")"
clock_clear

# --- 6b2. sitting clock with work in flight ----------------------------------
# The human nags answer a sitting clock with "land it", not "stop and talk":
# interrupting mid-work is what makes stepping away feel unsafe. The rung must
# NOT be spent, so the real break offer still arrives once the work lands.
WT="$SCRATCH/inflight"; mkdir -p "$WT"
git -C "$WT" init -q 2>/dev/null
git -C "$WT" checkout -q -b feature 2>/dev/null || true
: > "$WT/dirty.txt"

SID6j=sitflight
sitting "$SID6j" 61 10
out6j=$(payload "$TP2" "$SID6j" "$WT" | bash "$HOOK" prompt 0 2>&1)
has 'with work in flight the rung is held until it lands' \
    'with work in flight .*land this first, without asking.*comes back once it lands\. Standing orders' "$(ctx "$out6j")"
hasnt 'and does not point at the stop yet' 'past 1h00\. Write the single' "$(ctx "$out6j")"

clock 121 10
out6k=$(payload "$TP2" "$SID6j" "$WT" | bash "$HOOK" prompt 0 2>&1)
has   'two hours in flight still holds the rung' \
      'comes back once it lands' "$(ctx "$out6k")"
hasnt 'and still does not point at the stop' \
      'past 2h00\. Write the single' "$(ctx "$out6k")"

# dotfiles#282: unspent is not the same as unlimited -- the in-flight line
# still fires once per rung, not on every prompt.
clock 125 10
out6k2=$(payload "$TP2" "$SID6j" "$WT" | bash "$HOOK" prompt 0 2>&1)
t 'the in-flight line does not repeat inside its rung' '' "$(ctx "$out6k2")"

# ...and the unspent offer still arrives on the prompt after the work lands,
# at the rung that was already spoken in flight.
git -C "$WT" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
rm -f "$WT/dirty.txt"
out6k3=$(payload "$TP2" "$SID6j" "$WT" | bash "$HOOK" prompt 0 2>&1)
has 'and once the work lands the unspent shaping fires' \
    'past 2h00\. Write the single' "$(ctx "$out6k3")"
clock_clear

# --- 6b3. the sitting line's tail: clock first, list second ------------------
# Every knob below forces one branch: a meal window spanning the whole day,
# none at all, and the sunset hour gate at 0 (always) or 24 (never).
LOC="$STATE/location.json"; OUTS="$STATE/outside.txt"
TPt="$SCRATCH/tail.jsonl"; turn "$TPt" 1000
tail_line() {  # tail_line <session id> [env...]
  local id=$1; shift
  sitting "$id" 61 10
  msg "$(payload "$TPt" "$id" "$SCRATCH" | env "$@" bash "$HOOK" prompt 0 2>&1)"
}
# Longitude whose local mean solar time is $1 hours right now, on the equator,
# where the day is ~12h07 long all year.
solar_lon() {
  awk -v want="$1" -v now="$(date +%s)" 'BEGIN {
    utc = (now % 86400) / 3600; l = (want - utc) * 15
    while (l >= 180) l -= 360; while (l < -180) l += 360; printf "%.3f", l }'
}
NOMEAL=(METRICS_MEAL_WINDOWS= METRICS_SUN_AFTER_HOUR=0)

has 'a meal window asks what was eaten' '^⏱ 1h01 · context [0-9]+k · what did you eat today\?$' \
    "$(tail_line tail1 METRICS_MEAL_WINDOWS=0-24)"

printf '{"lat": 0, "lon": %s}\n' "$(solar_lon 10)" > "$LOC"
has 'daylight left names the sunset in hours' '^⏱ 1h01 · context [0-9]+k · sun sets in [0-9]+h [0-9]{2}$' \
    "$(tail_line tail2 "${NOMEAL[@]}")"
printf '{"lat": 0, "lon": %s}\n' "$(solar_lon 17.4)" > "$LOC"
has 'under an hour of daylight names it in minutes' '^⏱ 1h01 · context [0-9]+k · sun sets in [0-9]+ min$' \
    "$(tail_line tail3 "${NOMEAL[@]}")"
has 'the meal window outranks the sunset' 'what did you eat today' \
    "$(tail_line tail4 METRICS_MEAL_WINDOWS=0-24 METRICS_SUN_AFTER_HOUR=0)"
has 'before the sunset hour the sun is not mentioned' '^⏱ 1h01 · context [0-9]+k$' \
    "$(tail_line tail5 METRICS_MEAL_WINDOWS= METRICS_SUN_AFTER_HOUR=24)"

printf 'look at the plum tree\n\n' > "$OUTS"
printf '{"lat": 0, "lon": %s}\n' "$(solar_lon 22)" > "$LOC"
has 'after sunset the line comes from outside.txt' '^⏱ 1h01 · context [0-9]+k · look at the plum tree$' \
    "$(tail_line tail6 "${NOMEAL[@]}")"
printf '{"lat": null, "lon": null}\n' > "$LOC"
has 'a placeholder location skips the sunset' '^⏱ 1h01 · context [0-9]+k · look at the plum tree$' \
    "$(tail_line tail7 "${NOMEAL[@]}")"
rm -f "$OUTS" "$LOC"
has 'with no list and no clock tail the line is the time and context alone' '^⏱ 1h01 · context [0-9]+k$' \
    "$(tail_line tail8 "${NOMEAL[@]}")"
clock_clear

# --- 6b4. the stay valve ------------------------------------------------------
TPs="$SCRATCH/stay.jsonl"; turn "$TPs" 1000
SPROMPT() { payload "$TPs" "$1" "$SCRATCH" UserPromptSubmit "$2" | bash "$HOOK" prompt 0 2>&1; }
sitting stay1 89 2
o=$(SPROMPT stay1 "stay 40")
has 'stay <n> answers on screen with the quiet window' \
    '^⏱ 1h29 · staying 40, quiet until 2h09$' "$(msg "$o")"
t   'and asks the model for a one-line acknowledgement' \
    'The user said stay: acknowledge in one line, nothing else.' "$(ctx "$o")"
t   'quiet_until lands in the machine-wide clock file' yes \
    "$( q=$(jq -r '.quiet_until' "$SITF"); d=$(( q - $(date +%s) - 2400 )); [ "${d#-}" -le 5 ] && echo yes || echo no )"
t   'and the use is logged as a stay crossing' 40 \
    "$(jq -r 'select(.kind == "stay") | .at' "$STATE/metrics/crossings/st/stay1.jsonl" 2>/dev/null)"

# Two hours passes inside the quiet window: nothing on screen, nothing to the model.
q=$(jq -r '.quiet_until' "$SITF")
jq --argjson ss "$(( $(date +%s) - 121 * 60 ))" '.sitting_start = $ss' "$SITF" > "$SITF.t" && mv "$SITF.t" "$SITF"
o=$(SPROMPT stay1 "go on")
hasnt 'a rung crossed while quiet prints no sitting line' '⏱' "$(msg "$o")"
t     'and sends no sitting injection' '' "$(ctx "$o")"
# ...and once the quiet ends, the unspent rung is said on the next prompt.
jq '.quiet_until = 1' "$SITF" > "$SITF.t" && mv "$SITF.t" "$SITF"
o=$(SPROMPT stay1 "go on")
has 'after the quiet the rung it covered is said' '^⏱ 2h01' "$(msg "$o")"
has 'and the stop is shaped then' 'past 2h00\. Write the single' "$(ctx "$o")"

sitting stay2 10 2
o=$(SPROMPT stay2 "stay")
has 'bare stay quiets for the default 30' 'staying 30, quiet until 40m$' "$(msg "$o")"
sitting stay3 61 2
o=$(SPROMPT stay3 "stay a while longer")
hasnt 'anything but stay [minutes] is an ordinary prompt' 'staying' "$(msg "$o")"
has   'and the rung fires as usual' '^⏱ 1h01' "$(msg "$o")"
clock_clear

# --- 6b5. bedtime --------------------------------------------------------------
# One question per evening, machine-wide, on the first prompt after the night
# hour; a bare clock time is the reply; a warning NAG_BED_WARN_MIN before it,
# the hour itself once, then silence. Night is forced with METRICS_STOP_HOUR=0
# and the clock read in UTC through location.json's tz.
# The clock is pinned (METRICS_NOW) so the case cannot move under the minute
# and hour boundaries it rounds to: the bedtime arms compare minute-rounded
# times and an hour-rounded bare hour against "now". 2026-10-01 20:58:09Z is
# the instant this case was last red in CI, two minutes short of the hour.
# BED_PIN overrides the pin, to probe another instant.
PIN=${BED_PIN:-1790888289}
TPb="$SCRATCH/bed.jsonl"; turn "$TPb" 1000
LOC="$STATE/location.json"; printf '{"tz": "UTC"}\n' > "$LOC"
NIGHT=(METRICS_STOP_HOUR=0 METRICS_NIGHT_END_HOUR=0 METRICS_NOW="$PIN")
BP() { payload "$TPb" "$1" "$SCRATCH" UserPromptSubmit "$2" | env "${NIGHT[@]}" bash "$HOOK" prompt 0 2>&1; }
BT() { payload "$TPb" "$1" "$SCRATCH" PostToolUse | env "${NIGHT[@]}" bash "$HOOK" posttooluse 0 show 2>&1; }
BD() { payload "$TPb" "$1" "$SCRATCH" UserPromptSubmit "$2" | env METRICS_NOW="$PIN" bash "$HOOK" prompt 0 2>&1; }
bedf() { jq -r "$1" "$SITF" 2>/dev/null; }
set_bed() { jq --argjson b "$1" '.bed_at = $b' "$SITF" > "$SITF.t" && mv "$SITF.t" "$SITF"; }
kinds() { jq -r '.kind' "$STATE/metrics/crossings/${1:0:2}/$1.jsonl" 2>/dev/null | grep '^bed_' | tr '\n' ' '; }
clock_clear
o=$(BD bed1 "go on")
t 'by day nothing is asked' '' "$(msg "$o")"
o=$(BP bed1 "go on")
t 'the first prompt after the night hour asks' 'what time would you like to go to bed?' "$(msg "$o")"
t 'and nothing goes to the model for it' '' "$(ctx "$o")"
t 'the ask is stamped on the evening, machine-wide' "$(TZ=UTC date -d "@$PIN" +%Y-%m-%d)" "$(bedf .bed_asked_eve)"
o=$(BP bed1 "go on")
t 'the next prompt does not ask again' '' "$(msg "$o")"
o=$(BP bed2 "go on")
t 'nor does another session the same evening' '' "$(msg "$o")"
o=$(BP bed1 "11 is bedtime")
t 'a sentence with a number in it is an ordinary prompt' '' "$(msg "$o")"
o=$(BP bed1 "25")
t 'an hour past 23 is not a time' '' "$(msg "$o")"
nowb=$PIN; want=$(TZ=UTC date -d "@$((nowb + 420))" +%H:%M)
o=$(BP bed1 "$want")
t 'a bare HH:MM is the reply' "bed at $want noted" "$(msg "$o")"
t 'and the model is told to acknowledge in one line' \
  "The user named a bedtime, $want: acknowledge in one line, nothing else." "$(ctx "$o")"
d=$(( $(bedf .bed_at) - nowb - 420 ))
t 'bed_at lands in the machine-wide clock file' yes "$([ "${d#-}" -le 60 ] && echo yes || echo no)"
hb=$(( ($(TZ=UTC date -d "@$PIN" +%H | sed 's/^0*//;s/^$/0/') + 1) % 24 ))
# In an hour's last minutes the next hour is inside the warning window, and a
# warning landing here would add a crossing the count below doesn't expect.
o=$(METRICS_BED_WARN_MIN=0 BP bed1 "$hb")
has 'a bare hour is the next time the clock reads it' '^bed at [0-9][0-9]:00 noted$' "$(msg "$o")"
d=$(( $(bedf .bed_at) - $PIN ))
t 'and that is within the hour' yes "$([ "$d" -gt 0 ] && [ "$d" -le 3600 ] && echo yes || echo no)"

set_bed $(( $PIN + 240 ))
o=$(BP bed1 "go on")
has 'inside the warning window the minutes left are on screen' '^4 min to [0-9][0-9]:[0-9][0-9]$' "$(msg "$o")"
has 'and the model gets the sitting rung'"'"'s shaping instruction' \
    'Bedtime [0-9:]+ is 4 minutes away\. Write the single next step.*Standing orders' "$(ctx "$o")"
hasnt 'which never asks' '\?' "$(ctx "$o")"
o=$(BP bed1 "go on")
t 'the warning is said once' '' "$(msg "$o")$(ctx "$o")"
o=$(BT bed2)
has 'another open session says it once too, on a tool call' '^4 min to ' "$(msg "$o")"

set_bed $(( $PIN - 60 ))
o=$(BP bed1 "go on")
has 'past the hour: the time now, and the time named' "^ok, it's [0-9:]+, you said [0-9:]+$" "$(msg "$o")"
has 'the model says it once and shapes the stop' \
    "^It's [0-9:]+; the user said bed at [0-9:]+\. Say that once\. Write the single next step.*Standing orders" "$(ctx "$o")"
o=$(BP bed1 "go on")
t 'then silence' '' "$(msg "$o")$(ctx "$o")"
o=$(BT bed1)
t 'on tool calls too' '' "$(ctx "$o")"
t 'every step is a crossing the measurement can read' 'bed_ask bed_set bed_set bed_warn bed_past ' "$(kinds bed1)"

want2=$(TZ=UTC date -d "@$(( $PIN + 600 ))" +%H:%M)
o=$(BP bed1 "$want2")
t 'a new time can be named after the hour' "bed at $want2 noted" "$(msg "$o")"
set_bed $(( $PIN + 170 ))
o=$(BP bed1 "go on")
has 'and it re-arms the warning' '^3 min to ' "$(msg "$o")"

set_bed $(( $PIN - 60 ))
o=$(BD bed3 "go on")
t 'a bedtime left from last night is not read out by day' '' "$(msg "$o")$(ctx "$o")"

rm -f "$LOC"; clock_clear
BP bed4 "go on" >/dev/null
wantp=$(TZ=America/Los_Angeles date -d "@$(( $PIN + 420 ))" +%H:%M)
o=$(BP bed4 "$wantp")
t 'without a tz in location.json the clock is Pacific' "bed at $wantp noted" "$(msg "$o")"
clock_clear

# A METRICS_NOW that is not a plain integer is ignored: the hook stays on the
# real clock and the value is never evaluated.
rm -f "$SCRATCH/pwned"
payload "$TPb" bedx "$SCRATCH" UserPromptSubmit "go on" \
  | env METRICS_NOW="a[\$(touch $SCRATCH/pwned)]" METRICS_STOP_HOUR=24 bash "$HOOK" prompt 0 >/dev/null 2>&1
t 'a non-integer METRICS_NOW runs nothing' no "$([ -e "$SCRATCH/pwned" ] && echo yes || echo no)"
t 'and the hook still records its session on the real clock' yes \
  "$([ "$(jq -r '.updated_at[0:4]' "$STATE/metrics/live/be/bedx.json" 2>/dev/null)" = "$(date -u +%Y)" ] && echo yes || echo no)"

# --- 6c. model injection: decision load, mirrors section 6 --------------------
# askturn() is turn() with an assistant "ask" message, the shape
# session-metrics.jq counts as a decision pushed to the user.
askturn() {  # like turn(), but the assistant text is an ask
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" \
    '{type:"assistant", timestamp:$ts, requestId:("q-" + (now|tostring)),
      message:{model:"claude-opus-5", role:"assistant",
               content:[{type:"text", text:"Which way should this go?"}],
               usage:{input_tokens:40000, output_tokens:10,
                      cache_read_input_tokens:0, cache_creation_input_tokens:0}}}' >> "$1"
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" \
    '{type:"queue-operation", operation:"enqueue", timestamp:$ts,
      sessionId:"t", content:"the first one"}' >> "$1"
}
TP6c="$SCRATCH/decmodel.jsonl"; SID6c=decmodel
turn "$TP6c" 40000
ctx6j=$(payload "$TP6c" "$SID6c" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
t 'below the first decision rung, nothing reaches the model' '' "$ctx6j"

# One-entry-point §5 (2026-09-30): the decision count never nudges the model.
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22; do askturn "$TP6c"; done
ctx6k=$(payload "$TP6c" "$SID6c" "$SCRATCH" \
        | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 2>&1 | jq -r '.hookSpecificOutput.additionalContext // ""')
hasnt 'past every old decision rung, nothing about decisions reaches the model' \
      'decisions pushed to Solace' "$ctx6k"

# --- 7. the sitting line carries context and git state ----------------------
# Ruled by Solace, 2026-10-01: the rung line keeps the context and the ⎇ git
# state it carried before the tail rework. A fresh repo, not $REPO -- that one
# already carries a leftover "dirty" file from the archivable tests above, and
# this is checking the exact count.
REPO7="$SCRATCH/repo7"; mkdir -p "$REPO7"
git -C "$REPO7" init -q -b feat/nags
git -C "$REPO7" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
TP7="$SCRATCH/sit7.jsonl"; turn "$TP7" 41000
: > "$REPO7/scratch-file"
o7=$(clock 61 10; payload "$TP7" sit7 "$REPO7" | METRICS_MEAL_WINDOWS='' METRICS_SUN_AFTER_HOUR=24 bash "$HOOK" prompt 0 2>&1)
has 'the sitting line carries the context' '^⏱ 1h0[0-9] · context 41k' "$(msg "$o7")"
has 'and shows the dirty tree at its end'  '^⏱ 1h0[0-9] · context 41k ⎇ 1~$' "$(msg "$o7")"
clock_clear

# --- 8. the 📦 line is stop-continuity.py's verdict, read back -------------
# Whether a branch with no upstream is a hazard is stop-continuity.py's call
# now (stop-continuity.test.py: "never pushed", "zero commits ahead"). What
# is left here: the notice shows the planted reason, explains it, and refuses
# a verdict older than this Stop sequence's start (STOP_VERDICT_SINCE).
REPO8="$SCRATCH/repo8"; mkdir -p "$REPO8"
git -C "$REPO8" init -q -b feat/ahead
git -C "$REPO8" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
TP8="$SCRATCH/repo8.jsonl"; turn "$TP8" 1000
S8() { payload "$TP8" "$1" "$REPO8" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1; }
after_box() { printf '%s\n' "$1" | awk '/📦/ { getline; print; exit }'; }

plant stop8a 'not archivable: `feat/ahead` has no upstream (never pushed)'
m8=$(msg "$(S8 stop8a)")
has 'a planted reason is the 📦 line' \
    '^📦 not archivable: `feat/ahead` has no upstream \(never pushed\)\. \(feat/ahead stop8a\)$' "$m8"
has 'and the line under it explains it' '^→ never pushed: ' "$(after_box "$m8")"

plant stop8b
m8b=$(msg "$(S8 stop8b)")
has   'a planted archivable verdict is the 📦 line' '^📦 archivable\. \(feat/ahead stop8b\)$' "$m8b"
hasnt 'and nothing explains it' '^→ ' "$m8b"

plant stop8c 'not archivable: worktree dirty, 2 commit(s) unpushed'
m8c=$(msg "$(S8 stop8c)")
t 'two reasons, one explanation line each' 2 "$(grep -c '^→ ' <<<"$m8c")"

now8=$(date -u +%s)
plant stop8d archivable $((now8 - 100))
m8d=$(msg "$(payload "$TP8" stop8d "$REPO8" Stop \
      | STOP_VERDICT_SINCE=$now8 METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)")
has 'a verdict older than this Stop reads as did not finish' \
    '^📦 not archivable: the Stop hook did not finish\. ' "$m8d"
has 'and is explained as such' '^→ no verdict this turn: ' "$(after_box "$m8d")"
m8e=$(msg "$(payload "$TP8" stop8d "$REPO8" Stop \
      | STOP_VERDICT_SINCE=$((now8 - 100)) METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)")
has 'the same verdict at the boundary is current' '^📦 archivable\. ' "$m8e"

m8f=$(msg "$(S8 stop8none)")
has 'no verdict at all reads as did not finish' \
    '^📦 not archivable: the Stop hook did not finish\. ' "$m8f"

plant stop8g 'not archivable: something no explanation knows'
m8g=$(msg "$(S8 stop8g)")
has 'an unknown reason is still shown' 'something no explanation knows' "$m8g"

# --- 9. the turns line survives a clean tree --------------------------------
# The block's second line is "⇢ turns ⚙ tools", with git state appended only
# when there is any. `work` used to yield jq's `empty` on a clean tree, and an
# empty stream swallows the concatenation whole -- so the line that always
# applies vanished exactly when nothing else was wrong (#149).
REPO9="$SCRATCH/repo9"; mkdir -p "$REPO9"
git -C "$REPO9" init -q -b main
git -C "$REPO9" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
TP9="$SCRATCH/repo9.jsonl"; turn "$TP9" 1000
o9=$(payload "$TP9" show9 "$REPO9" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)
has 'a clean tree still prints the turns line' '⇢ [0-9]+ ⚙ [0-9]+' "$(msg "$o9")"
hasnt 'and says nothing about git state' '⎇' "$(msg "$o9")"

: > "$REPO9/scratch-file"
o9b=$(payload "$TP9" show9b "$REPO9" Stop | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show 2>&1)
has 'a dirty tree appends git state to the same line' '⇢ [0-9]+ ⚙ [0-9]+ ⎇ 1~' "$(msg "$o9b")"

# --- 9b. the turns line is byte-identical to the jq it replaced -------------
# metrics-format.sh's fmt_turns/fmt_work now build this line in plain shell
# (#149 step 7, the wiring PR). Prove the replacement changed nothing on
# screen: feed the cache object each run above wrote to the old jq expression
# and diff its bytes against the line the hook actually rendered.
old_second() {  # old_second <merged.json>
  jq -r -L "$(dirname "$HOOK")" \
    'include "lib-metrics-fmt";
     turns + ((work // "") as $w | if $w == "" then "" else " " + $w end)' \
    "$1" 2>/dev/null
}
rendered_second() { grep -oE '⇢.*' <<<"$1" | head -1; }

t 'clean tree: turns line matches the jq it replaced' \
  "$(old_second "$STATE/metrics/live/sh/show9.json")" \
  "$(rendered_second "$(msg "$o9")")"
t 'dirty tree: turns line matches the jq it replaced' \
  "$(old_second "$STATE/metrics/live/sh/show9b.json")" \
  "$(rendered_second "$(msg "$o9b")")"

# --- 10. the block survives $OUT being deleted mid-run -----------------------
# dotfiles#152: stop-continuity.py's Stop hook deletes $OUT concurrently, and
# metrics-live.sh spends real time in archivable()'s `gh pr list` between
# writing $OUT and reaching the display check. If that delete lands in the
# window, the display must still open with the block -- it comes from
# $metrics/$merged in memory now, not a re-read of the cache file.
#
# A clean, pushed repo of its own -- not $REPO, which carries the leftover
# "dirty" file from test 3 onward. archivable() short-circuits on a dirty
# worktree before it ever shells out to `gh`, so reusing $REPO would let this
# test pass on the timing of the script's own subprocess spawns rather than
# on the slow `gh` mock it's actually exercising. And it needs a pushed
# `main` to compare against, and a commit ahead of it -- branch-home-gate.sh
# quiet-exits on "no default branch to compare against" before it ever
# reaches `gh` otherwise (mirrors test 8's ORIGIN8/REPO8 setup).
ORIGIN10="$SCRATCH/origin10.git"; git init -q --bare "$ORIGIN10"
REPO10="$SCRATCH/repo10"; mkdir -p "$REPO10"
git -C "$REPO10" init -q -b main
git -C "$REPO10" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
git -C "$REPO10" remote add origin "$ORIGIN10"
git -C "$REPO10" push -q -u origin main
git -C "$REPO10" checkout -q -b feat/race
git -C "$REPO10" -c user.email=t@t -c user.name=t commit -q --allow-empty -m work
git -C "$REPO10" push -q -u origin feat/race

TP10="$SCRATCH/race.jsonl"; turn "$TP10" 1000
cat > "$SCRATCH/bin/gh" <<'GH'
#!/bin/sh
sleep 0.3
echo 1
GH
chmod +x "$SCRATCH/bin/gh"
OUT10="$STATE/metrics/live/ra/race.json"
payload "$TP10" race "$REPO10" Stop \
  | METRICS_STOP_HOUR=24 bash "$HOOK" stop 0 show > "$SCRATCH/o10.out" 2>&1 &
hook_pid=$!
until [ -f "$OUT10" ]; do :; done
rm -f "$OUT10"
wait "$hook_pid"
o10=$(cat "$SCRATCH/o10.out")
has 'the block still opens with $OUT removed mid-run' '^(»|⛁)' "$(msg "$o10")"
t   '$OUT was actually gone when the hook read it' absent \
    "$( [ -f "$OUT10" ] && echo present || echo absent )"
cat > "$SCRATCH/bin/gh" <<'GH'
#!/bin/sh
echo 1
GH
chmod +x "$SCRATCH/bin/gh"

# --- 11. calm states, and the ⏰ tier ---------------------------------------
# ✅ has shown blocked=0 since the #137 spec landed; friction and decisions
# vanished at zero instead, so "no friction" and "this field does not exist"
# looked the same. Ruled 2026-09-22: 🌌 friction, 🧘 decisions, bare --
# the glyph names its own field, so no ⚡/⚖ prefix.
# DAY forces the night window shut: a leftover sitting clock plus a real
# Pacific hour past 22:00 otherwise trips the night reason and every "calm"
# assertion below reads red between 22:00 and 05:00 (#362, #347).
DAY=(METRICS_STOP_HOUR=24 METRICS_NIGHT_END_HOUR=0)
rm -f "$STATE/metrics/sitting.json"
TP11="$SCRATCH/calm.jsonl"; turn "$TP11" 1000
o11=$(msg "$(payload "$TP11" calm "$SCRATCH" | env "${DAY[@]}" bash "$HOOK" posttooluse 0 show 2>&1)")
has 'friction at zero shows its calm glyph'  '🌌\(x0\)' "$o11"
has 'decisions at zero show theirs'          '🧘\(x0\)' "$o11"
has 'and blocked is unchanged'               '🔧✅\(x0\)' "$o11"
hasnt 'a calm block carries no verdict tail' ' — ' "$o11"

# dotfiles#137: UserPromptSubmit renders the block same as every other wired
# event now -- high frequency was the explicit ask, not a per-event opt-in.
TP11P="$SCRATCH/calm-prompt.jsonl"; turn "$TP11P" 1000
o11p=$(msg "$(payload "$TP11P" calmprompt "$SCRATCH" | bash "$HOOK" prompt 0 show 2>&1)")
has 'UserPromptSubmit renders the block too' '^(»|⛁)' "$o11p"

# The sitting cluster gets louder past NAG_SIT_HOT_RUNG rungs, night or day,
# so the night glyph still reads at the front of a long evening.
SITF11=$STATE/metrics/sitting.json
mkdir -p "$(dirname "$SITF11")"
jq -nc --argjson s "$(( $(date +%s) - 9000 ))" \
  '{sitting_start: $s, last_prompt: $s}' > "$SITF11"
o11b=$(msg "$(payload "$TP11" calm2 "$SCRATCH" | env "${DAY[@]}" bash "$HOOK" posttooluse 0 show 2>&1)")
has 'past the hot rung the glyph changes'     '⏱2h30(⏱️|🌙){3}⏰⏰' "$o11b"
o11c=$(msg "$(payload "$TP11" calm3 "$SCRATCH" | env "${DAY[@]}" METRICS_SIT_HOT_RUNG=9 \
  bash "$HOOK" posttooluse 0 show 2>&1)")
has 'and the rung is a knob like every other' '⏱2h30(⏱️|🌙){5}' "$o11c"

# dotfiles#137: the reason cluster trips on the same hot rung as the glyph
# itself, no second threshold to keep in sync.
has 'the sitting reason glyph trips at the hot rung' '— [^ ]*⏱️' "$o11b"
o11d=$(msg "$(payload "$TP11" calm4 "$SCRATCH" | env "${DAY[@]}" METRICS_SIT_HOT_RUNG=9 \
  bash "$HOOK" posttooluse 0 show 2>&1)")
hasnt 'and stays quiet while the rung is raised past it' ' — ' "$o11d"

# The night arm of the same window, forced open rather than waited for: a
# sitting clock past one rung proposes stopping at night however calm the
# rest of the block is. This is the behaviour that used to reach CI only
# between 22:00 and 05:00 Pacific, as a failure.
o11n=$(msg "$(payload "$TP11" calm5 "$SCRATCH" | env METRICS_STOP_HOUR=0 \
  METRICS_NIGHT_END_HOUR=24 METRICS_SIT_HOT_RUNG=9 \
  bash "$HOOK" posttooluse 0 show 2>&1)")
has 'at night a sitting clock alone trips the night reason' '— 🌙$' "$o11n"
rm -f "$SITF11"

# --- 12. PostToolUse drives the engine and may carry an injection ------------
# dotfiles#137, ruled 2026-09-22. Context is the one counter that climbs while
# the model works, so its rung is spoken on the tool call that crosses it and
# repeated after NAG_MODEL_CONTEXT_REPEAT tool calls of unacted silence. Both
# are behaviour a prompt-only engine could not have.
TP12="$SCRATCH/ptu.jsonl"
turn "$TP12" 40000
payload "$TP12" ptu "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
turn "$TP12" 152000
o12=$(payload "$TP12" ptu "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)
has 'a rung crossed by a tool call injects on that call'     'Context at 152k' "$(ctx "$o12")"
t   'and the injection names PostToolUse, not the prompt event' PostToolUse     "$(printf '%s' "$o12" | jq -r '.hookSpecificOutput.hookEventName // ""')"
has 'while the block still renders in the same object' '— 💸'     "$(msg "$o12")"

turn "$TP12" 153000
o12b=$(payload "$TP12" ptu "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)
t   'the next tool call injects nothing -- no new rung' '' "$(ctx "$o12b")"
has 'though the block is unaffected' '— 💸' "$(msg "$o12b")"

# The repeat arm, at 3 rather than the shipped 20 so the case is three calls.
for n in 2 3; do
  turn "$TP12" $((153000 + n))
  o12c=$(payload "$TP12" ptu "$SCRATCH" \
         | METRICS_MODEL_CONTEXT_REPEAT=3 bash "$HOOK" posttooluse 0 show 2>&1)
done
has 'a raised rung is said again after the repeat count'     'for 3 tool calls: a stopping point is due' "$(ctx "$o12c")"
turn "$TP12" 154000
o12d=$(payload "$TP12" ptu "$SCRATCH" \
       | METRICS_MODEL_CONTEXT_REPEAT=3 bash "$HOOK" posttooluse 0 show 2>&1)
t   'and the counter resets, so it does not repeat every call' '' "$(ctx "$o12d")"

# A Stop takes no injection: hookSpecificOutput is not a thing it may carry,
# and its crossings reach the model through the block reason instead.
TP12s="$SCRATCH/ptu-stop.jsonl"
turn "$TP12s" 152000
o12e=$(payload "$TP12s" ptustop "$SCRATCH" | bash "$HOOK" stop 0 show 2>&1)
t   'a Stop never carries an additionalContext' '' "$(ctx "$o12e")"

# Prompts still own the counters wound by the user's rhythm: a tool call must
# not advance the sitting clock or the decision ladder.
SITF12=$STATE/metrics/sitting.json
before12=$(jq -r '.sitting_start // 0' "$SITF12" 2>/dev/null || echo 0)
payload "$TP12" ptu "$SCRATCH" | bash "$HOOK" posttooluse 0 show >/dev/null 2>&1
t   'a tool call leaves the sitting clock where it found it' "$before12" \
    "$(jq -r '.sitting_start // 0' "$SITF12" 2>/dev/null || echo 0)"

# --- 13. day decisions: counted machine-wide, never nagged (#301) -----------
# The counter keeps counting across sessions; no line or injection reads it
# (one-entry-point §5, 2026-09-30).
DAYF="$STATE/metrics/day-decisions.json"
rm -f "$DAYF"

TP13a="$SCRATCH/day-a.jsonl"; SID13a=day-a
turn "$TP13a" 40000
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22; do askturn "$TP13a"; done
o13b=$(payload "$TP13a" "$SID13a" "$SCRATCH" \
       | METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 show 2>&1)
t    'no day line on screen at any count'      '' "$(msg "$o13b" | grep -o '☀.*' || true)"
t    'no gate line on screen at any count'     '' "$(msg "$o13b" | grep -o '⚖ [0-9].*' || true)"
t    'and nothing about decisions reaches the model' '' \
     "$(ctx "$o13b" | grep -o '[0-9]* decisions.*' || true)"
t    'but the day counter still counts'        '22' \
     "$(jq -r '.sessions["day-a"].total // 0' "$DAYF" 2>/dev/null)"

# A gap past METRICS_DECISION_GAP_MIN anywhere on the machine starts a fresh
# day: back-date day-decisions.json's last_prompt and confirm the map clears.
jq --argjson past "$(( $(date +%s) - 200 * 60 ))" '.last_prompt = $past' "$DAYF" \
   > "$DAYF.tmp" && mv "$DAYF.tmp" "$DAYF"
TP13d="$SCRATCH/day-c.jsonl"; SID13d=day-c
turn "$TP13d" 40000
payload "$TP13d" "$SID13d" "$SCRATCH" \
  | METRICS_DECISION_GAP_MIN=180 METRICS_SIT_EVERY_MIN=0 bash "$HOOK" prompt 0 show >/dev/null 2>&1
t    'a gap past the limit clears the day, so the store holds only the new session' \
     "$SID13d" "$(jq -r '.sessions | keys[0] // ""' "$DAYF" 2>/dev/null)"

# --- 14. the nag lock never blocks the hook (dotfiles#161) -------------------
# A concurrent invocation of the same session already holds
# $LIVE/<sid>.lock (a live pid, so state_lock must not reclaim it as stale):
# save_nag must skip its write rather than wait or fail the hook, and once
# the lock is free again a later call writes normally and cleans up after
# itself.
TP14="$SCRATCH/lock.jsonl"; SID14=lockcase
turn "$TP14" 103000
LOCKDIR="$STATE/metrics/live/$SID14.lock"
mkdir -p "$LOCKDIR"
printf 'pid=%s\nhostname=%s\n' "$$" "$(uname -n)" > "$LOCKDIR/meta"
out14=$(payload "$TP14" "$SID14" "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1); rc14=$?
t    'a held lock never blocks the hook' 0 "$rc14"
has  'the block still renders normally' '⛁' "$(msg "$out14")"
t    'and the nag write is skipped while the lock is held' no \
     "$([ -f "$STATE/metrics/live/${SID14:0:2}/$SID14.nag.json" ] && echo yes || echo no)"

rm -rf "$LOCKDIR"
payload "$TP14" "$SID14" "$SCRATCH" | bash "$HOOK" posttooluse 0 show >/dev/null 2>&1
t    'once the lock is free, the same session writes normally' yes \
     "$([ -f "$STATE/metrics/live/${SID14:0:2}/$SID14.nag.json" ] && echo yes || echo no)"
t    'and releases the lock dir behind it' no \
     "$([ -d "$LOCKDIR" ] && echo yes || echo no)"

# --- 15. what followed a sitting rung ----------------------------------------
# Each ⏱ crossing is stamped once, at the session's next prompt: minutes to
# that prompt, whether it was a `stay`, and whether the gap ran past the
# sitting gap. The crossing's own prompt never stamps it.
TP15="$SCRATCH/after.jsonl"; turn "$TP15" 1000
X15="$STATE/metrics/crossings/af/aft.jsonl"
backdate() {  # backdate <minutes> -- move every time crossing's ts that far back
  jq -c --arg ts "$(date -u -d "@$(( $(date +%s) - $1 * 60 ))" +%Y-%m-%dT%H:%M:%SZ)" \
    'if .kind == "time" then .ts = $ts else . end' "$X15" > "$X15.t" && mv "$X15.t" "$X15"
}
after() { jq -c 'select(.kind == "time_after") | [.at, .min, .stay, .quiet]' "$X15" 2>/dev/null; }
sitting aft 61 5
payload "$TP15" aft "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
t 'the crossing prompt stamps nothing' '' "$(after)"
backdate 3
payload "$TP15" aft "$SCRATCH" UserPromptSubmit | jq -c '. + {prompt: "  Stay."}' | bash "$HOOK" prompt 0 >/dev/null 2>&1
t 'the next prompt stamps minutes, stay, not quiet' '[60,3,true,false]' "$(after)"
payload "$TP15" aft "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
t 'and a crossing is stamped once' 1 "$(after | wc -l | tr -d ' ')"

sitting aft2 61 5
X15="$STATE/metrics/crossings/af/aft2.jsonl"
payload "$TP15" aft2 "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
backdate 40
payload "$TP15" aft2 "$SCRATCH" UserPromptSubmit | jq -c '. + {prompt: "stay here and fix it"}' \
  | bash "$HOOK" prompt 0 >/dev/null 2>&1
t 'a gap past the sitting gap is quiet; a sentence is not a stay' \
  '[60,40,false,true]' "$(after)"

sitting aft3 61 5
X15="$STATE/metrics/crossings/af/aft3.jsonl"
payload "$TP15" aft3 "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
backdate 1
payload "$TP15" aft3 "$SCRATCH" UserPromptSubmit | jq -c '. + {prompt: "/stay 30"}' \
  | bash "$HOOK" prompt 0 >/dev/null 2>&1
t '`stay <minutes>` is a stay' '[60,1,true,false]' "$(after)"

# --- 16. how a sitting rung's sitting ended -----------------------------------
# A `stay <n>` keeps its minutes; each crossing gets minutes to the sitting's
# final prompt, on Stop and at the next sitting start, and whether a `stay <n>`
# deadline was overrun. A Stop that changes nothing appends nothing.
shift_ts() {  # shift_ts <file> <kind> <minutes> -- move that kind's ts back
  jq -c --arg k "$2" --argjson m "$3" 'if .kind == $k
    then .ts = ((.ts | fromdateiso8601) - $m * 60 | todateiso8601) else . end' "$1" > "$1.t" && mv "$1.t" "$1"
}
said() { payload "$TP15" "$1" "$SCRATCH" UserPromptSubmit | jq -c --arg p "$2" '. + {prompt: $p}' \
  | bash "$HOOK" prompt 0 >/dev/null 2>&1; }
stop() { payload "$TP15" "$1" "$SCRATCH" Stop | bash "$HOOK" stop 0 >/dev/null 2>&1; }
last() { jq -c 'select(.kind == "time_last") | [.min_to_last, .overrun]' "$STATE/metrics/crossings/${1:0:2}/$1.jsonl"; }

sitting end1 61 5; said end1 go; shift_ts "$STATE/metrics/crossings/en/end1.jsonl" time 10
said end1 'stay 30'
t '`stay <n>` keeps its minutes' 30 \
  "$(jq 'select(.kind == "time_after") | .stay_min' "$STATE/metrics/crossings/en/end1.jsonl")"
stop end1
t 'Stop stamps minutes to the last prompt, deadline not overrun' '[10,false]' "$(last end1)"
stop end1
t 'and an unchanged reading is not stamped again' 1 "$(last end1 | wc -l | tr -d ' ')"

sitting end2 61 5; said end2 go; X16="$STATE/metrics/crossings/en/end2.jsonl"
shift_ts "$X16" time 15; said end2 'stay 2'; shift_ts "$X16" time_after 5; stop end2
t 'a prompt past the `stay <n>` deadline is an overrun' '[15,true]' "$(last end2)"

sitting end3 61 5; said end3 go; shift_ts "$STATE/metrics/crossings/en/end3.jsonl" time 50
sitting end4 80 40; said end4 back
t 'the next sitting start stamps every chat, from the old last prompt' '[10,null]' "$(last end3)"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
