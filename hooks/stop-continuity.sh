#!/usr/bin/env bash
# Stop hook: record the session, then commit and push it. Every time.
#
# This is the load-bearing half of continuity. The standing orders say chats
# are ephemeral executors and durable state lives in files -- but a rule that
# only fires when someone says "wrap up" loses every session that ends any
# other way, which on an ephemeral cloud container is most of them. So this
# runs unconditionally on Stop and needs nothing from the conversation.
#
# It writes seven things, all derived from the transcript and from git:
# (each <dir>/<id>.* below sits in <dir>/<first two of id>/; lib-state.sh
# state_shard_path)
#   metrics/sessions/<id>.json    cost and shape of the session
#   metrics/decisions/<id>.jsonl  each decision pushed to the user, typed by cost
#   metrics/friction/<id>.jsonl   each friction event, typed by cost -- see
#                                  claude_prompts_scratch/state/global/log/
#                                  2026-08-21-friction-metric-spec.md
#   metrics/blocked/<id>.jsonl    each tool call the permission layer refused
#   log/auto/<date>-<repo>-<id>.md  a resumable checkpoint the next session reads
#   pickup/<start>-<id>.md        this session's pickup item, which /pickup reads
#   items/<id>.md                 this session's work item, via stop-item.py
#   curia/<id>/digest.md          a floor stamped on any curia digest the
#                                  session touched
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
LIVE="$SD/metrics/live"
SESSF=$(state_shard_path "$SD/metrics/sessions" "$sid.json" "$sid")
DECF=$(state_shard_path "$SD/metrics/decisions" "$sid.jsonl" "$sid")
FRICF=$(state_shard_path "$SD/metrics/friction" "$sid.jsonl" "$sid")
BLKF=$(state_shard_path "$SD/metrics/blocked" "$sid.jsonl" "$sid")
ckpt=$(state_shard_path "$SD/log/auto" "$today-$work_repo-${sid:0:8}.md" "$sid")
mkdir -p "${SESSF%/*}" "${DECF%/*}" "${FRICF%/*}" "${BLKF%/*}" "${ckpt%/*}" "$LIVE" 2>/dev/null || exit 0

# The per-session lock metrics-live.sh's nag read-modify-write also takes
# (dotfiles#161). state_lock installs no trap of its own (lib-state.sh), so
# this is where it is armed; a failed acquisition degrades to running
# unlocked rather than skipping the write -- a metrics hook never blocks Stop.
# archivable_reasons() runs inside $(...) below, so the home line it fetches
# comes back through this file (lib-state.sh), not a variable; the pickup
# item reads it rather than paying the gh round trip again. Fresh per Stop.
ARCHIVABLE_HOME_FILE="${TMPDIR:-/tmp}/claude-stop-home.$$"
rm -f "$ARCHIVABLE_HOME_FILE" 2>/dev/null
# One exit path, so a later step extends it rather than retyping it.
on_exit() {
  state_unlock; rm -f "$ARCHIVABLE_HOME_FILE" 2>/dev/null
}
trap on_exit EXIT TERM INT

# Commit count comes from git, never from grepping the transcript for
# "git commit": a heredoc that writes a script containing that string is
# indistinguishable from actually running it.
started=$(printf '%s' "$metrics" | jq -r '.session.started_at // empty')
ncommits=0
[ -n "$work_root" ] && ncommits=$(git -C "$work_root" rev-list --count \
  --since="${started:-1 day ago}" HEAD 2>/dev/null || echo 0)

printf '%s\n' "$metrics" \
  | jq -c --argjson c "${ncommits:-0}" '.session + {commits: $c}' \
  > "$SESSF"
printf '%s\n' "$metrics" | jq -c '.decisions[]' > "$DECF"
printf '%s\n' "$metrics" | jq -c '.friction[]' > "$FRICF"
printf '%s\n' "$metrics" | jq -c '.blocked[]' > "$BLKF"

# The live snapshot has served its purpose; the finished session file
# supersedes it, so drop it rather than leaving two records of one session.
# Locked against a concurrent metrics-live.sh writing the same path (#161
# finding 4); a lock that could not be taken still gets the delete, just
# unprotected -- deleting nothing is not a safer failure than a stale file.
state_lock "$LIVE/$sid.lock"
rm -f "$(state_shard_path "$LIVE" "$sid.json" "$sid")" 2>/dev/null
state_unlock
bash "$HOOK_DIR/metrics-rollup.sh" 2>/dev/null || true

# ---------------------------------------------------------------- checkpoint
# $ckpt is set above, beside the metrics paths.

# The resume block (dotfiles#110) is the one part of this file a *model*
# writes, and this hook rewrites the whole file on every Stop -- so it has to
# be lifted out of the old copy and put back, or the next Stop silently eats
# the hand-off the model was told to write. Everything from the `## Resume`
# heading to the next `## ` heading is carried verbatim, including the
# `- consumed:` marker a resuming session appends. Locked (#161 finding 2):
# metrics-live.sh's resume_ckpt() greps this same file, and the truncate
# below must not land mid-read.
state_lock "$LIVE/$sid.lock"
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

  rate=$(decision_rate "$(printf '%s' "$metrics" | jq -r '.session.decisions.total // 0')" \
           "$(printf '%s' "$metrics" | jq -r '.session.prompt_span_seconds // 0')")
  [ -n "$rate" ] && echo "- decision rate: $rate"

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
state_unlock

# One pusher at a time. Parallel sessions are the norm, and two concurrent
# rebase-and-push loops in the same worktree corrupt each other's index.
# The EXIT trap's state_unlock releases it.
state_lock_wait "$STATE_PUSH_LOCK" 90 || exit 0

# ------------------------------------------------------------ work repo
# Salvage whatever the session left uncommitted in the repo it worked on:
# commit it to this session's own `wip/<session-id>` ref and push that, never
# the branch the session is working on. Silent when there is nothing to do;
# every refusal after that is named in the checkpoint so it can carry whatever
# detail turns out to be useful.
sc_note() { printf '\n## Stop-commit\n\n%s\n' "$1" >> "$ckpt"; }

# Whether a commit made here should be signed: yes exactly when this machine
# has a signing key, the same test no-unsigned-push.sh uses (`git config
# user.signingkey`) so the two can never disagree. A commit made unsigned on a
# machine with a key is what that guard then refuses to push, forcing every
# other session here to re-sign it; a cloud VM has no key and stays unsigned.
# Prints the value for `-c commit.gpgsign=`. (The work-repo salvage commit
# below does not use this: it is fail-closed and forces `true`, keyless or not.)
sign_if_key() {
  if git -C "$1" config user.signingkey >/dev/null 2>&1; then echo true; else echo false; fi
}

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
#   4. this session's state is committed to the state repo -- locally is
#      enough on a machine that keeps its clone, and the push batches. A cloud
#      VM's clone dies with the VM, so there the push must also succeed.
#      Other sessions' unpushed commits in the same clone are theirs, never a
#      reason here. Passed in by the caller: not known until the bottom.
# "Could not verify" is never a pass, here as in the gate.
#
# This is the one verdict. metrics-live.sh's 📦 notice runs after this hook
# (stop-sequence.py) and reads it back from the metrics record, verdict_at
# included, rather than computing its own (dotfiles#149's second answer).
verdict=""
_archivable_reasons=""
_archivable_reasons_cached=0
set_verdict() {
  reasons=""
  add_reason() { reasons="${reasons:+$reasons, }$1"; }

  # Cached across calls: nothing about work_root changes between the salvage
  # and the state-repo push below, and the home check costs a `gh` round
  # trip. archivable_reasons() is lib-state.sh's -- the home/dirty/unpushed
  # check shared with metrics-live.sh's live nag, so the two can never
  # disagree about what "archivable" means (#149).
  if [ "$_archivable_reasons_cached" -eq 0 ]; then
    if [ -n "$work_root" ]; then
      _archivable_reasons=$(archivable_reasons "$work_root" "$work_branch" "$sid")
    else
      # The label metrics-live.sh's notice used before it read this verdict
      # back; "no PR and no pointer for \`\`" named a branch that isn't there.
      _archivable_reasons="not a git repo"
    fi
    _archivable_reasons_cached=1
  fi
  reasons="$_archivable_reasons"
  [ -n "${1:-}" ] && add_reason "$1"

  if [ -n "$reasons" ]; then verdict="not archivable: $reasons"; else verdict="archivable"; fi

  # Substitute rather than append: the line is at a known place and a second
  # verdict line would be a second answer.
  tmpc="$ckpt.verdict.$$"
  if awk -v v="**Verdict:** $verdict" '
       !done && /^\*\*Verdict:\*\* / { print v; done = 1; next } { print }
     ' "$ckpt" > "$tmpc" 2>/dev/null; then mv -f "$tmpc" "$ckpt" 2>/dev/null; else rm -f "$tmpc"; fi

  sf="$SESSF"
  if [ -f "$sf" ]; then
    tmpj="$sf.$$"
    if jq -c --arg v "$verdict" --argjson at "$(date -u +%s)" \
         '. + {verdict: $v, verdict_at: $at}' "$sf" > "$tmpj" 2>/dev/null; then
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
  # Settled policy, ruled by Solace on 2026-09-22 in issue #61: there is no
  # policy table and none is coming. The conservative default lives here, in
  # this public repo, reviewable beside the code it governs; the only inputs
  # from outside are reduce-only (CLAUDE_STOP_COMMIT=off, the CI refusal), so
  # nothing outside this file can grant the hook privilege it does not have.
  # Only the private state repo goes direct to main -- its own code path at
  # the bottom of this script, not a policy entry -- and the fallback for
  # everything else is the `wip/<session>` ref below, never the session's own
  # branch. These refusals fail closed on purpose: the files stay on disk,
  # with the reason in the checkpoint.
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
  # Never from CI. The shared PR reviewer runs Claude Code inside GitHub
  # Actions with this hook seeded from main, on a checkout whose .claude/
  # paths claude-code-action has restored to the base branch's versions, with
  # an app token that can push. Its Stop has nothing to salvage, and what it
  # did salvage were the "wip: session ... at Stop" reverts of dotfiles#196.
  if [ -n "${GITHUB_ACTIONS:-}" ] || [ -n "${CI:-}" ]; then
    sc_note "refused: running under CI (GITHUB_ACTIONS/CI set); a bot's checkout is not a session's work"; return 0
  fi
  # Never on top of a stale base. If the remote has moved since this checkout
  # last synced (a re-push by hand, another session, anything), the push
  # below would be rejected as non-fast-forward and the note would tell a
  # reader to "push by hand" -- and the obvious hand push of a stale base is
  # a force-push over the newer work. Fetch and check first.
  if timeout 60 git -C "$work_root" fetch -q origin "$work_branch" >/dev/null 2>&1 \
     && git -C "$work_root" rev-parse -q --verify "refs/remotes/origin/$work_branch" \
          >/dev/null 2>&1; then
    behind=$(git -C "$work_root" rev-list --count \
                HEAD.."origin/$work_branch" 2>/dev/null)
    if [ -n "$behind" ] && [ "$behind" -gt 0 ] 2>/dev/null; then
      sc_note "refused: \`$work_branch\` is $behind commit(s) behind \`origin/$work_branch\`; not committing on a stale base"
      return 0
    fi
  fi
  # Never a revert of the branch's own work. The tree can be "dirty" because
  # something put the base branch's version of a file back over the branch's
  # -- claude-code-action's restore above, a tool writing from a stale copy
  # -- and committing that publishes a reversion the push cannot detect: it
  # is a fast-forward. So fetch base (a stale tracking ref would compare
  # against content nobody restored) and, for every modified tracked file
  # the branch had changed, refuse if the working copy now matches base byte
  # for byte, naming the files. A session that really wants base's content
  # back commits it by hand.
  base=$(git -C "$work_root" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)
  base="${base:-origin/main}"
  git -C "$work_root" rev-parse -q --verify "$base" >/dev/null 2>&1 || base=origin/master
  timeout 60 git -C "$work_root" fetch -q origin "${base#origin/}" >/dev/null 2>&1
  if git -C "$work_root" rev-parse -q --verify "$base" >/dev/null 2>&1; then
    reverted=""
    while IFS= read -r f; do
      [ -n "$f" ] || continue
      # The branch changed this file, and the working copy is base's again.
      git -C "$work_root" diff --quiet "$base" HEAD -- "$f" 2>/dev/null && continue
      if git -C "$work_root" diff --quiet "$base" -- "$f" 2>/dev/null; then
        reverted="$reverted $f"
      fi
    done <<EOF
$(git -C "$work_root" diff --name-only HEAD -- . 2>/dev/null)
EOF
    if [ -n "$reverted" ]; then
      sc_note "refused: the working tree puts \`$base\`'s version back over this branch's changes to:$reverted -- that is a revert, not new work; not committing"
      return 0
    fi
  fi

  # dotfiles#280: a worktree checked out before some upstream commit deleted
  # a file still carries that file on disk, untracked, and `git add -A`
  # cannot tell it from real new work. Path history alone doesn't settle it
  # either -- a branch that itself added, deleted and is now legitimately
  # recreating the same path leaves an identical trail. What distinguishes
  # the two is content: only when the untracked file was tracked at some
  # commit in HEAD's own history, is missing from `$base`, *and* the working
  # copy still matches that commit's content byte for byte is it the old
  # leftover rather than new work -- a session's freshly written file
  # essentially never matches old bytes by chance. A shallow checkout can
  # hide the commit that first added a long-lived path, so unshallow first;
  # unable to, refuse rather than guess. Paths are read NUL-delimited so
  # control characters and non-ASCII names survive intact.
  if git -C "$work_root" rev-parse -q --verify "$base" >/dev/null 2>&1; then
    if [ "$(git -C "$work_root" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ] \
       && ! timeout 60 git -C "$work_root" fetch -q --unshallow origin >/dev/null 2>&1; then
      sc_note "refused: repo is shallow and could not be unshallowed -- can't tell a real stale leftover from new work; not committing"
      return 0
    fi
    stale=""
    while IFS= read -r -d '' f; do
      [ -n "$f" ] || continue
      ever_tracked=$(git -C "$work_root" log -1 --format=%H HEAD -- "$f" 2>/dev/null)
      [ -n "$ever_tracked" ] || continue
      git -C "$work_root" cat-file -e "$base:$f" 2>/dev/null && continue
      # The last commit to touch the path may be the one that deleted it, so
      # there is no blob there to compare -- fall back to its parent, the
      # last commit where the path actually existed.
      last_live="$ever_tracked"
      git -C "$work_root" cat-file -e "$last_live:$f" 2>/dev/null || last_live="$last_live^"
      cmp -s <(git -C "$work_root" show "$last_live:$f" 2>/dev/null) "$work_root/$f" || continue
      stale="$stale $f"
    done < <(git -C "$work_root" ls-files -z --others --exclude-standard 2>/dev/null)
    if [ -n "$stale" ]; then
      sc_note "refused: untracked path(s) were tracked in this branch's history, are gone from \`$base\` now, and still match their last tracked content -- stale leftovers from before this checkout last synced, not new work; not committing:$stale"
      return 0
    fi
  fi

  # --- the commit: repo hooks run as configured, signing is required -------
  # `commit.gpgsign=true` rather than the machine's setting: a cloud session
  # has no signing key, so "as configured" meant unsigned, and the salvage
  # commit is how unsigned commits kept reaching open pull requests. Fail
  # closed -- the commit is refused and the files are left for a machine that
  # can sign.
  #
  # The commit is made on the current branch because that is the only way the
  # repo's own hooks and signing config run over it -- and it is moved straight
  # off again, below, before anything is pushed. The branch never keeps it.
  wip_ref="wip/$sid"
  head_before=$(git -C "$work_root" rev-parse HEAD 2>/dev/null)
  if [ -z "$head_before" ] \
     || ! git -C "$work_root" add -A >/dev/null 2>&1 \
     || ! timeout 30 git -C "$work_root" -c commit.gpgsign=true commit -q \
          -m "wip: session ${sid:0:8} at Stop ($today)" \
          -m "Co-Authored-By: Claude <noreply@anthropic.com>" >/dev/null 2>&1; then
    git -C "$work_root" reset -q >/dev/null 2>&1
    sc_note "refused: commit failed (hook or signing) — files left as they were"; return 0
  fi

  # --- and off the branch again: the destination is this session's wip ref --
  # dotfiles#285, and the #61 ruling behind it. The session's branch is the
  # head of an open PR; a machine commit pushed there is what #177, #196 and
  # #280 have in common, and no reader can tell it from work a human meant to
  # publish. So the commit lands on `refs/heads/wip/<session-id>` -- a ref no
  # PR points at, named for the one session that writes it -- and the branch
  # is put back where it was with a mixed reset, which leaves the files in the
  # working tree exactly as the session left them. Salvage, not publication:
  # the next session picks the ref up from the checkpoint.
  salvaged=$(git -C "$work_root" rev-parse HEAD 2>/dev/null)
  git -C "$work_root" update-ref "refs/heads/$wip_ref" "$salvaged" >/dev/null 2>&1
  wrote_ref=$?
  # Unconditional, and before the ref write is judged: whatever else happened,
  # the work branch must not be left carrying the commit.
  if ! git -C "$work_root" reset -q "$head_before" >/dev/null 2>&1; then
    sc_note "committed \`${salvaged:-?}\` but could not put \`$work_branch\` back at \`$head_before\` — that commit is sitting on the branch; move or drop it before pushing"
    return 0
  fi
  if [ "$wrote_ref" -ne 0 ]; then
    sc_note "refused: could not write \`refs/heads/$wip_ref\` — nothing committed, files left as they were"; return 0
  fi

  # --force, and only ever this ref: `wip/<session-id>` has exactly one
  # writer, and each Stop's snapshot is a sibling of the last (same parent,
  # supersetting content), so a fast-forward push would fail from the second
  # Stop of every session onwards.
  if timeout 120 git -C "$work_root" push -q --force origin -- \
       "refs/heads/$wip_ref:refs/heads/$wip_ref" >/dev/null 2>&1; then
    sc_note "salvaged to \`$wip_ref\` and pushed it (\`$salvaged\`); \`$work_branch\` is untouched and the files are still in the working tree"
  else
    sc_note "salvaged to \`$wip_ref\` (\`$salvaged\`) but the push failed — the commit is local only; \`$work_branch\` is untouched"
  fi
}
sc_salvage
# After the salvage, not before: the verdict has to describe the tree the
# salvage leaves behind. It leaves it dirty on purpose -- the work is safe on
# the wip ref, not landed on the branch -- so "worktree dirty" stays the truth
# and the session is not archivable until a human lands it.
set_verdict

# The session claim stamp on the branch's card (dotfiles#287). Archivable
# means this session is done with the branch, so the claim comes off; anything
# else means it is still holding it, so the timestamp is bumped -- which is
# what makes another machine able to tell a live session from a dead one.
#
# Free when this session never claimed anything: both paths read a per-session
# record under TMPDIR first and return without a network call when there is
# none, and the refresh is debounced besides. Stop fires on every turn, so
# that has to stay true.
if [ -n "$work_root" ] && [ -x "$HOOK_DIR/claim-stamp.sh" ]; then
  if [ "$verdict" = archivable ]; then
    sh "$HOOK_DIR/claim-stamp.sh" release -C "$work_root" "$sid" >/dev/null 2>&1 || true
  else
    sh "$HOOK_DIR/claim-stamp.sh" refresh -C "$work_root" "$sid" >/dev/null 2>&1 || true
  fi
fi

# ------------------------------------------------------- the pickup item
# One item per session in pickup/, which /pickup reads in place of the old
# checkpoint resume block (dotfiles#110). The resume block depended on a
# model remembering to write it, and a session that ends any other way --
# context ceiling, a closed laptop, a reaped container -- hands off to
# nobody. This needs nothing from the model: status, branch state, PR,
# model and the first line of the last user prompt are all machine facts,
# and `pickup-list` shows them newest first. The body is the hand-off a
# model may write over the hook's default (the prompt line); on later
# Stops the hook only replaces a body that still reads exactly as it last
# set it, so an edited body survives every rewrite and the model never has
# to flag that it edited.
#
# The id is the session's start minute plus its short id, so every Stop of
# a session finds the same file and two sessions never share one. `pr:` is
# looked up only while empty and only once the branch is on origin (a PR
# cannot exist before that), and a miss is cached ten minutes so a pushed
# branch with no PR does not pay a gh call every turn.
pi_branch_line=none; pi_pr=none; pi_file=""
pickup_item() {
  local dir id f start prompt body status \
        old_prompt old_body old_status old_pr old_until ust ust_desc dirty \
        home miss tmp
  dir="$SD/pickup"
  mkdir -p "$dir" 2>/dev/null || return 0
  start=$(printf '%s' "$metrics" | jq -r '.session.started_at // empty')
  [ -n "$start" ] || start=$now
  id="$(printf '%s' "$start" | sed -E 's/^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}).*/\1T\2-\3/')-${sid:0:8}"
  f="$dir/$id.md"; pi_file=$f
  prompt=$(printf '%s' "$metrics" | jq -r '.session.last_prompt // empty')

  old_prompt=""; old_body=""; old_status=""; old_pr=""; old_until=""
  if [ -f "$f" ]; then
    old_prompt=$(sed -n 's/^prompt: //p' "$f" | head -1)
    old_status=$(sed -n 's/^status: //p' "$f" | head -1)
    old_pr=$(sed -n 's/^pr: //p' "$f" | head -1)
    # Header only: a hand-off body may well hold a line starting "until: ".
    old_until=$(awk '/^---$/ { exit } sub(/^until: /, "") { print; exit }' "$f")
    old_body=$(awk 'f { print } /^---$/ { f = 1 }' "$f")
  fi

  body=$old_body
  if [ -z "$(printf '%s' "$body" | tr -d '[:space:]')" ] || [ "$body" = "$old_prompt" ]; then
    body=$prompt
  fi
  status=$old_status
  # A new prompt reopens a session's item: the last thing talked about is
  # what the next session picks up, whatever the item said before.
  { [ -z "$status" ] || [ "$prompt" != "$old_prompt" ]; } && status=open

  pi_pr=${old_pr:-none}
  if [ -n "$work_root" ]; then
    ust=$(unpushed_state "$work_root" "$work_branch")
    case "$ust" in
      'ahead '*)     ust_desc="${ust#ahead } ahead" ;;
      never-pushed)  ust_desc="never pushed" ;;
      safe)          ust_desc="nothing ahead" ;;
      *)             ust_desc="ahead unknown" ;;
    esac
    dirty=clean
    [ -z "$(git -C "$work_root" status --porcelain 2>/dev/null)" ] || dirty=dirty
    pi_branch_line="$work_repo $work_branch ($ust_desc, $dirty)"
    miss="${TMPDIR:-/tmp}/claude-pickup-pr-miss.$(printf '%s' "$sid" | tr -c 'A-Za-z0-9_-' '_')"
    if [ "$pi_pr" = none ] && [ "$ust" = 'ahead 0' ] && [ -x "$HOOK_DIR/branch-home-gate.sh" ] \
       && [ -z "$(find "$miss" -mmin -10 2>/dev/null)" ]; then
      # The verdict's own home check (archivable_reasons, lib-state.sh)
      # left its line in ARCHIVABLE_HOME_FILE; reuse it rather than paying
      # the gh round trip twice in one Stop.
      home=$(cat "$ARCHIVABLE_HOME_FILE" 2>/dev/null)
      [ -n "$home" ] || home=$(sh "$HOOK_DIR/branch-home-gate.sh" --check "$work_root" 2>/dev/null)
      case "$home" in
        'home: https://'*) pi_pr=$(printf '%s' "$home" | sed 's/^home: //' | grep -oE '^https://[^ ]+') ;;
        *) : > "$miss" 2>/dev/null ;;
      esac
      [ -n "$pi_pr" ] || pi_pr=none
    fi
  fi

  tmp="$f.$$"
  {
    printf 'status: %s\nupdated: %s\nsession: %s\nmodel: %s\n' \
      "$status" "$now" "$sid" \
      "$(printf '%s' "$metrics" | jq -r '.session.model // "?"')"
    printf 'branch: %s\npr: %s\nwhere: %s\n' \
      "$pi_branch_line" "$pi_pr" "${ckpt#"$SD"/}"
    # until: is written by a model or the user (a date, an event or a PR/issue
    # link); the hook only carries it across rewrites, and writes no empty
    # line for an item that has none.
    [ -z "$old_until" ] || printf 'until: %s\n' "$old_until"
    printf 'prompt: %s\n---\n%s\n' "$prompt" "$body"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "$f" 2>/dev/null || rm -f "$tmp" 2>/dev/null
}
pickup_item

# ------------------------------------------------------- the session's item
# The session's record as one work item in items/ (requirements section 14):
# minted at its first Stop, or written onto the item it claimed, before the
# state commit below so this Stop commits it. The deciding is Python
# (stop-item.py); every write goes through bin/work-item. It fails open: its
# one outcome line, or why it did not run, goes in the checkpoint, and the
# pickup item above stands either way.
si_out=$(timeout 60 python3 "$HOOK_DIR/stop-item.py" --session "$sid" \
  --items "$SD/items" --pickup "$pi_file" --pr "$pi_pr" --checkpoint "$ckpt" \
  --work-root "$work_root" --repo "$work_repo" --started "$started" \
  --model "$(printf '%s' "$metrics" | jq -r '.session.model // empty')" 2>/dev/null) || true
printf '\n## Session item\n\n%s\n' "${si_out:-failed: stop-item.py did not run}" >> "$ckpt" 2>/dev/null

# ------------------------------------------------------- curia digests
# A session that touched a curia -- a state/global/curia/<id> path, a
# `/curia <id>` or `confer <id>` in the transcript -- leaves the machine
# floor on that curia's digest.md, so a sitting that dies any way at all
# still hands off. One write per Stop, under the pickup item's body-ownership
# protocol: a floor block at the end of "Where this stands" (last touched,
# branch, PR), hook-owned by its markers, model text above it untouched.
# The user's words are not written here: curia-roll.py appends them to the
# curia's roll.md, and digest.md refers to them by stamp.
curia_floor() {  # curia_floor <digest.md>
  local t tmp
  t=$1; tmp="$t.$$"
  awk -v now="$now" -v sid8="${sid:0:8}" -v model="$cu_model" \
      -v branch="$pi_branch_line" -v pr="$pi_pr" '
    function floor() {
      print "<!-- floor: stop-continuity.sh; text above survives, this block does not -->"
      print "- last touched: " now " \302\267 session " sid8 " \302\267 " model
      print "- branch: " branch " \302\267 pr: " pr
      print "<!-- /floor -->"
    }
    /^<!-- floor/ { drop = 1; next }
    /^<!-- \/floor -->$/ { drop = 0; next }
    drop { next }
    { lines[++n] = $0 }
    END {
      ws = 0; ins = 0
      for (i = 1; i <= n; i++) {
        if (!ws) { if (lines[i] ~ /^## Where this stands/) ws = i }
        else if (lines[i] ~ /^## /) { ins = i; break }
      }
      for (i = 1; i <= n; i++) {
        if (ins && i == ins) { floor(); print "" }
        print lines[i]
      }
      if (!ins) floor()
    }
  ' "$t" > "$tmp" 2>/dev/null && mv -f "$tmp" "$t" 2>/dev/null || rm -f "$tmp" 2>/dev/null
}
cu_model=$(printf '%s' "$metrics" | jq -r '.session.model // "?"')
for cu_ref in $(printf '%s' "$metrics" | jq -r '.session.curia_refs[]? // empty'); do
  cu_thread="$SD/curia/$cu_ref/digest.md"
  # thread.md is the name before digest.md; read it until every curia is moved.
  # roll.md is the words log, written only by its hook: never touched here.
  [ -f "$cu_thread" ] || cu_thread="$SD/curia/$cu_ref/thread.md"
  [ -f "$cu_thread" ] || continue
  curia_floor "$cu_thread"
done

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

# Everything under state/ goes in, the board's items/ included.
git add state/ >/dev/null 2>&1
git diff --cached --quiet 2>/dev/null && exit 0   # nothing changed

# Bounded like the salvage commit: signing calls out to gpg or ssh-agent, and a
# locked agent must not hang the Stop. A failed signature is not retried
# unsigned -- that is the commit the push guard refuses; the state stays staged
# for the next Stop and the verdict says why.
timeout 30 git -c user.name="${GIT_AUTHOR_NAME:-Claude}" \
    -c user.email="${GIT_AUTHOR_EMAIL:-noreply@anthropic.com}" \
    -c commit.gpgsign="$(sign_if_key .)" \
    commit -q -m "State: $work_repo session ${sid:0:8} ($today)" >/dev/null 2>&1 || { set_verdict "state-repo commit failed"; exit 0; }

# Debounce the push, not the commit: every Stop still commits locally (cheap,
# never lost), but this clone pushes at most once per debounce window, however
# many sessions stop. A cloud session pushes whenever archivable, so its last
# commit is never left on a VM about to be reaped; a local one batches, because
# its commit is already safe in the clone and a later Stop carries it.
#
# The stamp lives in the clone's git dir, never in the tracked tree. Under
# state/ it was committed by the next Stop, shared with every other machine,
# and rewritten by any `pull --rebase --autostash` that brought in another
# machine's stamp -- or left as conflict markers, which read as "never pushed"
# and let the next Stop push at once. It records the attempt, not the success:
# a push that keeps failing is retried once per window, not on every Stop.
cloud=0; [ "${CLAUDE_CODE_REMOTE:-}" = true ] && cloud=1
# "$SR/.git" is the directory state_repo found, not a git query that can come
# back empty and put the stamp at the filesystem root.
PUSH_SENTINEL="$SR/.git/claude-last-state-push"
debounce_secs=300
if { [ "$cloud" -eq 0 ] || [ "$verdict" != "archivable" ]; } && [ -f "$PUSH_SENTINEL" ]; then
  last_push=$(cat "$PUSH_SENTINEL" 2>/dev/null || echo 0)
  now_epoch=$(date -u +%s)
  case "$last_push" in ''|*[!0-9]*) last_push=0 ;; esac
  if [ $((now_epoch - last_push)) -lt "$debounce_secs" ]; then
    exit 0   # committed locally; next push (debounced or archivable) carries it
  fi
fi
date -u +%s > "$PUSH_SENTINEL" 2>/dev/null

for attempt in 1 2; do
  # A conflicted rebase left in place wedges this clone for every later Stop
  # and every hand commit; back out, and let the push below fail and say so.
  timeout 120 git pull --rebase --autostash -q >/dev/null 2>&1 \
    || git rebase --abort >/dev/null 2>&1
  timeout 120 git push -q origin HEAD >/dev/null 2>&1 && exit 0
  sleep $((attempt * 3))
done
# In the cloud the optimistic verdict is now known to be wrong. Correcting it
# leaves the checkpoint one commit behind the state repo -- the next Stop
# carries both the correction and this commit. Locally the commit is the
# promise, and it held.
[ "$cloud" -eq 1 ] && set_verdict "state-repo push failed"
exit 0
