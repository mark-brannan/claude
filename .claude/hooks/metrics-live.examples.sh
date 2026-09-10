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

show "friction crossing (committed contentious fixture)"
FIX="$(dirname "$HOOK")/fixtures/friction-contentious.jsonl"
if [ -f "$FIX" ]; then
  out=$(payload "$FIX" e "$SCRATCH" | METRICS_FRICTION_TURNS=200 bash "$HOOK" prompt 0 2>&1)
  printf '  additionalContext: %s\n' "$(ctx "$out")"
else
  printf '  (fixture missing)\n'
fi

printf '\n'
