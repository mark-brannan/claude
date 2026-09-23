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
# ⚖ gate, ⚡ friction and ⏱ sitting-clock crossings, and any glyph
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
#             stop, and plainly on each further rung, never twice for the
#             same one
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
NAG_CONTEXT_LINES="${METRICS_CONTEXT_LINES:-60000 90000 120000 150000 185000}"
NAG_CONTEXT_STOP_AT="${METRICS_CONTEXT_STOP_AT:-150000}"
NAG_CONTEXT_STEP="${METRICS_CONTEXT_STEP:-35000}"
NAG_SIT_EVERY_MIN="${METRICS_SIT_EVERY_MIN:-60}"
NAG_SIT_GAP_MIN="${METRICS_SIT_GAP_MIN:-15}"
# Sitting rungs from here up draw ⏰ instead of ⏱️/🌙. 3 = past 90 min.
NAG_SIT_HOT_RUNG="${METRICS_SIT_HOT_RUNG:-3}"
NAG_FRICTION_N="${METRICS_FRICTION_N:-3}"
NAG_FRICTION_TURNS="${METRICS_FRICTION_TURNS:-20}"
NAG_GATE_EVERY="${METRICS_GATE_EVERY:-5}"
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
NAG_MODEL_DECISION_LINES="${METRICS_MODEL_DECISION_LINES:-3 5 8 13 21}"
NAG_MODEL_DECISION_STEP="${METRICS_MODEL_DECISION_STEP:-21}"
# Local hour from which a Stop on an archivable session is worth interrupting.
NAG_STOP_HOUR="${METRICS_STOP_HOUR:-22}"

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
  jq -n --argjson ss "$sit_start" --argjson lp "$last_prompt" \
    --arg local "$last_local" --arg sid "$sid" --arg repo "$work_repo" \
    --arg branch "$work_branch" --arg slug "$last_slug" --arg ckpt "$last_ckpt" \
    --arg cwd "$cwd" --arg prompt "${prompt_text:-}" \
    '{sitting_start: $ss, last_prompt: $lp,
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
ctx_line=0; ctx_rungs=0; ctx_stop_line=0; time_line=0; tl_sitting=0; gate_line=0; fric_tripped=0
since_nag=0; resume_ts=0; nag_pending=0; late_nagged=0
m_ctx_at=0; m_sit_at=0; m_sit_said=0; m_dec_at=0; m_ctx_tools=0
if [ -f "$NAGF" ]; then
  IFS=$'\t' read -r ctx_line ctx_rungs ctx_stop_line time_line tl_sitting gate_line fric_tripped \
                    since_nag resume_ts nag_pending late_nagged m_ctx_at m_sit_at m_sit_said m_dec_at \
                    m_ctx_tools \
    <<<"$(jq -r '[(.context_line // 0), (.context_rungs // 0), (.context_stop_line // 0),
                  (.time_line // 0), (.time_line_sitting // -1),
                  (.gate_line // 0),
                  (if .friction_tripped then 1 else 0 end),
                  (if .since_nag then 1 else 0 end),
                  (.resume_ts // 0),
                  (if .nag_pending then 1 else 0 end),
                  (if .late_nagged then 1 else 0 end),
                  (.model_context_at // 0), (.model_sitting_at // 0),
                  (.model_sitting_said // .model_sitting_at // 0),
                  (.model_decision_at // 0),
                  (.model_context_tools // 0)] | @tsv' "$NAGF" 2>/dev/null)"
fi
for v in ctx_line ctx_rungs ctx_stop_line time_line tl_sitting gate_line fric_tripped \
         since_nag resume_ts nag_pending late_nagged m_ctx_at m_sit_at m_sit_said m_dec_at \
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
  jq -n --argjson cl "$ctx_line" --argjson cr "$ctx_rungs" --argjson cs "$ctx_stop_line" \
        --argjson tl "$time_line" --argjson ts "$tl_sitting" \
        --argjson gl "$gate_line" --argjson ft "$fric_tripped" \
        --argjson sn "$since_nag" --argjson rt "$resume_ts" --argjson np "$nag_pending" \
        --argjson ln "$late_nagged" \
        --argjson mc "$m_ctx_at" --argjson ms "$m_sit_at" \
        --argjson mss "$m_sit_said" --argjson md "$m_dec_at" \
        --argjson mct "$m_ctx_tools" \
    '{context_line: $cl, context_rungs: $cr, context_stop_line: $cs,
      time_line: $tl, time_line_sitting: $ts, gate_line: $gl,
      friction_tripped: ($ft == 1),
      since_nag: ($sn == 1), resume_ts: $rt, nag_pending: ($np == 1),
      late_nagged: ($ln == 1),
      model_context_at: $mc, model_sitting_at: $ms,
      model_sitting_said: $mss, model_decision_at: $md,
      model_context_tools: $mct}' \
    > "$NAGF.$$" 2>/dev/null \
    && mv -f "$NAGF.$$" "$NAGF" 2>/dev/null || rm -f "$NAGF.$$" 2>/dev/null
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
  mkdir -p "$CROSSD" 2>/dev/null || return 0
  jq -nc --arg sid "$sid" --arg now "$now" --arg kind "$1" \
         --argjson at "$2" --arg text "$3" \
    '{session_id: $sid, ts: $now, kind: $kind, at: $at, text: $text}' \
    >> "$CROSSD/$sid.jsonl" 2>/dev/null || true
}

# Human nags (sitting, friction) gate on this; machine nags (context,
# decisions) do not -- a context ceiling is a real limit, while a sitting
# clock is answered by landing the work. Memoized; can shell out to `gh`.
in_flight() {
  [ -n "${in_flight_memo+x}" ] || in_flight_memo=$([ -n "$work_root" ] \
    && archivable_reasons "$work_root" "$work_branch")
  [ -n "$in_flight_memo" ]
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

  IFS=$'\t' read -r ctx gates decisions fric_total fric_win <<<"$(printf '%s\n' "$metrics" | jq -r \
    --argjson w "$NAG_FRICTION_TURNS" \
    '(.session.user_turns // 0) as $t
     | [ (.session.context_peak // 0),
         (.session.decisions.gate // 0),
         (.session.decisions.total // 0),
         (.session.friction.total // 0),
         ([ .friction[]?
            | select(.type == "correction" or .type == "rebuke")
            | select((.turn_ordinal // 0) > ($t - $w)) ] | length) ] | @tsv')"
  [ -n "${ctx:-}" ] || ctx=0
  [ -n "${gates:-}" ] || gates=0
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
        add_model "Context at $(kfmt "$ctx"), past $(kfmt "$r") — a stopping point. Offer one, or /wrapup."
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
        add_model "Context at $(kfmt "$ctx"), past $(kfmt "$m_ctx_at") for $m_ctx_tools tool calls. If there's a stopping point, offer it, or /wrapup."
        m_ctx_tools=0
      fi
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
      #
      # Work in flight (dirty tree / unpushed / open PR -- in_flight()) never
      # gets a stop-or-stand verdict: landing unfinished work is not "stop
      # here" advice, it is the same instruction the model-directed line
      # already gives. Reassure instead of advise -- name the time, promise
      # the session keeps going to the next checkpoint, nothing to act on.
      if in_flight; then
        verdict="still landing it -- will stop cleanly at the next checkpoint"
      elif [ "$n" -ge $((NAG_SIT_EVERY_MIN * 2)) ]; then
        verdict="stop here, run /wrapup"; since_nag=1
      else verdict="stand up"; fi
      t="⏱ sitting $(hm "$n") — context $(kfmt "$ctx"): $verdict."
      w=$(work_str); [ -n "$w" ] && t="$t $w"
      add_line "$t"; record_crossing time "$n" "$t"
      time_line=$n
    fi
  fi

  # Model side of the sitting clock. Reads the same thresholds the screen
  # line does and defines none of its own; a rung of 0 means the shared clock
  # restarted, which spends the injection with it.
  #
  # Two markers, not one: m_sit_said is the last rung this session spoke, and
  # gates the repeat (dotfiles#282); m_sit_at is the last rung whose *offer*
  # was made, which the in-flight branch deliberately leaves unspent so the
  # offer still fires at the same rung once the work has landed.
  if [ "$is_prompt" -eq 1 ] && [ "$NAG_SIT_EVERY_MIN" -gt 0 ] \
     && [ "$sit_start" -gt 0 ]; then
    m_min=$(( (now_ts - sit_start) / 60 ))
    r=$(rung_of "$NAG_SIT_EVERY_MIN" "$NAG_SIT_EVERY_MIN" "$m_min")
    if [ "$r" -eq 0 ]; then
      m_sit_at=0; m_sit_said=0
    elif [ "$r" -gt "$m_sit_said" ] \
         || { [ "$m_sit_at" -eq 0 ] && ! in_flight; }; then
      inf=""; in_flight && inf=" with work in flight ($in_flight_memo)"
      if [ -n "$inf" ]; then sv="Do not offer a break or /wrapup yet: land this without asking -- commit, push, open the PR -- then offer."
      elif [ "$r" -ge $((NAG_SIT_EVERY_MIN * 2)) ]; then
        # Only a genuine repeat (m_sit_at already spent) gets the softened
        # wording -- a first crossing, including the deferred offer that
        # fires once in-flight work lands, keeps the original imperative.
        if [ "$m_sit_at" -eq 0 ]; then sv="Stop here and run /wrapup."
        else sv="If the work is landed, this is a good place to stop; if not, land it and then offer."
        fi
      else sv="Say so and offer a break."; fi
      if [ "$m_sit_at" -eq 0 ]; then
        [ -n "$inf" ] || m_sit_at=$r   # unspent while in flight: fires once landed
        add_model "Sitting $(hm "$m_min") at this machine, past $(hm "$r")$inf. $sv"
      else
        add_model "Sitting $(hm "$m_min"), past $(hm "$r") (last offered at $(hm "$m_sit_at")). $sv"
        m_sit_at=$r
      fi
      m_sit_said=$r
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

  # Model side of the decision load, counting every decision pushed to the
  # user this session -- scoping, inline and gate -- not gate alone: the
  # capacity that runs out is the capacity to decide, whatever kind.
  if [ "$is_prompt" -eq 1 ]; then
    r=$(rung_of "$NAG_MODEL_DECISION_LINES" "$NAG_MODEL_DECISION_STEP" "$decisions")
    if [ "$r" -gt "$m_dec_at" ]; then
      if [ "$m_dec_at" -eq 0 ]; then
        add_model "$decisions decisions pushed to Solace this session ($gates of them gates), past $r. Front-load or card the rest."
      else
        add_model "$decisions decisions pushed to Solace this session ($gates of them gates), past $r (last noted at $m_dec_at)."
      fi
      m_dec_at=$r
    fi
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
# anything: clean worktree, nothing unpushed, the state repo's own commits
# pushed, and the branch either has an open PR or is named by a pointer card.
archival_reasons=""
archivable() {
  local sr n
  archival_reasons=""
  add_areason() { archival_reasons="${archival_reasons:+$archival_reasons, }$1"; }

  if [ -z "$work_root" ]; then
    add_areason "not a git repo"
  else
    # archivable_reasons() is lib-state.sh's -- the home/dirty/unpushed
    # check shared with stop-continuity.sh's Stop-hook verdict (#149).
    archival_reasons=$(archivable_reasons "$work_root" "$work_branch")
  fi

  sr=$(state_repo 2>/dev/null) || sr=""
  if [ -n "$sr" ]; then
    n=$(git -C "$sr" rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
    [ "${n:-0}" -eq 0 ] || add_areason "state repo $n commit(s) unpushed"
  fi

  [ -z "$archival_reasons" ]
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
  fi

  if [ "$nag_pending" -eq 1 ]; then
    # The block above has been answered. Whether the resume block exists is a
    # fact on disk, not an inference from having asked. Either way the nag is
    # spent: a missing block is reported once, never re-blocked on, or this
    # would be the level-triggered nag again.
    nag_pending=0; since_nag=0
    found=$(resume_ckpt)
    if [ -n "$found" ]; then
      resume_ts=$now_ts
      add_arch "Archivable. Resume block written $(hhmm "$resume_ts") in $(basename "$found"). Next time: \`/pickup\`."
    else
      add_arch "Archivable, but no \`## Resume\` block in $(state_dir)/log/auto/*-${sid:0:8}.md. Not asking again this session."
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
      # in front of the instruction rather than being dropped -- nags, then
      # the archival verdict, same order as the screen.
      reason="Write the resume block: append a \`## Resume\` block (next, link, model, effort) to this session's checkpoint in $(state_dir)/log/auto/."
      pre="$sys_lines"
      [ -z "$arch_lines" ] || pre="${pre:+$pre
}$arch_lines"
      [ -z "$pre" ] || reason="$pre
$reason"
      printf '{"decision":"block","reason":%s}\n' "$(json_str "$reason")"
      exit 0
    fi
    # Nothing new to say. Later Stops carry the block's age and nothing else.
    if [ "$resume_ts" -gt 0 ]; then
      add_arch "Resume block $(hm $(( (now_ts - resume_ts) / 60 ))) old."
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
    sg="⏱️"; { [ "$pac_hour" -ge 22 ] || [ "$pac_hour" -lt 5 ]; } && sg="🌙"
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
  # The tail is a verdict, not decoration -- Solace ruled it disappears
  # entirely when nothing proposes stopping, no "still room" filler (#137).
  if [ "$bl_propose" -eq 1 ]; then
    bl_main="$bl_main — ${bl_reason:+$bl_reason }propose stopping."
  fi

  bl_second=$(printf '%s\n' "$merged" | jq -r -L "$HOOK_DIR" \
    'include "lib-metrics-fmt";
     turns + ((work // "") as $w | if $w == "" then "" else " " + $w end)' \
    2>/dev/null)
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
