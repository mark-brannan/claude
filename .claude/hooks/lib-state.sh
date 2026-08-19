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

json_str() { jq -Rn --rawfile f /dev/stdin '$f'; }
