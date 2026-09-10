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
#   metrics/decisions/<id>.jsonl  each decision pushed to the user, typed by cost
#   metrics/friction/<id>.jsonl   each friction event, typed by cost -- see
#                                  claude_prompts_scratch/state/global/log/
#                                  2026-08-21-friction-metric-spec.md
#   metrics/blocked/<id>.jsonl    each tool call the permission layer refused
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
  --arg cwd "$cwd" --arg now "$now" --arg slug "$today-$work_repo-${sid:0:8}" \
  -f "$JQPROG" "$tp" 2>/dev/null) || exit 0
[ -n "$metrics" ] || exit 0

SD=$(state_dir)
mkdir -p "$SD/metrics/sessions" "$SD/metrics/decisions" "$SD/metrics/friction" "$SD/metrics/blocked" \
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
printf '%s\n' "$metrics" | jq -c '.blocked[]' > "$SD/metrics/blocked/$sid.jsonl"

# The live snapshot has served its purpose; the finished session file
# supersedes it, so drop it rather than leaving two records of one session.
rm -f "$SD/metrics/live/$sid.json" 2>/dev/null
bash "$HOOK_DIR/metrics-rollup.sh" 2>/dev/null || true

# ---------------------------------------------------------------- checkpoint
ckpt="$SD/log/auto/$today-$work_repo-${sid:0:8}.md"

# The resume block (dotfiles#110) is the one part of this file a *model*
# writes, and this hook rewrites the whole file on every Stop -- so it has to
# be lifted out of the old copy and put back, or the next Stop silently eats
# the hand-off the model was told to write. Everything from the `## Resume`
# heading to the next `## ` heading is carried verbatim, including the
# `- consumed:` marker a resuming session appends.
resume_block=""
[ -f "$ckpt" ] && resume_block=$(awk '
  /^## Resume[[:space:]]*$/ { f = 1; print; next }
  f && /^## / { exit }
  f { print }
' "$ckpt" 2>/dev/null)

{
  echo "# Auto-checkpoint — $work_repo @ \`$work_branch\`"
  echo
  # The verdict is the first thing in the file because it is the one line a
  # reader needs: archivable means archive, no wrap-up. It cannot be computed
  # yet -- the salvage commit and the state-repo push have not happened -- so
  # it starts as a refusal and set_verdict() substitutes it below. A Stop that
  # dies in between leaves this line, which is the truth: nothing was decided.
  echo "**Verdict:** not archivable: the Stop hook did not finish"
  echo
  echo "Machine-written by \`stop-continuity.sh\`; rewritten on every Stop, so"
  echo "this is the session's current state, not a history. Narrative entries"
  echo "belong in \`log/\` proper."
  echo
  [ -n "$work_root" ] && echo "- worktree \`$work_root\`"
  printf '%s' "$metrics" | jq -r '.session |
    "- session `\(.session_id)` · \(.model // "?") · started \(.started_at // "?")",
    "- \(.user_turns) prompts, \(.assistant_turns) turns, \(.tool_calls) tool calls",
    "- \(.output_tokens) output tokens, context peak \(.context_peak)",
    "- decisions: \(.decisions.total) total (\(.decisions.scoping) scoping, \(.decisions.inline) inline, \(.decisions.gate) gate)",
    "- friction: \(.friction.total) total (\(.friction.correction) correction, \(.friction.override) override, \(.friction.rebuke) rebuke, \(.friction.pushback) pushback)",
    "- blocked: \(.blocked.total // 0) tool calls refused (\(.blocked.classifier // 0) classifier, \(.blocked.rule // 0) rule, \(.blocked.user // 0) user-declined)"'

  if [ -n "$resume_block" ]; then
    echo
    printf '%s\n' "$resume_block"
  fi

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

  # branch-home-gate.sh writes one line per outcome to a per-session file
  # under TMPDIR; this is where it becomes durable. The checkpoint is
  # rewritten on every Stop, so the gate cannot append to it directly.
  bh="${TMPDIR:-/tmp}/claude-branch-home.$(printf '%s' "$sid" | tr -c 'A-Za-z0-9_-' '_')"
  if [ -s "$bh" ]; then
    echo
    echo "## Branch home"
    echo
    sed 's/^/- /' "$bh"
  fi

  dq=$(printf '%s' "$metrics" | jq -r '.decisions[] | "- (\(.type)) \(.question)"')
  if [ -n "$dq" ]; then
    echo
    echo "## Decisions pushed to the user"
    echo
    printf '%s\n' "$dq"
  fi
} > "$ckpt" 2>/dev/null

# One pusher at a time. Parallel sessions are the norm, and two concurrent
# rebase-and-push loops in the same worktree corrupt each other's index.
LOCK="${TMPDIR:-/tmp}/claude-state-push.lock"
exec 9>"$LOCK" 2>/dev/null || exit 0
flock -w 90 9 2>/dev/null || exit 0

# ------------------------------------------------------------ work repo
# Salvage whatever the session left uncommitted in the repo it worked on:
# commit to the current branch and push. Silent when there is nothing to
# do; every refusal after that is named in the checkpoint so it can carry
# whatever detail turns out to be useful.
sc_note() { printf '\n## Stop-commit\n\n%s\n' "$1" >> "$ckpt"; }

# ------------------------------------------------------------ the verdict
# set_verdict [extra reason] -- computes the archive verdict (dotfiles#110)
# and writes it into the checkpoint's placeholder line and into the session's
# metrics record. Idempotent: it rewrites whatever verdict line is already
# there, so it can be called again once the state-repo push has been tried.
#
# "wrap up" is expensive and was being paid every session, including sessions
# whose work already had a home. Archivable means archive; wrap up only when
# the session holds something no issue, PR or card carries. Four conditions,
# reasons named in this order:
#   1. the branch has a home -- an open PR, or a pointer card/issue (#108).
#      branch-home-gate.sh --check answers it, so this verdict and that gate
#      can never disagree about what counts as a home;
#   2. the worktree is clean;
#   3. nothing is unpushed;
#   4. the state-repo push succeeded (passed in by the caller, because it is
#      not known until the bottom of this script).
# "Could not verify" is never a pass, here as in the gate.
verdict=""
set_verdict() {
  reasons=""
  add_reason() { reasons="${reasons:+$reasons, }$1"; }

  # Cached across calls: the check costs a `gh` round trip and the branch's
  # home does not change between the salvage and the state-repo push.
  [ -n "${home:-}" ] || home=$(sh "$HOOK_DIR/branch-home-gate.sh" --check "$cwd" 2>/dev/null)
  case "$home" in
    home:*)       : ;;
    unverified:*) add_reason "branch home unverified (${home#unverified: })" ;;
    *)            add_reason "no PR and no pointer for \`$work_branch\`" ;;
  esac
  if [ -n "$work_root" ]; then
    [ -n "$(git -C "$work_root" status --porcelain 2>/dev/null)" ] && add_reason "worktree dirty"
    # Whether the branch holds work that exists nowhere else -- lib-state.sh
    # owns that question and its carve-outs, so this verdict and the one
    # metrics-live.sh draws cannot disagree (#149). Only the wording is here.
    ust=$(unpushed_state "$work_root" "$work_branch")
    case "$ust" in
      'ahead 0')   ;;
      'ahead '*)   add_reason "${ust#ahead } commit(s) unpushed" ;;
      unknown)     add_reason "could not count unpushed commits" ;;
      never-pushed)
        if [ "$work_branch" = HEAD ] || [ -z "$work_branch" ]; then
          add_reason "detached HEAD, no upstream to compare against"
        else
          add_reason "\`$work_branch\` has no upstream (never pushed)"
        fi
        ;;
    esac
  fi
  [ -n "${1:-}" ] && add_reason "$1"

  if [ -n "$reasons" ]; then verdict="not archivable: $reasons"; else verdict="archivable"; fi

  # Substitute rather than append: the line is at a known place and a second
  # verdict line would be a second answer.
  tmpc="$ckpt.verdict.$$"
  if awk -v v="**Verdict:** $verdict" '
       !done && /^\*\*Verdict:\*\* / { print v; done = 1; next } { print }
     ' "$ckpt" > "$tmpc" 2>/dev/null; then mv -f "$tmpc" "$ckpt" 2>/dev/null; else rm -f "$tmpc"; fi

  sf="$SD/metrics/sessions/$sid.json"
  if [ -f "$sf" ]; then
    tmpj="$sf.$$"
    if jq -c --arg v "$verdict" '. + {verdict: $v}' "$sf" > "$tmpj" 2>/dev/null; then
      mv -f "$tmpj" "$sf" 2>/dev/null
    else rm -f "$tmpj"; fi
  fi
}
sc_salvage() {
  # --- silent exits: the normal case for most sessions ---------------------
  # Not inside a git repo at all.
  [ -n "$work_root" ] || return 0
  # The state repo is committed by its own section below.
  [ "$work_root" != "$(state_repo 2>/dev/null)" ] || return 0
  # Deliberately switched off.
  [ "${CLAUDE_STOP_COMMIT:-on}" != off ] || return 0
  # Nothing uncommitted (tracked or untracked).
  [ -n "$(git -C "$work_root" status --porcelain 2>/dev/null)" ] || return 0

  # Re-read the branch: the value captured at hook start can be stale by now
  # if anything detached HEAD since (e.g. a hand-run abandon-branch.sh), and
  # pushing the name it used to have would put an abandoned branch straight
  # back on the remote.
  work_branch=$(git -C "$work_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

  # --- named refusals: something is dirty but we will not touch it ---------
  # These three cases are a provisional best-effort fallback, NOT a decided
  # policy. Real per-repo policy -- where it lives, which repos commit
  # direct to main, what the fallback should be -- is open in issue #61.
  # Don't treat what runs here as the intended design just because it runs.
  # dotfiles: the worktree is $HOME and only yadm's pre_commit gate may
  # commit there.
  if [ "$work_root" = "$HOME" ]; then
    sc_note "refused: checkout is \$HOME (yadm gate); not committing"; return 0
  fi
  # The default branch is never committed to unattended.
  case "$work_branch" in
    main|master|HEAD|"")
      sc_note "refused: on \`$work_branch\`; uncommitted work left in place"; return 0 ;;
  esac
  # Only a checkout Claude Code created: a .claude/worktrees path or a
  # claude/ branch. A human's checkout on a human branch is not ours to
  # commit into.
  case "$work_root" in */.claude/worktrees/*) claude_made=1 ;; *) claude_made= ;; esac
  [ "${work_branch#claude/}" != "$work_branch" ] && claude_made=1
  if [ -z "$claude_made" ]; then
    sc_note "refused: \`$work_root\` on \`$work_branch\` does not look Claude-made"; return 0
  fi
  # Nowhere to push.
  if ! git -C "$work_root" remote get-url origin >/dev/null 2>&1; then
    sc_note "refused: no origin remote"; return 0
  fi

  # --- the commit: repo hooks and signing run as configured ----------------
  if ! git -C "$work_root" add -A >/dev/null 2>&1 \
     || ! git -C "$work_root" commit -q \
          -m "wip: session ${sid:0:8} at Stop ($today)" \
          -m "Co-Authored-By: Claude <noreply@anthropic.com>" >/dev/null 2>&1; then
    git -C "$work_root" reset -q >/dev/null 2>&1
    sc_note "refused: commit failed (hook or signing) — files left as they were"; return 0
  fi
  if timeout 120 git -C "$work_root" push -q -u origin -- "$work_branch" >/dev/null 2>&1; then
    sc_note "committed and pushed to \`$work_branch\`"
  else
    sc_note "committed to \`$work_branch\` but push failed — push by hand"
  fi
}
sc_salvage
# After the salvage, not before: a session whose work this hook just committed
# and pushed is not "dirty, unpushed".
set_verdict

# ------------------------------------------------------------ state repo
state_is_repo || exit 0
SR=$(state_repo) || exit 0
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
      set_verdict "state repo not committed (git filter \`$f\` unconfigured)"
      exit 0
    fi
  done
fi

# The board is linted before it is staged. This hook commits and pushes at
# every Stop, so a card that restates a PR's state or a line ticked instead
# of deleted would be in history before anyone read it. A failing lint
# leaves the board's edits in the working tree and names them in the
# checkpoint; a missing lint is treated the same way, never as a pass.
board=state/global/kanban.md
board_ok=1
# If a human had already staged board edits, the unstage below must not eat
# them: remember the exact staged blob and put it back in the index once this
# hook is done committing.
board_pre_blob=
git diff --cached --quiet -- "$board" 2>/dev/null || board_pre_blob=$(git rev-parse ":$board" 2>/dev/null)
restore_board() {
  [ -n "$board_pre_blob" ] || return 0
  git update-index --cacheinfo "100644,$board_pre_blob,$board" >/dev/null 2>&1
}
if [ -n "$(git status --porcelain -- "$board" 2>/dev/null)" ]; then
  if [ -f "$HOOK_DIR/kanban-lint.sh" ]; then
    lint_out=$(sh "$HOOK_DIR/kanban-lint.sh" --diff "$SR" "$board" 2>&1) || board_ok=0
  else
    lint_out="kanban-lint.sh is missing from $HOOK_DIR, so the board could not be linted"; board_ok=0
  fi
  [ "$board_ok" = 1 ] || printf '\n## Board NOT committed\n\n`%s` failed kanban-lint; its edits stay uncommitted in the working tree (anything you had already staged for it is left staged). Fix or delete the lines, then commit by hand or let the next Stop try again.\n\n```\n%s\n```\n' "$board" "$lint_out" >> "$ckpt"
fi

# Before the add, so the correction is what gets committed.
[ "$board_ok" = 1 ] || set_verdict "board not committed (kanban-lint failed)"
git add state/ >/dev/null 2>&1
if [ "$board_ok" != 1 ]; then
  git reset -q -- "$board" >/dev/null 2>&1
  [ -n "$board_pre_blob" ] && trap restore_board EXIT
fi
git diff --cached --quiet 2>/dev/null && exit 0   # nothing changed

git -c user.name="${GIT_AUTHOR_NAME:-Claude}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-noreply@anthropic.com}" \
    -c commit.gpgsign=false \
    commit -q -m "State: $work_repo session ${sid:0:8} ($today)" >/dev/null 2>&1 || { set_verdict "state-repo commit failed"; exit 0; }

for attempt in 1 2; do
  timeout 120 git pull --rebase --autostash -q >/dev/null 2>&1
  if timeout 120 git push -q origin HEAD >/dev/null 2>&1; then
    exit 0
  fi
  sleep $((attempt * 3))
done
# The optimistic verdict is now known to be wrong. Correcting it leaves the
# checkpoint one commit behind the state repo -- the next Stop carries both
# the correction and this commit.
set_verdict "state-repo push failed"
exit 0
