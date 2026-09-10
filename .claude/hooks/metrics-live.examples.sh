#!/usr/bin/env bash
# Rendered output for the interesting scenarios in metrics-live.sh's crossing
# engine -- not a test (no assertions, nothing fails), a display. Run this
# and paste its output into a PR that touches any # FROZEN block, per the
# guard at the top of metrics-live.sh: rendered examples, not prose.
#
# Uses the same transcript-building harness as metrics-live.test.sh, so a
# shape change is fixed once in lib-metrics-test-harness.sh, not twice.
#
# Run: bash .claude/hooks/metrics-live.examples.sh
set -uo pipefail
HOOK="$(cd "$(dirname "$0")" && pwd)/metrics-live.sh"
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export HOME="$SCRATCH/home"; mkdir -p "$HOME"
export CLAUDE_STATE_REPO=""

# shellcheck source=lib-metrics-test-harness.sh
. "$(dirname "$HOOK")/lib-metrics-test-harness.sh"

show() { printf '\n### %s\n' "$1"; }

show "first context crossing (100k)"
TP="$SCRATCH/a.jsonl"; turn "$TP" 103000
out=$(payload "$TP" a "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  %s\n' "$(msg "$out")"

show "second crossing, same session (150k)"
turn "$TP" 152000
out=$(payload "$TP" a "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '  %s\n' "$(msg "$out")"

show "one jump crosses six rungs at once (350k)"
TP2="$SCRATCH/b.jsonl"; turn "$TP2" 350000
out=$(payload "$TP2" b "$SCRATCH" | bash "$HOOK" prompt 0 2>&1)
printf '%s\n' "$(msg "$out")" | sed 's/^/  /'

show "model injection: below stop threshold (103k) -- screen only"
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

show "model injection: sitting clock past 1h (screen + model)"
TP5="$SCRATCH/f.jsonl"; turn "$TP5" 40000
export METRICS_MODEL_CONTEXT_LINES=999999999
now=$(date +%s)
out=$(payload "$TP5" f "$SCRATCH" | METRICS_SIT_EVERY_MIN=60 bash "$HOOK" prompt 0 2>&1)
SITFILE=$(find "$HOME" -name sitting.json 2>/dev/null | head -1)
sed -i "s/\"sitting_start\": *[0-9]*/\"sitting_start\": $((now - 4300))/" \
  "$SITFILE" 2>/dev/null
turn "$TP5" 41000
out=$(payload "$TP5" f "$SCRATCH" | METRICS_SIT_EVERY_MIN=60 bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"
printf '  additionalContext: %s\n' "$(ctx "$out")"

show "model injection: sitting past 2h, next prompt (already raised)"
sed -i "s/\"sitting_start\": *[0-9]*/\"sitting_start\": $((now - 7400))/" \
  "$SITFILE" 2>/dev/null
turn "$TP5" 42000
out=$(payload "$TP5" f "$SCRATCH" | METRICS_SIT_EVERY_MIN=60 bash "$HOOK" prompt 0 2>&1)
printf '  screen:           %s\n' "$(msg "$out")"
printf '  additionalContext: %s\n' "$(ctx "$out")"
unset METRICS_MODEL_CONTEXT_LINES

rm -f "$SITFILE"

show "model injection: decision load past 3, then past 5"
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

show "friction crossing (committed contentious fixture)"
FIX="$(dirname "$HOOK")/fixtures/friction-contentious.jsonl"
if [ -f "$FIX" ]; then
  out=$(payload "$FIX" e "$SCRATCH" | METRICS_FRICTION_TURNS=200 bash "$HOOK" prompt 0 2>&1)
  printf '  additionalContext: %s\n' "$(ctx "$out")"
else
  printf '  (fixture missing)\n'
fi

printf '\n'
