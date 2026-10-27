#!/usr/bin/env bash
# Tests for gh-resolve-thread. Run: bash bin/gh-resolve-thread.test.sh
#
# What matters: one thread id, shaped like one; only the hard-coded mutations
# reach gh, with id and body as variables, never inside the query; a reply is
# refused unsigned; a bare resolve is refused unless the thread's last comment
# is an agent's; and a result GitHub does not confirm is a failure. gh is
# faked: the read that checks the last comment answers from gh.last (as --jq
# would print it), every other call from gh.out; each call's argv is recorded.
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/gh-resolve-thread"
pass=0; fail=0
T=$(mktemp -d); export T
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
export PATH="$T/bin:$PATH"
cat > "$T/bin/gh" <<'G'
#!/bin/sh
printf '%s\n' "$@" >> "$T/gh.argv"
rc=$(cat "$T/gh.rc" 2>/dev/null || echo 0); [ "$rc" -eq 0 ] || { echo "gh: boom" >&2; exit "$rc"; }
case "$*" in
  *'comments(last:1)'*) cat "$T/gh.last" 2>/dev/null ;;
  *) cat "$T/gh.out" 2>/dev/null ;;
esac
G
chmod +x "$T/bin/gh"

run() { rc=0; : > "$T/gh.argv"; out=$(sh "$SCRIPT" "$@" 2>&1) || rc=$?; }
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; echo "  rc=$rc out=$out"; }
expect_rc() { [ "$rc" -eq "$1" ] && ok || bad "$2 (want rc $1)"; }
expect_out() { case $out in *"$1"*) ok ;; *) bad "$2 (want output containing '$1')" ;; esac; }
no_mutation() { grep -q 'mutation' "$T/gh.argv" && bad "$1 must not send a mutation" || ok; }
id_not_in_query() { grep '^query=' "$T/gh.argv" | grep -q 'PRRT_kwDOabc123' && bad "id must not be interpolated into the query" || ok; }

SIGNED=$'🤖 Fixed in 96d9b1c.\n\n🤖 claude-opus-5-5 · high · a0e46df2'
RESOLVED='{"data":{"resolveReviewThread":{"thread":{"isResolved":true}}}}'
REPLIED='{"data":{"addPullRequestReviewThreadReply":{"comment":{"url":"https://github.com/o/r/pull/1#r9"}}'

# --- usage ------------------------------------------------------------------
run;                    expect_rc 1 "no args refused"; expect_out usage "no args prints usage"
[ -s "$T/gh.argv" ] && bad "no args must not call gh" || ok
run a b;                expect_rc 1 "two args refused"
run PRRT_x --resolve "$SIGNED"; expect_rc 1 "unknown flag refused"
run 12345;              expect_rc 1 "non-PRRT id refused"; expect_out "not a review-thread id" "non-PRRT id names the shape"
[ -s "$T/gh.argv" ] && bad "bad id must not call gh" || ok

# --- bare resolve: only after an agent's reply --------------------------------
printf '%s\n' "$RESOLVED" > "$T/gh.out"
printf '🤖 Fixed.\n🤖 claude-opus-5-5 · - · a0e46df2\n' > "$T/gh.last"
run PRRT_kwDOabc123
expect_rc 0 "resolved thread exits 0"; expect_out "resolved PRRT_kwDOabc123" "reports the id"
grep -q 'resolveReviewThread(input:{threadId:$id})' "$T/gh.argv" && ok || bad "mutation is resolveReviewThread with a variable"
grep -qx 'id=PRRT_kwDOabc123' "$T/gh.argv" && ok || bad "id passed as -f id=<threadId>"
id_not_in_query
grep -qE 'deleteRef|closePullRequest|addPullRequestReviewThreadReply' "$T/gh.argv" && bad "bare resolve sends only the resolve" || ok

printf 'Please also handle the empty case.\n' > "$T/gh.last"
run PRRT_kwDOabc123;    expect_rc 1 "last comment not an agent's: refused"; expect_out "no agent reply" "says why"
no_mutation "an unanswered thread"
: > "$T/gh.last"
run PRRT_kwDOabc123;    expect_rc 1 "no comments at all: refused"
no_mutation "an empty thread"

# --- --reply: reply and resolve in one request ----------------------------------
printf '{"data":{"addPullRequestReviewThreadReply":{"comment":{"url":"https://github.com/o/r/pull/1#r9"}},"resolveReviewThread":{"thread":{"isResolved":true}}}}\n' > "$T/gh.out"
run PRRT_kwDOabc123 --reply "$SIGNED"
expect_rc 0 "reply and resolve exits 0"; expect_out "resolved PRRT_kwDOabc123" "reports the id"
[ "$(grep -c '^graphql$' "$T/gh.argv")" -eq 1 ] && ok || bad "one round trip"
grep -q 'addPullRequestReviewThreadReply(input:{pullRequestReviewThreadId:$id,body:$body})' "$T/gh.argv" && ok || bad "reply mutation uses variables"
grep -q 'resolveReviewThread' "$T/gh.argv" && ok || bad "same request resolves"
grep -qx 'body=🤖 Fixed in 96d9b1c.' "$T/gh.argv" && ok || bad "body passed as -f body="
id_not_in_query
printf '%s\n' "$REPLIED}" > "$T/gh.out"
run PRRT_kwDOabc123 --reply "$SIGNED"; expect_rc 1 "posted but not resolved is a failure"

# --- --reply-only: thread stays open --------------------------------------------
printf '%s}\n' "$REPLIED" > "$T/gh.out"
run PRRT_kwDOabc123 --reply-only "$SIGNED"
expect_rc 0 "reply-only exits 0"; expect_out "replied on PRRT_kwDOabc123" "reports the id"
grep -q 'resolveReviewThread' "$T/gh.argv" && bad "reply-only must not resolve" || ok
printf '{"errors":[{"message":"Could not resolve to a node"}]}\n' > "$T/gh.out"
run PRRT_kwDOabc123 --reply-only "$SIGNED"; expect_rc 1 "reply not posted is a failure"; expect_out "Could not resolve" "surfaces the error"

# --- unsigned replies never reach gh --------------------------------------------
for body in "Fixed in 96d9b1c." $'🤖 Fixed.' $'🤖 Fixed.\n🤖 claude-opus-5-5 · high' $'Fixed.\n🤖 claude-opus-5-5 · high · a0e46df2'; do
  run PRRT_kwDOabc123 --reply "$body"; expect_rc 1 "unsigned body refused: ${body//$'\n'/⏎}"
  [ -s "$T/gh.argv" ] && bad "unsigned body must not call gh" || ok
done

# --- failure paths ------------------------------------------------------------
printf '🤖 x\n🤖 m · - · a0e46df2\n' > "$T/gh.last"
printf '{"data":{"resolveReviewThread":{"thread":{"isResolved":false}}}}\n' > "$T/gh.out"
run PRRT_kwDOabc123;    expect_rc 1 "isResolved:false is a failure"; expect_out "not resolved" "says not resolved"
printf '{"errors":[{"message":"Could not resolve to a node"}]}\n' > "$T/gh.out"
run PRRT_kwDOnope;      expect_rc 1 "GraphQL error is a failure"; expect_out "Could not resolve" "surfaces the GraphQL error"
echo 4 > "$T/gh.rc"
run PRRT_kwDOabc123;    expect_rc 4 "gh's own exit status propagates"
run PRRT_kwDOabc123 --reply "$SIGNED"; expect_rc 4 "gh's status propagates on reply"
rm -f "$T/gh.rc"

echo "gh-resolve-thread: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
