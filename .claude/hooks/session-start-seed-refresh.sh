#!/usr/bin/env bash
# SessionStart hook: re-run the cloud seed so a reused container tracks this
# repo instead of the commit it was provisioned from.
#
# The environment's setup script runs once, when the container is created,
# and the container is then checkpointed and reused. So without this a rule
# edited here reaches only the sessions that get a cold VM -- and the ones
# that don't look identical to the ones that do, which is the failure this
# repo has already been bitten by twice (the deleted hook that kept running,
# and the settings.json fallback that ran a stranger's copy).
#
# What it can and cannot do, and the difference matters:
#   - hooks, rules/ and settings.json are read from disk when they fire, so a
#     refresh here reaches THIS session for everything after session start.
#   - CLAUDE.md was already loaded before this hook ran. A change to it would
#     otherwise sit on disk unread until the next session, so when the
#     refresh actually rewrites it the new copy is emitted as
#     additionalContext. That costs a second copy in context, which is why it
#     is emitted only on the sessions where it changed -- rare by
#     construction, since most refreshes change nothing at all.
#
# Remote-only. On a real machine yadm owns $HOME and the installer refuses
# there anyway, but returning before the network call keeps a local session
# start free of it.
set -uo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = true ] || exit 0

SEED="${DOTFILES_SEED:-$HOME/.local/share/dotfiles-seed}"
SETUP="$SEED/.local/bin/cloud-session-setup.sh"
ORDERS="$HOME/.claude/CLAUDE.md"

[ -x "$SETUP" ] || [ -f "$SETUP" ] || exit 0

before=$(cksum <"$ORDERS" 2>/dev/null || echo absent)

# The installer's own progress lines are for a setup-script log, not for a
# session's context window: stdout here is charged to every session. Keep
# them out and let the exit status carry the outcome.
CLOUD_SESSION=1 sh "$SETUP" >/dev/null 2>&1

after=$(cksum <"$ORDERS" 2>/dev/null || echo absent)

[ "$before" = "$after" ] && exit 0
[ "$after" = absent ] && exit 0

command -v jq >/dev/null 2>&1 || exit 0

{
  echo "## Standing orders were refreshed after this session started"
  echo
  echo "\`~/.claude/CLAUDE.md\` changed on the seed refresh, so the copy loaded"
  echo "at session start is stale. This is the current one; it supersedes it."
  echo
  cat "$ORDERS"
} | jq -Rn --rawfile ctx /dev/stdin \
  '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$ctx}}'
