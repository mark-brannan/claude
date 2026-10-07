#!/usr/bin/env bash
# AGENTS MUST read metrics-live-requirements.md before making changes!
#
# Recompute the session's metrics NOW and cache them where the statusline can
# read them without paying for the computation itself.
#
# Why a cache file at all: `session-metrics.jq` slurps the whole transcript,
# which is fine a few times a turn but not on every statusline render (those
# fire several times a second). The statusline just prints what is already on
# disk, and recomputes only past its own staleness age.
#
# Four wirings: UserPromptSubmit, PostToolUse, Stop and SubagentStop.
# UserPromptSubmit renders the block same as the rest (#137) -- high
# frequency is the explicit ask, not a per-event opt-in. It used to be
# wired to nine events,
# eight of them with `show`, and the readout spoke often enough to be tuned
# out -- a level-triggered nag. What replaced it is not a lower frequency but
# the crossing engine below: a line fires once, when a threshold is first
# crossed, and then says nothing until the next line. PostToolUse renders the
# block on every tool call and drives the engine, which is how a context rung
# crossed mid-turn is spoken when it happens rather than at the next prompt.
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
# ⛁ context (» below the first rung; ¢ and ○ were the other candidates),
# ⚡ friction and ⏱ sitting-clock crossings, and any glyph
# family added alongside them) is frozen: do not modify without direct,
# explicit interaction with Solace.
#
# Changes here are small and contained -- one glyph/family at a time. Never
# a wholesale rewrite: don't drop an existing glyph, family, or behavior
# without her explicit call to drop it. That includes cadence: don't make
# the readout appear less often as a "cleanup" -- that is frequency, never
# lines per event (dotfiles#137). She wants this more frequent, not
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
# shellcheck source=metrics-format.sh
. "$HOOK_DIR/metrics-format.sh"

command -v jq >/dev/null 2>&1 || exit 0

EVENT_ARG="${1:-}"          # explicit override; only statusline and tests pass this now
MAX_AGE="${2:-0}"           # seconds; >0 means "skip if cache is fresher"
SHOW="${3:-}"               # "show" -> also print a systemMessage block

# ---------------------------------------------------- counters and their lines
# Every threshold in this file is here, and every one is overridable. A line
# fires once, when the counter first crosses it this session, and then says
# nothing until the next line up -- edge-triggered, not level-triggered.
#
#   context   size and a verdict; the 💸 reason glyph from CONTEXT_STOP_AT up.
#             The line repeats its glyph once per threshold rung crossed this
#             session (capped at 5, then "(xN)"), and the ladder extends past
#             the last configured line by CONTEXT_STEP forever, so it keeps
#             escalating instead of going quiet at the top. At or above
#             CONTEXT_STOP_AT it also reaches the model: once as an offer to
#             stop, and plainly on each further rung, never twice for the
#             same one
#   sitting   elapsed, context, tail, git state -- driven entirely by prompts: it
#             starts at the first one, restarts when the gap between two of
#             them runs past SIT_GAP_MIN (a session picked up after dinner is
#             a new sitting, not a nine-hour one), and is never read or moved
#             by a Stop. Each hour rung prints the elapsed time and one
#             outward-pointing tail (a meal, the sunset, a line from
#             outside.txt), and asks the model to shape a stopping point.
#             A prompt of `stay [minutes]` quiets it until then.
#             The clock itself is machine-wide, not per session -- three open
#             chats are still one chair -- while the line is reported once per
#             session, so each chat says it where its user is reading
#   bedtime   one question per evening, machine-wide, on the first prompt after
#             STOP_HOUR: "what time would you like to go to bed?". A bare clock
#             time is the reply; a warning BED_WARN_MIN before it, the hour
#             itself once, then silence. No reply is an answer: never re-asked
#   friction  corrections and rebukes inside a window of human turns; the one
#             line that goes to the model rather than to the screen, since the
#             standing orders' capacity rule is what it is asking for
#
# There is no decision-count line here, on screen or to the model: the count
# is measured, never alarmed (one-entry-point §5, 2026-09-30). Friction is the
# one alarm. The decisions-per-session-hour ratio is shown at session start and
# in the Stop summary only, never here.
NAG_CONTEXT_LINES="${METRICS_CONTEXT_LINES:-60000 90000 120000 150000 185000}"
NAG_CONTEXT_STOP_AT="${METRICS_CONTEXT_STOP_AT:-150000}"
NAG_CONTEXT_STEP="${METRICS_CONTEXT_STEP:-35000}"
NAG_SIT_EVERY_MIN="${METRICS_SIT_EVERY_MIN:-60}"
NAG_SIT_GAP_MIN="${METRICS_SIT_GAP_MIN:-15}"
# Sitting rungs from here up draw ⏰ instead of ⏱️/🌙. 3 = past 90 min.
NAG_SIT_HOT_RUNG="${METRICS_SIT_HOT_RUNG:-3}"
# The sitting line's tail, picked by the clock first and the list second.
# Meal windows are local hours, start inclusive, end exclusive; "" disables.
NAG_MEAL_WINDOWS="${METRICS_MEAL_WINDOWS-12-14 18-20}"
NAG_SUN_AFTER_HOUR="${METRICS_SUN_AFTER_HOUR:-13}"
NAG_STAY_DEFAULT_MIN="${METRICS_STAY_DEFAULT_MIN:-30}"
NAG_FRICTION_N="${METRICS_FRICTION_N:-3}"
NAG_FRICTION_TURNS="${METRICS_FRICTION_TURNS:-20}"
# Model-facing ladders. Separate from the screen ladders above: the screen
# line is a glance, the injection is an instruction, and they escalate on
# different numbers. Edge-triggered, the same as the screen lines: one
# injection per rung crossed, and silence on the prompts in between.
NAG_MODEL_CONTEXT_LINES="${METRICS_MODEL_CONTEXT_LINES:-105000 125000 175000 200000}"
NAG_MODEL_CONTEXT_STEP="${METRICS_MODEL_CONTEXT_STEP:-50000}"
# Tool calls of silence after a context rung was raised and not acted on,
# before the line is said again. The one deliberate repeat in the engine:
# context is the only counter that climbs while the model works rather than
# between prompts, so a rung crossed mid-turn would otherwise go unsaid until
# the next prompt -- which may be thousands of tokens later. 0 disables it.
NAG_MODEL_CONTEXT_REPEAT="${METRICS_MODEL_CONTEXT_REPEAT:-20}"
# The day counter below keeps counting across sessions since the last break
# (#301); nothing reads it for a nudge. The gap that starts a fresh day is its
# own knob, distinct from the 15-minute sitting gap.
NAG_DECISION_GAP_MIN="${METRICS_DECISION_GAP_MIN:-180}"
# Local hour from which a Stop on an archivable session is worth interrupting,
# and the hour night ends. The block's night glyph reads the same two, so
# "when is it night" is one pair of knobs and the tests can force either side.
NAG_STOP_HOUR="${METRICS_STOP_HOUR:-22}"
NAG_NIGHT_END_HOUR="${METRICS_NIGHT_END_HOUR:-5}"
# Minutes before the named bedtime that the warning lands.
NAG_BED_WARN_MIN="${METRICS_BED_WARN_MIN:-5}"

# One jq for all three fields: the statusline reaches this code on every
# render, and three spawns before the staleness check was most of its cost.
input=$(cat 2>/dev/null || echo '{}')
IFS=$'\t' read -r tp sid cwd hook_name prompt_text <<<"$(printf '%s' "$input" | jq -r \
  '[(.transcript_path // ""), (.session_id // ""),
    (.cwd // .workspace.current_dir // ""),
    (.hook_event_name // ""),
    (.prompt // "")] | @tsv')"
[ -n "$tp" ] && [ -f "$tp" ] && [ -n "$sid" ] || exit 0
[ -n "$cwd" ] || cwd=$PWD

# Default EVENT to hook_event_name verbatim, lowercased, so a new hook
# needs no matching entry here.
if [ -n "$EVENT_ARG" ]; then
  EVENT="$EVENT_ARG"
else
  EVENT=$(printf '%s' "${hook_name:-tool}" | tr '[:upper:]' '[:lower:]')
fi

# statusline reaches this code several times a second and is not a hook
# event Claude Code will render a systemMessage for -- SHOW stays cleared
# there. UserPromptSubmit renders the block like every other wired event
# now (#137): high frequency was the explicit ask, not a per-event opt-in.
case "$EVENT" in statusline) SHOW="" ;; esac

# HUMAN NOTE: The statement "the jq pass is too expensive" is categorically wrong.
# Do not consider jq passes to be "too expensive" even if the code is suboptimal;
# compute over text processing is dirt cheap...the only real cost is tokens.
# A git event means an actual git-state change, not every Bash call: the jq
# pass is too expensive to run after `ls` (wrong - FIXME). The set is git_event_re in
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
OUT=$(state_shard_path "$LIVE" "$sid.json" "$sid")

# Throttle: the statusline asks constantly, events ask rarely. An event
# always recomputes; the statusline only does so if the cache has gone stale.
if [ "$MAX_AGE" -gt 0 ] && [ -f "$OUT" ]; then
  age=$(( $(date +%s) - $(stat -c %Y "$OUT" 2>/dev/null || stat -f %m "$OUT" 2>/dev/null || echo 0) ))
  [ "$age" -lt "$MAX_AGE" ] && exit 0
fi

# METRICS_NOW pins the engine's clock to an epoch, for tests (the cache-age
# check and the local_hour and pac_hour reads stay on the real clock): the
# bedtime arms compare minute-rounded times against it, so a test that reads
# the real clock is red at some minutes of the hour and green at others.
# Only a plain integer is taken: the value feeds shell arithmetic.
now_ts=${METRICS_NOW:-}
case "$now_ts" in ''|*[!0-9]*) now_ts=$(date +%s) ;; esac
now_ts=$((10#$now_ts))
now=$(date -u -d "@$now_ts" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -r "$now_ts" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
  || date -u +%Y-%m-%dT%H:%M:%SZ)
work_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || echo "")
work_repo=$([ -n "$work_root" ] && basename "$work_root" || basename "$cwd")
work_branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

metrics=$(jq -s \
  --arg sid "$sid" --arg repo "$work_repo" --arg branch "$work_branch" \
  --arg cwd "$cwd" --arg now "$now" \
  -f "$JQPROG" "$tp" 2>/dev/null) || exit 0
[ -n "$metrics" ] || exit 0

# Git state, the part that decides whether the chat is safe to kill.
dirty=0; unpushed=0; no_upstream=0; ncommits=0; start_sha=""
if [ -n "$work_root" ]; then
  dirty=$(git -C "$work_root" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  # Whether this branch holds work that exists nowhere else. lib-state.sh
  # owns the answer, carve-outs and all, so this hook and stop-continuity.sh
  # cannot disagree about it (#149).
  ust=$(unpushed_state "$work_root" "$work_branch")
  case "$ust" in
    'ahead '*)    unpushed=${ust#ahead } ;;
    never-pushed) no_upstream=1 ;;
  esac
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

mkdir -p "${OUT%/*}" 2>/dev/null || exit 0

# Wall clock, read once. The sitting clock in the engine below is the only
# thing that reads it, and only a prompt moves that clock.
#
# There used to be a second timer here, backed by metrics/last_activity.json:
# every event stamped it, including every statusline render, so the readout
# kept its own break timer alive simply by being drawn. A clock the display
# winds is not measuring the user. It is gone, and with it break_nag in
# lib-metrics-fmt.jq -- the sitting clock is the only sitting clock now.
merged=$(printf '%s\n' "$metrics" | jq -c \
  --arg ev "$EVENT" --arg now "$now" \
  --argjson d "${dirty:-0}" --argjson u "${unpushed:-0}" --argjson c "${ncommits:-0}" \
  --arg sha "$start_sha" \
  '.session + {last_event: $ev, updated_at: $now, start_sha: $sha,
               dirty: $d, unpushed: $u, commits: $c}' 2>/dev/null)

tmp="$OUT.$$"
if [ -n "$merged" ]; then
  printf '%s\n' "$merged" > "$tmp" 2>/dev/null \
    && mv -f "$tmp" "$OUT" 2>/dev/null || rm -f "$tmp" 2>/dev/null
fi

# =========================================================== crossing engine
# Edge-triggered. State lives in one small file per session next to the cache;
# it is NOT the cache, because stop-continuity.sh deletes the cache at the end
# of a session and the crossings have to outlive it.
NAGF=$(state_shard_path "$LIVE" "$sid.nag.json" "$sid")
CROSSD="$(state_dir)/metrics/crossings"
CROSSF=$(state_shard_path "$CROSSD" "$sid.jsonl" "$sid")
# state_lock installs no trap of its own (a caller's is easily clobbered);
# this one covers every save_nag write below and every exit path, including
# the Stop `block` decision's early `exit 0`.
trap 'state_unlock' EXIT TERM INT

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

# bed_asked_eve is the local date of the evening the bedtime question was
# put (one ask per evening, machine-wide); bed_at the epoch it was answered
# with, 0 until then. Both live here because the person is one per machine.
sit_start=0; last_prompt=0; quiet_until=0; bed_asked_eve=""; bed_at=0
if [ -f "$SITF" ]; then
  IFS=$'\t' read -r sit_start last_prompt quiet_until bed_asked_eve bed_at \
    <<<"$(jq -r '[(.sitting_start // 0), (.last_prompt // 0), (.quiet_until // 0),
                  (.bed_asked_eve // ""), (.bed_at // 0)] | @tsv' "$SITF" 2>/dev/null)"
fi
[ -n "$sit_start" ] || sit_start=0
[ -n "$last_prompt" ] || last_prompt=0
[ -n "$quiet_until" ] || quiet_until=0
[ -n "$bed_at" ] || bed_at=0

save_sitting() {
  mkdir -p "$(dirname "$SITF")" 2>/dev/null || return 0
  # Debug fields only -- nothing here is read by the clock itself. They
  # exist so a wrong-looking readout can be diagnosed without re-deriving
  # sid/cwd/branch by hand: which session last wound the clock, from where,
  # and what local wall time that was. worktree_slug isn't computed yet at
  # this point in the file (that happens near the archival block below), so
  # it's derived inline from work_root the same way that block does.
  local last_local last_slug last_ckpt
  last_local=$(TZ="America/Los_Angeles" date -d "@$last_prompt" +"%Y-%m-%d %H:%M %Z" 2>/dev/null \
    || TZ="America/Los_Angeles" date -r "$last_prompt" +"%Y-%m-%d %H:%M %Z" 2>/dev/null || echo "")
  case "$work_root" in
    */.claude/worktrees/*) last_slug=$(basename "$work_root") ;;
    *) last_slug="" ;;
  esac
  last_ckpt="$(date -u -d "@$last_prompt" +%Y-%m-%d 2>/dev/null \
    || date -u -r "$last_prompt" +%Y-%m-%d 2>/dev/null)-${work_repo}-${sid:0:8}.md"
  # Preview only, not the full prompt -- enough to recognize which turn wound
  # the clock without keeping a growing transcript excerpt in a machine-wide
  # file that gets read constantly.
  jq -n --argjson ss "$sit_start" --argjson lp "$last_prompt" --argjson qu "$quiet_until" \
    --arg be "$bed_asked_eve" --argjson ba "$bed_at" \
    --arg local "$last_local" --arg sid "$sid" --arg repo "$work_repo" \
    --arg branch "$work_branch" --arg slug "$last_slug" --arg ckpt "$last_ckpt" \
    --arg cwd "$cwd" --arg prompt "${prompt_text:-}" \
    '{sitting_start: $ss, last_prompt: $lp, quiet_until: $qu,
      bed_asked_eve: $be, bed_at: $ba,
      last_prompt_local: $local, last_session_id: $sid, last_repo: $repo,
      last_branch: $branch, last_worktree_slug: $slug, last_checkpoint: $ckpt,
      last_cwd: $cwd, last_prompt_preview: ($prompt[0:80])}' \
    > "$SITF.$$" 2>/dev/null \
    && mv -f "$SITF.$$" "$SITF" 2>/dev/null || rm -f "$SITF.$$" 2>/dev/null
}

# time_line stays per session: the clock is shared, but the report of it is
# each session's own, so a threshold is spoken once in every chat that is
# open when it is crossed rather than once on the machine. tl_sitting is the
# sitting_start that time_line was recorded against -- when the shared clock
# restarts, every session's line is stale, including the ones that were not
# the prompt that restarted it, and they must be free to speak again.
ctx_line=0; ctx_rungs=0; ctx_stop_line=0; time_line=0; tl_sitting=0; fric_tripped=0
since_nag=0; resume_ts=0; nag_pending=0; late_nagged=0
m_ctx_at=0; m_sit_at=0; m_sit_said=0; m_ctx_tools=0
bed_warn_at=0; bed_past_at=0
if [ -f "$NAGF" ]; then
  IFS=$'\t' read -r bed_warn_at bed_past_at \
    <<<"$(jq -r '[(.bed_warn_at // 0), (.bed_past_at // 0)] | @tsv' "$NAGF" 2>/dev/null)"
  [ -n "$bed_warn_at" ] || bed_warn_at=0
  [ -n "$bed_past_at" ] || bed_past_at=0
  IFS=$'\t' read -r ctx_line ctx_rungs ctx_stop_line time_line tl_sitting fric_tripped \
                    since_nag resume_ts nag_pending late_nagged m_ctx_at m_sit_at m_sit_said \
                    m_ctx_tools \
    <<<"$(jq -r '[(.context_line // 0), (.context_rungs // 0), (.context_stop_line // 0),
                  (.time_line // 0), (.time_line_sitting // -1),
                  (if .friction_tripped then 1 else 0 end),
                  (if .since_nag then 1 else 0 end),
                  (.resume_ts // 0),
                  (if .nag_pending then 1 else 0 end),
                  (if .late_nagged then 1 else 0 end),
                  (.model_context_at // 0), (.model_sitting_at // 0),
                  (.model_sitting_said // .model_sitting_at // 0),
                  (.model_context_tools // 0)] | @tsv' "$NAGF" 2>/dev/null)"
fi
for v in ctx_line ctx_rungs ctx_stop_line time_line tl_sitting fric_tripped \
         since_nag resume_ts nag_pending late_nagged m_ctx_at m_sit_at m_sit_said \
         m_ctx_tools; do
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
  # Never blocks the hook: a lock already held by a concurrent invocation
  # of this same session (dotfiles#161 findings 1/2/4) just skips this
  # write rather than waiting or failing the hook.
  state_lock "$LIVE/$sid.lock" || return 0
  # Its own shard dir: the live cache may still sit at the flat path.
  mkdir -p "${NAGF%/*}" 2>/dev/null
  jq -n --argjson cl "$ctx_line" --argjson cr "$ctx_rungs" --argjson cs "$ctx_stop_line" \
        --argjson tl "$time_line" --argjson ts "$tl_sitting" \
        --argjson ft "$fric_tripped" \
        --argjson sn "$since_nag" --argjson rt "$resume_ts" --argjson np "$nag_pending" \
        --argjson ln "$late_nagged" \
        --argjson mc "$m_ctx_at" --argjson ms "$m_sit_at" \
        --argjson mss "$m_sit_said" \
        --argjson mct "$m_ctx_tools" \
        --argjson bw "$bed_warn_at" --argjson bp "$bed_past_at" \
    '{context_line: $cl, context_rungs: $cr, context_stop_line: $cs,
      time_line: $tl, time_line_sitting: $ts,
      friction_tripped: ($ft == 1),
      since_nag: ($sn == 1), resume_ts: $rt, nag_pending: ($np == 1),
      late_nagged: ($ln == 1),
      model_context_at: $mc, model_sitting_at: $ms,
      model_sitting_said: $mss,
      model_context_tools: $mct,
      bed_warn_at: $bw, bed_past_at: $bp}' \
    > "$NAGF.$$" 2>/dev/null \
    && mv -f "$NAGF.$$" "$NAGF" 2>/dev/null || rm -f "$NAGF.$$" 2>/dev/null
  state_unlock
}

# Only the four wired events drive the engine. The statusline reaches this
# file too, several times a minute, and must never consume a crossing.
#
# can_inject is narrower than run_engine and wider than is_prompt: it is the
# set of events where Claude Code accepts hookSpecificOutput.additionalContext
# at all. UserPromptSubmit and PostToolUse do; Stop and SubagentStop do not,
# and a Stop says its piece through the block's reason instead.
#
# is_prompt stays the gate for anything wound by the user's own rhythm -- the
# sitting clock, decision load. Those are counted between prompts and must not
# advance because a tool ran.
is_prompt=0; run_engine=0; can_inject=0
case "$EVENT" in
  prompt|userpromptsubmit)   is_prompt=1; run_engine=1; can_inject=1 ;;
  posttooluse)               run_engine=1; can_inject=1 ;;
  stop|subagentstop)         run_engine=1 ;;
esac

# The hookEventName a hookSpecificOutput must carry back. It has to match the
# event Claude Code dispatched, not the argument the statusline or a test
# passed, or the injection is discarded silently.
inject_event="UserPromptSubmit"
[ "$EVENT" = posttooluse ] && inject_event="PostToolUse"

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

fib_rungs() {
  local total="$1" n=0 L
  for L in 1 2 3 5 8; do [ "$total" -ge "$L" ] && n=$((n + 1)); done
  printf '%s' "$n"
}

time_rungs() {
  local total="$1" n=0 L
  for L in 25 47 62 90 120; do [ "$total" -ge "$L" ] && n=$((n + 1)); done
  printf '%s' "$n"
}

# $1 ladder, $2 step, $3 value -- the highest rung at or below the value, or
# 0 if it is under the first one. The ladder extends by $2 past its last
# configured rung forever, the same shape as the screen context ladder.
rung_of() {
  local v="$3" hit=0 L last=0
  for L in $1; do [ "$v" -ge "$L" ] && hit=$L; last=$L; done
  if [ "$2" -gt 0 ] && [ "$last" -gt 0 ] && [ "$v" -ge "$last" ]; then
    L=$((last + $2))
    while [ "$v" -ge "$L" ]; do hit=$L; L=$((L + $2)); done
  fi
  printf '%s' "$hit"
}

# Git state folded into a nag line -- the same shorthand as lib-metrics-fmt.jq's
# `work`, but the crossing lines run in bash, not jq. Empty on a clean tree.
work_str() {
  [ "${ncommits:-0}" -gt 0 ] || [ "${dirty:-0}" -gt 0 ] || [ "${unpushed:-0}" -gt 0 ] \
    || [ "${no_upstream:-0}" -gt 0 ] || return 0
  local s="⎇ "
  [ "${ncommits:-0}" -gt 0 ] && s="${s}${ncommits}c"
  [ "${dirty:-0}" -gt 0 ]    && s="${s}${dirty}~"
  if [ "${no_upstream:-0}" -gt 0 ]; then s="${s}no-upstream"
  elif [ "${unpushed:-0}" -gt 0 ]; then s="${s}${unpushed}↑"; fi
  printf '%s' "$s"
}

# Minutes until today's sunset at location.json's lat/lon, or nothing when
# the file is missing or unfilled, or the sun is already down. NOAA's
# sunrise equation, solved for the solar noon nearest now.
sunset_min() {
  local lat lon
  IFS=$'\t' read -r lat lon <<<"$(jq -r '[(.lat // ""), (.lon // "")] | @tsv' \
    "$(state_dir)/location.json" 2>/dev/null)"
  [ -n "$lat" ] && [ -n "$lon" ] || return 0
  awk -v now="$now_ts" -v lat="$lat" -v lon="$lon" 'BEGIN {
    r = atan2(0, -1) / 180
    jd = now / 86400 + 2440587.5
    n = int(jd - 2451545.0009 + lon / 360 + 0.5)
    js = 2451545.0009 - lon / 360 + n
    m = (357.5291 + 0.98560028 * (js - 2451545)) % 360
    c = 1.9148 * sin(m*r) + 0.02 * sin(2*m*r) + 0.0003 * sin(3*m*r)
    l = (m + c + 282.9372) % 360
    jt = js + 0.0053 * sin(m*r) - 0.0069 * sin(2*l*r)
    sd = sin(l*r) * sin(23.4397*r)
    cd = sqrt(1 - sd * sd)
    cw = (sin(-0.833*r) - sin(lat*r) * sd) / (cos(lat*r) * cd)
    if (cw < -1 || cw > 1) exit
    w = atan2(sqrt(1 - cw * cw), cw) / r
    left = int(((jt + w / 360 - 2440587.5) * 86400 - now) / 60)
    if (left > 0) print left
  }'
}

# The bedtime clock's zone: location.json's tz, else Pacific.
local_tz() {
  local tz
  tz=$(jq -r '.tz // ""' "$(state_dir)/location.json" 2>/dev/null)
  printf '%s' "${tz:-America/Los_Angeles}"
}
lhhmm() {  # lhhmm <epoch> -- HH:MM on the local (bedtime) clock
  TZ="$LTZ" date -d "@$1" +%H:%M 2>/dev/null || TZ="$LTZ" date -r "$1" +%H:%M 2>/dev/null || echo "??:??"
}
# The epoch of the next time the local clock reads h:mm, read the way a
# person says it at night: "11" is 23:00, "1" is 01:00, "12:30" is 00:30.
# Every candidate (h, h+12 below noon, 0 for 12) today and tomorrow is
# tried and the earliest one still ahead wins. Built from local midnight by
# arithmetic, so a DST change between now and then is off by the hour.
bed_resolve() {  # bed_resolve <hour> <minute>
  local h=$1 m=$2 hh c best=0 cands
  cands="$h"
  [ "$h" -lt 12 ] && cands="$cands $((h + 12))"
  [ "$h" -eq 12 ] && cands="$cands 0"
  for hh in $cands; do
    for c in $((l_midnight + hh * 3600 + m * 60)) $((l_midnight + 86400 + hh * 3600 + m * 60)); do
      if [ "$c" -gt "$now_ts" ] && { [ "$best" -eq 0 ] || [ "$c" -lt "$best" ]; }; then best=$c; fi
    done
  done
  printf '%s' "$best"
}

# The sitting line's tail: outward, never an instruction. Clock first (a
# meal window, then the daylight left), the list second.
sit_tail() {
  local h w lo hi left
  h=$(date -d "@$now_ts" +%H 2>/dev/null || date -r "$now_ts" +%H); h=$((10#$h))
  for w in $NAG_MEAL_WINDOWS; do
    lo=${w%-*}; hi=${w#*-}
    if [ "$h" -ge "$lo" ] && [ "$h" -lt "$hi" ]; then
      printf 'what did you eat today?'; return 0
    fi
  done
  if [ "$h" -ge "$NAG_SUN_AFTER_HOUR" ]; then
    left=$(sunset_min)
    if [ -n "$left" ]; then
      if [ "$left" -ge 60 ]; then
        printf 'sun sets in %dh %02d' $((left / 60)) $((left % 60))
      else
        printf 'sun sets in %d min' "$left"
      fi
      return 0
    fi
  fi
  local lines=()
  mapfile -t lines < <(grep -v '^[[:space:]]*$' "$(state_dir)/outside.txt" 2>/dev/null)
  [ "${#lines[@]}" -gt 0 ] && printf '%s' "${lines[RANDOM % ${#lines[@]}]}"
  return 0
}

sys_lines=""; model_line=""; arch_lines=""
add_line()  { sys_lines="${sys_lines:+$sys_lines
}$1"; }
add_model() { model_line="${model_line:+$model_line
}$1"; }
# Stop's archival verdict (📦 and what follows it) prints last, after the
# block -- a separate bucket from the crossing nags above, which print first.
add_arch()  { arch_lines="${arch_lines:+$arch_lines
}$1"; }
record_crossing() {
  mkdir -p "${CROSSF%/*}" 2>/dev/null || return 0
  jq -nc --arg sid "$sid" --arg now "$now" --arg kind "$1" \
         --argjson at "$2" --arg text "$3" \
    '{session_id: $sid, ts: $now, kind: $kind, at: $at, text: $text}' \
    >> "$CROSSF" 2>/dev/null || true
}

# `stay` or `stay <minutes>` and nothing else (any case, optional leading
# slash, trailing punctuation): the user's answer to a sitting rung.
is_stay() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]' \
    | grep -Eq '^[[:space:]]*/?stay([[:space:]]+[0-9]+m?)?[[:punct:][:space:]]*$'
}

# What followed each ⏱ crossing, stamped once at the session's next prompt:
# minutes to it, whether it was a `stay`, whether the gap ran past the sitting
# gap. Runs before the engine can record a crossing, so the crossing's own
# prompt never stamps it. Measured only; nothing here speaks.
stamp_time_after() {
  local f="$CROSSF" stay=false sm out
  [ -f "$f" ] || return 0
  is_stay "${prompt_text:-}" && { stay=true; sm=$(printf '%s' "$prompt_text" | tr -cd 0-9); }
  out=$(jq -sc --argjson now "$now_ts" --arg ts "$now" --argjson stay "$stay" \
               --argjson sm "${sm:-null}" \
               --argjson gap "$((NAG_SIT_GAP_MIN * 60))" \
    '[.[] | select(.kind == "time_after") | .crossing_ts] as $done
     | .[] | select(.kind == "time") | .ts as $c
     | select(any($done[]; . == $c) | not)
     | ($now - ($c | fromdateiso8601)) as $s
     | {session_id, ts: $ts, kind: "time_after", at, crossing_ts: $c,
        min: ($s / 60 | floor), stay: $stay, stay_min: $sm, quiet: ($s > $gap)}' \
    "$f" 2>/dev/null) || return 0
  [ -n "$out" ] && printf '%s\n' "$out" >> "$f" 2>/dev/null
  return 0
}

# <files> | stamp_time_last <final prompt> <sitting start>: minutes from each of
# the sitting's crossings to its final prompt, and whether a `stay <n>` was overrun.
# Stamped on Stop and at the next sitting start when changed; the latest one counts.
stamp_time_last() {
  local fin=$1 ss=$2 f out
  while IFS= read -r f; do
    out=$(jq -sc --argjson fin "$fin" --argjson ss "$ss" --arg ts "$now" \
      '(map(select(.kind == "time_last")) | INDEX(.crossing_ts)) as $last
       | (map(select(.kind == "time_after")) | INDEX(.crossing_ts)) as $aft
       | .[] | select(.kind == "time") | .ts as $c | ($c | fromdateiso8601) as $cs
       | select($cs >= $ss and $cs <= $fin) | $aft[$c] as $a
       | {session_id, ts: $ts, kind: "time_last", at, crossing_ts: $c,
          min_to_last: (($fin - $cs) / 60 | floor), overrun: (if $a.stay_min == null
            then null else $fin > ($a.ts | fromdateiso8601) + $a.stay_min * 60 end)}
       | select([$last[$c] | .min_to_last, .overrun] != [.min_to_last, .overrun])' \
      "$f" 2>/dev/null) || continue
    [ -n "$out" ] && printf '%s\n' "$out" >> "$f" 2>/dev/null
  done
}

# Human nags (sitting, friction) gate on this; machine nags (context,
# decisions) do not -- a context ceiling is a real limit, while a sitting
# clock is answered by landing the work. Memoized; can shell out to `gh`.
in_flight() {
  [ -n "${in_flight_memo+x}" ] || in_flight_memo=$([ -n "$work_root" ] \
    && archivable_reasons "$work_root" "$work_branch" "$sid")
  [ -n "$in_flight_memo" ]
}

if [ "$run_engine" -eq 1 ]; then
  # The local clock the bedtime reads: hour, midnight and the evening's date.
  # An hour before NAG_NIGHT_END_HOUR still belongs to last night's evening.
  LTZ=$(local_tz)
  IFS=$'\t' read -r l_h l_m l_s l_date <<<"$(TZ="$LTZ" date -d "@$now_ts" $'+%H\t%M\t%S\t%Y-%m-%d' 2>/dev/null \
    || TZ="$LTZ" date -r "$now_ts" $'+%H\t%M\t%S\t%Y-%m-%d' 2>/dev/null)"
  l_h=$((10#${l_h:-0})); l_m=$((10#${l_m:-0})); l_s=$((10#${l_s:-0}))
  l_midnight=$((now_ts - l_h * 3600 - l_m * 60 - l_s))
  bed_night=0
  { [ "$l_h" -ge "$NAG_STOP_HOUR" ] || [ "$l_h" -lt "$NAG_NIGHT_END_HOUR" ]; } && bed_night=1
  l_eve=$l_date
  [ "$l_h" -lt "$NAG_NIGHT_END_HOUR" ] && l_eve=$(TZ="$LTZ" date -d "@$((now_ts - 86400))" +%Y-%m-%d 2>/dev/null \
    || TZ="$LTZ" date -r "$((now_ts - 86400))" +%Y-%m-%d 2>/dev/null)

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
    stamp_time_after
    if [ "$last_prompt" -gt 0 ] \
       && [ $((now_ts - last_prompt)) -gt $((NAG_SIT_GAP_MIN * 60)) ]; then
      find "$CROSSD" -type f -mmin -$(( (now_ts - sit_start) / 60 + 1 )) 2>/dev/null \
        | stamp_time_last "$last_prompt" "$sit_start"
      sit_start=$now_ts
      time_line=0
    fi
    last_prompt=$now_ts
    [ "$sit_start" -gt 0 ] || sit_start=$now_ts
    tl_sitting=$sit_start
    # The stay valve: `stay` or `stay <minutes>`, exactly, quiets the
    # sitting line and its injection until then. Machine-wide, like the clock.
    if [[ "$prompt_text" =~ ^[[:space:]]*stay([[:space:]]+([0-9]+))?[[:space:]]*$ ]]; then
      stay_min=$NAG_STAY_DEFAULT_MIN
      [ -n "${BASH_REMATCH[2]}" ] && stay_min=$((10#${BASH_REMATCH[2]}))
      quiet_until=$((now_ts + stay_min * 60))
      sit_min=$(( (now_ts - sit_start) / 60 ))
      t="⏱ $(hm "$sit_min") · staying $stay_min, quiet until $(hm $((sit_min + stay_min)))"
      add_line "$t"; record_crossing stay "$stay_min" "$t"
      add_model "The user said stay: acknowledge in one line, nothing else."
    fi
    # Bedtime (Solace, 2026-10-01). The question goes on screen once per
    # evening, machine-wide, on the first prompt after the night hour, and
    # is never repeated: no answer is an answer. A bare clock time typed
    # after it -- and nothing else -- is the reply, any number of times.
    if [ -n "$bed_asked_eve" ] && [ "$bed_asked_eve" = "$l_eve" ] \
       && [[ "$prompt_text" =~ ^[[:space:]]*([0-9]{1,2})(:([0-9]{2}))?[[:space:]]*$ ]] \
       && [ "$((10#${BASH_REMATCH[1]}))" -le 23 ] && [ "$((10#${BASH_REMATCH[3]:-0}))" -le 59 ]; then
      bed_at=$(bed_resolve "$((10#${BASH_REMATCH[1]}))" "$((10#${BASH_REMATCH[3]:-0}))")
      t="bed at $(lhhmm "$bed_at") noted"
      add_line "$t"; record_crossing bed_set "$bed_at" "$t"
      add_model "The user named a bedtime, $(lhhmm "$bed_at"): acknowledge in one line, nothing else."
    elif [ "$bed_night" -eq 1 ] && [ "$bed_asked_eve" != "$l_eve" ]; then
      bed_asked_eve=$l_eve; bed_at=0
      t="what time would you like to go to bed?"
      add_line "$t"; record_crossing bed_ask 0 "$t"
    fi
    save_sitting
  elif [ "$EVENT" = stop ]; then echo "$CROSSF" | stamp_time_last "$last_prompt" "$sit_start"
  fi
  sit_quiet=0; [ "$quiet_until" -gt "$now_ts" ] && sit_quiet=1

  IFS=$'\t' read -r ctx decisions fric_total fric_win <<<"$(printf '%s\n' "$metrics" | jq -r \
    --argjson w "$NAG_FRICTION_TURNS" \
    '(.session.user_turns // 0) as $t
     | [ (.session.context_peak // 0),
         (.session.decisions.total // 0),
         (.session.friction.total // 0),
         ([ .friction[]?
            | select(.type == "correction" or .type == "rebuke")
            | select((.turn_ordinal // 0) > ($t - $w)) ] | length) ] | @tsv')"
  [ -n "${ctx:-}" ] || ctx=0
  [ -n "${decisions:-}" ] || decisions=0
  [ -n "${fric_total:-}" ] || fric_total=0
  [ -n "${fric_win:-}" ] || fric_win=0

  # FROZEN -- THAW CAREFULLY. See the file header for the rule this tags.
  # context -- lines ascending, so a jump past several of them reports each in
  # order. The ladder is the configured lines, then NAG_CONTEXT_STEP forever
  # past the last one, so a session that blows through every configured line
  # keeps counting instead of going quiet. The rung count reaches the screen
  # only through the block's ⛁ cluster; the rung value never does.
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
  # landing between prompts, or a subagent's output). Each is counted, none
  # is spoken: one notice per event, and that notice is the block. The model
  # injection below is one line per crossing of its own ladder, however many
  # rungs went by here.
  for L in $ladder; do
    if [ "$ctx" -ge "$L" ] && [ "$L" -gt "$ctx_line" ]; then
      ctx_rungs=$((ctx_rungs + 1))
      [ "$L" -ge "$NAG_CONTEXT_STOP_AT" ] && ctx_stop_line=$L
      record_crossing context "$L" ""
      ctx_line=$L; since_nag=1
    fi
  done
  # Model injection rides its own ladder, edge-triggered like everything
  # else here: once per rung, on the event that crossed it, and nothing on
  # the events after (dotfiles#282 -- a line repeated with no new number in
  # it is the level-triggered nag the engine exists to replace). The first
  # one offers a stopping point; a later rung names the one already spoken,
  # which is new information because the number has moved.
  #
  # It runs on can_inject, not is_prompt: context is the one counter that
  # climbs while the model works, and a rung crossed by a large tool result
  # mid-turn is exactly the moment worth saying so. Waiting for the next
  # prompt means saying it tens of thousands of tokens late, or never, in a
  # turn that runs long enough to hit the ceiling on its own.
  if [ "$can_inject" -eq 1 ]; then
    r=$(rung_of "$NAG_MODEL_CONTEXT_LINES" "$NAG_MODEL_CONTEXT_STEP" "$ctx")
    if [ "$r" -gt "$m_ctx_at" ]; then
      if [ "$m_ctx_at" -eq 0 ]; then
        add_model "Context at $(kfmt "$ctx"), past $(kfmt "$r"): a stopping point is due."
      else
        add_model "Context at $(kfmt "$ctx"), past $(kfmt "$r") (last offered at $(kfmt "$m_ctx_at"))."
      fi
      m_ctx_at=$r; m_ctx_tools=0
    elif [ "$EVENT" = posttooluse ] && [ "$m_ctx_at" -gt 0 ] \
         && [ "$NAG_MODEL_CONTEXT_REPEAT" -gt 0 ]; then
      # The one repeat in the engine, and it is deliberate. A rung raised
      # and not acted on goes quiet for NAG_MODEL_CONTEXT_REPEAT tool calls
      # and then says so again, with the tool count as the new number -- a
      # long autonomous run can burn a whole rung's worth of context without
      # ever reaching a prompt, and silence there reads as permission.
      # Counted in tool calls, not prompts: tool calls are what is spending
      # the context during the stretch this arm exists to cover.
      m_ctx_tools=$((m_ctx_tools + 1))
      if [ "$m_ctx_tools" -ge "$NAG_MODEL_CONTEXT_REPEAT" ]; then
        add_model "Context at $(kfmt "$ctx"), past $(kfmt "$m_ctx_at") for $m_ctx_tools tool calls: a stopping point is due."
        m_ctx_tools=0
      fi
    fi
  fi

  # FROZEN -- THAW CAREFULLY.
  # sitting clock -- read on a prompt and nowhere else, so the line lands
  # where the user is already reading, at the top of a turn. Elapsed time and
  # an outward tail, no verdict: an instruction on screen is one more thing
  # to argue with from the chair. Quiet after `stay` leaves the rung unspent,
  # so it is said on the first prompt after the quiet ends.
  if [ "$is_prompt" -eq 1 ] && [ "$NAG_SIT_EVERY_MIN" -gt 0 ] \
     && [ "$sit_start" -gt 0 ] && [ "$sit_quiet" -eq 0 ]; then
    sit_min=$(( (now_ts - sit_start) / 60 ))
    n=$(( sit_min / NAG_SIT_EVERY_MIN * NAG_SIT_EVERY_MIN ))
    if [ "$n" -ge "$NAG_SIT_EVERY_MIN" ] && [ "$n" -gt "$time_line" ]; then
      # Two hours arms the Stop block's hand-off, unless work is in flight:
      # landing it comes first, and the injection below already says so.
      if [ "$n" -ge $((NAG_SIT_EVERY_MIN * 2)) ] && ! in_flight; then since_nag=1; fi
      t="⏱ $(hm "$sit_min") · context $(kfmt "$ctx")"
      sit_t=$(sit_tail); [ -n "$sit_t" ] && t="$t · $sit_t"
      w=$(work_str); [ -n "$w" ] && t="$t $w"
      add_line "$t"; record_crossing time "$n" "$t"
      time_line=$n
    fi
  fi

  # The Stop hook asks for the pickup only from two hours, so the first rung
  # writes it here. Off-screen: recall is from the user's own list. The file
  # is named by its suffix: the Stop hook keys it on the session's short id,
  # and a model that has to guess picks another session's item.
  pickup_duty="Write the single next step as the body (below \`---\`) of this session's pickup item, $(state_dir)/pickup/*-${sid:0:8}.md, without showing it."

  # The sitting rung carries the fact, the mechanics the orders don't hold,
  # and a pointer: the orders say how to stop, and a procedure here would
  # displace them. The test checks the lead still exists in .claude/CLAUDE.md.
  # Landing first is the one rule held in both places on purpose (Solace,
  # 2026-10-01): durable enough to duplicate. Don't fold it into the pointer.
  sit_orders='Standing orders: "At a sitting rung".'

  # Model side of the sitting clock. Reads the same thresholds the screen
  # line does and defines none of its own; a rung of 0 means the shared clock
  # restarted, which spends the injection with it.
  #
  # Two markers: m_sit_said is the last rung this session spoke, and gates
  # the repeat (dotfiles#282); m_sit_at is the last rung whose stop was
  # shaped, which work in flight leaves unspent so the shaping still fires
  # at that rung once the work has landed.
  if [ "$is_prompt" -eq 1 ] && [ "$NAG_SIT_EVERY_MIN" -gt 0 ] \
     && [ "$sit_start" -gt 0 ]; then
    m_min=$(( (now_ts - sit_start) / 60 ))
    r=$(rung_of "$NAG_SIT_EVERY_MIN" "$NAG_SIT_EVERY_MIN" "$m_min")
    if [ "$r" -eq 0 ]; then
      m_sit_at=0; m_sit_said=0
    elif [ "$sit_quiet" -eq 0 ] && in_flight && [ "$r" -gt "$m_sit_said" ]; then
      add_model "Sitting $(hm "$m_min") at this machine, past $(hm "$r"), with work in flight ($in_flight_memo). Don't raise the time yet: land this first, without asking -- commit, push, open the PR. This rung comes back once it lands. $sit_orders"
      m_sit_said=$r
    elif [ "$sit_quiet" -eq 0 ] && ! in_flight && [ "$r" -gt "$m_sit_at" ]; then
      add_model "Sitting $(hm "$m_min") at this machine, past $(hm "$r"). $pickup_duty $sit_orders"
      m_sit_at=$r; m_sit_said=$r
    fi
  fi

  # Bedtime, the two arms after the reply: the warning NAG_BED_WARN_MIN
  # before it, and the hour itself. Each is said once per session for the
  # bedtime it was set for -- a re-set bedtime re-arms both -- and then
  # nothing. Gated on the night, so a bedtime left from last night is not
  # read out this morning. On can_inject like the context ladder: the hour
  # arrives on the wall clock, not on the user's rhythm, and a long turn
  # would otherwise carry past it in silence.
  if [ "$can_inject" -eq 1 ] && [ "$bed_at" -gt 0 ] && [ "$bed_night" -eq 1 ]; then
    if [ "$now_ts" -ge "$bed_at" ] && [ "$bed_past_at" -ne "$bed_at" ]; then
      t="ok, it's $(lhhmm "$now_ts"), you said $(lhhmm "$bed_at")"
      add_line "$t"; record_crossing bed_past $(( (now_ts - bed_at) / 60 )) "$t"
      add_model "It's $(lhhmm "$now_ts"); the user said bed at $(lhhmm "$bed_at"). Say that once. $pickup_duty $sit_orders"
      bed_past_at=$bed_at; bed_warn_at=$bed_at
    elif [ "$now_ts" -ge $((bed_at - NAG_BED_WARN_MIN * 60)) ] && [ "$bed_warn_at" -ne "$bed_at" ]; then
      bed_left=$(( (bed_at - now_ts + 59) / 60 ))
      t="$bed_left min to $(lhhmm "$bed_at")"
      add_line "$t"; record_crossing bed_warn "$bed_left" "$t"
      add_model "Bedtime $(lhhmm "$bed_at") is $bed_left minutes away. $pickup_duty $sit_orders"
      bed_warn_at=$bed_at
    fi
  fi

  # Keep the machine-wide day counter counting (#301). Measurement only: no
  # line, no injection reads it (one-entry-point §5, 2026-09-30). Gated on
  # is_prompt: the gap that starts a fresh day is measured between prompts
  # anywhere on the machine.
  if [ "$is_prompt" -eq 1 ]; then
    day_decisions "$sid" "$decisions" 0 "$now_ts" $((NAG_DECISION_GAP_MIN * 60)) >/dev/null
  fi

  # FROZEN -- THAW CAREFULLY.
  # friction -- measured in human turns, so only a prompt can trip it, and it
  # is addressed to the model, which is the thing the capacity rule asks of.
  #
  # Work in flight (in_flight(), dotfiles#192) gets the same land-it redirect
  # as the sitting clock: fric_tripped is left unset, so this line repeats on
  # every prompt while the window stays over threshold, and the ordinary
  # capacity-rule line still fires -- unspent -- once the work lands and this
  # falls to the else branch below. No record_crossing here on purpose: the
  # real crossing is the one that trips fric_tripped, not each in-flight repeat.
  if [ "$is_prompt" -eq 1 ] && [ "$fric_tripped" -ne 1 ] \
     && [ "$fric_win" -ge "$NAG_FRICTION_N" ]; then
    if in_flight; then
      fm="$fric_win corrections or rebukes in the last $NAG_FRICTION_TURNS turns, with work in flight. Do not raise capacity or offer a stopping point yet: land this without asking -- commit, push, open the PR -- then apply the capacity rule."
      add_model "$fm"
    else
      fm="$fric_win corrections or rebukes in the last $NAG_FRICTION_TURNS turns. Apply the capacity rule from the standing orders, once."
      add_model "$fm"; record_crossing friction "$fric_win" "$fm"
      fric_tripped=1; since_nag=1
    fi
  fi
fi

# ---------------------------------------------------------------- Stop nag
# Fires on a real Stop only -- hook_event_name, not the event argument, so a
# preview or a test harness asking for the `stop` readout never blocks a turn.
#
# "archivable" is the verdict that the chat can be closed without losing
# anything. stop-continuity.sh computes it -- after its salvage, after its
# state commit -- and stop-sequence.py runs this only once that hook is done,
# so this reads the verdict back instead of computing a second one. Two
# computations, run in parallel against a state repo mid-commit, are how a
# checkpoint said "archivable" while this said "not" (dotfiles#149's second
# answer). STOP_VERDICT_SINCE is the epoch the sequence started: a verdict
# older than that is the last turn's, and this turn's never came.
archival_reasons=""
archival_verdict=""
archivable() {
  local rec at
  rec=$(state_shard_path "$(state_dir)/metrics/sessions" "$sid.json" "$sid")
  archival_verdict=$(jq -r '.verdict // empty' "$rec" 2>/dev/null)
  at=$(jq -r '.verdict_at // 0' "$rec" 2>/dev/null)
  case "$at" in ''|*[!0-9]*) at=0 ;; esac
  if [ -z "$archival_verdict" ] || [ "$at" -lt "${STOP_VERDICT_SINCE:-0}" ]; then
    archival_verdict="not archivable: the Stop hook did not finish"
  fi
  archival_reasons=${archival_verdict#archivable}
  archival_reasons=${archival_reasons#not archivable: }
  [ -z "$archival_reasons" ]
}

# The hand-off is the pickup item's body (stop-continuity.sh writes one
# item per session under state/global/pickup/; a model writes the hand-off
# over the hook's default, which is the last prompt line, and the hook
# keeps the edit). Never assume it was written because it was asked for:
# look, and an unedited body -- still exactly the prompt line -- is none.
resume_ckpt() {
  for _f in "$(state_dir)/pickup/"*"-${sid:0:8}.md"; do
    [ -f "$_f" ] || continue
    _p=$(sed -n 's/^prompt: //p' "$_f" | head -1)
    _b=$(awk 'f { print } /^---$/ { f = 1 }' "$_f")
    if [ -n "$(printf '%s' "$_b" | tr -d '[:space:]')" ] && [ "$_b" != "$_p" ]; then
      printf '%s\n' "$_f"; return 0
    fi
  done
  return 1
}

if [ "$hook_name" = Stop ]; then
  archivable > /dev/null
  # Worktree slug is the leaf dir name only when work_root is actually a
  # `~/.claude/worktrees/<name>` checkout (stop-continuity.sh:269's test) --
  # in the main checkout there's no separate slug worth repeating.
  case "$work_root" in
    */.claude/worktrees/*) worktree_slug=$(basename "$work_root") ;;
    *) worktree_slug="" ;;
  esac
  archivable_tag="${work_branch}${worktree_slug:+/$worktree_slug} ${sid:0:8}"
  if [ -z "$archival_reasons" ]; then
    add_arch "📦 archivable. (${archivable_tag})"
  else
    add_arch "📦 not archivable: ${archival_reasons}. (${archivable_tag})"
    why=$(verdict_explain "$archival_verdict" "$work_root")
    [ -z "$why" ] || add_arch "$why"
  fi

  if [ "$nag_pending" -eq 1 ]; then
    # The block above has been answered. Whether the hand-off exists is a
    # fact on disk, not an inference from having asked. Either way the nag is
    # spent: a missing hand-off is reported once, never re-blocked on, or this
    # would be the level-triggered nag again.
    nag_pending=0; since_nag=0
    found=$(resume_ckpt)
    if [ -n "$found" ]; then
      resume_ts=$now_ts
      add_arch "Archivable. Hand-off written $(hhmm "$resume_ts") in $(basename "$found"). Next time: \`/pickup\`."
    else
      add_arch "Archivable, but no hand-off in the pickup item's body ($(state_dir)/pickup/*-${sid:0:8}.md). Not asking again this session."
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
    armed=0; found=""
    if [ "$since_nag" -eq 1 ] \
       || { [ "$late" -eq 1 ] && [ "$late_nagged" -eq 0 ]; }; then
      [ "$late" -eq 1 ] && late_nagged=1
      armed=1; found=$(resume_ckpt)
    fi
    if [ "$armed" -eq 1 ] && [ -n "$found" ]; then
      # The hand-off is already on disk: the turn that just ended wrapped up by
      # itself. Blocking now would force the extra turn that made the model,
      # not the user, speak last (dotfiles#391). Spend the arm; say what is there.
      since_nag=0
      [ "$resume_ts" -gt 0 ] || resume_ts=$now_ts
      add_arch "Hand-off already in $(basename "$found"). Next time: \`/pickup\`."
    elif [ "$armed" -eq 1 ]; then
      nag_pending=1; save_nag
      # The crossing lines that armed this Stop have already been persisted
      # as consumed, so this reason is their only chance to be seen. They go
      # in front of the instruction rather than being dropped -- nags, then
      # the archival verdict, same order as the screen.
      reason="Write the hand-off: replace the body (below \`---\`) of this session's pickup item in $(state_dir)/pickup/ with the next step, then link, model and effort lines. Then answer in one line naming where it landed -- no summary, no question, nothing new."
      pre="$sys_lines"
      [ -z "$arch_lines" ] || pre="${pre:+$pre
}$arch_lines"
      [ -z "$pre" ] || reason="$pre
$reason"
      printf '{"decision":"block","reason":%s}\n' "$(json_str "$reason")"
      exit 0
    elif [ "$resume_ts" -gt 0 ]; then
      # Nothing new to say. Later Stops carry the block's age and nothing else.
      add_arch "Hand-off $(hm $(( (now_ts - resume_ts) / 60 ))) old."
    fi
  fi
fi

[ "$run_engine" -eq 1 ] && save_nag

# UserPromptSubmit carries `show` now (#137), so it falls through to the
# block below like PostToolUse, and the injection merges into that one emit:
# two hookSpecificOutputs from one hook invocation would be one JSON object
# too many, and the second would be the one that was dropped.
#
# The model line survives only on an event that may carry one. A Stop's
# crossings have already been folded into its block reason above; re-emitting
# them here would say the same thing twice.
inject_model_line=""
[ "$can_inject" -eq 1 ] && inject_model_line="$model_line"

# ------------------------------------------------------------ event block
# Shown to the user at the end of a turn -- never sent to the model, so the
# running decision count costs nothing to display. Any crossing line rides on
# the front of it rather than arriving as a second message.
if [ "$SHOW" = show ] && [ -n "$metrics" ]; then
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

  IFS=$'\t' read -r bl_dec bl_fric bl_blocked bl_ctx <<<"$(printf '%s\n' "$metrics" | jq -r \
    '[(.session.decisions.total // 0), (.session.friction.total // 0),
      (.session.blocked.total // 0), (.session.context_peak // 0)] | @tsv')"

  bl_out=$(printf '%s\n' "$metrics" | jq -r '.session.output_tokens // 0')
  bl_ctx_glyphs="»"; [ "${ctx_rungs:-0}" -gt 0 ] && bl_ctx_glyphs=$(glyphs "$ctx_rungs" "⛁")
  bl_ctx_cluster="$bl_ctx_glyphs $(kfmt "$bl_out")/$(kfmt "$bl_ctx")"

  bl_dec_cluster="🧘(x0)"
  if [ "${bl_dec:-0}" -gt 0 ]; then
    r=$(fib_rungs "$bl_dec")
    g=""; for ((i = 0; i < r; i++)); do g="${g}⚖"; done
    p=""; [ "$bl_dec" -gt 3 ] && p="🤔"
    bl_dec_cluster="${p}${g}(x${bl_dec})"
  fi

  # A zero that shows beats a field that vanishes -- ✅ has done this for
  # blocked since #137's spec landed. 🧘‍♀️ decisions, 🌌 friction, no family prefix.
  bl_fric_cluster="🌌(x0)"
  if [ "${bl_fric:-0}" -gt 0 ]; then
    r=$(fib_rungs "$bl_fric")
    g=""; for ((i = 0; i < r; i++)); do g="${g}⚡"; done
    bl_fric_cluster="${g}(x${bl_fric})"
  fi

  bl_blocked_state="✅"; [ "${bl_blocked:-0}" -gt 0 ] && bl_blocked_state="⛔"
  bl_blocked_cluster="🔧${bl_blocked_state}(x${bl_blocked:-0})"

  bl_sit_cluster=""
  if [ "${sit_start:-0}" -gt 0 ]; then
    sit_min=$(( (now_ts - sit_start) / 60 ))
    r=$(time_rungs "$sit_min")
    pac_hour=$(( ( ($(date +%s) + TZOFF) / 3600 ) % 24 ))
    sg="⏱️"
    { [ "$pac_hour" -ge "$NAG_STOP_HOUR" ] \
      || [ "$pac_hour" -lt "$NAG_NIGHT_END_HOUR" ]; } && sg="🌙"
    # Louder past the hot rung, night or day: 🌙🌙🌙⏰⏰ keeps both signals.
    reps=""
    for ((i = 0; i < r; i++)); do
      if [ "$i" -ge "$NAG_SIT_HOT_RUNG" ]; then reps="${reps}⏰"
      else reps="${reps}${sg}"; fi
    done
    bl_sit_cluster="⏱$(hm "$sit_min")${reps}"
  fi

  bl_reason=""; bl_propose=0
  [ "${ctx_stop_line:-0}" -gt 0 ] && { bl_reason="${bl_reason}💸"; bl_propose=1; }
  [ "${bl_dec:-0}" -gt 3 ]        && { bl_reason="${bl_reason}🤔"; bl_propose=1; }
  [ "${bl_fric:-0}" -ge 2 ]       && { bl_reason="${bl_reason}⚡"; bl_propose=1; }
  # Night reuses the sitting cluster's own "is it night right now" read (sg)
  # and rung count (r) rather than a separate clock -- one signal, not two.
  [ "${sit_start:-0}" -gt 0 ] && [ "${sg:-}" = "🌙" ] && [ "${r:-0}" -ge 1 ] \
    && { bl_reason="${bl_reason}🌙"; bl_propose=1; }
  # Sitting fires at the same rung the glyph itself turns to ⏰ -- one
  # config knob (NAG_SIT_HOT_RUNG), not a second threshold to keep in sync.
  [ "${sit_start:-0}" -gt 0 ] && [ "${r:-0}" -ge $((NAG_SIT_HOT_RUNG + 1)) ] \
    && { bl_reason="${bl_reason}⏱️"; bl_propose=1; }
  [ "${bl_blocked:-0}" -ge 3 ]    && { bl_reason="${bl_reason}⛔"; bl_propose=1; }
  bl_main="$bl_ctx_cluster"
  [ -n "$bl_dec_cluster" ] && bl_main="$bl_main $bl_dec_cluster"
  [ -n "$bl_fric_cluster" ] && bl_main="$bl_main $bl_fric_cluster"
  bl_main="$bl_main $bl_blocked_cluster"
  [ -n "$bl_sit_cluster" ] && bl_main="$bl_main $bl_sit_cluster"
  # The tail is the reason glyphs alone, no words (Solace, 2026-10-01), and
  # it disappears entirely when no reason trips -- no "still room" filler (#137).
  if [ "$bl_propose" -eq 1 ]; then
    bl_main="$bl_main — $bl_reason"
  fi

  IFS=$'\t' read -r bl_turns bl_toolcalls <<<"$(printf '%s\n' "$metrics" | jq -r \
    '"\(.session.user_turns // 0)\t\(.session.tool_calls // 0)"')"
  bl_second=$(fmt_turns "$bl_turns" "$bl_toolcalls")
  bl_work=$(fmt_work "${ncommits:-0}" "${dirty:-0}" "${unpushed:-0}")
  [ -n "$bl_work" ] && bl_second="$bl_second $bl_work"
  bl_block="$bl_main"
  [ -n "$bl_second" ] && bl_block="$bl_block
$bl_second"

  # The model line rides out with the block rather than as a message of its
  # own: on PostToolUse both are produced by the same invocation, and a hook
  # returns one object. Screen text and model text are still separate fields
  # and are never concatenated -- the requirements doc is explicit about that.
  jq -nc --arg s "$sys_lines" --arg b "$bl_block" --arg a "$arch_lines" \
         --arg m "$inject_model_line" --arg e "$inject_event" \
    '{systemMessage: ([$s, $b, $a] | map(select(. != "")) | join("\n"))}
     + (if $m == "" then {}
        else {hookSpecificOutput: {hookEventName: $e,
                                   additionalContext: $m}} end)'
elif [ -n "$sys_lines" ] || [ -n "$arch_lines" ] || [ -n "$inject_model_line" ]; then
  jq -nc --arg s "$sys_lines" --arg a "$arch_lines" \
         --arg m "$inject_model_line" --arg e "$inject_event" \
    '(([$s, $a] | map(select(. != "")) | join("\n")) as $t
      | if $t == "" then {} else {systemMessage: $t} end)
     + (if $m == "" then {}
        else {hookSpecificOutput: {hookEventName: $e,
                                   additionalContext: $m}} end)'
fi
exit 0
