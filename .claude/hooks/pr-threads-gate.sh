#!/bin/sh
# Blocks the end of a turn while a PR this session touched still has an
# unresolved review thread.
#
# Why: the PR ownership rules say review threads are mine to reply to AND
# resolve, and pr-ownership-context.sh puts that text in front of the session.
# Text is not a gate. 2026-09-07, colregs-engine#25: a session twice reported
# "all comments resolved" while a thread stayed open, with the rules in
# context both times. So the check moves from the model's memory to here:
# when the session tries to end its turn, re-fetch every touched PR's
# threads over GraphQL and refuse the stop if any is open or the fetch
# failed. The reason names each thread by id so the session can read it and
# resolve it, one at a time, or say plainly in its final message which ones
# stay open and why.
#
# Runs on Stop. Reads the record pr-ownership-context.sh appends to on each
# PR-shaped call (repo + number, or the cwd whose branch gh resolves to a PR).
# No record -> nothing to do, exit 0 -- most turns never touch a PR.
#
# Blocks at most once per turn: the harness sets stop_hook_active on the
# retry, and a second block would just loop against a thread only the user can
# close. One forced re-check is the whole point; the honest report after it
# is the model's job.
#
# GATE: no jq, no gh, gh failing, PR not found -> block once, saying the
# state could not be verified. A gate that goes quiet when it can't look is
# indistinguishable from one that looked and found nothing.
set -u

json_str() { printf '%s' "$1" | jq -Rs .; }
block() { printf '{"decision":"block","reason":%s}\n' "$(json_str "$1")"; exit 0; }

command -v jq >/dev/null 2>&1 || { printf '{"decision":"block","reason":"pr-threads-gate: jq is missing, so review threads on the PR you worked could not be re-checked. State in your final message, per thread id, which are resolved and which are open, then end the turn again."}\n'; exit 0; }
payload=$(cat) || exit 0
sid=$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)
[ -n "$sid" ] || exit 0
record="${TMPDIR:-/tmp}/claude-pr-threads.$(printf '%s' "$sid" | tr -c 'A-Za-z0-9_-' '_')"
[ -s "$record" ] || exit 0
[ "$(printf '%s' "$payload" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

command -v gh >/dev/null 2>&1 || block "pr-threads-gate: gh is not installed here, so review threads on the PR you worked could not be re-checked. State in your final message, per thread id, which are resolved and which are open, then end the turn again."

# Every distinct PR the session touched, as owner/name<TAB>number. A cwd line
# resolves through gh to whatever PR its current branch has; no PR there is
# fine (a `gh pr list` from a repo with no branch PR, say).
prs=$(sort -u "$record" | while IFS="$(printf '\t')" read -r kind a b; do
  case "$kind" in
    repo) printf '%s\t%s\n' "$a" "$b" ;;
    cwd)
      [ -d "$a" ] || continue
      # The PR url names the base repo, which is where the threads live; the
      # head repo would be wrong for a PR from a fork.
      (cd "$a" && gh pr view --json url -q .url 2>/dev/null | sed -n 's#^https://github\.com/\([^/]*/[^/]*\)/pull/\([0-9]*\)$#\1\t\2#p') || :
      ;;
  esac
done | sort -u)
[ -n "$prs" ] || exit 0

# One fetch per PR, all at once, each bounded by wall clock rather than the
# list by count: a session that fans out over eight PRs still gets every one
# checked, and a fetch that hangs is reported as unverified, never skipped.
# Without `timeout` the bound is gh's own; the fetch still runs.
WORK=$(mktemp -d "${TMPDIR:-/tmp}/pr-threads-gate.XXXXXX") || block "pr-threads-gate: cannot create a scratch directory, so review threads on the PR you worked could not be re-checked. State in your final message, per thread id, which are resolved and which are open, then end the turn again."
trap 'rm -rf "$WORK"' EXIT
TO=""; command -v timeout >/dev/null 2>&1 && TO="timeout ${PR_THREADS_GATE_TIMEOUT:-60}"
n=0
while IFS="$(printf '\t')" read -r repo num; do
  if [ -z "$repo" ] || [ -z "$num" ]; then continue; fi
  n=$((n + 1))
  printf '%s\t%s\n' "$repo" "$num" > "$WORK/$n.pr"
  owner=${repo%%/*}; name=${repo#*/}
  # shellcheck disable=SC2016  # GraphQL variables, not shell ones
  ( $TO gh api graphql -f owner="$owner" -f name="$name" -F number="$num" -f query='
    query($owner:String!,$name:String!,$number:Int!){
      repository(owner:$owner,name:$name){ pullRequest(number:$number){
        state
        reviewThreads(first:100){ nodes{ id isResolved path
          comments(first:1){ nodes{ author{login} body } } } } } } }' > "$WORK/$n.out" 2>&1
    echo $? > "$WORK/$n.rc" ) &
done <<EOF
$prs
EOF
wait

open=""
failed=""
i=0
while [ "$i" -lt "$n" ]; do
  i=$((i + 1))
  IFS="$(printf '\t')" read -r repo num < "$WORK/$i.pr"
  out=$(cat "$WORK/$i.out" 2>/dev/null)
  rc=$(cat "$WORK/$i.rc" 2>/dev/null)
  if [ "$rc" = 124 ]; then failed="$failed
- $repo#$num: fetch timed out"; continue; fi
  [ "$rc" = 0 ] || { failed="$failed
- $repo#$num: $(printf '%s' "$out" | head -3 | tr '\n' ' ')"; continue; }
  state=$(printf '%s' "$out" | jq -r '.data.repository.pullRequest.state // empty')
  [ -n "$state" ] || { failed="$failed
- $repo#$num: not found (no pullRequest in the GraphQL reply)"; continue; }
  [ "$state" = "OPEN" ] || continue
  threads=$(printf '%s' "$out" | jq -r '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved|not)
    | "  - \(.id)  \(.path // "(no file)")  @\(.comments.nodes[0].author.login // "?"): \((.comments.nodes[0].body // "") | split("\n")[0] | .[0:100])"')
  [ -n "$threads" ] && open="$open
- $repo#$num has $(printf '%s\n' "$threads" | wc -l | tr -d ' ') unresolved review thread(s):
$threads"
done

[ -z "$open" ] && [ -z "$failed" ] && exit 0

msg="pr-threads-gate: this turn cannot end yet. Live GraphQL re-check of the PR(s) this session worked:"
[ -n "$open" ] && msg="$msg
$open"
[ -n "$failed" ] && msg="$msg

Could not verify:$failed"
msg="$msg

For each open thread, in this order: read it (gh api graphql on the thread id, or the PR's review comments), fix or answer it, reply on the thread with the evidence, then resolve it by id --
  gh api graphql -f query='mutation(\$id:ID!){resolveReviewThread(input:{threadId:\$id}){thread{isResolved}}}' -f id=<threadId>
One thread at a time, never a loop over all unresolved ids. A thread only the user can close (a decision, a question to them) stays open: say so in your final message, by id, with what they need to decide. Never report 'all threads resolved' unless this check passes. Then end the turn again; this gate does not fire twice in one turn."
block "$msg"
