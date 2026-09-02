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
#     the PR will be blocked until resign-branch.sh is run from a machine
#     with the key, so it can say so in the handoff
#
# Only the current branch of the payload's cwd is inspected. A push that
# names another ref, or runs after a `cd`, is not caught; that is accepted
# imprecision, not a bypass anyone would reach for.
#
# GATE where a key exists: no jq or unreadable payload -> deny. Anything
# else uncertain (not a repo, no upstream and no origin/HEAD) -> allow.
set -u

json_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk 'BEGIN{ORS="\\n"} {print}' | sed 's/\\n$//; s/^/"/; s/$/"/'; }
deny()  { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":%s}}\n' "$(json_str "$1")"; exit 0; }
allow_with_note() { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":%s}}\n' "$(json_str "$1")"; exit 0; }

command -v jq >/dev/null 2>&1 || deny "no-unsigned-push: jq is missing, so the push payload can't be inspected. Install jq or ask Mark."
payload=$(cat) || deny "no-unsigned-push: could not read the hook payload."
cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null) || deny "no-unsigned-push: unreadable hook payload."
[ -n "$cmd" ] || exit 0

printf '%s' "$cmd" | grep -Eq \
  '(^|[^A-Za-z0-9_./-])git([[:space:]]+(-[cC][[:space:]]+[^[:space:]]+|--[^[:space:]]+))*[[:space:]]+push([[:space:]]|$)' \
  || exit 0

cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
[ -n "$cwd" ] && [ -d "$cwd" ] && cd "$cwd" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
git symbolic-ref -q HEAD >/dev/null 2>&1 || exit 0   # detached: nothing sensible to check

# Commits the push would send: upstream..HEAD, else origin/HEAD..HEAD.
base=$(git rev-parse -q --verify '@{u}' 2>/dev/null) \
  || base=$(git rev-parse -q --verify 'origin/HEAD' 2>/dev/null) \
  || exit 0
unsigned=$(git rev-list "$base..HEAD" 2>/dev/null | while read -r sha; do
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

if git config user.signingkey >/dev/null 2>&1; then
  deny "no-unsigned-push: $n unsigned commit(s) on $branch would be pushed, and this machine has a signing key, so sign them first:

$unsigned

Re-sign everything since the base and push again:
  git rebase -S --force-rebase $mb
If the branch is already on the remote, use \`resign-branch.sh $branch\` instead — it resets to the remote, re-signs, rebases onto main and force-pushes with lease. Never make commits with plumbing (\`git commit-tree\`) or \`-c commit.gpgsign=false\` in a repo that requires signatures."
fi

allow_with_note "no-unsigned-push: $n unsigned commit(s) on $branch are being pushed from a machine with no signing key:

$unsigned

A repo that requires signed commits will block the PR until someone runs \`resign-branch.sh $branch\` from a machine that has the key. Say so in the PR body and the handoff; do not try to sign here."
