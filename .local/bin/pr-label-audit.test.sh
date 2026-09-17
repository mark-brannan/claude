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
  "repository": { "name": "$1" }, "mergeable": "$5",
  "labels": { "nodes": $6 }, "reviewThreads": { "nodes": $7 },
  "commits": { "nodes": [ { "commit": { "statusCheckRollup": $8 } } ] } }
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
# carrying `after=` is asking for page two, and gets SEARCH_JSON_2 if one is set.
case "$*" in
  *graphql*)
    [ "${GH_FAIL:-0}" = 1 ] && { echo "gh: API rate limit exceeded" >&2; exit 1; }
    case "$*" in
      *after=*) cat "${SEARCH_JSON_2:-$SEARCH_JSON}" ;;
      *)        cat "$SEARCH_JSON" ;;
    esac
    exit 0 ;;
esac
# repos/<owner>/<repo>/labels: only `alpha` defines it, and any repo named in
# GH_LABEL_FAIL cannot be read at all.
for r in ${GH_LABEL_FAIL:-}; do
  case "$*" in *"/$r/labels"*) echo "gh: Not Found" >&2; exit 1 ;; esac
done
case "$*" in
  */alpha/labels*) echo awaiting-human; echo bug; exit 0 ;;
  */labels*)       echo bug; exit 0 ;;
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

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
