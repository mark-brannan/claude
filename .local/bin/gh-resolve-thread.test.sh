#!/usr/bin/env bash
# Tests for gh-resolve-thread. Run: bash .local/bin/gh-resolve-thread.test.sh
#
# What matters: exactly one argument, shaped like a thread id; the mutation
# sent to gh is the hard-coded resolveReviewThread and nothing else; the id
# travels as a variable, not inside the query; and a reply that does not say
# isResolved:true is a failure. gh is faked and records its argv.
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/gh-resolve-thread"
pass=0; fail=0
T=$(mktemp -d); export T
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
export PATH="$T/bin:$PATH"
cat > "$T/bin/gh" <<'G'
#!/bin/sh
printf '%s\n' "$@" > "$T/gh.argv"
rc=$(cat "$T/gh.rc" 2>/dev/null || echo 0); [ "$rc" -eq 0 ] || { echo "gh: boom" >&2; exit "$rc"; }
cat "$T/gh.out" 2>/dev/null
G
chmod +x "$T/bin/gh"

run() { rc=0; : > "$T/gh.argv"; out=$(sh "$SCRIPT" "$@" 2>&1) || rc=$?; }
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; echo "  rc=$rc out=$out"; }
expect_rc() { [ "$rc" -eq "$1" ] && ok || bad "$2 (want rc $1)"; }
expect_out() { case $out in *"$1"*) ok ;; *) bad "$2 (want output containing '$1')" ;; esac; }

# --- usage ------------------------------------------------------------------
run;                    expect_rc 1 "no args refused"; expect_out usage "no args prints usage"
[ -s "$T/gh.argv" ] && bad "no args must not call gh" || ok
run a b;                expect_rc 1 "two args refused"
run 12345;              expect_rc 1 "non-PRRT id refused"; expect_out "not a review-thread id" "non-PRRT id names the shape"
[ -s "$T/gh.argv" ] && bad "bad id must not call gh" || ok

# --- happy path: hard-coded mutation, id as a variable ----------------------
printf '{"data":{"resolveReviewThread":{"thread":{"isResolved":true}}}}\n' > "$T/gh.out"
run PRRT_kwDOabc123
expect_rc 0 "resolved thread exits 0"; expect_out "resolved PRRT_kwDOabc123" "reports the id"
argv=$(cat "$T/gh.argv")
case $argv in
  *'resolveReviewThread(input:{threadId:$id})'*) ok ;; *) bad "mutation is resolveReviewThread with a variable" ;;
esac
grep -qx 'id=PRRT_kwDOabc123' "$T/gh.argv" && ok || bad "id passed as -f id=<threadId>"
grep -q 'PRRT_kwDOabc123' <(grep '^query=' "$T/gh.argv") && bad "id must not be interpolated into the query" || ok
grep -qE 'deleteRef|closePullRequest' "$T/gh.argv" && bad "only one mutation" || ok
[ "$(head -1 "$T/gh.argv") $(sed -n 2p "$T/gh.argv")" = "api graphql" ] && ok || bad "calls gh api graphql"

# --- failure paths ------------------------------------------------------------
printf '{"data":{"resolveReviewThread":{"thread":{"isResolved":false}}}}\n' > "$T/gh.out"
run PRRT_kwDOabc123;    expect_rc 1 "isResolved:false is a failure"; expect_out "not resolved" "says not resolved"
printf '{"errors":[{"message":"Could not resolve to a node"}]}\n' > "$T/gh.out"
run PRRT_kwDOnope;      expect_rc 1 "GraphQL error is a failure"; expect_out "Could not resolve" "surfaces the GraphQL error"
echo 4 > "$T/gh.rc"
run PRRT_kwDOabc123;    expect_rc 4 "gh's own exit status propagates"
rm -f "$T/gh.rc"

echo "gh-resolve-thread: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
