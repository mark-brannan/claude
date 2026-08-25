#!/usr/bin/env bash
# SessionStart hook: hand the session its board and its recent history.
#
# The standing orders say new sessions open by pulling from a board. That only
# happens reliably if the board is already in front of the session -- asking
# Claude to go find it costs a prompt from Mark, which is the thing this is
# supposed to remove. So this reads the state repo and injects a short brief.
#
# Deliberately terse. Every line here is charged to every session in every
# repo, so it carries only what changes what the session does first: open
# work, what the last sessions left behind, and how much deciding Mark has
# already been asked to do this week.
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

# Freshen the board, but never block session start on it.
timeout 25 git -C "$SR" pull --rebase --autostash -q >/dev/null 2>&1 || true

{
  [ -n "$CONFIG_LINE" ] && { printf '%s\n' "$CONFIG_LINE"; echo; }
  echo "## Continuity brief"
  echo
  echo "State repo: \`$SR\` (board, checkpoints and metrics live here; the Stop"
  echo "hook commits and pushes to it automatically -- no need to be asked)."

  if [ -f "$SD/kanban.md" ]; then
    echo
    echo "### Open board items (\`state/global/kanban.md\`)"
    echo
    # Bullets under the first "## Backlog"-style heading onward, each folded
    # back onto one line -- board items wrap over several lines, and printing
    # only the first one turns "delete these three branches" into "delete".
    awk '
      /^## / { print ""; print "**" substr($0, 4) "**"; print "";
               inb = 1; buf = ""; next }
      !inb   { next }
      /^(- |[0-9]+\. )/ { if (buf != "") { print buf; if (++n >= 16) exit }
                          buf = $0; next }
      /^[ \t]*$/       { if (buf != "") { print buf; buf = ""
                                          if (++n >= 16) exit } next }
                        { if (buf != "") buf = buf " " $0 }
      END               { if (buf != "" && n < 16) print buf }
    ' "$SD/kanban.md" | sed 's/[[:space:]][[:space:]]*/ /g' | cut -c1-260
  fi

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
      echo "\`gate\` is expensive (open-ended, mid-flight, needs Mark to reload"
      echo "context). Prefer front-loading questions; board the rest."
    fi
  fi
} | emit

exit 0
