#!/bin/sh
# Stops unsigned commits from leaving a checkout unnoticed. Repos with a
# signed-commits ruleset grey out the merge button when any commit on the
# PR is unsigned, and nobody finds out until merge time — days later, in a
# session with no context, which then improvises (2026-09-01: a session
# re-signed the wrong commit and pushed it to a stray branch). The commits
# come from paths that skip commit.gpgsign: cloud VMs with no key, plumbing
# like `git commit-tree`, `-c commit.gpgsign=false`.
#
# On a `git push` from the Bash tool, look at the commits that push would
# send and ask whether each carries a signature header at all. Validity is
# GitHub's job; a cloud VM has no allowed-signers file, so %G? would report
# every signed commit as unsigned there.
#   - unsigned + this machine has a signing key -> DENY, with the exact
#     rebase command that re-signs them
#   - unsigned + no key here (cloud)          -> ALLOW, and tell the session
#     the PR will be blocked until resign-branch.sh is run (any machine --
#     it falls back to a GitHub-API-signed commit with no local key), so it
#     can say so in the handoff
#
# The current branch of the *pushed* repo is inspected -- which is the
# payload's cwd unless the command itself names a different one, via a
# leading `cd DIR &&`/`cd DIR;` or a `git -C DIR push`. Without following
# those, a push run against one repo from a session sitting in another gets
# checked against the wrong repo: a false deny (the real target is clean but
# the session's cwd has unsigned commits) or a false allow (the reverse).
# A push that names another ref, or a `cd` reached through a pipe or a
# multi-hop chain, is still not caught; that is accepted imprecision, not a
# bypass anyone would reach for.
#
# GATE where a key exists: no jq or unreadable payload -> deny. Anything
# else uncertain (not a repo, no upstream and no origin/HEAD) -> allow.
set -u

json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk 'BEGIN{ORS="\\n"} {print}' | sed 's/\\n$//; s/^/"/; s/$/"/'; }
deny()  { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "$(json_str "$1")"; exit 0; }
allow_with_note() { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":%s}}\n' "$(json_str "$1")"; exit 0; }

command -v jq >/dev/null 2>&1 || deny "no-unsigned-push: jq is missing, so the push payload can't be inspected. Install jq or ask the user."
payload=$(cat) || deny "no-unsigned-push: could not read the hook payload."
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null) || deny "no-unsigned-push: unreadable hook payload."
[ -n "$cmd" ] || exit 0

printf '%s' "$cmd" | grep -Eq \
  '(^|[^A-Za-z0-9_./-])git([[:space:]]+(-[cC][[:space:]]+[^[:space:]]+|--[^[:space:]]+))*[[:space:]]+push([[:space:]]|$)' \
  || exit 0

cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$cwd" ] && [ -d "$cwd" ] || exit 0

target_cwd=$cwd

# Only a `cd` at the very start of the command counts -- `git push && cd ..`
# must not be read as the push's directory (tail -1 over an unanchored match
# used to pick that up). `cd -` has no way to resolve OLDPWD from here, so it
# is left unhandled rather than guessed.
leading_cd=$(printf '%s' "$cmd" | grep -oE '^[[:space:]]*cd[[:space:]]+[^;&]*' | sed -E 's/^[[:space:]]*cd[[:space:]]+//; s/[[:space:]]*(&&.*)?$//; s/^["'"'"']//; s/["'"'"']$//')
case $leading_cd in
  '-') leading_cd='' ;;
  '~') leading_cd=$HOME ;;
  '~/'*) leading_cd="$HOME/${leading_cd#\~/}" ;;
  '$HOME') leading_cd=$HOME ;;
  '$HOME/'*) leading_cd="$HOME/${leading_cd#'$HOME/'}" ;;
esac
if [ -n "$leading_cd" ]; then
  case $leading_cd in
    /*) target_cwd=$leading_cd ;;
    *) target_cwd=$cwd/$leading_cd ;;
  esac
fi

# -C is only the push's own, from the matched `git ... push` invocation
# itself -- not from an unrelated `git commit -C HEAD` earlier in the
# command, nor from a second `git -C other ...` after it.
pushseg=$(printf '%s' "$cmd" | grep -oE \
  '(^|[^A-Za-z0-9_./-])git([[:space:]]+(-[cC][[:space:]]+[^[:space:]]+|--[^[:space:]]+))*[[:space:]]+push([[:space:]]|$)' \
  | tail -1)
cflag=$(printf '%s' "$pushseg" | grep -oE '\-C[[:space:]]+[^[:space:]]+' | tail -1 | sed -E 's/^-C[[:space:]]+//; s/^["'"'"']//; s/["'"'"']$//')
if [ -n "$cflag" ]; then
  case $cflag in
    /*) target_cwd=$cflag ;;
    *) target_cwd=$target_cwd/$cflag ;;
  esac
fi

# A resolved target that doesn't exist (bad expansion, typo) falls back to
# payload.cwd rather than exiting 0 -- a gate hook fails closed, not open.
[ -d "$target_cwd" ] && cwd=$target_cwd

cd "$cwd" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
git symbolic-ref -q HEAD >/dev/null 2>&1 || exit 0   # detached: nothing sensible to check

# Commits the push would send: upstream..HEAD, else origin/HEAD..HEAD.
# Anything already on origin/HEAD is excluded either way. A branch that merged
# main after its first push carries main's history past its own upstream; if
# main holds unsigned commits (a web edit, a key-less VM), counting them here
# denies every such branch or goads it into re-signing main into duplicates.
# The PR doesn't list them and they are not this branch's to fix.
main=$(git rev-parse -q --verify 'origin/HEAD' 2>/dev/null) || main=""
base=$(git rev-parse -q --verify '@{u}' 2>/dev/null) || base=$main
[ -n "$base" ] || exit 0
unsigned=$(git rev-list HEAD --not "$base" ${main:+"$main"} 2>/dev/null | while read -r sha; do
  git cat-file -p "$sha" | grep -q '^gpgsig' || git log -1 --pretty='%h %s' "$sha"
done)
[ -n "$unsigned" ] || exit 0

# $unsigned carries commit subject lines verbatim into permissionDecisionReason
# / additionalContext, which land in the session's context. Anyone who can get
# a commit into this branch's history -- a cherry-pick, a pulled-in fork
# commit, a bot -- writes that text, so treat it as untrusted input rather
# than as instructions. Kept verbatim on purpose: a mangled subject line is
# not identifiable, and identifying the commit is the whole point of the note.
n=$(printf '%s\n' "$unsigned" | wc -l | tr -d ' ')
branch=$(git symbolic-ref --short HEAD)
mb=$(git merge-base "$base" HEAD 2>/dev/null || echo "$base")
# Same trap in the remedy: past a merged main, a rebase from the upstream
# replays main's commits as new ones (--rebase-merges too), so rebase from
# the merged main tip; that rewrites pushed commits, hence the lease.
how="Re-sign everything since the base and push again:
  git rebase -S --force-rebase $mb
If the branch is already on the remote, use \`resign-branch.sh $branch\` instead — it resets to the remote, re-signs, rebases onto main and force-pushes with lease."
if [ -n "$main" ] && mbm=$(git merge-base "$main" HEAD 2>/dev/null) && ! git merge-base --is-ancestor "$mbm" "$mb" 2>/dev/null; then
  mb=$mbm
  how="This branch merged main after it was pushed, so re-sign from the merged main tip (a rebase from the upstream would replay main's commits as new ones), then push with --force-with-lease — the rebase rewrites the pushed commits too, and resign-branch.sh refuses a branch with local commits the remote lacks:
  git rebase -S --force-rebase $mb"
fi

if git config user.signingkey >/dev/null 2>&1; then
  deny "no-unsigned-push: $n unsigned commit(s) on $branch would be pushed, and this machine has a signing key, so sign them first:

$unsigned

$how
Never make commits with plumbing (\`git commit-tree\`) or \`-c commit.gpgsign=false\` in a repo that requires signatures."
fi

allow_with_note "no-unsigned-push: $n unsigned commit(s) on $branch are being pushed from a machine with no signing key:

$unsigned

A repo that requires signed commits will block the PR until someone runs \`resign-branch.sh $branch\`. It falls back to a GitHub-API-signed commit when this machine has no local signing key, so it does not need to run from a machine that has one -- but it also does not preserve author identity in that fallback (see resign-branch.sh's own notes). Say so in the PR body and the handoff; do not try to sign here."
