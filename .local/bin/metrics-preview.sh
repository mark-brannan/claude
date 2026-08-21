#!/bin/sh
# Render every metrics readout, by running the scripts that actually produce
# them, so the format can be iterated from the command line.
#
# Why this exists: every readout ends in `2>/dev/null` -- correct for a hook,
# since a broken format must never break a session -- but it means a jq
# syntax error is indistinguishable from "no metrics yet". Nothing that fails
# here fails visibly in a session; that is the whole point of the tool.
#
# It drives the real scripts rather than reproducing their jq. An earlier
# version reimplemented both layouts, which meant the tool built to catch
# drift was itself a third copy that could drift. If you find yourself
# writing a layout in here, put it in `lib-metrics-fmt.jq` instead and call
# it from all three.
#
# Checks, in order:
#   compile   the shared module parses at all
#   silent    the two paths that must print nothing still print nothing --
#             `prompt` (the model would read it) and a non-git Bash command
#             (the jq pass is too expensive to run after `ls`)
#   block     the two-line event block, once per event type
#   row       the statusline row
# Exits non-zero if any check fails, so it is usable in a pre-commit or CI.
#
# Reads the newest local transcript, so the numbers are a real session's.
# Usage: metrics-preview.sh [ruler-width] [--fields] [--quiet]
#   --quiet  report only failures, and say nothing at all when everything
#            passes -- the shape a pre-commit or CI step wants.
set -u

HOOKS="$HOME/.claude/hooks"
[ -d "$HOOKS" ] || { echo "no hooks at $HOOKS" >&2; exit 1; }
# shellcheck source=.claude/hooks/lib-state.sh
. "$HOOKS/lib-state.sh"

WIDTH=75
PADW=30                 # header pad width the two-line block is built to
FIELDS=""
QUIET=""
for a in "$@"; do
  case "$a" in
    --fields) FIELDS=1 ;;
    --quiet)  QUIET=1 ;;
    *[!0-9]*) echo "usage: metrics-preview.sh [ruler-width] [--fields] [--quiet]" >&2; exit 2 ;;
    *)        WIDTH="$a" ;;
  esac
done

fails=0
say() { [ -n "$QUIET" ] || printf '%s\n' "$*"; }
ok()   { say "  ok    $1"; }
bad()  { printf '  FAIL  %s\n' "$1" >&2; fails=$((fails + 1)); }

# shellcheck disable=SC2012  # session ids are hex; `find -printf` is not POSIX
tp=$(ls -t "$HOME"/.claude/projects/*/*.jsonl 2>/dev/null | head -1)
[ -n "$tp" ] || { echo "no transcript found" >&2; exit 1; }
sid=$(basename "$tp" .jsonl)

# The payload every hook entry point receives. `cmd` decides whether the git
# filter in metrics-live.sh lets the event through.
payload() {
  jq -nc --arg tp "$tp" --arg sid "$sid" --arg cwd "$PWD" --arg cmd "$1" \
    '{transcript_path:$tp, session_id:$sid, cwd:$cwd, tool_input:{command:$cmd}}'
}

# --- compile ---------------------------------------------------------------
say "--- checks"
if jq -e -L "$HOOKS" 'include "lib-metrics-fmt"; .' /dev/null >/dev/null 2>&1 \
   || jq -n -L "$HOOKS" 'include "lib-metrics-fmt"; empty' >/dev/null; then
  ok "lib-metrics-fmt.jq compiles"
else
  bad "lib-metrics-fmt.jq does not compile -- fix that first"
  jq -n -L "$HOOKS" 'include "lib-metrics-fmt"; empty' 2>&1 | sed 's/^/        /' >&2
  exit 1
fi

# Populate the cache both readouts print from, through the real producer.
payload "git commit -m preview" | bash "$HOOKS/metrics-live.sh" git 0 >/dev/null

F="$(state_dir)/metrics/live/$sid.json"
[ -f "$F" ] || { echo "metrics-live.sh wrote no cache at $F" >&2; exit 1; }

# --- silence ---------------------------------------------------------------
# These two must stay silent. A regression here is invisible in a session:
# `prompt` leaking means the block becomes model context instead of display,
# and the git filter leaking means a transcript-wide jq pass after every `ls`.
out=$(payload "git commit -m preview" | bash "$HOOKS/metrics-live.sh" prompt 0 show 2>&1)
if [ -z "$out" ]; then ok "prompt event prints nothing (would become model context)"
else bad "prompt event printed: $out"; fi

out=$(payload "ls -la" | bash "$HOOKS/metrics-live.sh" git 0 show 2>&1)
if [ -z "$out" ]; then ok "non-git Bash command is filtered out"
else bad "non-git command printed: $out"; fi

# --- block -----------------------------------------------------------------
# Straight from metrics-live.sh, including the SHOW guard and the
# systemMessage envelope -- not a local re-render of `block`.
for ev in git question stop; do
  say ""
  say "--- metrics-live.sh $ev 0 show"
  out=$(payload "git commit -m preview" | bash "$HOOKS/metrics-live.sh" "$ev" 0 show 2>&1)
  msg=$(printf '%s' "$out" | jq -r '.systemMessage // empty' 2>/dev/null)
  if [ -n "$msg" ]; then
    say "$msg"
  else
    bad "$ev produced no systemMessage; raw: ${out:-<empty>}"
  fi
done

# --- row -------------------------------------------------------------------
say ""
say "--- statusline-metrics.sh"
row=$(jq -nc --arg sid "$sid" --arg cwd "$PWD" \
        '{session_id:$sid, cwd:$cwd, model:{display_name:"Opus 5"}}' \
      | bash "$HOOKS/statusline-metrics.sh" 2>&1)
case "$row" in
  ""|*"warming up"*|*"⛁ —"*) bad "statusline fell back to: ${row:-<empty>}" ;;
  *) say "$row" ;;
esac

# --- fields ----------------------------------------------------------------
# One field per line with its width: the only way to see which one is eating
# the budget when the whole line is over. Introspection, not layout.
if [ -n "$FIELDS" ]; then
  say ""
  say "--- fields (name, width, |value|)"
  jq -r -L "$HOOKS" 'include "lib-metrics-fmt";
    [ {n:"env",  v:env},  {n:"cost",  v:cost},  {n:"time", v:time},
      {n:"dec",  v:dec},  {n:"turns", v:turns},
      {n:"work", v:(work // "(empty on a clean tree)")},
      {n:"split",v:split} ]
    | .[] | "  \(.n + "        "[0:(6 - (.n | length))])"
          + "\((.v | length | tostring) + "   "[0:(4 - (.v | length | tostring | length))])"
          + "|\(.v)|"' "$F"
fi

# --- ruler -----------------------------------------------------------------
if [ -z "$QUIET" ]; then
  echo ""
  echo "--- ruler (block header pads to $PADW)"
  awk -v w="$WIDTH" -v p="$PADW" 'BEGIN{
    for (i=1;i<=w;i++)
      printf (i==p) ? "|" : ((i%10==0) ? substr(i,length(i)-1,1) : (i%5==0 ? "+" : "-"));
    printf "  <- col %d\n", w}'
fi

[ "$fails" -eq 0 ] || { printf '\n%d check(s) failed\n' "$fails" >&2; exit 1; }
