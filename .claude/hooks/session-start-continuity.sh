#!/usr/bin/env bash
# SessionStart hook: hand the session its board and its recent history.
#
# The standing orders say new sessions open by pulling from a board. That only
# happens reliably if the board is already in front of the session -- asking
# Claude to go find it costs a prompt from the user, which is the thing this is
# supposed to remove. So this reads the state repo and injects a short brief.
#
# Deliberately terse. Every line here is charged to every session in every
# repo, so it carries only what changes what the session does first: open
# work, what the last sessions left behind, and how much deciding the user has
# already been asked to do this week.
#
# The board is not read here. It used to be: the first 16 bullets of
# kanban.md, half of them ticked, ~4 KB into every session, and a bullet
# above the first heading never printed at all. `worklist --brief` owns that
# view now -- live PR and issue state plus the `## Needs ruling` and
# `## Claude's` cards, <= 3 KB by
# its contract, served from cache so it is fast. This hook only caps the wait
# at 6 s (a hung gh call must never hold session start) and clips the output
# at 4 KB, so a broken worklist cannot become a 40 KB tax. Missing worklist
# is reported, not worked around; the old dump is not a fallback.
#
# Never clones. A private clone needs credentials a hook cannot count on and
# would stall session start on the network; absence is reported with the fix
# instead of silently papered over.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"

emit() {
  jq -Rn --rawfile ctx /dev/stdin \
    '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$ctx}}'
}

command -v jq >/dev/null 2>&1 || exit 0

# Config sync status (strategy doc §6.7/§13 P1) -- one line, folded into this
# hook rather than a hook of its own, since a new hook doubles the fixed
# context tax every session pays. Cloud-only: a real machine is yadm-managed,
# never runs the installer, and would never have this file -- printing
# DEGRADED there would be a false alarm, not a signal.
sync_status_line() {
  [ "${CLAUDE_CODE_REMOTE:-}" = true ] || return 0
  SF="$HOME/.claude/.sync-status.json"
  if [ ! -f "$SF" ]; then
    echo "config: DEGRADED — no .sync-status.json (installer never ran, or predates P1)"
    return 0
  fi
  complete=$(jq -r '.complete' "$SF" 2>/dev/null)
  sha=$(jq -r '.sha' "$SF" 2>/dev/null | cut -c1-7)
  channel=$(jq -r '.channel' "$SF" 2>/dev/null)
  at=$(jq -r '.installed_at' "$SF" 2>/dev/null)
  if [ "$complete" != true ]; then
    echo "config: DEGRADED — incomplete install ($channel@$sha, $at)"
  else
    echo "config: $channel@$sha (installed $at)"
  fi
}
CONFIG_LINE=$(sync_status_line)

if ! SR=$(state_repo); then
  {
    [ -n "$CONFIG_LINE" ] && printf '%s\n\n' "$CONFIG_LINE"
    cat <<'MSG'
## Continuity: state repo NOT available

`claude_prompts_scratch` is not checked out here, so the board, the prior
checkpoints and the metrics are all missing, and `stop-continuity.sh` will
write to `~/.claude/state/global` (local, unpushed, lost when this container
is reclaimed).

Fix it now: `mcp__Claude_Code_Remote__add_repo` with owner `mark-brannan`,
repo `claude_prompts_scratch`, access `push`, then clone it to
`/workspace/claude_prompts_scratch` -- a path `state_repo` already searches.
Do this every cold session; there is no environment setting that does it for
you. Cloud environments configure only name, network access, environment
variables and a setup script -- repositories attach per session, and the
GitHub proxy 403s any repo not attached, so a setup script cannot clone this.
MSG
  } | emit
  exit 0
fi

SD="$SR/state/global"

# Runs worklist --brief under a wall-clock cap. Background + sleep + kill
# rather than timeout(1): macOS has no timeout, and one code path is one to
# test. Both children get their stdio pointed away from this hook's pipe --
# a child still holding it would keep jq reading until the child died.
board_view() {
  wl="$HOME/.local/bin/worklist"
  if [ ! -x "$wl" ]; then
    echo "worklist not installed -- live board view unavailable; this is not a clean state (run dotsync / cloud-session-setup.sh)"
    return 0
  fi
  out=$(mktemp "${TMPDIR:-/tmp}/worklist-brief.XXXXXX") || return 0
  "$wl" --brief >"$out" 2>/dev/null </dev/null &
  wl_pid=$!
  ( sleep 6; kill "$wl_pid" 2>/dev/null ) >/dev/null 2>&1 </dev/null &
  wd_pid=$!
  wait "$wl_pid" 2>/dev/null
  rc=$?
  kill "$wd_pid" 2>/dev/null
  if [ "$rc" -gt 128 ]; then
    echo "worklist --brief did not return in 6 s -- board view unavailable this session; run \`worklist --brief\` yourself"
  elif [ "$rc" -ne 0 ]; then
    echo "worklist --brief exited $rc -- board view unavailable this session; run \`worklist --brief\` yourself"
  fi
  head -c 4096 "$out"
  rm -f "$out"
}

# A card written above the first "## " heading belongs to no section, so the
# lint, worklist and every reader skip it. One line, so someone moves it.
board_lint_warning() {
  [ -f "$SD/kanban.md" ] || return 0
  if awk '/^## / { exit } /^- \[/ { found = 1; exit } END { exit !found }' "$SD/kanban.md"; then
    echo
    echo "WARNING: kanban.md has a card above its first \`## \` heading -- no section, invisible to every reader. Move it under \`## Needs ruling\` or \`## Claude's\`."
  fi
}

# Freshen the board, but never block session start on it.
timeout 25 git -C "$SR" pull --rebase --autostash -q >/dev/null 2>&1 || true

{
  [ -n "$CONFIG_LINE" ] && { printf '%s\n' "$CONFIG_LINE"; echo; }
  echo "## Continuity brief"
  echo
  echo "State repo: \`$SR\` (board, checkpoints and metrics live here; the Stop"
  echo "hook commits and pushes to it automatically -- no need to be asked)."

  echo
  board_view
  board_lint_warning

  if [ -d "$SD/log/auto" ]; then
    recent=$(ls -t "$SD/log/auto"/*.md 2>/dev/null | head -3)
    if [ -n "$recent" ]; then
      echo
      echo "### Where recent sessions left off"
      echo
      for f in $recent; do
        echo "**$(basename "$f" .md)**"
        sed -n '/^- session/,/^$/p' "$f" | head -6
        sed -n '/^## Uncommitted at Stop/,/^## /p' "$f" \
          | grep -v '^## ' | grep -v '^$' | head -6 | sed 's/^/    /'
        echo
      done
    fi
  fi

  if [ -d "$SD/metrics/decisions" ]; then
    since=$(date -u -d '7 days ago' +%Y-%m-%d 2>/dev/null \
            || date -u -v-7d +%Y-%m-%d 2>/dev/null || echo "")
    counts=$(cat "$SD/metrics/decisions"/*.jsonl 2>/dev/null \
      | jq -r --arg since "$since" 'select(.ts >= $since) | .type' 2>/dev/null \
      | sort | uniq -c | awk '{printf "%s %s, ", $1, $2}' | sed 's/, $//')
    if [ -n "$counts" ]; then
      echo
      echo "### Decision load, last 7 days"
      echo
      echo "$counts — \`scoping\` is cheap (asked before work exists),"
      echo "\`gate\` is expensive (open-ended, mid-flight, needs the user to reload"
      echo "context). Prefer front-loading questions; board the rest."
    fi
  fi
} | emit

exit 0
