#!/usr/bin/env bash
# Tests for worklist. Run: bash .local/bin/worklist.test.sh
# Set AWK_PATH to a directory whose `awk` is another implementation (mawk,
# gawk, original-awk) to run the same cases under it.
#
# What matters: every PR and issue lands in the bucket the routing table says,
# failing checks are named, a cached view is served at once and refreshed
# behind the caller, --brief never waits on a hung GitHub, and every failure
# is named by cause rather than swallowed. gh is faked; GH_MODE picks a reply.
set -uo pipefail
[ -n "${AWK_PATH:-}" ] && PATH="$AWK_PATH:$PATH"

WL="$(cd "$(dirname "$0")" && pwd)/worklist"
pass=0; fail=0
S=$(mktemp -d); export S
cleanup() {
  pkill -f "$S/tmp/worklist-marker" 2>/dev/null
  pkill -f "$S/bin/gh" 2>/dev/null
  rm -rf "$S"
}
trap cleanup EXIT
mkdir -p "$S/bin" "$S/home" "$S/cache" "$S/tmp" "$S/fx" "$S/repo" "$S/nogit" "$S/state/.git" "$S/state/state/global"
export HOME="$S/home" XDG_CACHE_HOME="$S/cache" TMPDIR="$S/tmp" CLAUDE_STATE_REPO="$S/state" FIXTURES="$S/fx"
export GH_LOG="$S/gh.log"; : > "$GH_LOG"
CACHE="$S/cache/worklist"
export PATH="$S/bin:$PATH"

git -C "$S/repo" init -q && git -C "$S/repo" remote add origin https://github.com/o/alpha.git
cd "$S/repo" || exit 1

# --- the board -----------------------------------------------------------------
{
  printf '# Board\n\nA card names the pushed branch pointed-by-board somewhere in its body.\n\n## Needs ruling\n'
  printf -- '### demo\n'
  printf -- '- [ ] **Board sections** — decide whether a question is a card or an issue ([o/r#90](https://github.com/o/r/pull/90))\n'
  printf -- '### global\n'
  printf -- '- [ ] **Engine pin** — decide whether to pin the engine by tag ([o/r#93](https://github.com/o/r/pull/93))\n'
  printf -- '### colregs\n'
  printf -- '- [ ] **Give-way rule** — decide whether rule 15 wins ([o/r#94](https://github.com/o/r/pull/94))\n'
  printf '\n## Solace'"'"'s\n- [ ] **Not an agent card** — [x](https://example.invalid)\n\n## Claude'"'"'s\n'
  for i in 1 2 3 4 5 6 7 8 9 10; do
    printf -- '- [ ] **Card %s** — a card body long enough to be cut at eighty characters when brief is asked for ([link](https://example.invalid/%s))\n' "$i" "$i"
  done
  printf -- '- [x] **Ticked card** — done ([link](https://example.invalid/t))\n'
} > "$S/state/state/global/kanban.md"

# --- canned GitHub -------------------------------------------------------------
pr() { # number title draft mergeable rollup automerge unresolved contexts-json author
  jq -n --argjson n "$1" --arg t "$2" --argjson d "$3" --arg m "$4" --arg r "$5" --argjson am "$6" --argjson u "$7" --argjson cx "$8" --arg a "$9" '
    {number:$n, title:$t, url:"https://github.com/o/alpha/pull/\($n)", isDraft:$d, mergeable:$m,
     autoMergeRequest:(if $am then {enabledAt:"2026-09-08T00:00:00Z"} else null end), author:{login:$a},
     reviewThreads:{nodes:(([range($u)] | map({isResolved:false})) + [{isResolved:true}])},
     commits:{nodes:[{commit:{statusCheckRollup:(if $r == "NONE" then null else {state:$r, contexts:{nodes:$cx}} end)}}]}}'
}
issue() { # number title labels-json milestone-or-null [body]
  jq -n --argjson n "$1" --arg t "$2" --argjson l "$3" --argjson ms "$4" --arg b "${5:-}" '
    {number:$n, title:$t, url:"https://github.com/o/alpha/issues/\($n)", labels:{nodes:($l|map({name:.}))},
     milestone:(if $ms then {title:$ms} else null end), body:$b}'
}
green='[{"name":"ci-gate / gate","conclusion":"SUCCESS"}]'
red='[{"name":"ci-gate / gate","conclusion":"FAILURE"},{"context":"coverage","state":"FAILURE"},{"name":"lint","conclusion":"SUCCESS"}]'
long_title="A title that runs well past the eighty character mark so that brief output has to cut it short somewhere"
{
  echo '{"data":{"repository":{"defaultBranchRef":{"name":"main"},"pullRequests":{"nodes":['
  pr 10 "Ready PR" false MERGEABLE SUCCESS false 0 "$green" o; echo ,
  pr 11 "Queued PR" false MERGEABLE SUCCESS true 0 "$green" o; echo ,
  pr 12 "Threaded PR" false MERGEABLE SUCCESS false 1 "$green" o; echo ,
  pr 13 "Red PR" false MERGEABLE FAILURE false 0 "$red" o; echo ,
  pr 14 "Release PR" false MERGEABLE NONE false 0 '[]' 'release-please[bot]'
  echo ']},"issues":{"nodes":['
  issue 23 "Ready issue" '["ready"]' null; echo ,
  issue 24 "Blocked issue" '["blocked","ready"]' null; echo ,
  issue 25 "Unlabelled" '[]' null; echo ,
  issue 26 "Deferred" '[]' '"1.0"'; echo ,
  issue 27 "Formerly assigned" '[]' null; echo ,
  issue 28 "$long_title" '["ready"]' null; echo ,
  issue 40 "Milestone ready" '["ready"]' '"1.0"'; echo ,
  issue 41 "Milestone blocked" '["blocked"]' '"1.0"'; echo ,
  issue 42 "Points at a branch" '[]' null "see the pointed-by-issue branch for the change"
  echo ']},"refs":{"nodes":['
  echo '{"name":"main","associatedPullRequests":{"totalCount":0}},{"name":"release-please--branches--main","associatedPullRequests":{"totalCount":0}},{"name":"feature-x","associatedPullRequests":{"totalCount":0}},{"name":"pr-branch","associatedPullRequests":{"totalCount":1}},{"name":"pointed-by-board","associatedPullRequests":{"totalCount":0}},{"name":"pointed-by-issue","associatedPullRequests":{"totalCount":0}}'
  # five more unpointed branches, for the stranded bucket's own +N more line
  for i in 1 2 3 4 5; do printf ',{"name":"stray-%s","associatedPullRequests":{"totalCount":0}}' "$i"; done
  echo ']}}}}'
} | jq -c . > "$FIXTURES/alpha.json"
jq -nc '{data:{repository:{defaultBranchRef:{name:"main"},pullRequests:{nodes:[{number:5,title:"Draft PR",url:"https://github.com/o/beta/pull/5",isDraft:true,mergeable:"MERGEABLE",autoMergeRequest:null,author:{login:"o"},reviewThreads:{nodes:[]},commits:{nodes:[{commit:{statusCheckRollup:null}}]}}]},issues:{nodes:[]},refs:{nodes:[{name:"main",associatedPullRequests:{totalCount:0}}]}}}}' > "$FIXTURES/beta.json"
# seven more ready issues, for the +N more line
jq -c '.data.repository.issues.nodes += [range(30;37) | {number:., title:"Ready \(.)", url:"https://github.com/o/alpha/issues/\(.)", labels:{nodes:[{name:"ready"}]}, assignees:{nodes:[]}, milestone:null, comments:{nodes:[]}}]' "$FIXTURES/alpha.json" > "$FIXTURES/alpha-many.json"

cat > "$S/bin/gh" <<'GH'
#!/bin/sh
echo "$*" >> "$GH_LOG"
mode=${GH_MODE:-ok}
case $mode in
  hang) sleep 30; exit 1 ;;
  unauth) echo "To get started with GitHub CLI, please run:  gh auth login" >&2; exit 4 ;;
  network) echo "error connecting to api.github.com" >&2; exit 1 ;;
esac
case "$1 $2" in
  "repo view") printf '{"repositoryTopics":[{"name":"other"},{"name":"project-demo"}]}\n' ;;
  "repo list") printf '[{"name":"alpha"},{"name":"beta"}]\n' ;;
  "search prs") printf '[{"number":1},{"number":2},{"number":3}]\n' ;;
  "search issues") printf '[{"number":1},{"number":2}]\n' ;;
  "api graphql")
    name=""; for a in "$@"; do case $a in name=*) name=${a#name=} ;; esac; done
    if [ "$mode" = 403 ] && [ "$name" = beta ]; then echo "gh: Resource not accessible by integration (HTTP 403)" >&2; exit 1; fi
    if [ "$mode" = many ] && [ "$name" = alpha ]; then name=alpha-many; fi
    cat "$FIXTURES/$name.json" ;;
  *) echo "gh shim: unexpected $*" >&2; exit 1 ;;
esac
GH
chmod +x "$S/bin/gh"

# --- helpers -----------------------------------------------------------------
ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
has()  { if printf '%s\n' "$OUT" | grep -Eq -- "$2"; then ok; else bad "$1 (missing /$2/)" "$OUT"; fi; }
lacks(){ if printf '%s\n' "$OUT" | grep -Eq -- "$2"; then bad "$1 (has /$2/)" "$OUT"; else ok; fi; }
eq()   { if [ "$2" = "$3" ]; then ok; else bad "$1: want [$2] got [$3]"; fi; }
assert() { local d=$1; shift; if "$@"; then ok; else bad "$d"; fi; }
# the lines between a bucket heading and the next real heading -- a bucket
# body is bullets ("- ", board sections) or a table (blank/"| ..." rows,
# GitHub buckets), so only an unmarked, non-blank line ends it.
section() { printf '%s\n' "$OUT_ALL" | awk -v h="$1" 'f && NF > 0 && !/^-/ && !/^\|/ {exit} f {print} index($0, h) == 1 {f=1}'; }
run() { OUT=$(sh "$WL" "$@" 2>&1); RC=$?; OUT_ALL=$OUT; }
calls() { grep -c -- "$1" "$GH_LOG"; }
wait_refresh() { # until the cache written_at is newer than $1, at most 15 s
  local i=0
  while [ "$i" -lt 15 ] && [ "$(jq -r .written_at "$CACHE/o-demo.json")" -le "$1" ]; do sleep 1; i=$((i + 1)); done
}

# --- ok: two repos, every bucket ---------------------------------------------------
: > "$GH_LOG"
run
eq 'exit 0' 0 "$RC"
has 'stamp without cache note' '^as of [0-9]{2}:[0-9]{2}Z$'
has 'scope names the project and repos' '^project demo \(o\): alpha, beta$'
has 'scoped counts first, account-wide after' '^counts: 6 open PRs, 9 open issues in scope; 3 open PRs, 2 open issues across o$'
eq 'one GraphQL call per repo' 2 "$(calls 'api graphql')"
eq 'topic looked up once' 1 "$(calls 'repo view o/alpha --json repositoryTopics')"
eq 'repo set from the topic' 1 "$(calls 'repo list o --topic project-demo')"
eq 'two account-wide searches' 2 "$(calls 'search ')"
OUT_ALL=$OUT
OUT=$(section "Solace's turn")
has 'ready PR is Solace'"'"'s turn' '^\| \[alpha#10\]\(https://github.com/o/alpha/pull/10\) \| Ready PR \|  \|$'
has 'release PR (no checks, bot author) is Solace'"'"'s turn, author named' '^\| \[alpha#14\].* \| Release PR \| by release-please\[bot\]'
lacks 'no issue reaches Solace'"'"'s turn' 'alpha#2[0-9]'
lacks 'the (assigned) suffix is gone' '\(assigned\)'
lacks 'queued PR not Solace'"'"'s turn' 'alpha#11'
lacks 'threaded PR not Solace'"'"'s turn' 'alpha#12'
lacks 'red PR not Solace'"'"'s turn' 'alpha#13'
lacks 'draft PR not Solace'"'"'s turn' 'beta#5'
OUT=$(section "Queued (auto-merge)"); has 'queued PR listed separately' '^\| \[alpha#11\].* \| Queued PR \|'
OUT=$OUT_ALL
has 'Needs ruling reads the board section' "^Needs ruling, showing 2 of 2$"
first_section=$(printf '%s\n' "$OUT_ALL" | grep -E "^(Needs ruling|Solace's turn|Queued|Ready:|Board \()" | head -1)
assert 'Needs ruling prints before every GitHub bucket' [ "$first_section" = "Needs ruling, showing 2 of 2" ]
assert 'and after the counts header' \
  [ "$(printf '%s\n' "$OUT_ALL" | grep -nE '^(counts:|Needs ruling)' | head -1 | cut -d: -f1)" -lt \
    "$(printf '%s\n' "$OUT_ALL" | grep -n '^Needs ruling' | cut -d: -f1)" ]
OUT=$(section "Needs ruling")
has 'a ruling card renders, unprefixed in its own project' '^- \*\*Board sections\*\* — decide whether a question is a card or an issue'
has '### global is in scope everywhere' '^- \*\*Engine pin\*\*'
lacks 'another project'"'"'s group is out of scope' 'Give-way rule'
has 'the hidden groups are counted' '^- \+1 in other projects \(worklist --all-rulings\)$'
lacks 'no issue reaches Needs ruling' 'alpha#'
OUT=$OUT_ALL

# --all-rulings: every group, each card named by its group.
run --all-rulings
has 'all rulings shows every group' '^Needs ruling, showing 3 of 3$'
OUT=$(section "Needs ruling")
has 'a card carries its group'      '^- demo: \*\*Board sections\*\*'
has 'the other project is listed'   '^- colregs: \*\*Give-way rule\*\*'
lacks 'nothing is hidden'           'in other projects'
run
OUT=$OUT_ALL
lacks 'the Ruled, unlanded bucket is gone' 'Ruled, unlanded'
OUT=$(section "Ready"); has 'ready label' '^\| \[alpha#23\].* \| Ready issue \|'; lacks 'blocked beats ready' 'alpha#24'
OUT=$(section "Blocked"); has 'blocked label' '^\| \[alpha#24\].* \| Blocked issue \|'
OUT=$(section "Not ready (agent's turn)")
has 'unresolved thread named as a count' '^\| \[alpha#12\].* \| Threaded PR \| 1 unresolved thread\(s\)'
has 'failing checks named, never a boolean' '^\| \[alpha#13\].* \| Red PR \| failing: ci-gate / gate, coverage'
lacks 'a green check is not listed as failing' 'lint'
has 'draft noted' '^\| \[beta#5\].* \| Draft PR \| draft \|'
OUT=$OUT_ALL
has 'untriaged is a count, deferred separately' '^Untriaged: 3 \(deferred to a milestone: 1\)$'
q_line=$(printf '%s\n' "$OUT_ALL" | grep -n '^Queued (auto-merge)' | cut -d: -f1)
s_line=$(printf '%s\n' "$OUT_ALL" | grep -n '^Stranded branches (no PR)' | cut -d: -f1)
r_line=$(printf '%s\n' "$OUT_ALL" | grep -n '^Ready$\|^Ready:' | head -1 | cut -d: -f1)
assert 'Stranded branches sits after Queued' [ "$q_line" -lt "$s_line" ]
assert 'Stranded branches sits before Ready' [ "$s_line" -lt "$r_line" ]
OUT=$(section "Stranded branches (no PR)")
has 'branch with no PR' '^\| alpha \| feature-x \|  \|$'
has 'each stray branch is its own row' '^\| alpha \| stray-3 \|  \|$'
eq 'one row per branch, all six shown (full mode cap is eight)' 6 "$(printf '%s\n' "$OUT" | grep -c '^| alpha |')"
lacks 'no overflow line under the cap' '\+.* more'
lacks 'main is not stranded' 'main'; lacks 'release-please branch is not stranded' 'release-please'; lacks 'branch with a PR is not stranded' 'pr-branch'
lacks 'branch pointed at by a board card is not stranded' 'pointed-by-board'
lacks 'branch pointed at by an open issue is not stranded' 'pointed-by-issue'
OUT=$OUT_ALL
has 'board heading with counts' "^Board \(## Claude's, showing 8 of 10\)$"
eq 'at most eight cards' 8 "$(printf '%s\n' "$OUT" | grep -c '^- \*\*Card ')"
lacks 'ticked card dropped' 'Ticked card'
has 'Solace section shown with its count' "^Board \(## Solace's, showing 1 of 1\)$"
OUT=$(section "Board (## Solace's")
has 'click-work card shown' 'Not an agent card'
OUT=$OUT_ALL
has 'full mode keeps the whole card' 'eighty characters when brief is asked for \(\[link\]'
has 'long title uncut in full mode' "$long_title"
assert 'cache written under owner-project key' test -f "$CACHE/o-demo.json"

# --- cache-fresh: served at once, nothing fetched ---------------------------------
: > "$GH_LOG"
run
has 'stamp says cached' '^as of [0-9]{2}:[0-9]{2}Z \(cached <1 min\)$'
has 'content from cache' 'alpha#10\].* \| Ready PR \|'
eq 'no gh call on a fresh cache' 0 "$(calls '')"
assert 'no refresh spawned on a fresh cache' test ! -f "$CACHE/o-demo.lock"

# --- cache-stale: served at once, refreshed behind the caller --------------------------
old=$(( $(date +%s) - 1800 ))
jq --argjson t "$old" '.written_at = $t' "$CACHE/o-demo.json" > "$CACHE/tmp.json" && mv "$CACHE/tmp.json" "$CACHE/o-demo.json"
: > "$GH_LOG"
t0=$(date +%s); run; t1=$(date +%s)
has 'stamp says how stale' '^as of [0-9]{2}:[0-9]{2}Z \(cached 30 min\)$'
assert "stale cache served immediately (took $((t1 - t0)) s)" test $((t1 - t0)) -le 2
wait_refresh "$old"
assert 'background refresh rewrote the cache' test "$(jq -r .written_at "$CACHE/o-demo.json")" -gt "$old"
eq 'refresh fetched both repos' 2 "$(calls 'api graphql')"

# --- --fresh bypasses the cache ------------------------------------------------------
: > "$GH_LOG"; run --fresh
has 'fresh stamp has no cache note' '^as of [0-9]{2}:[0-9]{2}Z$'
eq 'fresh fetches' 2 "$(calls 'api graphql')"

# --- --brief ---------------------------------------------------------------------------
GH_MODE=many run --fresh --brief
eq 'exit 0' 0 "$RC"
assert "brief is <= 3 KB ($(printf '%s' "$OUT" | wc -c) bytes)" test "$(printf '%s' "$OUT" | wc -c)" -le 3072
OUT_ALL=$OUT
OUT=$(section "Ready")
eq 'bucket capped at five lines plus header, separator and overflow line' 8 "$(printf '%s\n' "$OUT" | grep -c .)"
has 'overflow line' '^\| \+5 more \| \| run `worklist` \|$'
OUT=$(section "Stranded branches (no PR)")
eq 'stranded branches capped at five rows too, one row per branch' 8 "$(printf '%s\n' "$OUT" | grep -c .)"
has 'stranded overflow line' '^\| \+1 more \| \| run `worklist` \|$'
OUT=$OUT_ALL
lacks 'no urls in brief' 'https://github.com/o/alpha/pull/10'
cut_title=$(printf '%s\n' "$OUT" | sed -n 's/^| alpha#28 | \(.*\) |  |$/\1/p')
eq 'long title cut to 80 chars ending in ...' '80 ...' "$(printf '%s' "$cut_title" | wc -m | tr -d ' ') $(printf '%s' "$cut_title" | tail -c 3)"
lacks 'long title not whole' 'cut it short somewhere'
card1=$(printf '%s\n' "$OUT" | sed -n 's/^- \(\*\*Card 1\*\*.*\)$/\1/p')
eq 'card cut to 80 chars ending in ...' '80 ...' "$(printf '%s' "$card1" | wc -m | tr -d ' ') $(printf '%s' "$card1" | tail -c 3)"
has 'brief keeps the failing check names' 'failing: ci-gate / gate, coverage'

# --- --json ---------------------------------------------------------------------------
run --json
eq 'json exit 0' 0 "$RC"
eq 'json carries both repos' 2 "$(printf '%s' "$OUT" | jq '.records | length')"
eq 'json carries the raw PRs' 5 "$(printf '%s' "$OUT" | jq '.records[0].data.pullRequests.nodes | length')"

# --- --milestone: buckets scoped, milestone not deferred, json same shape ------
run --milestone 1.0
eq 'exit 0' 0 "$RC"
has 'heading names the milestone' "^## Project 'demo' worklist \(milestone: 1.0\)$"
OUT_ALL=$OUT
OUT=$(section "Ready");   has 'milestone ready issue' 'alpha#40\].* \| Milestone ready \|';   lacks 'unscoped ready issue gone' 'alpha#23'
OUT=$(section "Blocked"); has 'milestone blocked issue' 'alpha#41\].* \| Milestone blocked \|'; lacks 'unscoped blocked issue gone' 'alpha#24'
OUT=$OUT_ALL
has 'milestone issues are untriaged, not deferred' '^Untriaged: 1$'
lacks 'no deferred suffix in milestone mode' 'deferred to a milestone'
has 'PR buckets untouched' 'alpha#10\].* \| Ready PR \|'
run --milestone 1.0 --json
eq 'json exit 0' 0 "$RC"
eq 'json keeps the record shape' 2 "$(printf '%s' "$OUT" | jq '.records | length')"
eq 'json issues scoped to the milestone' '["1.0"]' "$(printf '%s' "$OUT" | jq -c '[.records[].data.issues.nodes[].milestone.title] | unique')"
eq 'json PRs untouched' 5 "$(printf '%s' "$OUT" | jq '.records[0].data.pullRequests.nodes | length')"
run --milestone; eq 'bare --milestone is a usage error' 2 "$RC"

# --- one repo 403 ---------------------------------------------------------------------------
GH_MODE=403 run --fresh
eq 'exit 0' 0 "$RC"
has 'the 403 repo named with the fix' '^o/beta: 403 -- attach the repo$'
has 'the other repo still rendered' 'alpha#10\].* \| Ready PR \|'
GH_MODE=403 run --fresh --json; eq 'json exit 0 when something was fetched' 0 "$RC"

# --- gh missing -------------------------------------------------------------------------
mkdir -p "$S/nogh"; for b in sh jq awk sed grep head cut tr date sleep cat mktemp mv rm mkdir git wc dirname nohup setsid; do p=$(command -v $b) && ln -sf "$p" "$S/nogh/$b"; done
rm -f "$CACHE"/*.json
OUT=$(PATH="$S/nogh" sh "$WL" 2>&1); RC=$?
eq 'exit 0 without gh' 0 "$RC"
has 'says no gh' '^no gh'
has 'board still printed without gh' "^Board \(## Claude's"
OUT=$(PATH="$S/nogh" sh "$WL" --json 2>&1); RC=$?
eq 'json exits 1 with nothing fetched' 1 "$RC"

# --- unauthenticated, network: one line, not one per repo -----------------------------------
GH_MODE=unauth run --fresh
eq 'exit 0' 0 "$RC"
has 'unauthenticated named once' '^gh unauthenticated$'
eq 'not repeated per repo' 1 "$(printf '%s\n' "$OUT" | grep -c '^gh unauthenticated$')"
has 'counts named unavailable' '^counts: unavailable'
GH_MODE=network run --fresh
has 'network named' '^network$'
GH_MODE=network run --fresh --json; eq 'json exits 1 when nothing fetched' 1 "$RC"

# --- hang: brief returns inside 6 s --------------------------------------------------------
: > "$GH_LOG"
t0=$(date +%s); GH_MODE=hang run --fresh --brief; t1=$(date +%s)
eq 'exit 0' 0 "$RC"
assert "brief returned in $((t1 - t0)) s (limit 6)" test $((t1 - t0)) -le 6
has 'says GitHub has not answered' 'has not answered in 5 s'
has 'board still printed' "^Board \(## Claude's"
pkill -f "$S/tmp/worklist-marker" 2>/dev/null; pkill -f "$S/bin/gh" 2>/dev/null

# --- --here and an explicit project skip the topic lookup ------------------------------------
: > "$GH_LOG"; run --here --fresh
has 'scope is the cwd repo' '^repo o/alpha alpha$'
eq 'no topic lookup' 0 "$(calls 'repo view')"
eq 'no repo list' 0 "$(calls 'repo list')"
assert 'here cache keyed by repo' test -f "$CACHE/o-alpha.json"
: > "$GH_LOG"; run demo --fresh
has 'explicit project' '^project demo \(o\): alpha, beta$'
eq 'no topic lookup with a project name' 0 "$(calls 'repo view')"
eq 'repo set from the named topic' 1 "$(calls 'repo list o --topic project-demo')"

# --- not in a repo ------------------------------------------------------------------------------
cd "$S/nogit" || exit 1
run
eq 'exit 0 outside a repo' 0 "$RC"
has 'says so' '^not in a GitHub repo'
cd "$S/repo" || exit 1

# --- board edge: no kanban ------------------------------------------------------------------
mv "$S/state/state/global/kanban.md" "$S/kb.bak"; run; has 'missing board named' '^Board: no kanban.md at'; mv "$S/kb.bak" "$S/state/state/global/kanban.md"

# --- the resume bucket is first (dotfiles#110) ------------------------------------
run
has 'resume bucket present' '^Resume: none$'
eq 'resume is the first bucket' 'Resume: none' \
  "$(printf '%s\n' "$OUT" | grep -nE '^(Resume|Needs ruling|Solace|Queued|Ready|Blocked|Untriaged|Stranded)' | head -1 | cut -d: -f2-)"
mkdir -p "$S/state/state/global/log/auto"
{ printf '# Auto-checkpoint — alpha @ `claude/x`\n\n**Verdict:** archivable\n\n- worktree `%s`\n\n' "$S/repo"
  printf '## Resume\n\n- next: Finish the thing\n- link: o/alpha#10\n- model: opus\n- effort: high\n'
} > "$S/state/state/global/log/auto/2026-09-09-alpha-abcd1234.md"
run
has 'a real block shows in worklist' '\| `claude/x` \| Finish the thing \|'
rm -rf "$S/state/state/global/log"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
