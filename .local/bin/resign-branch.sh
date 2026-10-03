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
#      you run it from never changes branch (refuses if <branch> in any
#      clone of the repo on this machine has commits the remote lacks —
#      they would be orphaned)
#   2. resolves the rebase target: the base branch of the open PR for
#      <branch>, so a stacked PR stays stacked; the default branch when
#      no PR is open. RESIGN_BASE=<name> overrides the lookup
#   3. if every commit already verifies, every commit is authored as this
#      machine's user.email, there are no merge commits and the branch is
#      up to date with the base, exits 0 without touching anything —
#      safe to run repeatedly
#   4. otherwise, with a local signing key: rebases onto the base with -S,
#      which re-signs every commit, reauthors any commit not authored as
#      this machine's user.email (original identity kept as a
#      Co-Authored-By trailer), drops any "Update branch" merge commits and
#      brings the branch up to date — a signed, linear stand-in for
#      GitHub's "Update branch" button; a conflict aborts the rebase and
#      exits 1, branch untouched. Refuses if linearizing would drop content
#      from a hand-resolved merge.
#      Without a local key: rebases onto the base locally, unsigned (a
#      conflict exits 1, branch untouched), then replays each commit as a GitHub-API-signed
#      commit (GraphQL createCommitOnBranch) on a scratch branch, one API
#      commit per original commit, each attributed to the `gh` token's
#      account with the original author kept as a Co-Authored-By trailer
#      (the API has no author-override field, so this path cannot reauthor
#      to this machine's user.email the way the local-key path does).
#      Refuses if the branch has merge commits, or any commit changes a
#      file's executable bit, adds/removes a symlink or submodule, or does
#      anything else createCommitOnBranch's additions/deletions can't
#      express — resolve those by hand or from a machine with a local key.
#   5. verifies every rewritten commit (locally on the key path, via the
#      GitHub API's verification.verified on the fallback), then
#      force-pushes with lease
#   6. if an open PR has this branch as its head, writes or updates a
#      `Head: <sha>` line in its body naming the new push (dotfiles#286),
#      so the rewrite is visible before anyone merges. Best effort: never
#      fails the run, and does nothing when gh is unusable or no PR is open
#
# Rewrites history. Single-author PR branches only; it refuses to run
# against the default branch.
#
# A commit can carry a locally-valid signature and still fail GitHub's
# check with reason "unknown_key" -- not because the key is wrong, but
# because the commit's author/committer email (e.g. a cloud session's
# noreply@anthropic.com) belongs to a different GitHub account than the
# one this key is registered to. Local `git log --pretty=%G?` reports
# such a commit "good" regardless -- it checks the signature against
# allowed_signers, not against GitHub's email-to-account mapping -- so
# that check alone under-detects this case. Any commit whose author or
# committer email isn't this machine's user.email gets reauthored to it
# (original identity preserved as a Co-Authored-By trailer) in the same
# pass that resigns.
#
# No local key: GitHub API fallback. When user.signingkey is unset, commits
# are rebuilt one-for-one through the `createCommitOnBranch` GraphQL
# mutation, which GitHub signs itself (verification reason "valid"). The
# mutation only knows additions and plain-blob deletions -- no merges, no
# executable bit, no symlinks, no submodules, no author override -- so a
# branch that needs any of those is refused rather than silently
# mishandled, and every resulting commit is attributed to the `gh` token's
# account with the original author preserved as a Co-Authored-By trailer,
# never reauthored to this machine's user.email (the API has no field for
# that). The rewrite happens on a scratch branch on the remote so the real
# branch is only ever touched by the final force-with-lease push.
set -eu

branch="${1:?usage: resign-branch.sh <branch> [<remote>]}"
remote="${2:-origin}"

die() { echo "resign-branch: $*" >&2; exit 1; }

git rev-parse --git-dir >/dev/null 2>&1 || die "not in a git repo"

signingkey=$(git config user.signingkey 2>/dev/null) || signingkey=""
localemail=$(git config user.email 2>/dev/null) || die "no user.email configured on this machine"
localname=$(git config user.name 2>/dev/null) || die "no user.name configured on this machine"
if [ -z "$signingkey" ]; then
  command -v gh >/dev/null 2>&1 || die "no user.signingkey configured on this machine, and gh is not installed for the GitHub-API-signed-commit fallback — nothing to sign with"
  command -v jq >/dev/null 2>&1 || die "no user.signingkey configured on this machine, and jq is not installed to build the GitHub API fallback's payload — nothing to sign with"
fi

# Local verification of an SSH signature needs an allowed-signers file. If
# none is configured, build one from our own key for this run only, so the
# verify step below can't false-alarm on a good signature. Format is
# "<principal> <key-type> <key>" — the opposite order from authorized_keys.
# Only relevant on the local-key path -- the API fallback verifies through
# GitHub, not through git's own signature check.
if [ -n "$signingkey" ]; then
  signers=$(git config gpg.ssh.allowedSignersFile 2>/dev/null || true)
  case "$signers" in "~"*) signers="$HOME${signers#\~}" ;; esac
  if [ -z "$signers" ] || [ ! -f "$signers" ]; then
    case "$signingkey" in "~"*) signingkey="$HOME${signingkey#\~}" ;; esac
    [ -f "$signingkey" ] || die "user.signingkey ($signingkey) is not a public-key file; can't build an allowed-signers file"
    signers=$(mktemp); tmpsigners=$signers
    printf '%s %s\n' "$(git config user.email)" "$(cut -d' ' -f1,2 "$signingkey")" > "$signers"
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=gpg.ssh.allowedSignersFile GIT_CONFIG_VALUE_0="$signers"
  fi
fi

# Fetch everything, not just the branch: a stale base would replay commits
# the base already has and leave the branch behind.
git fetch -q "$remote"
git rev-parse --verify -q "$remote/$branch" >/dev/null || die "$remote has no branch $branch"
git rev-parse --verify -q "$remote/HEAD" >/dev/null || git remote set-head -q "$remote" -a
default=$(git symbolic-ref --short "refs/remotes/$remote/HEAD")   # e.g. origin/main
[ "$remote/$branch" != "$default" ] || die "refusing to rewrite the default branch"
old=$(git rev-parse "$remote/$branch")
url=$(git remote get-url "$remote")

# Rebase onto the PR's base, not the default branch. A stacked PR -- one
# whose base is another PR's branch -- would otherwise be flattened onto
# main with no error anywhere: the rebase succeeds, the push goes through,
# and the PR now shows its parent's commits as its own. GitHub is the only
# authority on the base, so an unanswerable lookup is a stop, not a guess;
# RESIGN_BASE=<name> is the way through when gh can't be used.
if [ -n "${RESIGN_BASE:-}" ]; then
  base=$RESIGN_BASE
else
  command -v gh >/dev/null 2>&1 || die "gh is not installed, so the PR's base branch can't be looked up. Set RESIGN_BASE=<branch> to name it (the default branch is ${default#"$remote/"})."
  bases=$(gh pr list -R "$url" --head "$branch" --state open --json baseRefName --jq '.[].baseRefName') \
    || die "gh could not list open PRs for $branch on $url (auth? network?). Set RESIGN_BASE=<branch> to name the base by hand."
  nbases=$(printf '%s\n' "$bases" | grep -c .) || true
  if [ "$nbases" -eq 0 ]; then
    base=${default#"$remote/"}
    echo "resign-branch: no open PR for $branch; rebasing onto the default branch $default" >&2
  elif [ "$nbases" -gt 1 ]; then
    die "$nbases open PRs have head $branch, with bases: $(printf '%s' "$bases" | tr '\n' ' '). Set RESIGN_BASE=<branch> to pick one."
  else
    base=$bases
  fi
  # The other half of a stack: PRs based on this branch will show its old
  # commits as their own until they are re-signed onto the rewritten ones.
  children=$(gh pr list -R "$url" --base "$branch" --state open --json number --jq '.[].number' 2>/dev/null | tr '\n' ' ') || children=""
  [ -z "$children" ] || echo "resign-branch: $branch is the base of open PR(s) ${children% }; after this run, re-sign each of those too so they pick up the rewritten commits" >&2
fi
target="$remote/$base"
git rev-parse --verify -q "$target" >/dev/null || die "$remote has no branch $base to rebase $branch onto"
[ "$target" != "$remote/$branch" ] || die "$branch cannot be rebased onto itself"

# Every clone of this repo on this machine has its own refs/heads/<branch>,
# and any of them may be the one holding commits nobody pushed. The clone
# this runs from is one. dotfiles has two more -- ~/dotfiles/.git and the
# yadm repo -- and they count only when they are clones of the same remote.
# A candidate that matches but can't be read is a hard stop, because from
# here "not checked" and "nothing there" look identical.
# Same repo, different remote form: git@host:owner/repo(.git) (SCP-style)
# and scheme://[user@]host/owner/repo(.git) (ssh://, https://, git://) must
# compare equal, or two clones of the same GitHub repo on different
# protocols take the same silent-skip path as "not a clone of this repo" --
# the exact failure finding 2 exists to close.
norm_url() {
  u=${1%/}; u=${u%.git}
  case "$u" in
    *://*) u=${u#*://}; u=${u#*@} ;;                               # scheme://[user@]host/path -> host/path
    *@*:*) u=${u#*@}; u=$(printf '%s' "$u" | sed 's/:/\//') ;;      # user@host:path -> host/path
    *:*) u=$(printf '%s' "$u" | sed 's/:/\//') ;;                   # host:path -> host/path
  esac
  printf '%s\n' "$u"
}
gitdir=$(cd "$(git rev-parse --git-common-dir)" && pwd -P)
gitdirs=$gitdir
candidates="$HOME/dotfiles/.git"
if command -v yadm >/dev/null 2>&1; then
  yrepo=$(yadm introspect repo 2>/dev/null) || die "yadm is installed but 'yadm introspect repo' failed, so its clone can't be checked for an unpushed $branch"
  candidates="$candidates
$yrepo"
fi
while IFS= read -r d; do
  [ -e "$d" ] || continue   # empty $d fails -e too
  dabs=$(cd "$d" 2>/dev/null && pwd -P) || die "$d exists but can't be entered, so it can't be checked for an unpushed $branch"
  [ "$dabs" != "$gitdir" ] || continue
  git --git-dir="$dabs" rev-parse --git-dir >/dev/null 2>&1 || die "$dabs exists but git can't read it, so it can't be checked for an unpushed $branch"
  durl=$(git --git-dir="$dabs" remote get-url "$remote" 2>/dev/null) || continue   # no remote by that name: not a clone of this repo
  [ "$(norm_url "$durl")" = "$(norm_url "$url")" ] || continue
  gitdirs="$gitdirs
$dabs"
done <<CANDIDATES
$candidates
CANDIDATES

# The orphan guard proper. A clone that has never fetched $old can't
# compare against it, so fetch there first; a fetch that fails is a stop.
while IFS= read -r d; do
  git --git-dir="$d" rev-parse --verify -q "refs/heads/$branch" >/dev/null || continue
  git --git-dir="$d" cat-file -e "$old^{commit}" 2>/dev/null \
    || git --git-dir="$d" fetch -q "$remote" \
    || die "can't fetch $remote in $d, so its $branch can't be compared with $remote/$branch"
  ahead=$(git --git-dir="$d" rev-list --count "$old..refs/heads/$branch")
  [ "$ahead" -eq 0 ] || die "$branch in $d has $ahead commit(s) not on $remote/$branch — they would be orphaned by the rewrite. Push or rebase them onto $remote/$branch first."
done <<GITDIRS
$gitdirs
GITDIRS

# All the rewriting happens in a throwaway worktree, so the checkout this
# runs from — which cron and other sessions may be using — never changes
# branch and never needs to be clean.
wt=$(mktemp -d)
succeeded=0
cleanup() {
  git worktree remove --force "$wt" 2>/dev/null
  rm -rf "$wt" ${tmpsigners:+"$tmpsigners"} ${reauthor:+"$reauthor"}
  # Only delete the scratch branch on success. The die() messages on the
  # API-fallback path below tell the user it is "left on $remote for
  # inspection" so they can look at the partial API-built commits after a
  # failure -- an unconditional delete here would have already removed it
  # by the time those messages print, since die()'s exit fires this trap.
  if [ -n "${tmpremotebranch:-}" ] && [ "$succeeded" -eq 1 ]; then
    git push -q "$remote" ":refs/heads/$tmpremotebranch" 2>/dev/null || true
  fi
}
trap cleanup EXIT
git worktree add -q --detach "$wt" "$old"
g() { git -C "$wt" "$@"; }

# %G? is G (good), U (good, key not in allowed signers or unknown trust),
# N (unsigned), B (bad), E (can't check — e.g. GitHub's own GPG merges).
# Only G and U count as ours and good.
count_unverified() {
  g log --pretty='%G?' "$1" | grep -vc -E '^[GU]$' || true
}
# Commits whose author or committer email isn't this machine's identity --
# the case %G? can't see (see header comment).
count_foreign() {
  g log --pretty='%ae%n%ce' "$1" | grep -vxcF -- "$localemail" || true
}
# The API fallback's commits carry GitHub's signature, which %G? can't
# check locally, and the gh account's email, which it can't change -- so
# without a key, GitHub's own verdict is the only test, and "foreign" is
# not something a rerun could fix. Without this, every rerun rewrites.
count_unverified_gh() {
  n=0
  for c in $(g rev-list "$1"); do
    v=$(gh api "repos/$nameWithOwner/commits/$c" --jq .commit.verification.verified 2>/dev/null) || v=""
    [ "$v" = "true" ] || n=$((n+1))
  done
  echo "$n"
}
nameWithOwner=$(norm_url "$url"); nameWithOwner=${nameWithOwner#*/}
foreign=$(count_foreign "$target..HEAD")
if [ -n "$signingkey" ]; then
  unverified=$(count_unverified "$target..HEAD"); fixable_foreign=$foreign
else
  unverified=$(count_unverified_gh "$target..HEAD"); fixable_foreign=0
fi
merges=$(g rev-list --count --merges "$target..HEAD")
total=$(g rev-list --count "$target..HEAD")
behind=$(g rev-list --count "HEAD..$target")

if [ "$unverified" -eq 0 ] && [ "$fixable_foreign" -eq 0 ] && [ "$merges" -eq 0 ] && [ "$behind" -eq 0 ]; then
  if [ -n "$signingkey" ]; then
    echo "resign-branch: all $total commit(s) on $branch verify, all authored as $localemail, no merge commits, up to date with $target — nothing to do"
  else
    echo "resign-branch: all $total commit(s) on $branch verify on GitHub, no merge commits, up to date with $target — nothing to do"
  fi
  exit 0
fi

if [ -n "$signingkey" ]; then
  echo "resign-branch: $total commit(s) on $branch, $unverified unverified, $foreign not authored as $localemail, $merges merge commit(s), $behind behind $target; rebasing onto $target with -S"
else
  echo "resign-branch: $total commit(s) on $branch, $unverified unverified, $foreign not authored as $localemail, $merges merge commit(s), $behind behind $target; no local signing key -- replaying onto $target as GitHub-API-signed commits"
fi

if [ -n "$signingkey" ]; then

reauthor=$(mktemp)
cat >"$reauthor" <<REAUTHOR
#!/bin/sh
set -eu
ae=\$(git log -1 --format=%ae)
ce=\$(git log -1 --format=%ce)
[ "\$ae" = "$localemail" ] && [ "\$ce" = "$localemail" ] && exit 0
an=\$(git log -1 --format=%an)
msg=\$(git log -1 --format=%B)
trailer="Co-Authored-By: \$an <\$ae>"
case "\$msg" in *"\$trailer"*) : ;; *) msg="\$msg
\$trailer" ;; esac
GIT_AUTHOR_NAME="$localname" GIT_AUTHOR_EMAIL="$localemail" git commit -q --amend --allow-empty -S --reset-author -m "\$msg"
REAUTHOR
chmod +x "$reauthor"

if ! GIT_SEQUENCE_EDITOR=true g rebase -q -S --force-rebase --exec "$reauthor" "$target"; then
  g rebase --abort 2>/dev/null || true
  rm -f "$reauthor"
  die "rebase onto $target conflicted; $branch is untouched. Resolve by hand: git rebase -S $target $branch"
fi
rm -f "$reauthor"

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
    die "$merges merge commit(s) on $branch and the equivalent merge does not apply cleanly, so the rebase result cannot be checked against it. $branch is untouched; resolve by hand: git merge $target, fix the conflicts, commit (signed like any other commit), push as a plain fast-forward. Do not rebase or re-run this script afterwards -- a rebase drops whatever lives solely in the merge commit's tree. If the push is refused by mergify-cli's pre-push hook, it is keying on the checked-out branch's Change-Id trailers, not the ref you push: push from a detached throwaway worktree."
  elif [ "$want" != "$got" ]; then
    die "rebasing dropped content from $merges merge commit(s) on $branch -- the rebased tree differs from the merge result, which means a hand-resolved merge was replayed differently. $branch is untouched. Merge $target in instead: git merge $target, resolve, commit (the merge commit signs like any other; if it did not, git commit --amend -S --no-edit keeps both parents), then push it as a plain fast-forward. Do not rebase or re-run this script afterwards -- a rebase replays only single-parent commits and drops whatever lives solely in the merge commit's tree."
  fi
fi

unverified=$(count_unverified "$target..HEAD")
[ "$unverified" -eq 0 ] || {
  g log --pretty='%h %G? %s' "$target..HEAD" >&2
  die "$unverified commit(s) still don't verify after the rebase — not pushing"
}
foreign=$(count_foreign "$target..HEAD")
[ "$foreign" -eq 0 ] || {
  g log --pretty='%h %ae %ce %s' "$target..HEAD" >&2
  die "$foreign commit(s) still not authored as $localemail after the rebase — not pushing"
}

new=$(g rev-parse HEAD)

else
# --- GitHub API fallback: no local signing key -----------------------------
# createCommitOnBranch takes fileChanges of plain 100644 blobs only -- no
# mode changes, symlinks, submodules or merges -- and it moves the *named*
# branch it's given, so every commit is built on a scratch branch and the
# real branch is only touched by the final force-with-lease push below.
[ "$merges" -eq 0 ] || die "$merges merge commit(s) on $branch; the GitHub API fallback (createCommitOnBranch) can't replay a merge. Resolve by hand, or run this from a machine with a local user.signingkey."

# Rebase locally first, unsigned, so each replayed commit's diff is against
# the base tip and not its old parent. Replaying the old diffs' whole-file
# blobs onto a newer base would overwrite any base-side edit to the same
# file -- silently, since the API has no merge. A conflict stops here, the
# same way it does on the key path, before anything is staged on GitHub.
if ! GIT_SEQUENCE_EDITOR=true g -c commit.gpgsign=false rebase -q --force-rebase "$target"; then
  g rebase --abort 2>/dev/null || true
  die "rebase onto $target conflicted; $branch is untouched. Resolve by hand: git rebase $target $branch, push, then re-run this"
fi
commits=$(g rev-list --reverse "$target..HEAD")

# Validate every commit before making any API call, so a violation partway
# through the branch fails before anything is staged on GitHub. A path git
# still quotes with quotePath off has a tab, newline, quote or backslash in
# it, and the name-status parse below would get it wrong.
for c in $commits; do
  bad=$(g diff-tree --no-commit-id --no-renames --raw -r "$c" | awk '
    { om=$1; sub(/^:/,"",om); nm=$2
      if ((om!="000000" && om!="100644") || (nm!="000000" && nm!="100644")) print
    }')
  [ -z "$bad" ] || die "commit $(g rev-parse --short "$c") changes a file's executable bit, or adds/removes a symlink or submodule -- the GitHub API fallback can only create or delete plain 100644 blobs: $bad. Resolve by hand, or run this from a machine with a local user.signingkey."
  quoted=$(g -c core.quotePath=false diff-tree --no-commit-id --no-renames --name-only -r "$c" | grep '^"' || true)
  [ -z "$quoted" ] || die "commit $(g rev-parse --short "$c") touches a path with a tab, newline, quote or backslash in it ($quoted), which the GitHub API fallback doesn't handle. Resolve by hand, or run this from a machine with a local user.signingkey."
done

tmpremotebranch="resign-tmp/$branch.$$"
base_oid=$(g rev-parse "$target")
git push -q "$remote" "$base_oid:refs/heads/$tmpremotebranch" \
  || die "could not create the scratch branch $tmpremotebranch on $remote to stage the API-signed commits"

# File contents go through temp files, never argv: a base64 blob past
# ~128 KiB is over Linux's per-argument limit and jq --arg would fail.
query='mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) { commit { oid } } }'
statuses=$(mktemp); changes=$(mktemp); blob=$(mktemp); payload=$(mktemp)
head_oid=$base_oid
for c in $commits; do
  headline=$(g log -1 --format=%s "$c")
  body=$(g log -1 --format=%b "$c")
  an=$(g log -1 --format=%an "$c"); ae=$(g log -1 --format=%ae "$c")
  trailer="Co-Authored-By: $an <$ae>"
  case "$body" in
    *"$trailer"*) : ;;
    *) if [ -n "$body" ]; then body="$body
$trailer"; else body="$trailer"; fi ;;
  esac

  g -c core.quotePath=false diff-tree --no-commit-id --no-renames --name-status -r "$c" > "$statuses"
  : > "$changes"
  while IFS="$(printf '\t')" read -r status path; do
    case "$status" in
      A|M)
        g show "$c:$path" | base64 | tr -d '\n' > "$blob"
        jq -n --arg path "$path" --rawfile contents "$blob" '{op:"add", path:$path, contents:$contents}' >> "$changes"
        ;;
      D)
        jq -n --arg path "$path" '{op:"del", path:$path}' >> "$changes"
        ;;
      *)
        rm -f "$statuses" "$changes" "$blob" "$payload"
        die "commit $(g rev-parse --short "$c") has diff-tree status '$status' for $path, which the GitHub API fallback doesn't handle. $branch is untouched. $tmpremotebranch is left on $remote for inspection."
        ;;
    esac
  done < "$statuses"

  jq -n \
    --arg query "$query" \
    --arg repo "$nameWithOwner" \
    --arg branch "$tmpremotebranch" \
    --arg headline "$headline" \
    --arg body "$body" \
    --arg oid "$head_oid" \
    --slurpfile changes "$changes" \
    '{query:$query, variables:{input:{
        branch:{repositoryNameWithOwner:$repo, branchName:$branch},
        message:{headline:$headline, body:$body},
        fileChanges:{
          additions:[$changes[] | select(.op=="add") | {path, contents}],
          deletions:[$changes[] | select(.op=="del") | {path}]},
        expectedHeadOid:$oid}}}' > "$payload"

  head_oid=$(gh api graphql --input - --jq '.data.createCommitOnBranch.commit.oid' < "$payload") \
    || { rm -f "$statuses" "$changes" "$blob" "$payload"; die "GitHub API failed to create a commit for $(g rev-parse --short "$c") on $tmpremotebranch (see error above); $branch is untouched. $tmpremotebranch is left on $remote for inspection: git push $remote :refs/heads/$tmpremotebranch to clean it up"; }
  [ -n "$head_oid" ] || { rm -f "$statuses" "$changes" "$blob" "$payload"; die "GitHub API returned no commit oid for $(g rev-parse --short "$c") on $tmpremotebranch; $branch is untouched. $tmpremotebranch is left on $remote for inspection."; }
done
rm -f "$statuses" "$changes" "$blob" "$payload"

g fetch -q "$remote" "refs/heads/$tmpremotebranch" \
  || die "could not fetch the staged commits from $tmpremotebranch on $remote; $branch is untouched. $tmpremotebranch is left on $remote for inspection."

# The API built each tree from our additions/deletions; the rebase built
# the same tree locally. Any difference is content the replay got wrong.
[ "$(g rev-parse "$head_oid^{tree}")" = "$(g rev-parse 'HEAD^{tree}')" ] \
  || die "the API-built tip $head_oid has a different tree from the local rebase -- not pushing. $branch is untouched. $tmpremotebranch is left on $remote for inspection."

unverified=$(count_unverified_gh "$base_oid..$head_oid")
[ "$unverified" -eq 0 ] || die "GitHub reports $unverified API-built commit(s) on $tmpremotebranch as unverified -- not pushing. $branch is untouched. $tmpremotebranch is left on $remote for inspection."
new=$head_oid

fi

g push --force-with-lease="refs/heads/$branch:$old" "$remote" "$new:refs/heads/$branch"
succeeded=1

# This push moves the head an open PR merges from underneath whoever last
# looked at it -- the exact case dotfiles#286 exists to surface. Best
# effort: RESIGN_BASE runs assume gh may be unusable, and a PR the branch
# doesn't have (yet, or ever) isn't a failure here.
if command -v gh >/dev/null 2>&1; then
  pr_number=$(gh pr list -R "$url" --head "$branch" --state open --json number --jq '.[0].number // empty' 2>/dev/null) || pr_number=""
  if [ -n "$pr_number" ]; then
    old_body=$(gh pr view "$pr_number" -R "$url" --json body --jq '.body' 2>/dev/null) || old_body=""
    if printf '%s\n' "$old_body" | grep -q '^Head: '; then
      new_body=$(printf '%s\n' "$old_body" | sed "s/^Head: .*/Head: $new/")
    elif [ -n "$old_body" ]; then
      new_body=$(printf '%s\n\nHead: %s\n' "$old_body" "$new")
    else
      new_body="Head: $new"
    fi
    if gh pr edit "$pr_number" -R "$url" --body "$new_body" >/dev/null 2>&1; then
      echo "resign-branch: updated Head: $new on PR #$pr_number"
    else
      echo "resign-branch: pushed, but could not update the Head: line on PR #$pr_number's body" >&2
    fi
  fi
fi

while IFS= read -r d; do
  git --git-dir="$d" rev-parse --verify -q "refs/heads/$branch" >/dev/null || continue
  git --git-dir="$d" cat-file -e "$new^{commit}" 2>/dev/null || git --git-dir="$d" fetch -q "$remote" || true
  git --git-dir="$d" branch -f "$branch" "$new" 2>/dev/null \
    || echo "resign-branch: $branch in $d is checked out somewhere and still points at $old; run there: git checkout -B $branch $remote/$branch" >&2
done <<GITDIRS
$gitdirs
GITDIRS
if [ -n "$signingkey" ]; then
  echo "resign-branch: pushed $branch to $remote; every commit verifies locally. Confirm on GitHub:"
else
  echo "resign-branch: pushed $branch to $remote; GitHub reports every API-built commit verified. Confirm on GitHub:"
fi
echo "  gh api repos/{owner}/{repo}/pulls/<n>/commits --jq '.[]|\"\\(.sha[0:7]) \\(.commit.verification.verified)\"'"
