#!/bin/sh
# Blocks the end of a session on a branch that is ahead of the default branch
# with neither a PR nor a pointer -- a card on the global board or an open
# issue that names it.
#
# Why: twice in one week real design work was lost to a branch that was
# pushed, never opened as a PR, and pointed at from nowhere durable. The Stop
# hook records *unpushed* commits, so a pushed orphan trips no alarm, and
# `worklist` lists stranded branches at the bottom where nobody acts on them.
# Detection is not closure. Ruled 2026-09-09 (Solace): a PR is not required
# for every branch, but until one exists a pointer must -- a board card or an
# open issue naming the branch and what it holds.
#
# Runs on Stop, alongside kanban-gate.sh and pr-threads-gate.sh. The quiet
# path costs nothing: HEAD on the default branch, a detached HEAD, no origin,
# or no commits ahead and the hook exits before any network call.
#
# Read-only: detects and blocks, never deletes. Abandon lives in its own
# script now, abandon-branch.sh; see dotfiles#115.
#
# Two outcomes:
#   pass      a PR, a board card or an open issue names the branch
#   block     once per session, with the branch, what was searched, and the
#             two ways out
#
# Blocks at most once per session (a marker beside the notes file under
# TMPDIR, the same convention pr-ownership-context.sh uses for its record --
# NOT under the state dir, which stop-continuity.sh commits and pushes, so a
# per-session marker there would be repo churn in every session). A gate that
# can trap a session is worse than no gate.
#
# GATE: no jq, no gh, gh failing or unauthenticated -> block once saying the
# branch could not be verified. A guard that goes quiet when it cannot look is
# indistinguishable from one that looked and found nothing.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib-state.sh
. "$HERE/lib-state.sh"

# json_str(), block() and names_branch() come from lib-state.sh, sourced above.

# timeout is coreutils; a machine without it runs the command unbounded
# rather than failing every check and blocking every session.
run_to() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi
}

payload=$(cat) || exit 0

# stop_hook_active is the last-resort loop breaker.
if command -v jq >/dev/null 2>&1; then
  active=$(printf '%s' "$payload" | jq -r '.stop_hook_active // false' 2>/dev/null)
else
  active=false
  printf '%s' "$payload" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true' && active=true
  [ "$active" = true ] && exit 0
  block "branch-home-gate: jq is missing here, so this session's branch could not be checked for a PR or a pointer card. This is a gate and fails closed: open the PR, or file a pointer card naming the branch and what it holds (/card-write), then end the turn again."
fi

sid=$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$sid" ] || exit 0
[ -n "$cwd" ] || cwd=$PWD

# ------------------------------------------------------------- quiet path
work_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$work_root" ] || exit 0
branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
case "$branch" in
  ''|HEAD|main|master) exit 0 ;;   # default branch or detached: nothing to strand
esac
# No origin means nothing was published and nothing can be: a purely local
# repo has no orphan to leave behind.
git -C "$work_root" remote get-url origin >/dev/null 2>&1 || exit 0

# The base to measure "ahead" against: origin's default branch, however it is
# named here.
base=
for cand in "$(git -C "$work_root" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)" \
            origin/main origin/master; do
  [ -n "$cand" ] || continue
  if git -C "$work_root" rev-parse --verify -q "$cand" >/dev/null 2>&1; then base=$cand; break; fi
done
[ -n "$base" ] || exit 0
[ "$base" = "origin/$branch" ] && exit 0
ahead=$(git -C "$work_root" rev-list --count "$base..HEAD" 2>/dev/null || echo 0)
[ "${ahead:-0}" -gt 0 ] 2>/dev/null || exit 0

# One file per session: the once-per-session marker (a line beginning
# "blocked") for the checkpoint.
rec="${TMPDIR:-/tmp}/claude-branch-home.$(printf '%s' "$sid" | tr -c 'A-Za-z0-9_-' '_')"
note() { printf '%s\n' "$1" >> "$rec" 2>/dev/null || true; }

# --------------------------------------------------------- already blocked
[ -f "$rec" ] && grep -q '^blocked' "$rec" 2>/dev/null && exit 0
[ "$active" = true ] && exit 0

# ------------------------------------------------------------ find a home
# 0 found, 1 none, 2 could not verify. The board is a local file, so it is
# read before anything costs a network call.
found=
unverified=
board="$(state_dir)/kanban.md"
if [ -f "$board" ] && names_branch "$branch" < "$board" 2>/dev/null; then
  found="a card on $board names it"
fi

if [ -z "$found" ]; then
  if command -v gh >/dev/null 2>&1; then
    # Any PR with this head is a home: an open one is the point, and a
    # merged or closed one is still a durable record naming the branch.
    if prs=$( (cd "$work_root" && run_to 30 gh pr list --head "$branch" --state all --limit 5 --json url) 2>/dev/null ); then
      url=$(printf '%s' "$prs" | jq -r '.[0].url // empty' 2>/dev/null)
      [ -n "$url" ] && found="$url has this head"
    else
      unverified="gh pr list failed (not authenticated here?)"
    fi
  else
    unverified="gh is not installed here"
  fi
fi

if [ -z "$found" ] && [ -z "$unverified" ]; then
  if iss=$( (cd "$work_root" && run_to 30 gh issue list --state open --limit 200 --json number,title,body) 2>/dev/null ); then
    # Whole-token match via names_branch, same as the board check: jq's
    # `contains` is a plain substring test and gives claude/foobar's issue
    # to claude/foo too.
    num=$(printf '%s' "$iss" | jq -r \
      '.[] | [.number, (((.title // "") + " " + (.body // "")) | gsub("\n";" "))] | @tsv' 2>/dev/null \
      | while IFS="$(printf '\t')" read -r n text; do
          printf '%s' "$text" | names_branch "$branch" && { printf '%s\n' "$n"; break; }
        done)
    [ -n "$num" ] && found="open issue #$num names it"
  else
    unverified="gh issue list failed (not authenticated here?)"
  fi
fi

[ -n "$found" ] && exit 0

# The remote's name, not the checkout's: a worktree directory is named for
# the branch, which would make the block message say "in stop-hook-refusal".
repo=$(git -C "$work_root" remote get-url origin 2>/dev/null | sed 's#/*$##; s#\.git$##; s#.*[/:]##')
[ -n "$repo" ] || repo=$(basename "$work_root")
if [ -n "$unverified" ]; then
  note "blocked: could not verify a home for \`$branch\` ($unverified)"
  block "branch-home-gate: this session cannot end yet. Branch \`$branch\` in $repo is $ahead commit(s) ahead of $base, and whether it has a home could not be verified -- $unverified. This is a gate and fails closed, so \"can't check\" is not a pass: open the PR, or file a pointer card (/card-write) naming the branch and what it holds, then end the turn again. This gate fires once per session."
fi

note "blocked: \`$branch\` is $ahead commit(s) ahead of $base with no PR and no pointer"
block "branch-home-gate: this session cannot end yet. Branch \`$branch\` in $repo is $ahead commit(s) ahead of $base with no PR and no pointer: no PR has this head, no open issue names the branch, and no card on the board does either.

Take one of the two ways out, then end the turn again:
  - open the PR (not draft), or
  - file a pointer card (/card-write) naming the branch and what it holds -- a card on the global board or an open issue, either counts.

Detection is not closure -- a pushed branch nobody points at is how two pieces of design work were lost. This gate fires once per session."
