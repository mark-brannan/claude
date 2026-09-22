#!/usr/bin/env bash
# Tests for pr-label-audit. Run: bash .local/bin/pr-label-audit.test.sh
#
# The audit is one GraphQL query plus one label lookup per repository, and all
# of its judgement lives in the jq program. So the whole suite is a fake `gh`
# on PATH: a canned search payload in, the rendered sections out.
#
# What matters: every verdict lands in exactly the section that tells the
# reader what to DO about it -- a missing label needs `gh label create`, a
# missing gate needs the ci-gate workflow, a green-but-unlabelled pull request
# means the Mergify rule itself is broken -- and those three have different
# fixes, so confusing them is the one failure that makes the audit useless.
# Drafts are excluded because nobody is waiting on them. And a failing query
# exits non-zero rather than printing a reassuringly empty report, because an
# empty report and a broken query look identical.
# CI sets AWK_PATH to a directory whose `awk` is another implementation and
# runs this under each: the section helpers below are POSIX awk by contract.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

AUDIT="$(cd "$(dirname "$0")" && pwd)/pr-label-audit"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export PR_LABEL_AUDIT_OWNER=testowner

# --- the fixture -------------------------------------------------------------
# One repo that defines the label (alpha) and one that does not (nolabel),
# with a pull request per verdict the jq program can reach.
pr() { # pr <repo> <number> <title> <draft> <mergeable> <labels-json> <threads-json> <rollup-json>
  cat <<EOF
{ "number": $2, "title": "$3", "isDraft": $4,
  "url": "https://github.com/testowner/$1/pull/$2",
  "repository": { "name": "$1", "owner": { "login": "testowner" } }, "mergeable": "$5",
  "labels": { "nodes": $6 }, "reviewThreads": { "nodes": $7 },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "committedDate": "2026-01-01T00:00:00Z",
    "statusCheckRollup": $8 } } ] } }
EOF
}
green='{"contexts":{"nodes":[{"name":"ci-gate / gate","conclusion":"SUCCESS"}]}}'
red='{"contexts":{"nodes":[{"name":"ci-gate / gate","conclusion":"FAILURE"}]}}'
lab='[{"name":"awaiting-human"}]'

# A page as the API returns one: `hasNextPage` decides whether the script
# follows the cursor.
page() { # page <hasNextPage> <nodes-json...>
  local more=$1; shift
  printf '{"data":{"search":{"pageInfo":{"hasNextPage":%s,"endCursor":"CUR"},"nodes":[%s]}}}\n' \
    "$more" "$*"
}

{
  printf '{"data":{"search":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":['
  pr alpha   1 "green and labelled"   false MERGEABLE   "$lab" '[]' "$green"
  printf ,; pr alpha   2 "green unlabelled"     false MERGEABLE   '[]'   '[]' "$green"
  printf ,; pr alpha   3 "stale label"          false MERGEABLE   "$lab" '[]' "$red"
  printf ,; pr alpha   4 "no gate at all"       false MERGEABLE   '[]'   '[]' 'null'
  printf ,; pr alpha   5 "threads open"         false MERGEABLE   '[]'   '[{"isResolved":false}]' "$green"
  printf ,; pr alpha   6 "conflicted"           false CONFLICTING '[]'   '[]' "$green"
  printf ,; pr alpha   7 "a draft"              true  MERGEABLE   '[]'   '[]' "$red"
  printf ,; pr nolabel 1 "repo lacks the label" false MERGEABLE   '[]'   '[]' "$green"
  printf ']}}}\n'
} > "$S/search.json"

BIN="$S/bin"; mkdir -p "$BIN"
cat > "$BIN/gh" <<'EOF'
#!/bin/sh
# graphql: the search payload, or a failure when GH_FAIL is set. A call
# carrying `after=` is asking for page two, and gets SEARCH_JSON_2 if one is
# set, or -- for the exact-page-count boundary test -- counts pages against
# COUNTFILE and swaps in SEARCH_JSON_SEQ_LAST once SEARCH_JSON_SEQ_LAST_AT is
# reached.
COUNTFILE="$(dirname "$0")/.count"
case "$*" in
  *graphql*)
    [ "${GH_FAIL:-0}" = 1 ] && { echo "gh: API rate limit exceeded" >&2; exit 1; }
    case "$*" in
      *pullRequest\(number:*)
        # --pr mode: a single-PR lookup, not a search page.
        cat "$PR_SINGLE_JSON"
        exit 0 ;;
    esac
    case "$*" in
      *after=*)
        if [ -n "${SEARCH_JSON_SEQ_LAST:-}" ]; then
          n=$(( $(cat "$COUNTFILE" 2>/dev/null || echo 1) + 1 ))
          echo "$n" > "$COUNTFILE"
          if [ "$n" -ge "${SEARCH_JSON_SEQ_LAST_AT:-10}" ]; then
            cat "$SEARCH_JSON_SEQ_LAST"
          else
            cat "$SEARCH_JSON"
          fi
        else
          cat "${SEARCH_JSON_2:-$SEARCH_JSON}"
        fi
        ;;
      *) cat "$SEARCH_JSON" ;;
    esac
    exit 0 ;;
esac
# repos/<owner>/<repo>/labels: only `alpha` defines it, and any repo named in
# GH_LABEL_FAIL cannot be read at all.
for r in ${GH_LABEL_FAIL:-}; do
  case "$*" in *"/$r/labels"*) echo "gh: Not Found" >&2; exit 1 ;; esac
done
case "$*" in
  */alpha/labels*) echo awaiting-human; echo bug; echo fixup-hard; exit 0 ;;
  */labels*)       echo bug; exit 0 ;;
esac
# `gh api user -q .login`: the account `--refresh` posts as.
case "$*" in
  *"api user"*) echo "${GH_LOGIN:-mergify-bot}"; exit 0 ;;
esac
# `gh pr comment <n> -R owner/repo --body ...`: record it instead of posting,
# so the test can assert on what would have been sent.
case "$*" in
  "pr comment "*)
    [ "${GH_COMMENT_FAIL:-0}" = 1 ] && { echo "gh: could not comment" >&2; exit 1; }
    echo "$*" >> "$(dirname "$0")/.comments"
    exit 0 ;;
esac
exit 1
EOF
chmod +x "$BIN/gh"
export PATH="$BIN:$PATH" SEARCH_JSON="$S/search.json"

run() { OUT=$(sh "$AUDIT" 2>&1); RC=$?; }
assert() { local m=$1; shift; if "$@"; then pass=$((pass + 1)); else fail=$((fail + 1)); echo "FAIL: $m"; fi; }
has()  { assert "$1: /$2/ in output" grep -qE "$2" <<<"$OUT" || printf '%s\n' "$OUT" | sed 's/^/    /'; }
hasnt() { assert "$1: /$2/ absent" bash -c '! grep -qE "$1" <<<"$2"' _ "$2" "$OUT"; }
eq()   { assert "$1: expected [$2], got [$3]" test "$2" = "$3"; }

# Which `## ` section a given pull request was FIRST printed under.
section_of() { # section_of <repo#number>
  awk -v want="$1" '/^## /{s=$0} index($0, want){print s; exit}' <<<"$OUT"
}
# Whether a given section lists it. A pull request may appear twice on purpose:
# one that is labelled and no longer green is both a stale label to distrust
# and a pull request a session left unfinished, and the reader needs both.
section_lists() { # section_lists <heading substring> <repo#number>
  awk -v head="$1" -v want="$2" '
    /^## /{ inside = index($0, head) > 0 }
    inside && index($0, want) { found = 1 }
    END { exit found ? 0 : 1 }' <<<"$OUT"
}

# --- the happy path -----------------------------------------------------------
run
eq 'exit 0 on a good query' 0 "$RC"
has 'Your turn is always present' '^## Your turn \(1\)$'
has 'and ends with the live search link' 'https://github.com/pulls\?q=.*label%3Aawaiting-human'

# --- each verdict lands in the section that names its fix ----------------------
eq 'green + labelled is your turn' \
  '## Your turn (1)' "$(section_of 'alpha#1')"
eq 'green + unlabelled indicts the Mergify rule' \
  '## Green and thread-free but NOT labelled' "$(section_of 'alpha#2')"
assert 'labelled but red is listed as a stale label' \
  section_lists 'Labelled but no longer green' 'alpha#3 '
assert 'and also as work a session left unfinished' \
  section_lists 'a session left these unfinished' 'alpha#3 '
hasnt 'but never as your turn' 'alpha#3.*your turn'
eq 'a missing gate is its own section' \
  '## No `ci-gate / gate` check -- the label can never apply' "$(section_of 'alpha#4')"
eq 'threads open is unfinished work, not a broken rule' \
  '## Gated, unlabelled -- a session left these unfinished' "$(section_of 'alpha#5')"
eq 'a conflict is unfinished work too' \
  '## Gated, unlabelled -- a session left these unfinished' "$(section_of 'alpha#6')"
has 'and the verdict is spelled out inline' 'alpha#6 \[conflicted\]'
has 'as it is for threads' 'alpha#5 \[threads-open\]'

# --- a repo without the label is a repo problem, not a PR problem --------------
has 'the repo is named once, under its own heading' \
  '^## Repositories that do not define the `awaiting-human` label'
eq 'the repo, not its PRs, is listed' '## Repositories that do not define the `awaiting-human` label' \
  "$(section_of 'nolabel')"
hasnt 'and its green PR is not blamed on the Mergify rule' 'nolabel#1'
has 'the fix is a copy-pasteable command' 'gh label create awaiting-human -R testowner/<repo>'

# --- drafts are nobody`s turn ---------------------------------------------------
hasnt 'draft excluded' 'alpha#7'

# --- empty sections do not print --------------------------------------------------
page false "$(pr alpha 1 'green and labelled' false MERGEABLE "$lab" '[]' "$green")" > "$S/search.json"
run
eq 'a clean audit still exits 0' 0 "$RC"
eq 'and prints exactly one heading' 1 "$(grep -c '^## ' <<<"$OUT")"
has 'the one that matters' '^## Your turn \(1\)$'

# --- nothing at all is said so, not left blank --------------------------------------
page false > "$S/search.json"
run
has 'no open PRs says nothing, not an empty list' '  nothing'

# --- a second page is followed, not silently dropped ----------------------------------
# A truncated report looks exactly like a complete one, which is the failure
# the whole script exists to avoid.
page true  "$(pr alpha 1 'on page one' false MERGEABLE "$lab" '[]' "$green")" > "$S/search.json"
page false "$(pr alpha 2 'on page two' false MERGEABLE "$lab" '[]' "$green")" > "$S/page2.json"
SEARCH_JSON_2="$S/page2.json" run
eq 'both pages counted' 0 "$RC"
has 'page one kept' 'alpha#1 on page one'
has 'page two fetched and merged' 'alpha#2 on page two'
has 'and both are your turn' '^## Your turn \(2\)$'
unset SEARCH_JSON_2

# --- a cursor that never ends is a refusal, not an under-report -------------------------
page true "$(pr alpha 1 'endless' false MERGEABLE "$lab" '[]' "$green")" > "$S/search.json"
run
eq 'runaway pagination exits non-zero' 1 "$RC"
has 'and says the report would be incomplete' 'more than 1000 open pull requests'
hasnt 'rather than printing a partial report' '## Your turn'

# --- exactly 1000 results (10 full pages, no more) is not a refusal --------------------
# The 10th page completing with hasNextPage:false is a finished report, not the
# runaway case above -- the refusal must check the cursor before counting pages.
rm -f "$BIN/.count"
page true "$(pr alpha 1 'on an early page' false MERGEABLE "$lab" '[]' "$green")" > "$S/search.json"
page false "$(pr alpha 2 'on the last page' false MERGEABLE "$lab" '[]' "$green")" > "$S/last.json"
SEARCH_JSON_SEQ_LAST="$S/last.json" run
eq 'a report that completes on page ten is not a refusal' 0 "$RC"
has 'the last page is still counted' 'alpha#2 on the last page'
unset SEARCH_JSON_SEQ_LAST

# --- a label lookup that FAILED is not a repo that lacks the label -------------------------
# Folding the two together prints `gh label create` as the fix for a transient
# API error -- wrong advice, and the audit exists to stop exactly that.
page false "$(pr beta 1 'lookup will fail' false MERGEABLE '[]' '[]' "$green")" > "$S/search.json"
GH_LABEL_FAIL=beta run
eq 'an unreadable lookup still exits 0' 0 "$RC"
has 'reported as not checked' '^## Repositories whose labels could not be read'
eq 'and listed only there' '## Repositories whose labels could not be read' "$(section_of 'beta')"
hasnt 'never as a repo that lacks the label' 'do not define'
hasnt 'and no create-the-label advice' 'gh label create awaiting-human -R testowner/<repo>'
has 'the reader is told not to act on it' 'do NOT create the label here'
hasnt 'nor is its green PR blamed on the Mergify rule' 'beta#1 lookup'

# --- a repo that genuinely lacks the label is still reported as missing -----------------------
run
eq 'a readable lookup exits 0' 0 "$RC"
has 'missing, not unchecked' '^## Repositories that do not define the `awaiting-human` label'
hasnt 'and not reported as unreadable' 'could not be read'

# --- a broken query must not look like a clean audit ----------------------------------
GH_FAIL=1 run
eq 'a failed query exits non-zero' 1 "$RC"
has 'and says so' 'the GitHub query failed'
hasnt 'rather than printing a reassuring report' '## Your turn'

# --- a missing dependency is named ------------------------------------------------------
EMPTY="$S/empty"; mkdir -p "$EMPTY"
OUT=$(PATH="$EMPTY" /bin/sh "$AUDIT" 2>&1); RC=$?
eq 'no gh: exit 1' 1 "$RC"
has 'no gh: names the tool' 'pr-label-audit: gh is required'

# --- --json: one row per PR, mapped 1:1 onto the human section headings ----------------
# repo `nolabel` still lacks both labels here (fixup-hard is added back to its
# label list where a test needs it defined instead).
runargs() { OUT=$(sh "$AUDIT" "$@" 2>&1); RC=$?; }
# How many recorded `gh pr comment` calls match a pattern -- 0 when none, or
# when nothing was recorded at all. (`grep -c` prints 0 AND exits 1 on no
# match, so `|| echo 0` would print a second 0.)
posted() { { grep -c -- "$1" "$BIN/.comments" 2>/dev/null; } | { read -r n; echo "${n:-0}"; }; }
row() { # row <repo#number> -- the one JSON object for that PR, from ndjson output
  printf '%s\n' "$OUT" | jq -c "select(has(\"number\")) | select(\"\\(.repo)#\\(.number)\" == \"$1\")"
}

{
  printf '{"data":{"search":{"pageInfo":{"hasNextPage":false,"endCursor":null},"nodes":['
  pr alpha 1 "green and labelled"   false MERGEABLE   "$lab" '[]' "$green"
  printf ,; pr alpha 2 "green unlabelled" false MERGEABLE '[]' '[]' "$green"
  printf ,; pr alpha 3 "stale label"      false MERGEABLE "$lab" '[]' "$red"
  printf ,; pr alpha 4 "no gate at all"   false MERGEABLE '[]' '[]' 'null'
  printf ,; pr nolabel 1 "repo lacks the label" false MERGEABLE '[]' '[]' "$green"
  printf ']}}}\n'
} > "$S/search.json"
runargs --json
eq '--json exits 0' 0 "$RC"
eq 'green + labelled maps to your-turn' 'your-turn' "$(row 'alpha#1' | jq -r .section)"
eq 'green + unlabelled maps to green-unlabelled' 'green-unlabelled' "$(row 'alpha#2' | jq -r .section)"
eq 'labelled + red maps to stale-label (one row, not two)' 'stale-label' "$(row 'alpha#3' | jq -r .section)"
eq 'no gate maps to no-gate' 'no-gate' "$(row 'alpha#4' | jq -r .section)"
eq 'green + unlabelled + repo missing the label maps to no-label-repo' 'no-label-repo' "$(row 'nolabel#1' | jq -r .section)"
eq 'exactly one JSON row per PR' 1 "$(printf '%s\n' "$OUT" | jq -c 'select(has("number"))' | grep -c 'alpha#3\|"number":3')"
has '--json also carries the repo-level fixup-hard fact' 'repos_missing_fixup_hard'
eq 'nolabel is missing fixup-hard' 'nolabel' "$(printf '%s\n' "$OUT" | jq -r 'select(has("repos_missing_fixup_hard")) | .repos_missing_fixup_hard[]' | grep -x nolabel)"
eq 'each row carries mergeable' 'MERGEABLE' "$(row 'alpha#1' | jq -r .mergeable)"
eq 'and its labels array' '["awaiting-human"]' "$(row 'alpha#1' | jq -c .labels)"

# --- --pr: a single PR, restricted to one repository's query --------------------------
PR_SINGLE_JSON="$S/single.json"
cat > "$PR_SINGLE_JSON" <<EOF
{"data":{"repository":{"pullRequest":
$(pr colregs 193 "single PR lookup" false CONFLICTING '[]' '[]' "$green")
}}}
EOF
export PR_SINGLE_JSON
runargs --pr mark-brannan/colregs#193
eq '--pr exits 0' 0 "$RC"
has '--pr text mode still renders the human report' 'colregs#193'
runargs --pr mark-brannan/colregs#193 --json
eq '--pr --json exits 0' 0 "$RC"
eq '--pr --json is a single object, addressable with plain jq .field' \
  'CONFLICTING' "$(printf '%s\n' "$OUT" | jq -r 'select(has("number")) | .mergeable')"
eq '--pr --json has no repos_missing_fixup_hard line -- it is a fleet-wide fact, out of scope for one PR' \
  '' "$(printf '%s\n' "$OUT" | jq -r 'select(has("repos_missing_fixup_hard"))')"
eq '--pr --json carries the head commit date, not the API-deprecated pushedDate' \
  '2026-01-01T00:00:00Z' "$(printf '%s\n' "$OUT" | jq -r 'select(has("number")) | .head_committed_at')"

cat > "$PR_SINGLE_JSON" <<EOF
{"data":{"repository":{"pullRequest":
$(pr colregs 194 "a draft" true MERGEABLE '[]' '[]' "$green")
}}}
EOF
runargs --pr mark-brannan/colregs#194 --json
eq '--pr on a draft exits 0' 0 "$RC"
has '--pr on a draft says so instead of printing nothing' 'colregs#194 is a draft'
hasnt '--pr on a draft emits no row' '"number"'

# --- argument parsing: strict, because --refresh writes ------------------------------
runargs --jsno
eq 'an unknown flag exits 1' 1 "$RC"
has 'and names it' 'unknown argument: --jsno'
runargs --pr
eq 'a bare --pr exits 1' 1 "$RC"
has 'and prints usage' 'usage: pr-label-audit'
runargs --pr nonsense
eq '--pr without owner/repo#n exits 1' 1 "$RC"

# --- failing_checks: only checks that finished badly ---------------------------------
mixed='{"contexts":{"nodes":[{"name":"ci-gate / gate","conclusion":"SUCCESS"},{"name":"slow","status":"IN_PROGRESS","conclusion":null},{"name":"skipped","conclusion":"SKIPPED"},{"name":"lint","conclusion":"FAILURE","detailsUrl":"https://example.test/lint"},{"context":"legacy","state":"PENDING"}]}}'
page false "$(pr alpha 9 'mixed checks' false MERGEABLE '[]' '[]' "$mixed")" > "$S/search.json"
runargs --json
eq 'a running, skipped or pending check is not a failing one' '["lint"]' "$(row 'alpha#9' | jq -c '[.failing_checks[].name]')"
eq 'and a failing check carries its url' 'https://example.test/lint' "$(row 'alpha#9' | jq -r '.failing_checks[0].url')"

# --- --refresh: idempotent, and never fires without the flag ---------------------------
rm -f "$BIN/.comments"
page false "$(pr alpha 1 'stale label' false MERGEABLE "$lab" '[]' "$red")" > "$S/search.json"
run
eq 'default (no --refresh) still exits 0' 0 "$RC"
[ -f "$BIN/.comments" ] && { fail=$((fail + 1)); echo "FAIL: no --refresh: a comment was posted anyway"; } || pass=$((pass + 1))

rm -f "$BIN/.comments"
GH_LOGIN=mergify-bot runargs --refresh
eq '--refresh (nothing already posted) exits 0' 0 "$RC"
eq 'exactly one comment was posted, to the stale-label PR, by number and -R repo' 1 \
  "$(posted '^pr comment 1 -R testowner/alpha ')"
eq 'the comment text is exactly the refresh trigger' 1 \
  "$(posted '--body @mergifyio refresh')"

# A green-but-unlabelled PR in a repo that defines the label is the other
# refresh target; a green-and-labelled one is not.
rm -f "$BIN/.comments"
page false "$(pr alpha 2 'green unlabelled' false MERGEABLE '[]' '[]' "$green"),$(pr alpha 1 'green and labelled' false MERGEABLE "$lab" '[]' "$green")" > "$S/search.json"
GH_LOGIN=mergify-bot runargs --refresh
eq 'green-unlabelled is refreshed' 1 "$(posted '^pr comment 2 -R testowner/alpha ')"
eq 'green-and-labelled is left alone' 0 "$(posted '^pr comment 1 ')"

# Re-running --refresh right after must not repost: the fixture's PR now
# carries a lastComments entry matching what was just "posted".
page false "$(cat <<JSON
{ "number": 1, "title": "stale label", "isDraft": false,
  "url": "https://github.com/testowner/alpha/pull/1",
  "repository": { "name": "alpha", "owner": {"login": "testowner"} }, "mergeable": "MERGEABLE",
  "labels": { "nodes": $lab }, "reviewThreads": { "nodes": [] },
  "lastComments": { "nodes": [ { "author": {"login": "mergify-bot"}, "body": "@mergifyio refresh",
    "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" } ] },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "pushedDate": "2026-01-01T00:00:00Z", "statusCheckRollup": $red } } ] } }
JSON
)" > "$S/search.json"
rm -f "$BIN/.comments"
GH_LOGIN=mergify-bot runargs --refresh
eq 'already-refreshed within 24h: exits 0' 0 "$RC"
[ -f "$BIN/.comments" ] && { fail=$((fail + 1)); echo "FAIL: idempotency: reposted anyway"; } || pass=$((pass + 1))
unset GH_LOGIN

# --- a nested connection that truncates is a refusal, not an under-report (dotfiles#277) --
# `pr()` never sets totalCount, so it defaults to 0 and never trips this --
# these fixtures set it by hand to simulate GitHub reporting more items than
# the `first:` page actually returned.
trunc_labels='{ "number": 30, "title": "truncated labels", "isDraft": false,
  "url": "https://github.com/testowner/alpha/pull/30",
  "repository": { "name": "alpha", "owner": {"login": "testowner"} }, "mergeable": "MERGEABLE",
  "labels": { "totalCount": 25, "nodes": [{"name":"awaiting-human"}] },
  "reviewThreads": { "nodes": [] },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "committedDate": "2026-01-01T00:00:00Z",
    "statusCheckRollup": '"$green"' } } ] } }'
page false "$trunc_labels" > "$S/search.json"
run
eq 'a truncated labels connection is a refusal' 1 "$RC"
has 'and names the PR and which connection truncated' 'alpha#30: labels truncated \(25 total, 1 fetched\)'
hasnt 'rather than a report built on partial data' '## Your turn'

trunc_threads='{ "number": 31, "title": "truncated threads", "isDraft": false,
  "url": "https://github.com/testowner/alpha/pull/31",
  "repository": { "name": "alpha", "owner": {"login": "testowner"} }, "mergeable": "MERGEABLE",
  "labels": { "nodes": [] },
  "reviewThreads": { "totalCount": 150, "nodes": [] },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "committedDate": "2026-01-01T00:00:00Z",
    "statusCheckRollup": '"$green"' } } ] } }'
page false "$trunc_threads" > "$S/search.json"
run
eq 'a truncated reviewThreads connection is a refusal too' 1 "$RC"
has 'named specifically' 'alpha#31: reviewThreads truncated \(150 total, 0 fetched\)'

trunc_checks='{ "number": 32, "title": "truncated checks", "isDraft": false,
  "url": "https://github.com/testowner/alpha/pull/32",
  "repository": { "name": "alpha", "owner": {"login": "testowner"} }, "mergeable": "MERGEABLE",
  "labels": { "nodes": [] }, "reviewThreads": { "nodes": [] },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "committedDate": "2026-01-01T00:00:00Z",
    "statusCheckRollup": {"contexts": {"totalCount": 120,
      "nodes": [{"name":"ci-gate / gate","conclusion":"SUCCESS"}]}} } } ] } }'
page false "$trunc_checks" > "$S/search.json"
run
eq 'a truncated check-contexts connection is a refusal too' 1 "$RC"
has 'named specifically' 'alpha#32: checks truncated \(120 total, 1 fetched\)'

# A PR with no truncation at all, alongside the exact page sizes (20 labels,
# 100 threads, 100 contexts), must not false-positive.
full_labels=$(seq 1 20 | { i=0; out='['; while read -r n; do [ "$i" -gt 0 ] && out="$out,"; out="$out{\"name\":\"label-$n\"}"; i=$((i+1)); done; echo "$out]"; })
exact_pr='{ "number": 33, "title": "exactly at the page size", "isDraft": false,
  "url": "https://github.com/testowner/alpha/pull/33",
  "repository": { "name": "alpha", "owner": {"login": "testowner"} }, "mergeable": "MERGEABLE",
  "labels": { "totalCount": 20, "nodes": '"$full_labels"' },
  "reviewThreads": { "totalCount": 0, "nodes": [] },
  "commits": { "nodes": [ { "commit": { "oid": "abc", "committedDate": "2026-01-01T00:00:00Z",
    "statusCheckRollup": {"contexts": {"totalCount": 1,
      "nodes": [{"name":"ci-gate / gate","conclusion":"SUCCESS"}]}} } } ] } }'
page false "$exact_pr" > "$S/search.json"
run
eq 'totalCount equal to the fetched count is not a truncation' 0 "$RC"
has 'the PR is reported normally' 'alpha#33'

# --- --pr mode goes through the same truncation check -----------------------------------
cat > "$PR_SINGLE_JSON" <<EOF
{"data":{"repository":{"pullRequest":$trunc_labels}}}
EOF
runargs --pr mark-brannan/alpha#30
eq '--pr on a truncated PR is a refusal too' 1 "$RC"
has 'with the same message' 'alpha#30: labels truncated'
unset PR_SINGLE_JSON

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
