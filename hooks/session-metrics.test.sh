#!/usr/bin/env bash
# Tests for session-metrics.jq: the cost derivation (dotfiles#363) and
# context_peak (dotfiles#294).
# Run: bash hooks/session-metrics.test.sh
#
# Cost: every model this corpus actually uses has a price entry, and the
# entry is the list price. The bug this half of the suite exists to stop
# recurring is silent: a model with no entry fell through to a *cheaper*
# fallback, so the record read as a real dollar figure while being half the
# true one. Nothing in the record said so. So the assertions below are exact
# hand-computable dollars per model, not "greater than zero".
#
# context_peak: the one number in that file that claims to say how full the
# model's context window got. Four properties, all of them things #294 found
# wrong or unproven:
#   resident      a request's occupancy is its whole prompt (uncached input,
#                 cache reads, cache writes) plus the response it produced
#   main chain    a Task agent's requests carry isSidechain and are its window,
#                 not this session's, so they never set the peak
#   peak          the largest request wins, not the last one -- a window that
#                 was reset mid-session still reports how full it had been
#   no usage      a transcript with no assistant usage reports 0, not null
#
# The rest of the jq -- decisions, friction, verdict, timing -- is not covered
# here.
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
JQF="$HOOKS/session-metrics.jq"
JQPROG="$JQF"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
SCRATCH="$S"

eq() { # eq <what> <expected> <got>
  if [ "$2" = "$3" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi
}

# One assistant message on $1, with 1M tokens in every usage bucket, so the
# cost this script reports IS the per-MTok price sheet, readable by eye.
mtok_msg() {
  jq -cn --arg m "$1" --arg u "$2" '{
    type: "assistant", uuid: $u, timestamp: "2026-09-22T00:00:00.000Z",
    message: {model: $m, role: "assistant",
              content: [{type: "text", text: "x"}],
              usage: {input_tokens: 1000000, output_tokens: 1000000,
                      cache_read_input_tokens: 1000000,
                      cache_creation: {ephemeral_1h_input_tokens: 1000000}}}}'
}

# The cost this transcript derives, per model.
costs() { # costs <transcript>
  jq -s --arg sid s --arg repo r --arg branch b --arg cwd / --arg now n \
     -f "$JQF" "$1" | jq -c '.session.cost_usd_by_model'
}

# --- the price sheet, one model at a time -------------------------------------
# input 1x + 1h cache creation 2x + cache read (the model's rate) + output 1x,
# all at 1 MTok each. Fable 5.1 and Mythos 5.1 price cache reads at a flat
# $0.25/MTok; everything else is 0.1x base input.
#   fable-5-1   10 + 20 + 0.25 + 50 = 80.25
#   fable-5     10 + 20 + 1.00 + 50 = 81
#   opus-5       5 + 10 + 0.50 + 25 = 40.5
#   sonnet-5     2 +  4 + 0.20 + 10 = 16.2
#   sonnet-4-6   3 +  6 + 0.30 + 15 = 24.3
#   haiku-4-5    1 +  2 + 0.10 +  5 = 8.1
while read -r model expected; do
  mtok_msg "$model" one > "$S/one.jsonl"
  eq "$model is priced at list" "{\"$model\":$expected}" "$(costs "$S/one.jsonl")"
done <<'SHEET'
claude-fable-5-1 80.25
claude-fable-5 81
claude-opus-5 40.5
claude-sonnet-5 16.2
claude-sonnet-4-6 24.3
claude-haiku-4-5-20251001 8.1
SHEET

# --- an unknown model reads as expensive, never as free -----------------------
# The fallback has to be the top of the price sheet. When it was Opus, every
# fable session in the corpus was reported at half price with no signal.
mtok_msg claude-notyetreleased-9 one > "$S/new.jsonl"
eq 'an unrecognised model falls back to the most expensive tier' \
   '{"claude-notyetreleased-9":81}' "$(costs "$S/new.jsonl")"

# --- more than one model in a session is priced per model and summed ----------
mtok_msg claude-fable-5-1 a  > "$S/two.jsonl"
mtok_msg claude-sonnet-5  b >> "$S/two.jsonl"
eq 'each model is priced at its own rate' \
   '{"claude-fable-5-1":80.25,"claude-sonnet-5":16.2}' "$(costs "$S/two.jsonl")"
eq 'the session total is their sum' '96.45' \
   "$(jq -s --arg sid s --arg repo r --arg branch b --arg cwd / --arg now n \
        -f "$JQF" "$S/two.jsonl" | jq -c '.session.cost_usd')"

# --- a session with no assistant turn costs nothing ---------------------------
printf '%s\n' '{"type":"queue-operation","operation":"enqueue","timestamp":"2026-09-22T00:00:00.000Z","content":"hi"}' > "$S/none.jsonl"
eq 'no assistant turns, no cost' '0' \
   "$(jq -s --arg sid s --arg repo r --arg branch b --arg cwd / --arg now n \
        -f "$JQF" "$S/none.jsonl" | jq -c '.session.cost_usd')"

# amsg <file> <input> <cache_read> <cache_creation> <output> [sidechain]
amsg() {
  jq -nc --arg ts "2026-09-09T10:00:00.000Z" \
    --argjson i "$2" --argjson r "$3" --argjson c "$4" --argjson o "$5" \
    --argjson sc "${6:-false}" --arg u "req-$(wc -l < "$1" | tr -d ' ')" \
    '{type:"assistant", timestamp:$ts, requestId:$u, isSidechain:$sc,
      message:{model:"claude-opus-5", role:"assistant",
               content:[{type:"text", text:"ok"}],
               usage:{input_tokens:$i, cache_read_input_tokens:$r,
                      cache_creation_input_tokens:$c, output_tokens:$o}}}' >> "$1"
}

peak() {  # peak <transcript>
  jq -s --arg sid t --arg repo r --arg branch b --arg cwd . \
    --arg now "2026-09-09T11:00:00Z" --arg slug s \
    -f "$JQPROG" "$1" | jq -r '.session.context_peak'
}

# --- resident: every part of the prompt, and the response -------------------
tp="$SCRATCH/resident.jsonl"; : > "$tp"
amsg "$tp" 100 5000 400 60
eq "prompt parts and response all count" 5560 "$(peak "$tp")"

# --- main chain: a subagent's window is not this session's ------------------
tp="$SCRATCH/sidechain.jsonl"; : > "$tp"
amsg "$tp" 0 20000 0 0
amsg "$tp" 0 900000 0 0 true
eq "a sidechain request never sets the peak" 20000 "$(peak "$tp")"

# --- peak: the fullest request, not the last -------------------------------
tp="$SCRATCH/peak.jsonl"; : > "$tp"
amsg "$tp" 0 150000 0 0
amsg "$tp" 0 12000 0 0
eq "a reset window still reports its peak" 150000 "$(peak "$tp")"

# --- no usage: 0, never null ----------------------------------------------
tp="$SCRATCH/empty.jsonl"
jq -nc '{type:"queue-operation", operation:"enqueue",
         timestamp:"2026-09-09T10:00:00.000Z", sessionId:"t", content:"go on"}' > "$tp"
eq "no assistant usage reads 0" 0 "$(peak "$tp")"

# --- curia_refs: prompts name a curia; tool calls only read one -------------
# The Stop hook stamps the floor on every curia this list names. A
# `cat`/`ls`/Read of a curia's file is not a sitting on it, so tool commands
# and file paths never count (PR #388, design pass).
refs() {  # refs <transcript>
  jq -s --arg sid t --arg repo r --arg branch b --arg cwd . \
    --arg now "2026-09-09T11:00:00Z" --arg slug s \
    -f "$JQPROG" "$1" | jq -c '.session.curia_refs'
}
prompt() {  # prompt <transcript> <text>
  jq -nc --arg c "$2" '{type:"queue-operation", operation:"enqueue",
    timestamp:"2026-09-09T10:00:00.000Z", sessionId:"t", content:$c}' >> "$1"
}
tool() {  # tool <transcript> <name> <input-json>
  jq -nc --arg n "$2" --argjson i "$3" '{type:"assistant", uuid:("u" + $n),
    timestamp:"2026-09-09T10:00:01.000Z",
    message:{model:"claude-opus-5", role:"assistant",
             content:[{type:"tool_use", id:"t", name:$n, input:$i}]}}' >> "$1"
}
tp="$SCRATCH/curia-named.jsonl"; : > "$tp"
prompt "$tp" "confer one-question, then /curia two-question"
prompt "$tp" "see state/global/curia/one-question/roll.md again"
eq "a prompt names a curia, once each, in first-named order" \
  '["one-question","two-question"]' "$(refs "$tp")"

tp="$SCRATCH/curia-read.jsonl"; : > "$tp"
prompt "$tp" "what is open on the board?"
tool "$tp" Bash '{"command":"cat state/global/curia/one-question/roll.md; ls state/global/curia/"}'
tool "$tp" Read '{"file_path":"/x/state/global/curia/two-question/roll.md"}'
eq "a cat, ls or Read of a roll names nothing" '[]' "$(refs "$tp")"

# prompt_span_seconds: first human prompt to last, the denominator of
# decisions per session-hour. One prompt has no span; agent work after the
# last prompt does not extend it.
enq() {  # enq <transcript> <timestamp>
  jq -nc --arg ts "$2" '{type:"queue-operation", operation:"enqueue",
    timestamp:$ts, sessionId:"t", content:"go"}' >> "$1"
}
span() {
  jq -s --arg sid t --arg repo r --arg branch b --arg cwd . --arg now n \
     -f "$JQF" "$1" | jq -c '.session.prompt_span_seconds'
}
tp="$SCRATCH/span.jsonl"; : > "$tp"
enq "$tp" "2026-09-09T10:00:00.000Z"
eq "one prompt has no span" '0' "$(span "$tp")"
enq "$tp" "2026-09-09T11:10:00.000Z"
jq -nc '{type:"assistant", timestamp:"2026-09-09T12:00:00.000Z", requestId:"late",
  message:{model:"claude-opus-5", role:"assistant", content:[],
           usage:{input_tokens:1, output_tokens:1}}}' >> "$tp"
eq "first prompt to last, not to the agent's last event" '4200' "$(span "$tp")"

# Friction counts only the user's own prompts. Sub-agent hand-backs and
# injected system content are enqueued like prompts but are not the user
# speaking (card 17910117682e4cdfd8: 16 agora "rebukes" were all hand-backs).
fq() { jq -nc --arg c "$1" '{type:"queue-operation", operation:"enqueue",
  timestamp:"2026-09-22T00:00:01.000Z", content:$c}'; }
fa() { jq -nc '{type:"assistant", uuid:"a", timestamp:"2026-09-22T00:00:00.000Z",
  message:{model:"m", role:"assistant", content:[{type:"text", text:"Done."}]}}'; }
fric() { # fric <enqueued content> -> friction total
  { fq "please fix the thing"; fa; fq "$1"; fa; } \
    | jq -s --arg sid t --arg repo r --arg branch b --arg cwd . --arg now n \
        -f "$JQF" | jq -c '.session.friction.total'
}
eq "a real rebuke counts" '1' "$(fric "no, that's not what I asked for")"
eq "a task-notification is not a rebuke" '0' "$(fric "<task-notification>no, that's not what I asked for</task-notification>")"
eq "an agent-message is not a rebuke" '0' "$(fric "<agent-message from=x>no, that's not what I asked for</agent-message>")"
eq "a system-reminder is not a rebuke" '0' "$(fric "<system-reminder>no, that's not what I asked for</system-reminder>")"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
