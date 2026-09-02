#!/bin/sh
# resign-branch.sh — re-sign a PR branch's commits with this machine's key,
# rebase it onto the tip of the default branch, and force-push it.
#
# Why this exists: commits get made unsigned on paths that skip
# commit.gpgsign — Claude Code cloud sessions (no key on the VM; upstream
# closed https://github.com/anthropics/claude-code/issues/7711 "not planned"),
# plumbing like `git commit-tree`, and any `-c commit.gpgsign=false`. A repo
# whose ruleset requires signed commits blocks the PR until every commit on
# it verifies. This is the remedy, run once from a machine that has the key.
#
# Usage:
#   resign-branch.sh <branch> [<remote>]     remote defaults to origin
#
# What it does, in order:
#   1. fetches <remote>/<branch> into a throwaway worktree, so the checkout
#      you run it from never changes branch (refuses if your local <branch>
#      has commits the remote lacks — they would be orphaned)
#   2. if every commit already verifies, there are no merge commits and the
#      branch is up to date with <remote>/HEAD, exits 0 without touching
#      anything — safe to run repeatedly
#   3. otherwise rebases onto <remote>/HEAD with -S, which re-signs every
#      commit, drops any "Update branch" merge commits and brings the branch
#      up to date — a signed, linear stand-in for GitHub's "Update branch"
#      button; a conflict aborts the rebase and exits 1, branch untouched.
#      Refuses if linearizing would drop content from a hand-resolved merge
#   4. verifies every rewritten commit locally, then force-pushes with lease
#
# Rewrites history. Single-author PR branches only; it refuses to run
# against the default branch.
set -eu

branch="${1:?usage: resign-branch.sh <branch> [<remote>]}"
remote="${2:-origin}"

die() { echo "resign-branch: $*" >&2; exit 1; }

git rev-parse --git-dir >/dev/null 2>&1 || die "not in a git repo"

signingkey=$(git config user.signingkey 2>/dev/null) || die "no user.signingkey configured on this machine — nothing to sign with"

# Local verification of an SSH signature needs an allowed-signers file. If
# none is configured, build one from our own key for this run only, so the
# verify step below can't false-alarm on a good signature. Format is
# "<principal> <key-type> <key>" — the opposite order from authorized_keys.
signers=$(git config gpg.ssh.allowedSignersFile 2>/dev/null || true)
case "$signers" in "~"*) signers="$HOME${signers#\~}" ;; esac
if [ -z "$signers" ] || [ ! -f "$signers" ]; then
  case "$signingkey" in "~"*) signingkey="$HOME${signingkey#\~}" ;; esac
  [ -f "$signingkey" ] || die "user.signingkey ($signingkey) is not a public-key file; can't build an allowed-signers file"
  signers=$(mktemp); tmpsigners=$signers
  printf '%s %s\n' "$(git config user.email)" "$(cut -d' ' -f1,2 "$signingkey")" > "$signers"
  export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=gpg.ssh.allowedSignersFile GIT_CONFIG_VALUE_0="$signers"
fi

# Fetch everything, not just the branch: a stale <remote>/HEAD would replay
# commits main already has and leave the branch behind.
git fetch -q "$remote"
git rev-parse --verify -q "$remote/$branch" >/dev/null || die "$remote has no branch $branch"
git rev-parse --verify -q "$remote/HEAD" >/dev/null || git remote set-head -q "$remote" -a
target="$remote/HEAD"
default=$(git symbolic-ref --short "refs/remotes/$target")   # e.g. origin/main
[ "$remote/$branch" != "$default" ] || die "refusing to rewrite the default branch"
old=$(git rev-parse "$remote/$branch")

if git rev-parse --verify -q "refs/heads/$branch" >/dev/null; then
  ahead=$(git rev-list --count "$old..refs/heads/$branch")
  [ "$ahead" -eq 0 ] || die "local $branch has $ahead commit(s) not on $remote/$branch — they would be orphaned by the rewrite. Push or rebase them onto $remote/$branch first."
fi

# All the rewriting happens in a throwaway worktree, so the checkout this
# runs from — which cron and other sessions may be using — never changes
# branch and never needs to be clean.
wt=$(mktemp -d)
cleanup() { git worktree remove --force "$wt" 2>/dev/null; rm -rf "$wt" ${tmpsigners:+"$tmpsigners"}; }
trap cleanup EXIT
git worktree add -q --detach "$wt" "$old"
g() { git -C "$wt" "$@"; }

# %G? is G (good), U (good, key not in allowed signers or unknown trust),
# N (unsigned), B (bad), E (can't check — e.g. GitHub's own GPG merges).
# Only G and U count as ours and good.
count_unverified() {
  g log --pretty='%G?' "$1" | grep -vc -E '^[GU]$' || true
}
unverified=$(count_unverified "$target..HEAD")
merges=$(g rev-list --count --merges "$target..HEAD")
total=$(g rev-list --count "$target..HEAD")
behind=$(g rev-list --count "HEAD..$target")

if [ "$unverified" -eq 0 ] && [ "$merges" -eq 0 ] && [ "$behind" -eq 0 ]; then
  echo "resign-branch: all $total commit(s) on $branch verify, no merge commits, up to date with $default — nothing to do"
  exit 0
fi

echo "resign-branch: $total commit(s) on $branch, $unverified unverified, $merges merge commit(s), $behind behind $default; rebasing onto $default with -S"
if ! GIT_SEQUENCE_EDITOR=true g rebase -q -S --force-rebase "$target"; then
  g rebase --abort 2>/dev/null || true
  die "rebase onto $default conflicted; $branch is untouched. Resolve by hand: git rebase -S $target $branch"
fi

# A rebase linearizes through merge commits. That is intended for an
# "Update branch" merge, which carries no content of its own -- but a merge
# whose conflicts someone resolved by hand (GitHub's web editor, say) has
# content that exists in no single parent, and replaying the parents' commits
# can succeed with no conflict and quietly produce a different tree. Compare
# the rebased tree against the tree a merge would have produced, and refuse
# rather than push a silent content change.
if [ "$merges" -gt 0 ]; then
  want=$(g merge-tree --write-tree "$target" "$old" 2>/dev/null | head -1) || want=""
  got=$(g rev-parse 'HEAD^{tree}')
  if [ -z "$want" ]; then
    die "$merges merge commit(s) on $branch and the equivalent merge does not apply cleanly, so the rebase result cannot be checked against it. $branch is untouched; resolve by hand."
  elif [ "$want" != "$got" ]; then
    die "rebasing dropped content from $merges merge commit(s) on $branch -- the rebased tree differs from the merge result, which means a hand-resolved merge was replayed differently. $branch is untouched. Merge $default in instead: git merge $target, then re-sign with: git rebase -S --force-rebase \$(git merge-base $target HEAD)"
  fi
fi

unverified=$(count_unverified "$target..HEAD")
[ "$unverified" -eq 0 ] || {
  g log --pretty='%h %G? %s' "$target..HEAD" >&2
  die "$unverified commit(s) still don't verify after the rebase — not pushing"
}

new=$(g rev-parse HEAD)
g push --force-with-lease="refs/heads/$branch:$old" "$remote" "$new:refs/heads/$branch"
if git rev-parse --verify -q "refs/heads/$branch" >/dev/null; then
  git branch -f "$branch" "$new" 2>/dev/null \
    || echo "resign-branch: local $branch is checked out somewhere and still points at $old; run: git checkout -B $branch $remote/$branch" >&2
fi
echo "resign-branch: pushed $branch to $remote; every commit verifies locally. Confirm on GitHub:"
echo "  gh api repos/{owner}/{repo}/pulls/<n>/commits --jq '.[]|\"\\(.sha[0:7]) \\(.commit.verification.verified)\"'"
