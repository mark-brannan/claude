#!/usr/bin/env bash
# Shared helpers for the continuity hooks. Sourced, never run directly.
#
# The one job here is answering "where does durable state live on this
# machine?" without any hook having to guess. Every hook that writes state
# calls state_dir; every hook that reads it calls the same function, so a
# machine where the private repo is missing degrades identically everywhere
# instead of one hook writing to the repo and another to a local fallback.

# Resolve the private state repo's working tree, or empty if it isn't here.
#
# Order matters: an explicit env var wins, then the paths a cloud session
# checks out a source repo to, then the paths a real machine clones to.
# No cloning is attempted -- a SessionStart hook that clones a private repo
# would need credentials it cannot count on, and would stall session start
# on a network round trip. Absence is reported, not repaired.
state_repo() {
  local d
  for d in "${CLAUDE_STATE_REPO:-}" \
           /home/user/claude_prompts_scratch \
           /workspace/claude_prompts_scratch \
           "$HOME/claude_prompts_scratch" \
           "$HOME/src/claude_prompts_scratch" \
           "$HOME/Projects/claude_prompts_scratch" \
           "$HOME/code/claude_prompts_scratch"; do
    [ -n "$d" ] && [ -d "$d/.git" ] && { printf '%s' "$d"; return 0; }
  done
  return 1
}

# Directory that state files are written under, always. Falls back to a
# local, gitignored directory so a machine without the repo still keeps its
# own copy rather than silently dropping every line.
state_dir() {
  local repo
  if repo=$(state_repo); then
    printf '%s/state/global' "$repo"
  else
    printf '%s/.claude/state/global' "$HOME"
  fi
}

# True when state_dir is inside the git repo, i.e. worth committing.
state_is_repo() { state_repo >/dev/null 2>&1; }

# True when $1 appears as a whole branch-name token in text on stdin -- not
# merely as a substring. `-w` alone is not enough: branch names are built
# from hyphens too, so claude/homed-extra is a `-w` match for claude/homed.
# Extract every maximal run of branch-name characters and require one to
# equal the branch exactly. The charset is deliberately narrower than every
# character git allows in a branch name (no `~^:?*[\`, no non-ASCII): it
# exists to strip prose punctuation (a trailing period or comma) off a
# branch mention in a sentence, and `+`/`@` are the two git allows that
# never show up as that kind of padding. Shared by branch-home-gate.sh and
# worklist so a branch counts as pointed-at the same way in both.
names_branch() {
  grep -oE '[A-Za-z0-9._/+@-]+' | grep -qxF -- "$1"
}

# One JSON-string escaper for the hooks that source this. It takes its text as
# an argument, and falls back to sed/awk where jq is absent -- a hook that
# cannot emit its reason is a hook that fails open. Do not add a second
# json_str with a different signature: kanban-gate.sh once sourced this file
# and then shadowed it, and the two disagreed about stdin vs "$1".
json_str() {
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "$1" | jq -Rs .
  else
    printf '"%s"\n' "$(printf '%s' "$1" | tr '\t' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{ if (NR > 1) printf "\\n"; printf "%s", $0 }')"
  fi
}
block() { printf '{"decision":"block","reason":%s}\n' "$(json_str "$1")"; exit 0; }

# The set of tool calls that change git state, in one place.
#
# It lives here because three consumers have to agree on it: the PostToolUse
# matcher in settings.json, metrics-live.sh's "is this worth recomputing"
# filter, and measure-git-events.sh's pre-filter. When they disagreed the
# narrow one won by accident -- a `git push`, a `git reset`, a `git branch
# -D`, an MCP `push_files` or a `merge_pull_request` each changed the repo
# and none of them moved a counter until the Stop hook swept the transcript
# at the end of the session. A number that only becomes true afterwards is
# not a live number, and the git block the user actually reads never appeared at
# the moment the state changed.
#
# Deliberately NOT here: `git add`, `fetch`, `clone`, `remote`, `status`,
# `log`, `diff`. The first four are frequent and carry no decision; the rest
# are reads. Every entry costs a full jq pass over the transcript, so the
# line is drawn at "did the repo's history, refs or worktree move".
#
# Two shapes are matched: a shell command (Bash tool_input.command) and a
# bare tool name (any MCP tool that writes a repo, branch or PR).
git_event_re() {
  printf '%s' '\bgit\s+(commit|push|pull|merge|rebase|cherry-pick|revert|checkout|switch|branch|worktree|tag|stash|reset|restore|rm|mv|apply|am)\b|\bgh\s+(pr|release)\b|\b(yadm|dotsync)\b|create_pull_request|merge_pull_request|update_pull_request|update_pull_request_branch|push_files|create_or_update_file|delete_file|create_branch|create_repository|fork_repository'
}

# Answer "does this branch hold commits that exist nowhere but here?" for a
# repo root ($1) and the branch name ($2, `HEAD` or empty when detached).
#
# It lives here because two hooks have to agree on the answer: metrics-live.sh
# draws the ⎇ nag and the archival verdict from it, stop-continuity.sh's
# set_verdict decides from it whether the session is safe to kill. When each
# had its own copy they drifted -- #148 had to port two carve-outs back into
# metrics-live.sh that stop-continuity.sh had grown in #126 and #128/#143.
#
# Prints one word, plus a count for the first:
#   ahead <n>     an upstream exists; n commits are not on it (n may be 0)
#   unknown       an upstream exists, but the count could not be taken
#   never-pushed  no upstream, and there is work on the branch to lose
#   safe          no upstream, but nothing on the branch to lose
#
# The last two are the carve-outs. A detached HEAD whose commit already lives
# on some remote branch is not a hazard (#128/#143), and a named branch with
# no upstream is not one either until it is actually ahead of the default
# branch (#126) -- the same test branch-home-gate.sh applies before it looks
# for a home. `rev-list @{u}..HEAD` fails outright when there is no upstream,
# and the `|| echo 0` that used to swallow that read a never-pushed branch as
# fully pushed: the "lost work" failure one step earlier than #108/#110.
unpushed_state() {
  local root="$1" branch="$2" n base ahead

  if git -C "$root" rev-parse --verify -q --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    n=$(git -C "$root" rev-list --count '@{u}..HEAD' 2>/dev/null || printf '')
    [ -n "$n" ] && printf 'ahead %s' "$n" || printf 'unknown'
    return 0
  fi

  if [ "$branch" = HEAD ] || [ -z "$branch" ]; then
    [ -n "$(git -C "$root" branch -r --contains HEAD 2>/dev/null)" ] \
      && printf 'safe' || printf 'never-pushed'
    return 0
  fi

  base=$(git -C "$root" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)
  base="${base:-origin/main}"
  git -C "$root" rev-parse --verify -q "$base" >/dev/null 2>&1 || base=origin/master
  ahead=$(git -C "$root" rev-list --count "$base..HEAD" 2>/dev/null || printf 0)
  [ "${ahead:-0}" -gt 0 ] && printf 'never-pushed' || printf 'safe'
}

# archivable_reasons <work_root> <work_branch> -- the reasons a session on
# this branch is not yet archivable, comma-joined; empty when it is. Order:
# worktree dirty, unpushed commits, branch home.
#
# Lives here for the same reason unpushed_state does: metrics-live.sh's live
# nag and stop-continuity.sh's Stop-hook verdict must never disagree about
# what "archivable" means (dotfiles#149). Before this they didn't even
# agree on what a "home" is -- metrics-live.sh re-checked PR-or-kanban
# inline and never looked for a pointer issue, the one branch-home-gate.sh
# already finds.
#
# Requires $HOOK_DIR set by the caller: branch-home-gate.sh lives beside
# this file and is shelled out to, not sourced, so its own gate (which fires
# once per session, separately) and this read-only check never share state.
#
# Home is checked last, and only when dirty/unpushed are already clean: it's
# the one check here that can shell out to `gh` (up to two 30s calls in
# branch-home-gate.sh), so a dirty mid-work tree -- the common case, and the
# one Stop fires on every turn -- never pays that cost. Restores the
# short-circuit the pre-dotfiles#149 archivable() had.
#
# Not this function's job: "not a git repo" (there is no branch here to
# judge) and anything that only becomes true after a push is attempted --
# both are the caller's own facts to add.
archivable_reasons() {
  local work_root="$1" work_branch="$2" reasons="" home ust
  add_reason() { reasons="${reasons:+$reasons, }$1"; }

  [ -z "$(git -C "$work_root" status --porcelain 2>/dev/null)" ] || add_reason "worktree dirty"

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

  if [ -z "$reasons" ]; then
    home=$(sh "$HOOK_DIR/branch-home-gate.sh" --check "$work_root" 2>/dev/null)
    case "$home" in
      home:*)       : ;;
      unverified:*) add_reason "branch home unverified (${home#unverified: })" ;;
      *)            add_reason "no PR and no pointer for \`$work_branch\`" ;;
    esac
  fi

  printf '%s' "$reasons"
}
