#!/usr/bin/env bash
# Recompute the session's metrics NOW and cache them where the statusline can
# read them without paying for the computation itself.
#
# Why a cache file at all: `session-metrics.jq` slurps the whole transcript,
# which is fine a few times a turn but not on every statusline render (those
# fire several times a second). The statusline just prints what is already on
# disk, and recomputes only past its own staleness age.
#
# Three wirings, and only three: UserPromptSubmit (silent readout, may carry a
# crossing line), Stop and SubagentStop. It used to be wired to nine events,
# eight of them with `show`, which meant a jq pass over the transcript after
# every single tool call and a readout that spoke often enough to be tuned
# out. That is a level-triggered nag. What replaced it is the crossing engine
# below: a line fires once, when a threshold is first crossed, and then says
# nothing until the next line.
#
# One file per session, keyed by session_id: parallel sessions are normal
# here, and per-session paths mean two of them never write the same file.
# The rollup that merges them (`metrics/metrics.json`) is *generated* and
# gitignored -- it is never committed, so there is no shared file for two
# sessions to collide on. See metrics-rollup.sh.
#
# stdin: any hook payload carrying transcript_path/session_id/cwd.
# Always exits 0.
#
# FROZEN -- THAW CAREFULLY. Every block below tagged with that phrase (the
# ⛁ context, ⚖ gate, ⚡ friction and ⏱ sitting-clock crossings, and any glyph
# family added alongside them) is frozen: do not modify without direct,
# explicit interaction with Solace.
#
# Changes here are small and contained -- one glyph/family at a time. Never
# a wholesale rewrite: don't drop an existing glyph, family, or behavior
# without her explicit call to drop it. That includes cadence: don't make
# a line fire less often, coalesce, dedupe, or go quiet as a "cleanup" --
# she has said explicitly she wants this louder and more frequent, not
# calmer. Edge-triggered (once per new crossing) is the floor, not a ceiling
# to defend; if a change would make the reader see this line less, it is
# out of scope for a "small, contained" edit and needs to be asked about.
#
# Before touching any of these lines: propose it visually in-chat first --
# rendered before/after examples, not a description of the change. Before
# merging: the PR description carries those same rendered examples. Prose
# alone does not satisfy this.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"

command -v jq >/dev/null 2>&1 || exit 0

EVENT_ARG="${1:-}"          # explicit override; only statusline and tests pass this now
MAX_AGE="${2:-0}"           # seconds; >0 means "skip if cache is fresher"
SHOW="${3:-}"               # "show" -> also print a systemMessage block

# ---------------------------------------------------- counters and their lines
# Every threshold in this file is here, and every one is overridable. A line
# fires once, when the counter first crosses it this session, and then says
# nothing until the next line up -- edge-triggered, not level-triggered.
#
#   context   size and a verdict; "propose stopping" from CONTEXT_STOP_AT up.
#             The line repeats its glyph once per threshold rung crossed this
#             session (capped at 5, then "(xN)"), and the ladder extends past
#             the last configured line by CONTEXT_STEP forever, so it keeps
#             escalating instead of going quiet at the top. At or above
#             CONTEXT_STOP_AT it also reaches the model: once as an offer to
#             stop, and plainly, not repeated, on every rung after that
#   sitting   elapsed, context, verdict -- driven entirely by prompts: it
#             starts at the first one, restarts when the gap between two of
#             them runs past SIT_GAP_MIN (a session picked up after dinner is
#             a new sitting, not a nine-hour one), and is never read or moved
#             by a Stop. 60 min says stand up, 120 says stop here and wrap up.
#             The clock itself is machine-wide, not per session -- three open
#             chats are still one chair -- while the line is reported once per
#             session, so each chat says it where its user is reading
#   friction  corrections and rebukes inside a window of human turns; the one
#             line that goes to the model rather than to the screen, since the
#             standing orders' capacity rule is what it is asking for
#   gate      gate decisions pushed to the user, every GATE_EVERY
NAG_CONTEXT_LINES="${METRICS_CONTEXT_LINES:-100000 150000 200000}"
NAG_CONTEXT_STOP_AT="${METRICS_CONTEXT_STOP_AT:-150000}"
NAG_CONTEXT_STEP="${METRICS_CONTEXT_STEP:-50000}"
NAG_SIT_EVERY_MIN="${METRICS_SIT_EVERY_MIN:-60}"
NAG_SIT_GAP_MIN="${METRICS_SIT_GAP_MIN:-30}"
NAG_FRICTION_N="${METRICS_FRICTION_N:-3}"
NAG_FRICTION_TURNS="${METRICS_FRICTION_TURNS:-20}"
NAG_GATE_EVERY="${METRICS_GATE_EVERY:-5}"
# Local hour from which a Stop on an archivable session is worth interrupting.
NAG_STOP_HOUR="${METRICS_STOP_HOUR:-22}"

# One jq for all three fields: the statusline reaches this code on every
# render, and three spawns before the staleness check was most of its cost.
input=$(cat 2>/dev/null || echo '{}')
IFS=$'\t' read -r tp sid cwd hook_name <<<"$(printf '%s' "$input" | jq -r \
  '[(.transcript_path // ""), (.session_id // ""),
    (.cwd // .workspace.current_dir // ""),
    (.hook_event_name // "")] | @tsv')"
[ -n "$tp" ] && [ -f "$tp" ] && [ -n "$sid" ] || exit 0
[ -n "$cwd" ] || cwd=$PWD

# Default EVENT to hook_event_name verbatim, lowercased, so a new hook
# needs no matching entry here.
if [ -n "$EVENT_ARG" ]; then
  EVENT="$EVENT_ARG"
else
  EVENT=$(printf '%s' "${hook_name:-tool}" | tr '[:upper:]' '[:lower:]')
fi

# `show` on UserPromptSubmit would make the readout model context rather than
# display, every turn. The crossing lines below still reach the screen there;
# it is the whole block that stays suppressed.
case "$EVENT" in prompt|userpromptsubmit|statusline) SHOW="" ;; esac

# A git event means an actual git-state change, not every Bash call: the jq
# pass is too expensive to run after `ls`. The set is git_event_re in
# lib-state.sh -- shared with measure-git-events.sh so the counter and the
# display can never disagree about what counts. Both fields are tested, not
# one falling back to the other: an MCP tool has no `.command`, and a Bash
# call whose command does not match must not then match on the tool name.
if [ "$EVENT" = git ]; then
  printf '%s' "$input" \
    | jq -r '[(.tool_input.command // ""), (.tool_name // "")] | join("\n")' \
    | grep -qE "$(git_event_re)" \
    || exit 0
fi

JQPROG="$HOOK_DIR/session-metrics.jq"
[ -f "$JQPROG" ] || exit 0

LIVE="$(state_dir)/metrics/live"
OUT="$LIVE/$sid.json"

# Throttle: the statusline asks constantly, events ask rarely. An event
# always recomputes; the statusline only does so if the cache has gone stale.
if [ "$MAX_AGE" -gt 0 ] && [ -f "$OUT" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$OUT" 2>/dev/null || stat -f %m "$OUT" 2>/dev/null || echo 0) ))
  [ "$age" -lt "$MAX_AGE" ] && exit 0
fi

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
work_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || echo "")
work_repo=$([ -n "$work_root" ] && basename "$work_root" || basename "$cwd")
work_branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

metrics=$(jq -s \
  --arg sid "$sid" --arg repo "$work_repo" --arg branch "$work_branch" \
  --arg cwd "$cwd" --arg now "$now" \
  -f "$JQPROG" "$tp" 2>/dev/null) || exit 0
[ -n "$metrics" ] || exit 0

# Git state, the part that decides whether the chat is safe to kill.
dirty=0; unpushed=0; ncommits=0; start_sha=""
if [ -n "$work_root" ]; then
  dirty=$(git -C "$work_root" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  unpushed=$(git -C "$work_root" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
  # Commits counted from the SHA this session started at, not by timestamp.
  # `--since=<start>` counts everything in the window whatever wrote it, so a
  # fresh clone whose history landed today reports a session's commits as 13
  # when it made none -- and a number that is persistently wrong on screen is
  # worse than no number, because you stop reading the field.
  start_sha=$(jq -r '.start_sha // ""' "$OUT" 2>/dev/null)
  [ -n "$start_sha" ] \
    || start_sha=$(git -C "$work_root" rev-parse HEAD 2>/dev/null || echo "")
  if [ -n "$start_sha" ]; then
    ncommits=$(git -C "$work_root" rev-list --count "$start_sha..HEAD" 2>/dev/null || echo 0)
  fi
fi

mkdir -p "$LIVE" 2>/dev/null || exit 0

# Wall clock, read once. The sitting clock in the engine below is the only
# thing that reads it, and only a prompt moves that clock.
#
# There used to be a second timer here, backed by metrics/last_activity.json:
# every event stamped it, including every statusline render, so the readout
# kept its own break timer alive simply by being drawn. A clock the display
# winds is not measuring the user. It is gone, and with it break_nag in
# lib-metrics-fmt.jq -- the sitting clock is the only sitting clock now.
now_ts=$(date +%s)

tmp="$OUT.$$"
printf '%s\n' "$metrics" | jq -c \
  --arg ev "$EVENT" --arg now "$now" \
  --argjson d "${dirty:-0}" --argjson u "${unpushed:-0}" --argjson c "${ncommits:-0}" \
  --arg sha "$start_sha" \
  '.session + {last_event: $ev, updated_at: $now, start_sha: $sha,
               dirty: $d, unpushed: $u, commits: $c}' > "$tmp" 2>/dev/null \
  && mv -f "$tmp" "$OUT" 2>/dev/null || rm -f "$tmp" 2>/dev/null

# =========================================================== crossing engine
# Edge-triggered. State lives in one small file per session next to the cache;
# it is NOT the cache, because stop-continuity.sh deletes the cache at the end
# of a session and the crossings have to outlive it.
NAGF="$LIVE/$sid.nag.json"
CROSSD="$(state_dir)/metrics/crossings"

# The sitting clock is the one piece of this state that is NOT per session.
# A person with three chats open is one person in one chair: when the clock
# lived in the per-session file, every new session started its own clock at
# zero and a four-hour afternoon spread over four chats never reached the
# 60-minute line once. So sitting_start and last_prompt live in a single
# machine-wide file that any session's UserPromptSubmit advances.
#
# Per machine, and never a record: it answers "how long has this body been at
# this box", which does not survive being synced to another host. It is
# gitignored in the state repo for the same reason last_activity.json was.
#
# Two sessions prompting in the same second can clobber each other's write.
# The loss is bounded by the write being whole-file and atomic -- the reader
# sees one session's clock or the other's, never a torn one -- and both are
# writing near-identical values, so it is not worth a lock file that would
# have to work on a machine without flock.
SITF="$(state_dir)/metrics/sitting.json"

sit_start=0; last_prompt=0
if [ -f "$SITF" ]; then
  IFS=$'\t' read -r sit_start last_prompt \
    <<<"$(jq -r '[(.sitting_start // 0), (.last_prompt // 0)] | @tsv' "$SITF" 2>/dev/null)"
fi
[ -n "$sit_start" ] || sit_start=0
[ -n "$last_prompt" ] || last_prompt=0

save_sitting() {
  mkdir -p "$(dirname "$SITF")" 2>/dev/null || return 0
  jq -n --argjson ss "$sit_start" --argjson lp "$last_prompt" \
    '{sitting_start: $ss, last_prompt: $lp}' \
    > "$SITF.$$" 2>/dev/null \
    && mv -f "$SITF.$$" "$SITF" 2>/dev/null || rm -f "$SITF.$$" 2>/dev/null
}

# time_line stays per session: the clock is shared, but the report of it is
# each session's own, so a threshold is spoken once in every chat that is
# open when it is crossed rather than once on the machine. tl_sitting is the
# sitting_start that time_line was recorded against -- when the shared clock
# restarts, every session's line is stale, including the ones that were not
# the prompt that restarted it, and they must be free to speak again.
ctx_line=0; ctx_rungs=0; ctx_stop_line=0; time_line=0; tl_sitting=0; gate_line=0; fric_tripped=0
since_nag=0; resume_ts=0; nag_pending=0; late_nagged=0
if [ -f "$NAGF" ]; then
  IFS=$'\t' read -r ctx_line ctx_rungs ctx_stop_line time_line tl_sitting gate_line fric_tripped \
                    since_nag resume_ts nag_pending late_nagged \
    <<<"$(jq -r '[(.context_line // 0), (.context_rungs // 0), (.context_stop_line // 0),
                  (.time_line // 0), (.time_line_sitting // -1),
                  (.gate_line // 0),
                  (if .friction_tripped then 1 else 0 end),
                  (if .since_nag then 1 else 0 end),
                  (.resume_ts // 0),
                  (if .nag_pending then 1 else 0 end),
                  (if .late_nagged then 1 else 0 end)] | @tsv' "$NAGF" 2>/dev/null)"
fi
for v in ctx_line ctx_rungs ctx_stop_line time_line tl_sitting gate_line fric_tripped \
         since_nag resume_ts nag_pending late_nagged; do
  [ -n "${!v}" ] || eval "$v=0"
done
# -1 is a nag file written before the clock moved out of it: its time_line
# belongs to a sitting nobody can name, so it is spent rather than trusted.
[ "$tl_sitting" -eq "$sit_start" ] || { time_line=0; tl_sitting=$sit_start; }

# A nag file written before context_rungs/context_stop_line existed has
# context_line but defaults both new fields to 0 -- read literally, a session
# that already crossed 200k before the upgrade would show only the rungs it
# crosses from here, undercounting the glyph escalation, and would re-offer
# to stop as if for the first time. Derive both from context_line and the
# ladder as configured now, once, rather than trust a zero that only means
# "this field didn't exist yet".
if [ "$ctx_rungs" -eq 0 ] && [ "$ctx_line" -gt 0 ]; then
  for L in $NAG_CONTEXT_LINES; do
    [ "$L" -le "$ctx_line" ] && ctx_rungs=$((ctx_rungs + 1))
  done
  if [ "$NAG_CONTEXT_STEP" -gt 0 ]; then
    last_cfg=0
    for L in $NAG_CONTEXT_LINES; do last_cfg=$L; done
    if [ "$last_cfg" -gt 0 ]; then
      L=$((last_cfg + NAG_CONTEXT_STEP))
      while [ "$L" -le "$ctx_line" ]; do
        ctx_rungs=$((ctx_rungs + 1))
        L=$((L + NAG_CONTEXT_STEP))
      done
    fi
  fi
fi
[ "$ctx_stop_line" -eq 0 ] && [ "$ctx_line" -ge "$NAG_CONTEXT_STOP_AT" ] && ctx_stop_line=$ctx_line

save_nag() {
  jq -n --argjson cl "$ctx_line" --argjson cr "$ctx_rungs" --argjson cs "$ctx_stop_line" \
        --argjson tl "$time_line" --argjson ts "$tl_sitting" \
        --argjson gl "$gate_line" --argjson ft "$fric_tripped" \
        --argjson sn "$since_nag" --argjson rt "$resume_ts" --argjson np "$nag_pending" \
        --argjson ln "$late_nagged" \
    '{context_line: $cl, context_rungs: $cr, context_stop_line: $cs,
      time_line: $tl, time_line_sitting: $ts, gate_line: $gl,
      friction_tripped: ($ft == 1),
      since_nag: ($sn == 1), resume_ts: $rt, nag_pending: ($np == 1),
      late_nagged: ($ln == 1)}' \
    > "$NAGF.$$" 2>/dev/null \
    && mv -f "$NAGF.$$" "$NAGF" 2>/dev/null || rm -f "$NAGF.$$" 2>/dev/null
}

# Only the three wired events drive the engine. The statusline reaches this
# file too, several times a minute, and must never consume a crossing.
is_prompt=0; run_engine=0
case "$EVENT" in
  prompt|userpromptsubmit)   is_prompt=1; run_engine=1 ;;
  stop|subagentstop)         run_engine=1 ;;
esac

kfmt() { awk -v n="$1" 'BEGIN { if (n >= 1000) printf "%dk", int(n / 1000); else printf "%d", n }'; }
hm()   { awk -v m="$1" 'BEGIN { if (m >= 60) printf "%dh%02d", int(m / 60), m % 60; else printf "%dm", m }'; }
hhmm() { date -d "@$1" +%H:%M 2>/dev/null || date -r "$1" +%H:%M 2>/dev/null || echo "??:??"; }

# $1 glyph count, $2 glyph char -- repeats the glyph up to 5 times, then
# switches to "(xN)" so an escalation past the cap still reads as a number
# instead of a wall of characters.
glyphs() {
  local n="$1" g="$2" i shown out=""
  shown=$n; [ "$shown" -gt 5 ] && shown=5
  for ((i = 0; i < shown; i++)); do out="${out}${g}"; done
  [ "$n" -gt 5 ] && out="${out}(x${n})"
  printf '%s' "$out"
}

# Git state folded into a nag line -- the same shorthand as lib-metrics-fmt.jq's
# `work`, but the crossing lines run in bash, not jq. Empty on a clean tree.
work_str() {
  [ "${ncommits:-0}" -gt 0 ] || [ "${dirty:-0}" -gt 0 ] || [ "${unpushed:-0}" -gt 0 ] \
    || return 0
  local s="⎇ "
  [ "${ncommits:-0}" -gt 0 ] && s="${s}${ncommits}c"
  [ "${dirty:-0}" -gt 0 ]    && s="${s}${dirty}~"
  [ "${unpushed:-0}" -gt 0 ] && s="${s}${unpushed}↑"
  printf '%s' "$s"
}

sys_lines=""; model_line=""
add_line()  { sys_lines="${sys_lines:+$sys_lines
}$1"; }
add_model() { model_line="${model_line:+$model_line
}$1"; }
record_crossing() {
  mkdir -p "$CROSSD" 2>/dev/null || return 0
  jq -nc --arg sid "$sid" --arg now "$now" --arg kind "$1" \
         --argjson at "$2" --arg text "$3" \
    '{session_id: $sid, ts: $now, kind: $kind, at: $at, text: $text}' \
    >> "$CROSSD/$sid.jsonl" 2>/dev/null || true
}

if [ "$run_engine" -eq 1 ]; then
  # The sitting clock is wound by prompts and by nothing else -- started
  # here, reset here, and read only under is_prompt below. A Stop or a
  # SubagentStop leaves sitting_start exactly as it found it: those fire on
  # the agent's schedule, not the user's, so a session whose first wired
  # event is a Stop must not start a clock nobody has sat down at.
  #
  # The gap that resets it is the gap between prompts anywhere on the
  # machine, not in this chat: a session left idle for an hour while its
  # neighbour was worked in has not earned a fresh clock, because the person
  # never left the chair.
  if [ "$is_prompt" -eq 1 ]; then
    if [ "$last_prompt" -gt 0 ] \
       && [ $((now_ts - last_prompt)) -gt $((NAG_SIT_GAP_MIN * 60)) ]; then
      sit_start=$now_ts
      time_line=0
    fi
    last_prompt=$now_ts
    [ "$sit_start" -gt 0 ] || sit_start=$now_ts
    tl_sitting=$sit_start
    save_sitting
  fi

  IFS=$'\t' read -r ctx gates fric_total fric_win <<<"$(printf '%s\n' "$metrics" | jq -r \
    --argjson w "$NAG_FRICTION_TURNS" \
    '(.session.user_turns // 0) as $t
     | [ (.session.context_peak // 0),
         (.session.decisions.gate // 0),
         (.session.friction.total // 0),
         ([ .friction[]?
            | select(.type == "correction" or .type == "rebuke")
            | select((.turn_ordinal // 0) > ($t - $w)) ] | length) ] | @tsv')"
  [ -n "${ctx:-}" ] || ctx=0
  [ -n "${gates:-}" ] || gates=0
  [ -n "${fric_total:-}" ] || fric_total=0
  [ -n "${fric_win:-}" ] || fric_win=0

  # FROZEN -- THAW CAREFULLY. See the file header for the rule this tags.
  # context -- lines ascending, so a jump past several of them reports each in
  # order. The ladder is the configured lines, then NAG_CONTEXT_STEP forever
  # past the last one, so a session that blows through every configured line
  # keeps getting a line instead of going quiet. ⛁ repeats once per rung
  # crossed this session (glyphs(); capped at 5, then "(xN)") -- the same
  # escalation as ⚡, keyed off the friction total instead of the rung count.
  # ⚖ stays a plain digit; no rung tracks gate decisions.
  ladder="$NAG_CONTEXT_LINES"
  last_cfg=0
  for L in $NAG_CONTEXT_LINES; do last_cfg=$L; done
  if [ "$NAG_CONTEXT_STEP" -gt 0 ] && [ "$last_cfg" -gt 0 ]; then
    L=$((last_cfg + NAG_CONTEXT_STEP))
    while [ "$ctx" -ge "$L" ]; do
      ladder="$ladder $L"
      L=$((L + NAG_CONTEXT_STEP))
    done
  fi
  # A single invocation can cross several rungs at once (a big tool result
  # landing between prompts, or a subagent's output). Each still gets its own
  # screen line -- "reports each in order" above -- but the model injection
  # is once per *call*, not once per rung: stacking one "already raised" line
  # per rung crossed in the same call would claim a separate earlier occasion
  # for each, when they all just happened now and the model never had a turn
  # in between to act on any of them.
  ctx_stop_before=$ctx_stop_line
  ctx_stop_fired=0
  for L in $ladder; do
    if [ "$ctx" -ge "$L" ] && [ "$L" -gt "$ctx_line" ]; then
      ctx_rungs=$((ctx_rungs + 1))
      if [ "$L" -ge "$NAG_CONTEXT_STOP_AT" ]; then
        verdict="propose stopping"
        ctx_stop_fired=1
        ctx_stop_line=$L
      else
        verdict="still room"
      fi
      fpart=""
      [ "$fric_total" -gt 0 ] && fpart=" $(glyphs "$fric_total" "⚡") $fric_total"
      t="$(glyphs "$ctx_rungs" "⛁") $(kfmt "$ctx")/$(kfmt "$L") ⚖${gates}${fpart} — ${verdict}."
      add_line "$t"; record_crossing context "$L" "$t"
      ctx_line=$L; since_nag=1
    fi
  done
  # Model injection only from the stop threshold up, and only once per call:
  # the first time it ever fires, offer a stopping point; every call after
  # that says plainly the offer already went out and nothing came of it,
  # rather than repeating it verbatim.
  if [ "$ctx_stop_fired" -eq 1 ]; then
    if [ "$ctx_stop_before" -eq 0 ]; then
      add_model "Context at $(kfmt "$ctx") — a stopping point. Consider /wrapup."
    else
      add_model "Context at $(kfmt "$ctx"), past $(kfmt "$ctx_stop_line"). Already raised at $(kfmt "$ctx_stop_before") and not acted on."
    fi
  fi

  # FROZEN -- THAW CAREFULLY.
  # sitting clock -- read on a prompt and nowhere else, so the line lands
  # where the user is already reading, at the top of a turn.
  if [ "$is_prompt" -eq 1 ] && [ "$NAG_SIT_EVERY_MIN" -gt 0 ] \
     && [ "$sit_start" -gt 0 ]; then
    sit_min=$(( (now_ts - sit_start) / 60 ))
    n=$(( sit_min / NAG_SIT_EVERY_MIN * NAG_SIT_EVERY_MIN ))
    if [ "$n" -ge "$NAG_SIT_EVERY_MIN" ] && [ "$n" -gt "$time_line" ]; then
      # Only "stop here" arms the Stop block. "Stand up" is a nudge to leave
      # the chair for five minutes and come back to the same session; making
      # it demand a resume block turned the one-hour mark into a wrap-up
      # every hour. Two hours is the sitting clock's actual verdict.
      if [ "$n" -ge $((NAG_SIT_EVERY_MIN * 2)) ]; then
        verdict="stop here, run /wrapup"; since_nag=1
      else verdict="stand up"; fi
      t="⏱ sitting $(hm "$n") — context $(kfmt "$ctx"): $verdict."
      w=$(work_str); [ -n "$w" ] && t="$t $w"
      add_line "$t"; record_crossing time "$n" "$t"
      time_line=$n
    fi
  fi

  # FROZEN -- THAW CAREFULLY.
  # gate decisions
  if [ "$NAG_GATE_EVERY" -gt 0 ]; then
    n=$(( gates / NAG_GATE_EVERY * NAG_GATE_EVERY ))
    if [ "$n" -ge "$NAG_GATE_EVERY" ] && [ "$n" -gt "$gate_line" ]; then
      t="⚖ $gates gate decisions this session — front-load or card the rest."
      add_line "$t"; record_crossing gate "$n" "$t"
      gate_line=$n
    fi
  fi

  # FROZEN -- THAW CAREFULLY.
  # friction -- measured in human turns, so only a prompt can trip it, and it
  # is addressed to the model, which is the thing the capacity rule asks of.
  if [ "$is_prompt" -eq 1 ] && [ "$fric_tripped" -ne 1 ] \
     && [ "$fric_win" -ge "$NAG_FRICTION_N" ]; then
    fm="$fric_win corrections or rebukes in the last $NAG_FRICTION_TURNS turns. Apply the capacity rule from the standing orders, once."
    add_model "$fm"; record_crossing friction "$fric_win" "$fm"
    fric_tripped=1; since_nag=1
  fi
fi

# ---------------------------------------------------------------- Stop nag
# Fires on a real Stop only -- hook_event_name, not the event argument, so a
# preview or a test harness asking for the `stop` readout never blocks a turn.
#
# "archivable" is the verdict that the chat can be closed without losing
# anything: clean worktree, nothing unpushed, the state repo's own commits
# pushed, and the branch either has an open PR or is named by a pointer card.
_to() { if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi; }
archivable() {
  [ "${dirty:-0}" -eq 0 ] || return 1
  [ "${unpushed:-0}" -eq 0 ] || return 1
  local sr n c
  sr=$(state_repo 2>/dev/null) || sr=""
  if [ -n "$sr" ]; then
    n=$(git -C "$sr" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
    [ "${n:-0}" -eq 0 ] || return 1
  fi
  [ -n "$work_root" ] || return 1
  case "$work_branch" in main|master|HEAD|"") return 0 ;; esac
  if command -v gh >/dev/null 2>&1; then
    c=$( (cd "$work_root" 2>/dev/null \
          && _to 10 gh pr list --head "$work_branch" --state open --json number \
               --jq 'length') 2>/dev/null )
    [ "${c:-0}" -gt 0 ] 2>/dev/null && return 0
  fi
  [ -n "$sr" ] && grep -qF -- "$work_branch" "$sr/state/global/kanban.md" 2>/dev/null \
    && return 0
  return 1
}

# The resume block is a `## Resume` heading in this session's checkpoint
# (stop-continuity.sh names it <date>-<repo>-<sid8>.md; dotfiles#110 defines
# the block). The hook never assumes the block was written because it asked
# for it: it looks, and says what it found either way.
resume_ckpt() {
  grep -lE '^## Resume[[:space:]]*$' \
    "$(state_dir)/log/auto/"*"-${sid:0:8}.md" 2>/dev/null | head -1
}

if [ "$hook_name" = Stop ]; then
  if [ "$nag_pending" -eq 1 ]; then
    # The block above has been answered. Whether the resume block exists is a
    # fact on disk, not an inference from having asked. Either way the nag is
    # spent: a missing block is reported once, never re-blocked on, or this
    # would be the level-triggered nag again.
    nag_pending=0; since_nag=0
    found=$(resume_ckpt)
    if [ -n "$found" ]; then
      resume_ts=$now_ts
      add_line "Archivable. Resume block written $(hhmm "$resume_ts") in $(basename "$found"). Next time: \`/resume\`."
    else
      add_line "Archivable, but no \`## Resume\` block in $(state_dir)/log/auto/*-${sid:0:8}.md. Not asking again this session."
    fi
    save_nag
  elif archivable; then
    local_hour=$(date +%H); local_hour=${local_hour#0}
    late=0
    [ "${local_hour:-0}" -ge "$NAG_STOP_HOUR" ] && late=1
    # since_nag is armed by a context or time crossing and by the friction
    # counter tripping, and disarmed by the nag. The hour arms it once per
    # session -- otherwise every Stop after 22:00 would block again, which is
    # the level-triggered nag this replaced.
    if [ "$since_nag" -eq 1 ] \
       || { [ "$late" -eq 1 ] && [ "$late_nagged" -eq 0 ]; }; then
      [ "$late" -eq 1 ] && late_nagged=1
      nag_pending=1; save_nag
      # The crossing lines that armed this Stop have already been persisted
      # as consumed, so this reason is their only chance to be seen. They go
      # in front of the instruction rather than being dropped.
      reason="Write the resume block: append a \`## Resume\` block (next, link, model, effort) to this session's checkpoint in $(state_dir)/log/auto/."
      [ -z "$sys_lines" ] || reason="$sys_lines
$reason"
      printf '{"decision":"block","reason":%s}\n' "$(json_str "$reason")"
      exit 0
    fi
    # Nothing new to say. Later Stops carry the block's age and nothing else.
    if [ "$resume_ts" -gt 0 ]; then
      add_line "Resume block $(hm $(( (now_ts - resume_ts) / 60 ))) old."
    fi
  fi
fi

[ "$run_engine" -eq 1 ] && save_nag

# The crossing lines reach the user on every wired event; the friction line is
# the one that reaches the model, and only on UserPromptSubmit, where a hook
# can add context at all.
if [ -n "$sys_lines" ] || [ -n "$model_line" ]; then
  if [ "$is_prompt" -eq 1 ]; then
    jq -nc --arg s "$sys_lines" --arg a "$model_line" \
      '(if $s == "" then {} else {systemMessage: $s} end)
       + (if $a == "" then {}
          else {hookSpecificOutput: {hookEventName: "UserPromptSubmit",
                                     additionalContext: $a}} end)'
    exit 0
  fi
fi

# ------------------------------------------------------------ event block
# Shown to the user at the end of a turn -- never sent to the model, so the
# running decision count costs nothing to display. Any crossing line rides on
# the front of it rather than arriving as a second message.
if [ "$SHOW" = show ] && [ -f "$OUT" ]; then
  # night_nag needs Pacific time, not the host's TZ -- an ephemeral/cloud
  # session usually runs UTC, which read as "LATE!" all evening. Compute the
  # US/Pacific UTC offset here (handles PST/PDT) and hand it to jq as seconds,
  # since jq has no timezone database of its own.
  TZOFF=$(TZ="America/Los_Angeles" date +%z | awk '{
    sign = (substr($0,1,1) == "-") ? -1 : 1
    hh = substr($0,2,2) + 0
    mm = substr($0,4,2) + 0
    print sign * (hh * 3600 + mm * 60)
  }')
  export TZOFF
  jq -c -L "$HOOK_DIR" --arg x "$sys_lines" \
    'include "lib-metrics-fmt";
     {systemMessage: (if $x == "" then block else $x + "\n" + block end)}' \
    "$OUT" 2>/dev/null
elif [ -n "$sys_lines" ]; then
  jq -nc --arg s "$sys_lines" '{systemMessage: $s}'
fi
exit 0
