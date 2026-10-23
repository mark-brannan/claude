#!/usr/bin/env bash
# Denies GitHub's server-side "Update branch", whichever tool asks for it.
#
# Why: on a repo whose ruleset requires signed commits, `gh pr update-branch
# --rebase` silently destroys them. GitHub signs merge commits and commits
# authored in its web UI, but it does NOT re-sign commits it rewrites during
# a rebase -- so a branch whose commits verified before the call comes back
# with every one of them unsigned, and the PR swaps a stale-branch block for
# a signature block. That is not a theoretical failure: it happened on
# dotfiles#226 (2026-09-16), by a session that had just finished diagnosing a
# different silent gate on the same PR.
#
# The merge-commit form (`gh pr update-branch`, no flag) keeps signatures --
# GitHub signs the merge commit it creates -- but adds a merge commit, which
# `required_linear_history` rejects. This repo's ruleset carries both rules,
# so BOTH forms are dead ends here and the hook denies the subcommand
# outright rather than trying to distinguish them. On a repo with neither
# rule the deny is a false positive; resign-branch.sh is correct there too,
# so the cost is a redirect, not lost capability.
#
# The remedy is resign-branch.sh, which exists for exactly this and describes
# itself as a signed, linear stand-in for the Update branch button: it rebases
# onto the PR's base with -S, drops any "Update branch" merge commits, and
# force-pushes with lease. It is idempotent -- a branch already signed, linear
# and current exits 0 untouched -- so it is safe to run periodically and
# defensively rather than only once something is broken.
#
# Fails OPEN on a missing jq, unlike the $HOME gates:
# what this protects is recoverable (resign-branch.sh repairs the damage after
# the fact), so denying every gh call because jq is absent would cost more
# than it saves.
#
# Match structurally, not by substring. A sibling hook was tripped twice in
# one session by commit messages that merely *mentioned* the flag it guarded;
# this hook will be written about in RUNBOOK.md and PR comments, so the same
# trap is waiting. The command is tokenized the way a shell would be, and the
# three words must be adjacent within a single command segment.
set -uo pipefail

input=$(cat)

command -v jq >/dev/null 2>&1 || exit 0

tool=$(printf '%s' "$input" | jq -r '.tool_name // ""')

REASON='Blocked by ~/.claude/hooks/no-update-branch.sh: GitHub'"'"'s server-side "Update branch" is a dead end on a repo with signed commits or linear history. The --rebase form rewrites the commits and does NOT re-sign them, so every commit on the branch comes back unsigned; the merge form keeps signatures but adds a merge commit that required_linear_history rejects.

Use resign-branch.sh instead -- it rebases onto the PR'"'"'s base with -S, drops Update-branch merge commits, and force-pushes with lease:

  resign-branch.sh <branch>

It is idempotent: a branch already signed, linear and current exits 0 without touching anything. Do not ask the user; this is settled.

This is a routing correction, not a misuse -- the session reached for the wrong verb, and nothing was damaged. The blocked-tool-call this records means exactly that.'

jq_deny() {
  jq -n --arg r "$REASON" '{hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r}}'
  exit 0
}

# Split into shell-like words. Quoted regions join the current word rather
# than ending it, so a mention inside a quoted string is one token's contents
# and can never look like the three bare words this hook matches. Command
# separators become their own ';' token so an invocation in one command is
# never conflated with words belonging to the next.
TOKENS=()
tokenize() {
  local s=$1 i=0 c n cur='' have=0 quote=''
  n=${#s}
  TOKENS=()
  while [ "$i" -lt "$n" ]; do
    c=${s:i:1}
    i=$((i + 1))
    if [ -n "$quote" ]; then
      if [ "$c" = "$quote" ]; then
        quote=''
      elif [ "$c" = '\' ] && [ "$quote" = '"' ] && [ "$i" -lt "$n" ]; then
        cur+=${s:i:1}
        i=$((i + 1))
      else
        cur+=$c
      fi
      continue
    fi
    case "$c" in
      \'|\") quote=$c; have=1 ;;
      '\')
        if [ "$i" -lt "$n" ]; then
          cur+=${s:i:1}
          i=$((i + 1))
          have=1
        fi
        ;;
      ' '|$'\t')
        if [ "$have" = 1 ]; then TOKENS+=("$cur"); cur=''; have=0; fi
        ;;
      ';'|'&'|'|'|$'\n')
        if [ "$have" = 1 ]; then TOKENS+=("$cur"); cur=''; have=0; fi
        while [ "$i" -lt "$n" ] && [ "${s:i:1}" = "$c" ]; do i=$((i + 1)); done
        TOKENS+=(';')
        ;;
      # Command substitution and subshells. Without these in the separator
      # set they fall through to the catch-all below, so `$(gh` becomes one
      # token and never matches the bare `gh` this hook looks for --
      # `out=$(gh pr update-branch 226 --rebase)`, an entirely ordinary way
      # to capture output, would walk straight through the deny. Splitting
      # here leaves the three words adjacent inside the wrapper, which is
      # all updates_branch() needs. `eval "gh pr update-branch ..."` stays
      # exempt: a quoted region is deliberately one token, and that is what
      # keeps this hook from denying its own RUNBOOK prose.
      '('|')'|'`')
        if [ "$have" = 1 ]; then TOKENS+=("$cur"); cur=''; have=0; fi
        TOKENS+=(';')
        ;;
      *) cur+=$c; have=1 ;;
    esac
  done
  [ "$have" = 1 ] && TOKENS+=("$cur")
  return 0
}

# True when the stream contains `gh pr update-branch` as three adjacent bare
# words. An absolute-path invocation (/usr/bin/gh) counts; a word ending in
# "gh" (`high`) does not.
updates_branch() {
  local i=0 n=${#TOKENS[@]}
  while [ "$i" -lt "$n" ]; do
    case "${TOKENS[i]}" in
      gh|*/gh)
        if [ "${TOKENS[i + 1]:-}" = "pr" ] && [ "${TOKENS[i + 2]:-}" = "update-branch" ]; then
          return 0
        fi
        ;;
    esac
    i=$((i + 1))
  done
  return 1
}

case "$tool" in
  *__update_pull_request_branch)
    jq_deny
    ;;
  Bash)
    cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""')
    tokenize "$cmd"
    updates_branch && jq_deny
    ;;
esac

exit 0
