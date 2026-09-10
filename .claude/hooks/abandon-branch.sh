#!/bin/sh
# Deletes a branch locally and on its remote, deliberately. Split out of
# branch-home-gate.sh; see dotfiles#115.
#
# Usage: abandon-branch.sh [-C <path>] [<branch>]
#   -C <path>   the repo to act in (default: cwd)
#   <branch>    the branch to delete (default: the one checked out at <path>)
#
# Refuses in $HOME (yadm gate); only deletes the local branch once the
# remote side is a confirmed absence or a confirmed deletion, never on an
# indeterminate ls-remote (network, auth, a dead remote).
set -u

HERE=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=lib-state.sh
. "$HERE/lib-state.sh"

run_to() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi
}

work_root=.
while [ $# -gt 0 ]; do
  case "$1" in
    -C) work_root=$2; shift 2 ;;
    -C*) work_root=${1#-C}; shift ;;
    --) shift; break ;;
    -*) printf 'abandon-branch: unknown option %s\n' "$1" >&2; exit 2 ;;
    *) break ;;
  esac
done
branch=${1:-}

work_root=$(git -C "$work_root" rev-parse --show-toplevel 2>/dev/null) \
  || { printf 'abandon-branch: not a git repo\n' >&2; exit 1; }
[ -n "$branch" ] || branch=$(git -C "$work_root" rev-parse --abbrev-ref HEAD 2>/dev/null)
case "$branch" in
  ''|HEAD) printf 'abandon-branch: no branch (detached HEAD?) -- pass one explicitly\n' >&2; exit 1 ;;
  main|master) printf 'abandon-branch: refusing to abandon %s\n' "$branch" >&2; exit 1 ;;
esac

if [ "$work_root" = "$HOME" ]; then
  printf 'abandon-branch: refused -- %s is $HOME (yadm gate). Delete it by hand from a worktree.\n' "$work_root" >&2
  exit 1
fi

# Same lock stop-continuity.sh takes before it commits and pushes, so the
# two never interleave and a salvage push cannot resurrect the branch we are
# deleting. Best effort: a machine without flock proceeds unlocked.
if command -v flock >/dev/null 2>&1; then
  exec 9>"${TMPDIR:-/tmp}/claude-state-push.lock" 2>/dev/null && flock -w 90 9 2>/dev/null
fi

sha=$(git -C "$work_root" rev-parse --short "$branch" 2>/dev/null || echo '?')

git -C "$work_root" ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1
remote_rc=$?
# Exit 2 means ls-remote reached origin and found no matching ref: the
# branch is confirmed absent there. Any other nonzero (network, auth, a
# dead remote) is "could not check", not "not there" -- and must not be
# treated as license to delete the only copy.
if [ "$remote_rc" -eq 0 ]; then
  # Refspec form, not --delete: a ref name is never mistaken for a flag.
  if run_to 60 git -C "$work_root" push -q origin ":refs/heads/$branch" >/dev/null 2>&1; then
    remote=deleted
  else
    remote="NOT deleted (push failed)"
  fi
elif [ "$remote_rc" -eq 2 ]; then
  remote="not on the remote"
else
  remote="NOT deleted (could not verify remote, ls-remote exit $remote_rc)"
fi

# Only delete the local branch once the remote side is a confirmed absence
# or a confirmed deletion -- never on an indeterminate remote check.
case "$remote" in
  deleted|"not on the remote") local_state=deleted ;;
  *) local_state="kept ($remote)" ;;
esac
cur=$(git -C "$work_root" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')
if [ "$local_state" = deleted ] && [ "$cur" = "$branch" ]; then
  # The branch is checked out here, so detach first. Uncommitted changes
  # survive a detach; the commits stay reachable through the reflog.
  git -C "$work_root" checkout -q --detach >/dev/null 2>&1 \
    || local_state="NOT deleted (could not detach HEAD)"
fi
if [ "$local_state" = deleted ]; then
  git -C "$work_root" branch -q -D "$branch" >/dev/null 2>&1 \
    || local_state="NOT deleted (checked out in another worktree?)"
fi

printf 'abandon-branch: abandoned `%s` at %s -- local %s, remote %s. `git checkout -b %s %s` restores it while the reflog holds.\n' \
  "$branch" "$sha" "$local_state" "$remote" "$branch" "$sha"
