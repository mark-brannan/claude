#!/usr/bin/env bash
# Tests for junk-decision tagging (dotfiles#301): session-metrics.jq marks a
# decision junk when a non-retracted friction record lands within 30 index
# units after it, and metrics-rollup.sh reports the count and rate per day.
# Run: bash hooks/metrics-junk.test.sh
set -uo pipefail
HOOKS="$(cd "$(dirname "$0")" && pwd)"
JQF="$HOOKS/session-metrics.jq"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
eq() { if [ "$2" = "$3" ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }

fq() { jq -nc --arg c "$1" '{type:"queue-operation", operation:"enqueue",
  timestamp:"2026-09-22T00:00:01.000Z", content:$c}'; }
fa() { jq -nc --arg t "$1" '{type:"assistant", uuid:"a", timestamp:"2026-09-22T00:00:00.000Z",
  message:{model:"m", role:"assistant", content:[{type:"text", text:$t}]}}'; }
run() { jq -s --arg sid t --arg repo r --arg branch b --arg cwd . --arg now n -f "$JQF"; }
junk() { run | jq -c '[.decisions[].junk], .session.decisions.junk' | paste -sd' '; }

# ask -> answer -> (n filler turns) -> reply
case_with() { # case_with <filler pairs> <reply>
  { fq "start"; fa "Which one do you want?"; fq "the first"
    for _ in $(seq 1 "$1"); do fa "ok."; done
    fa "Done."; fq "$2"; fa "Done."; } | junk
}
eq "a rebuke right after a decision makes it junk" '[true] 1' "$(case_with 0 "no, that's not what I asked for")"
eq "a benign reply leaves it clean" '[false] 0' "$(case_with 0 "thanks, looks good")"
eq "friction past 30 entries is out of window" '[false] 0' "$(case_with 40 "no, that's not what I asked for")"
eq "a retracted correction does not count" '[false] 0' \
  "$({ fq "start"; fa "Which one do you want?"; fq "the first"; fa "Done."; fq "no, wrong file"; fa "You're right, my mistake."; } | junk)"

# rollup: junk count and rate per day
ST="$S/state"; mkdir -p "$ST/metrics/sessions"
jq -nc '{session_id:"a", started_at:"2026-09-21T10:00:00Z", decisions:{total:4,gate:1,junk:1}}' > "$ST/metrics/sessions/a.json"
jq -nc '{session_id:"b", started_at:"2026-09-21T15:00:00Z", decisions:{total:6,gate:0,junk:2}}' > "$ST/metrics/sessions/b.json"
jq -nc '{session_id:"c", started_at:"2026-09-22T09:00:00Z", decisions:{total:2,gate:0,junk:0}}' > "$ST/metrics/sessions/c.json"
# lib-state resolves the state dir from the repo; give it a fake one.
mkdir -p "$S/repo/.git" "$S/repo/state/global/metrics"
cp -r "$ST/metrics/sessions" "$S/repo/state/global/metrics/"
CLAUDE_STATE_REPO="$S/repo" bash "$HOOKS/metrics-rollup.sh"
R="$S/repo/state/global/metrics/metrics.json"
eq "total junk" '3' "$(jq -c '.totals.junk' "$R")"
eq "overall junk rate" '25' "$(jq -c '.totals.junk_rate' "$R")"
eq "junk per day" '[{"day":"2026-09-21","decisions":10,"junk":3,"junk_rate":30},{"day":"2026-09-22","decisions":2,"junk":0,"junk_rate":0}]' \
  "$(jq -c '.totals.junk_by_day' "$R")"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
