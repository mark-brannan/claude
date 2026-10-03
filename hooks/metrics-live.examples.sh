#!/usr/bin/env bash
# Rendered output for the interesting scenarios in metrics-live.sh's crossing
# engine -- not a test (no assertions, nothing fails), a display. Run this
# and paste its output into a PR that touches any # FROZEN block, per the
# guard at the top of metrics-live.sh: rendered examples, not prose.
#
# Uses the same transcript-building harness as metrics-live.test.sh, so a
# shape change is fixed once in lib-metrics-test-harness.sh, not twice.
#
# Run: bash hooks/metrics-live.examples.sh
set -uo pipefail
HOOK="$(cd "$(dirname "$0")" && pwd)/metrics-live.sh"
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export CLAUDE_STATE_REPO=""
# Daylight whatever the wall clock says, so the sitting cases render the same
# at midnight as at noon; the bedtime cases force the night per invocation.
export METRICS_STOP_HOUR=24 METRICS_NIGHT_END_HOUR=0

# shellcheck source=lib-metrics-test-harness.sh
. "$(dirname "$HOOK")/lib-metrics-test-harness.sh"

show() { printf '\n### %s\n' "$1"; }

# The crossing engine runs on a prompt and on a Stop; the block renders on
# every shown event. A crossing prints nothing of its own (dotfiles#137), so
# each case below is a prompt to move the rungs, then a shown event to see
# where they landed.
block() { payload "$1" "$2" "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1; }

show "first context crossing (100k)"
TP="$SCRATCH/a.jsonl"; turn "$TP" 103000
payload "$TP" a "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
printf '%s\n' "$(msg "$(block "$TP" a)")" | sed 's/^/  /'

show "second crossing, same session (150k)"
turn "$TP" 152000
payload "$TP" a "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
printf '%s\n' "$(msg "$(block "$TP" a)")" | sed 's/^/  /'

show "one jump crosses six rungs at once (350k)"
TP2="$SCRATCH/b.jsonl"; turn "$TP2" 350000
payload "$TP2" b "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
printf '%s\n' "$(msg "$(block "$TP2" b)")" | sed 's/^/  /'

show "model injection: below stop threshold (103k) -- nothing to the model"
TP3="$SCRATCH/c.jsonl"; turn "$TP3" 103000
out=$(payload "$TP3" c "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: [%s]\n' "$(ctx "$out")"

show "model injection: first crossing at/above stop threshold (152k)"
turn "$TP3" 152000
out=$(payload "$TP3" c "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "model injection: one call crossing three stop-armed rungs (0 -> 260k)"
TP4="$SCRATCH/d.jsonl"; turn "$TP4" 260000
out=$(payload "$TP4" d "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "model injection: same session, next prompt while still over (no new rung)"
turn "$TP3" 153000
out=$(payload "$TP3" c "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: %s\n' "$(ctx "$out")"

# The sitting line's tail is picked by the local clock, so each case below
# forces its branch with the knobs: a meal window, the sunset (an equator
# longitude two hours before local sunset), or a line from outside.txt.
STATE="$HOME/.claude/state/global"; mkdir -p "$STATE"
printf 'placeholder: the light on the hills\n' > "$STATE/outside.txt"
sun_lon=$(awk -v now="$(date +%s)" 'BEGIN { l = (16 - (now % 86400) / 3600) * 15
  while (l >= 180) l -= 360; while (l < -180) l += 360; printf "%.3f", l }')
printf '{"lat": 0, "lon": %s}\n' "$sun_lon" > "$STATE/location.json"
NOMEAL=(METRICS_MEAL_WINDOWS= METRICS_SUN_AFTER_HOUR=0)
NOSUN=(METRICS_MEAL_WINDOWS= METRICS_SUN_AFTER_HOUR=24)

show "sitting clock past 1h, list tail (screen + model)"
TP5="$SCRATCH/f.jsonl"; turn "$TP5" 40000
export METRICS_MODEL_CONTEXT_LINES=999999999
now=$(date +%s)
out=$(payload "$TP5" f "$SCRATCH" | METRICS_SIT_EVERY_MIN=60 bash "$HOOK" prompt 0 2>&1)
SITFILE=$(find "$HOME" -name sitting.json 2>/dev/null | head -1)
sed -i "s/\"sitting_start\": *[0-9]*/\"sitting_start\": $((now - 3660))/" \
  "$SITFILE" 2>/dev/null
turn "$TP5" 41000
out=$(payload "$TP5" f "$SCRATCH" | env "${NOSUN[@]}" bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "sitting past 2h, sunset tail (screen + model)"
sed -i "s/\"sitting_start\": *[0-9]*/\"sitting_start\": $((now - 7500))/" \
  "$SITFILE" 2>/dev/null
turn "$TP5" 42000
out=$(payload "$TP5" f "$SCRATCH" | env "${NOMEAL[@]}" bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "sitting still past 2h, no new rung (silent)"
turn "$TP5" 43000
out=$(payload "$TP5" f "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  screen:           [%s]\n' "$(msg "$out")"
printf '  additionalContext: [%s]\n' "$(ctx "$out")"

show "sitting past 3h in a meal window"
sed -i "s/\"sitting_start\": *[0-9]*/\"sitting_start\": $((now - 10900))/" \
  "$SITFILE" 2>/dev/null
out=$(payload "$TP5" f "$SCRATCH" | METRICS_MEAL_WINDOWS=0-24 bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"

show "sitting past 1h, list tail, dirty tree"
REPOX="$SCRATCH/repo"; git init -q -b feat/x "$REPOX"
git -C "$REPOX" -c user.email=t@t -c user.name=t commit -q --allow-empty -m init
: > "$REPOX/scratch-file"
TPX="$SCRATCH/x.jsonl"; turn "$TPX" 41000
jq -n --argjson ss "$((now - 3660))" --argjson lp "$((now - 60))" \
  '{sitting_start: $ss, last_prompt: $lp}' > "$SITFILE"
out=$(payload "$TPX" x "$REPOX" | env "${NOSUN[@]}" bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"

show "stay 40, at 1h29"
TP6="$SCRATCH/g.jsonl"; turn "$TP6" 40000
jq -n --argjson ss "$((now - 5340))" --argjson lp "$((now - 60))" \
  '{sitting_start: $ss, last_prompt: $lp}' > "$SITFILE"
out=$(payload "$TP6" g "$SCRATCH" UserPromptSubmit "stay 40" | bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"
printf '  additionalContext: %s\n' "$(ctx "$out")"
unset METRICS_MODEL_CONTEXT_LINES

# Bedtime: the night hour forced open, the clock read in UTC through
# location.json's tz so the rendered times are the same on any host.
NIGHT=(METRICS_STOP_HOUR=0 METRICS_NIGHT_END_HOUR=0)
printf '{"tz": "UTC"}\n' > "$STATE/location.json"
TPB="$SCRATCH/bed.jsonl"; turn "$TPB" 40000
bedp() { payload "$TPB" bed "$SCRATCH" UserPromptSubmit "$1" | env "${NIGHT[@]}" bash "$HOOK" prompt 0 2>&1; }
bedshow() { printf '  screen:           %s\n  additionalContext: [%s]\n' "$(msg "$1")" "$(ctx "$1")"; }
set_bed() { jq --argjson b "$1" '.bed_at = $b' "$SITFILE" > "$SITFILE.t" && mv "$SITFILE.t" "$SITFILE"; }
rm -f "$SITFILE"

show "bedtime: the first prompt after the night hour (screen only)"
bedshow "$(bedp "go on")"

show "bedtime: the next prompt, no reply yet (silent, never re-asked)"
bedshow "$(bedp "go on")"

show "bedtime: the reply, a bare time 30 minutes out"
bedshow "$(bedp "$(TZ=UTC date -d "@$(( $(date +%s) + 1800 ))" +%H:%M)")"

show "bedtime: five minutes before"
set_bed $(( $(date +%s) + 280 ))
bedshow "$(bedp "go on")"

show "bedtime: past the hour"
set_bed $(( $(date +%s) - 120 ))
bedshow "$(bedp "go on")"

show "bedtime: the prompt after that (silent)"
bedshow "$(bedp "go on")"
printf '{"lat": 0, "lon": %s}\n' "$sun_lon" > "$STATE/location.json"

show "sitting cluster: the ⏰ tier past the 90-minute rung"
jq -n --argjson ss "$((now - 9000))" '{sitting_start: $ss, last_prompt: $ss}' > "$SITFILE"
printf '%s\n' "$(msg "$(block "$TP5" f)")" | sed 's/^/  /'

rm -f "$SITFILE"

show "model injection: decisions past 3, then past 5 -- nothing to the model"
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
TP6="$SCRATCH/g.jsonl"; turn "$TP6" 40000
for _ in 1 2 3; do askturn "$TP6"; done
out=$(payload "$TP6" g "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: %s\n' "$(ctx "$out")"
for _ in 1 2; do askturn "$TP6"; done
out=$(payload "$TP6" g "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  additionalContext: %s\n' "$(ctx "$out")"
rm -f "$SITFILE"

# --- PostToolUse -------------------------------------------------------------
# The engine runs on tool calls too, so a context rung crossed by a large tool
# result mid-turn is spoken when it happens rather than at the next prompt. The
# block and the injection ride out together -- one hook invocation, one object.
show "PostToolUse: a tool result crosses a rung mid-turn (block + injection)"
TP7="$SCRATCH/h.jsonl"; turn "$TP7" 40000
payload "$TP7" h "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
turn "$TP7" 152000
out=$(payload "$TP7" h "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)
printf '  screen:            %s\n' "$(msg "$out" | head -1)"
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "PostToolUse: next tool call, no new rung (block only, model silent)"
turn "$TP7" 153000
out=$(payload "$TP7" h "$SCRATCH" | bash "$HOOK" posttooluse 0 show 2>&1)
printf '  screen:            %s\n' "$(msg "$out" | head -1)"
printf '  additionalContext: [%s]\n' "$(ctx "$out")"

show "PostToolUse: the repeat arm at METRICS_MODEL_CONTEXT_REPEAT=3"
# 3 rather than the shipped 20 so the example is three lines instead of
# twenty; the arm is the same one, counting tool calls of unacted silence.
TP8="$SCRATCH/i.jsonl"; turn "$TP8" 152000
payload "$TP8" i "$SCRATCH" | bash "$HOOK" prompt 0 >/dev/null 2>&1
for n in 1 2 3 4; do
  turn "$TP8" $((153000 + n))
  out=$(payload "$TP8" i "$SCRATCH" \
        | METRICS_MODEL_CONTEXT_REPEAT=3 bash "$HOOK" posttooluse 0 show 2>&1)
  printf '  tool call %d:       [%s]\n' "$n" "$(ctx "$out")"
done

show "friction crossing (committed contentious fixture)"
FIX="$(dirname "$HOOK")/fixtures/friction-contentious.jsonl"
if [ -f "$FIX" ]; then
  out=$(payload "$FIX" e "$SCRATCH" | METRICS_FRICTION_TURNS=200 bash "$HOOK" prompt 0 2>&1)
  printf '  additionalContext: %s\n' "$(ctx "$out")"
else
  printf '  (fixture missing)\n'
fi

printf '\n'
