#!/usr/bin/env bash
# Stop hook: record the session, then commit and push it. Every time.
#
# This is the load-bearing half of continuity. The standing orders say chats
# are ephemeral executors and durable state lives in files -- but a rule that
# only fires when someone says "wrap up" loses every session that ends any
# other way, which on an ephemeral cloud container is most of them. So this
# runs unconditionally on Stop and needs nothing from the conversation.
#
# It writes four things, all derived from the transcript and from git:
#   metrics/sessions/<id>.json    cost and shape of the session
#   metrics/decisions/<id>.jsonl  each decision pushed to Mark, typed by cost
#   metrics/friction/<id>.jsonl   each friction event, typed by cost -- see
#                                  claude_prompts_scratch/state/global/log/
#                                  2026-08-21-friction-metric-spec.md
#   log/auto/<date>-<repo>-<id>.md  a resumable checkpoint the next session reads
#
# One file per session, not one shared append-only log: parallel sessions are
# normal here, and per-session paths mean two of them never touch the same
# file and so never conflict on push.
#
# Always exits 0. A metrics hook that can fail a session is worse than no
# metrics hook.
set -uo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-state.sh
. "$HOOK_DIR/lib-state.sh"

command -v jq >/dev/null 2>&1 || exit 0

input=$(cat)
tp=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
sid=$(printf '%s' "$input" | jq -r '.session_id // empty')
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -n "$tp" ] && [ -f "$tp" ] || exit 0
[ -n "$sid" ] || exit 0
[ -n "$cwd" ] || cwd=$PWD

JQPROG="$HOOK_DIR/session-metrics.jq"
[ -f "$JQPROG" ] || exit 0

now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
today=$(date -u +%Y-%m-%d)

# Working repo (the one being worked on), distinct from the state repo.
work_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || echo "")
work_repo=$([ -n "$work_root" ] && basename "$work_root" || basename "$cwd")
work_branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

metrics=$(jq -s \
  --arg sid "$sid" --arg repo "$work_repo" --arg branch "$work_branch" \
  --arg cwd "$cwd" --arg now "$now" \
  -f "$JQPROG" "$tp" 2>/dev/null) || exit 0
[ -n "$metrics" ] || exit 0

SD=$(state_dir)
mkdir -p "$SD/metrics/sessions" "$SD/metrics/decisions" "$SD/metrics/friction" \
         "$SD/log/auto" 2>/dev/null || exit 0

# Commit count comes from git, never from grepping the transcript for
# "git commit": a heredoc that writes a script containing that string is
# indistinguishable from actually running it.
started=$(printf '%s' "$metrics" | jq -r '.session.started_at // empty')
ncommits=0
[ -n "$work_root" ] && ncommits=$(git -C "$work_root" rev-list --count \
  --since="${started:-1 day ago}" HEAD 2>/dev/null || echo 0)

printf '%s\n' "$metrics" \
  | jq -c --argjson c "${ncommits:-0}" '.session + {commits: $c}' \
  > "$SD/metrics/sessions/$sid.json"
printf '%s\n' "$metrics" | jq -c '.decisions[]' > "$SD/metrics/decisions/$sid.jsonl"
printf '%s\n' "$metrics" | jq -c '.friction[]' > "$SD/metrics/friction/$sid.jsonl"

# The live snapshot has served its purpose; the finished session file
# supersedes it, so drop it rather than leaving two records of one session.
rm -f "$SD/metrics/live/$sid.json" 2>/dev/null
bash "$HOOK_DIR/metrics-rollup.sh" 2>/dev/null || true

# ---------------------------------------------------------------- checkpoint
ckpt="$SD/log/auto/$today-$work_repo-${sid:0:8}.md"

{
  echo "# Auto-checkpoint — $work_repo @ \`$work_branch\`"
  echo
  echo "Machine-written by \`stop-continuity.sh\`; rewritten on every Stop, so"
  echo "this is the session's current state, not a history. Narrative entries"
  echo "belong in \`log/\` proper."
  echo
  printf '%s' "$metrics" | jq -r '.session |
    "- session `\(.session_id)` · \(.model // "?") · started \(.started_at // "?")",
    "- \(.user_turns) prompts, \(.assistant_turns) turns, \(.tool_calls) tool calls",
    "- \(.output_tokens) output tokens, context peak \(.context_peak)",
    "- decisions: \(.decisions.total) total (\(.decisions.scoping) scoping, \(.decisions.inline) inline, \(.decisions.gate) gate)",
    "- friction: \(.friction.total) total (\(.friction.correction) correction, \(.friction.override) override, \(.friction.rebuke) rebuke, \(.friction.pushback) pushback)"'

  if [ -n "$work_root" ]; then
    echo
    echo "## Commits this session"
    echo
    c=$(git -C "$work_root" log --oneline --since="${started:-1 day ago}" -20 2>/dev/null)
    [ -n "$c" ] && printf '%s\n' "$c" | sed 's/^/- /' || echo "- none"

    echo
    echo "## Uncommitted at Stop"
    echo
    u=$(git -C "$work_root" status --porcelain 2>/dev/null | head -40)
    [ -n "$u" ] && printf '```\n%s\n```\n' "$u" || echo "clean"

    up=$(git -C "$work_root" rev-list --count "@{u}..HEAD" 2>/dev/null || echo "")
    [ -n "$up" ] && [ "$up" != "0" ] && echo && echo "**$up commit(s) not pushed.**"
  fi

  dq=$(printf '%s' "$metrics" | jq -r '.decisions[] | "- (\(.type)) \(.question)"')
  if [ -n "$dq" ]; then
    echo
    echo "## Decisions pushed to Mark"
    echo
    printf '%s\n' "$dq"
  fi
} > "$ckpt" 2>/dev/null

# ------------------------------------------------------------ commit + push
state_is_repo || exit 0
SR=$(state_repo) || exit 0

# One pusher at a time. Parallel sessions are the norm, and two concurrent
# rebase-and-push loops in the same worktree corrupt each other's index.
LOCK="${TMPDIR:-/tmp}/claude-state-push.lock"
exec 9>"$LOCK" 2>/dev/null || exit 0
flock -w 90 9 2>/dev/null || exit 0

cd "$SR" 2>/dev/null || exit 0

# A fresh cloud clone has no git filters wired: the clean/smudge programs
# (sops and friends) are not on PATH, so `git add` through an unconfigured
# filter writes mangled content and the damage is only visible later. Refuse
# instead, and say so in the checkpoint rather than skipping quietly.
if [ -f .gitattributes ] && grep -qE '(^|[[:space:]])filter=' .gitattributes; then
  for f in $(sed -nE 's/.*[[:space:]]filter=([A-Za-z0-9_.-]+).*/\1/p' .gitattributes \
             | sort -u); do
    if ! git config --get "filter.$f.clean" >/dev/null 2>&1; then
      printf '\n**NOT COMMITTED** — git filter `%s` is declared in .gitattributes\n' "$f" >> "$ckpt"
      printf 'but not configured in this clone, so committing would mangle content.\n' >> "$ckpt"
      printf 'Run the repo'"'"'s filter setup, or commit by hand from a real machine.\n' >> "$ckpt"
      exit 0
    fi
  done
fi

git add state/ >/dev/null 2>&1
git diff --cached --quiet 2>/dev/null && exit 0   # nothing changed

git -c user.name="${GIT_AUTHOR_NAME:-Claude}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-noreply@anthropic.com}" \
    -c commit.gpgsign=false \
    commit -q -m "State: $work_repo session ${sid:0:8} ($today)" >/dev/null 2>&1 || exit 0

for attempt in 1 2; do
  timeout 120 git pull --rebase --autostash -q >/dev/null 2>&1
  if timeout 120 git push -q origin HEAD >/dev/null 2>&1; then
    exit 0
  fi
  sleep $((attempt * 3))
done
exit 0
