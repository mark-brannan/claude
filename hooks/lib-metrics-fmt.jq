# Shared field vocabulary for the two metrics readouts: the statusline row
# (`statusline-metrics.sh`) and the event block (`metrics-live.sh`).
#
# Why a module: the two say the same things in different layouts, and when
# each owned its own copy of the glyphs they drifted -- the statusline read
# "◆ 3 dec" while the event block read "decisions 3" for the same number, so
# neither taught you how to read the other. Fields live here, layout stays
# in the caller. Loaded with `jq -L "$HOOK_DIR" 'include "lib-metrics-fmt"; ...'`.
#
# Input: one live-metrics cache object (`metrics/live/<sid>.json`).

def k: if . >= 1000 then "\(. / 1000 | floor)k" else "\(.)" end;

# other UTF-8 single width chars for consideration:
# § ¶ ◊ ⁂ ‽ ⸎ ❖ ⌖ ◎ ⊙ ⦾ ⎊ • · ✦  ‖ ⁄ ⁞ ┄ — . ¤ ✎ ⚙  ⚑ ⚠
#
# emoji from 2026-09-10's mockup session, all now wired into metrics-live.sh's
# event block (#137): 🧘 decisions at zero, 🌌 friction at zero, ✅ blocked
# at zero, ⏰ the sitting cluster past its hot rung. Nothing is held in
# reserve here any more -- the next candidate goes on this list before it
# goes on screen.

# The branch is the one field with no upper bound -- `claude/*` names run to
# 36 characters and would push everything after it off the line on their own.
def env: " \(.repo)@\(.branch
           | if . == null or . == "" then "-"          # detached HEAD
             elif length > 20 then .[0:19] + "…"
             else . end)";

def dec: "⚖ \(.decisions.total)"
       + (if .last_event == "question" then "+1?" else "" end)
       + "[\(.decisions.scoping)/\(.decisions.inline)/\(.decisions.gate)]";

def cost:  "\(.output_tokens | k)/\(.context_peak | k)";

# ⚡ pairs with ⚖ (decisions) but is not a warning glyph -- friction is a
# measurement, not an alarm. Pushback is a weekly number, like `split`; it
# lives in the session JSON only, not this row. Null-guarded the same way as
# `time`: a cache written before this field existed drops the row instead of
# printing "null".
def fric:
  if .friction == null then empty
  else "⚡ \(.friction.total)[\(.friction.correction)/\(.friction.override)/\(.friction.rebuke)]"
  end;

# Harness refusals, shown only when there are any: on a clean session the row
# is noise, and the statusline is width-constrained.
def blk:
  if (.blocked.total // 0) == 0 then empty else "⛔ \(.blocked.total)" end;

def turns: "⇢ \(.user_turns) ⚙ \(.tool_calls)";

# Git state, the part that decides whether the chat is safe to kill. Empty
# when the tree is clean: "0c/0~/0↑" is the common case and says nothing.
def work:
  if .commits > 0 or .dirty > 0 or .unpushed > 0
  then "⎇ " + (if .commits  > 0 then "\(.commits)c" else "" end)
           + (if .dirty    > 0 then "\(.dirty)~"  else "" end)
           + (if .unpushed > 0 then "\(.unpushed)↑unpushed" else "" end)
           + (if .unpushed > 0 then "  ← not safe to kill" else "" end)
  else empty end;

# Seconds as a glanceable duration: "45s", "24m", "1h48".
def dur:
  (. // 0 | round) as $s
  | if   $s < 60   then "\($s)s"
    elif $s < 3600 then "\($s / 60 | floor)m"
    else "\($s / 3600 | floor)h"
         + ((($s % 3600) / 60 | floor | tostring)
            | if length < 2 then "0" + . else . end)
    end;

# The time row. Three numbers that do not substitute for one another:
#   active   silences clamped at 2 min, so walking away stops the clock but
#            thinking for a minute does not
#   split    of that active time, the gap ending in the user typing is hers, every
#            other gap is the agent's -- a message sent mid-turn is credited
#            to her too, the one place the split is generous to the machine
#   open     raw wall clock. Not work, but the number that predicts cost: an
#            old session re-sends a large context on every turn.
# Empty on a cache written before these fields existed, so an upgrade in
# flight drops the row rather than printing three zeros.
def time:
  if .elapsed_seconds == null then empty
  else " ⏱\(.active_seconds | dur)⟳"
     + " \(.elapsed_seconds | dur)"
  end;

# Who the active time went to, on its own. Not in either readout -- it is the
# interesting number once a week, not once a render, and `time` already
# carries the split inline.
def split: " ☺ \(.human_seconds | dur)/⚙ \(.agent_seconds | dur)";

# --- layouts --------------------------------------------------------------
# The two readouts are one vocabulary in two shapes, so both shapes live here
# next to each other. When they each owned their layout the field *order*
# drifted as well as the glyphs, and a third copy in `metrics-preview.sh`
# meant the tool built to check for drift could itself be the thing that had
# drifted. Callers now name a layout and pass no format at all.

# Field order, defined once. `work` yields empty on a clean tree and simply
# drops out of the array.
# Two groups, one line each: cost-and-time, then work-done. The desktop UI
# wraps around 75 columns and the two groups together run past 90, so the
# break is placed rather than left to the renderer -- an accidental wrap
# lands mid-field, a deliberate one does not.
def fields:  [cost, dec, fric, blk];
def fields2: [time, turns, work];

# One row, for the statusline; no 'event'
def row: (["◆\(env)"] + fields + fields2) | join(" ");
