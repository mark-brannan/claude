#!/usr/bin/env bash
# Tests for worklist. Run: bash bin/worklist.test.sh
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
unset CLAUDE_CODE_SESSION_ATTENDED
export HOME="$S/home" XDG_CACHE_HOME="$S/cache" TMPDIR="$S/tmp" CLAUDE_STATE_REPO="$S/state" FIXTURES="$S/fx"
export GH_LOG="$S/gh.log"; : > "$GH_LOG"
CACHE="$S/cache/worklist"
export PATH="$S/bin:$PATH"

git -C "$S/repo" init -q && git -C "$S/repo" remote add origin https://github.com/o/alpha.git
cd "$S/repo" || exit 1

# --- the board -----------------------------------------------------------------
# The cards are written in the old kanban.md line format and moved into the
# store the way the cutover did: one item per card, the line its brief
# verbatim (an id: is appended where a card has none), the section its owner,
# a `### group` its repo. kanban.md itself is never written.
I="$S/state/state/global/items"
migrate() { # migrate <board text file> <items dir> [<first synthetic id number>]
  local n=${3:-0}
  mkdir -p "$2"
  awk '
    function flush() { if (txt != "") print owner "\t" repo "\t" txt; txt = "" }
    /^## / { flush(); owner = ($0 ~ /Needs ruling/ ? "human-ruling" : $0 ~ /Human/ ? "human-click" : "agent"); repo = "-"; next }
    /^### / { flush(); repo = "o/" substr($0, 5); if (repo == "o/global") repo = "-"; next }
    /^- \[[xX]\]/ { flush(); skip = 1; next }
    /^- \[ \] / { flush(); skip = 0; txt = substr($0, 7); next }
    txt != "" && !skip && /^[ \t]+[^ \t]/ { t = $0; sub(/^[ \t]+/, "", t); txt = txt " " t; next }
    { flush() }
    END { flush() }' "$1" > "$S/migrate.tsv"
  while IFS=$'\t' read -r owner repo line; do
    n=$((n + 1))
    id=$(printf '%s' "$line" | grep -oE 'id: [0-9]{10}[0-9a-f]{8}' | head -1 | cut -c5-)
    if [ -z "$id" ]; then id=$(printf '1790837%03d%08x' "$n" "$n"); line="$line id: $id"; fi
    title=$(printf '%s' "$line" | sed -nE 's/^\*\*([^*]+)\*\*.*/\1/p')
    [ -n "$title" ] || title=$(printf '%s' "$line" | sed -E 's/\[([^]]*)\]\([^)]*\)/\1/g' | cut -c1-60)
    printf '# %s\n\n## Brief\n%s\n\n## Log\n2026-09-01T05:00:00Z 1d68120b status=open owner=%s repo=%s parent=- model=- effort=-\n2026-09-01T05:00:00Z 1d68120b briefed\n2026-09-01T05:00:00Z 1d68120b status=ready\n' \
      "$title" "$line" "$owner" "$repo" > "$2/$id.md"
  done < "$S/migrate.tsv"
}
{
  printf '# Board\n\n## Needs ruling\n'
  printf -- '### demo\n'
  printf -- '- [ ] **Board sections** — decide whether a question is a card or an issue ([o/r#90](https://github.com/o/r/pull/90))\n'
  printf -- '- [ ] **Later** — decide after the migration ([o/r#95](https://github.com/o/r/pull/95))\n'
  printf -- '      default: keep undo: revert until: the next migration risk: low judgment: direction\n'
  printf -- '### global\n'
  printf -- '- [ ] **Engine pin** — decide whether to pin the engine by tag ([o/r#93](https://github.com/o/r/pull/93)) id: 1790836842077c62eb\n'
  printf -- '### colregs\n'
  printf -- '- [ ] **Give-way rule** — decide whether rule 15 wins ([o/r#94](https://github.com/o/r/pull/94))\n'
  printf '\n## Human'"'"'s\n- [ ] **Not an agent card** — pointed-by-board names a pushed branch ([x](https://example.invalid))\n\n## Claude'"'"'s\n'
  printf -- '- [ ] **Card 0** — linked to its evidence, worked elsewhere ([o/beta#5](https://github.com/o/beta/pull/5)) repo: o/alpha id: 1790836843077c62eb\n'
  for i in 1 2 3 4 5 6 7; do
    printf -- '- [ ] **Card %s** — a card body long enough to be cut at eighty characters when brief is asked for ([link](https://example.invalid/%s))\n' "$i" "$i"
  done
  # Two more id'd cards so the side task's ordering is exercised: Card 8 is
  # newer and in the cwd repo (never beats Card 0); Card 9 is the oldest of
  # all but has no repo (wins only outside a repo).
  printf -- '- [ ] **Card 8** — newer, same repo ([link](https://example.invalid/8)) repo: o/alpha id: 1790836844077c62eb\n'
  printf -- '- [ ] **Card 9** — oldest, no repo ([link](https://example.invalid/9)) id: 1790836840077c62eb\n'
  printf -- '- [x] **Ticked card** — done ([link](https://example.invalid/t))\n'
} > "$S/board-src.md"
migrate "$S/board-src.md" "$I"

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
  # a salvage ref also shows up in the plain refs page, where it must not read as stranded
  printf ',{"name":"wip/aaaa1111-0000-0000-0000-000000000001","associatedPullRequests":{"totalCount":0}}'
  echo ']},"wip":{"nodes":['
  # one ref three days old (fixed date well in the past is not stable, so compute it)
  printf '{"name":"aaaa1111-0000-0000-0000-000000000001","target":{"committedDate":"%s"}},' "$(date -u -d '3 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-3d +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"name":"bbbb2222-0000-0000-0000-000000000002","target":{"committedDate":"%s"}}' "$(date -u -d '5 hours ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-5H +%Y-%m-%dT%H:%M:%SZ)"
  echo ']}}}}'
} | jq -c . > "$FIXTURES/alpha.json"
jq -nc '{data:{repository:{defaultBranchRef:{name:"main"},pullRequests:{nodes:[{number:5,title:"Draft PR",url:"https://github.com/o/beta/pull/5",isDraft:true,mergeable:"MERGEABLE",autoMergeRequest:null,author:{login:"o"},reviewThreads:{nodes:[]},commits:{nodes:[{commit:{statusCheckRollup:null}}]}}]},issues:{nodes:[]},refs:{nodes:[{name:"main",associatedPullRequests:{totalCount:0}}]}}}}' > "$FIXTURES/beta.json"
# seven more ready issues, for the +N more line
# (no salvage refs in this one: the brief view's 3 KB cut would otherwise land on the board tail the cut-card assertions read)
jq -c '.data.repository.wip.nodes = [] | .data.repository.issues.nodes += [range(30;37) | {number:., title:"Ready \(.)", url:"https://github.com/o/alpha/issues/\(.)", labels:{nodes:[{name:"ready"}]}, assignees:{nodes:[]}, milestone:null, comments:{nodes:[]}}]' "$FIXTURES/alpha.json" > "$FIXTURES/alpha-many.json"

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
  "api repos/"*)
    # sub_issues: a fixture named for the parent, else none
    k=$(printf '%s' "$2" | sed -e 's#^repos/##' -e 's#/issues/#-#' -e 's#/sub_issues.*##' -e 's#/#-#g')
    if [ -f "$FIXTURES/subs-$k.json" ]; then cat "$FIXTURES/subs-$k.json"; else echo '[]'; fi ;;
  "api graphql")
    case " $* " in *issueOrPullRequest*) echo issue-open; exit 0 ;; esac
    name=""; for a in "$@"; do case $a in name=*) name=${a#name=} ;; esac; done
    # pickup-list's fixup-hard search: no name=, a q= instead.
    case " $* " in *" q=is:pr "*) printf '{"data":{"search":{"nodes":[]}}}\n'; exit 0 ;; esac
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
has()  { if grep -Eq -- "$2" <<<"$OUT"; then ok; else bad "$1 (missing /$2/)" "$OUT"; fi; }
lacks(){ if grep -Eq -- "$2" <<<"$OUT"; then bad "$1 (has /$2/)" "$OUT"; else ok; fi; }
eq()   { if [ "$2" = "$3" ]; then ok; else bad "$1: want [$2] got [$3]"; fi; }
assert() { local d=$1; shift; if "$@"; then ok; else bad "$d"; fi; }
# the lines between a bucket heading and the next real heading -- a bucket
# body is bullets ("- ", board sections) or a table (blank/"| ..." rows,
# GitHub buckets), so only an unmarked, non-blank line ends it.
section() { printf '%s\n' "$OUT_ALL" | awk -v h="$1" 'f && NF > 0 && !/^-/ && !/^\|/ {exit} f {print} index($0, h) == 1 {f=1}'; }
run() { OUT=$(sh "$WL" "$@" 2>&1); RC=$?; OUT_ALL=$OUT; }
calls() { grep -c -- "$1" "$GH_LOG"; }

# The resume section is pickup-list's, and pickup-list now looks up the PRs a
# fixer gave up on -- once an hour, cached. Seed that cache fresh and empty so
# the counts below stay a measurement of worklist's own fetching, which is
# what every assertion here is actually about.
mkdir -p "$XDG_CACHE_HOME/pickup-list"; : > "$XDG_CACHE_HOME/pickup-list/fixup-hard"
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
OUT=$(section "Human's turn")
has 'ready PR is Human'"'"'s turn' '^\| \[alpha#10\]\(https://github.com/o/alpha/pull/10\) \| Ready PR \|  \|$'
has 'release PR (no checks, bot author) is Human'"'"'s turn, author named' '^\| \[alpha#14\].* \| Release PR \| by release-please\[bot\]'
lacks 'no issue reaches Human'"'"'s turn' 'alpha#2[0-9]'
lacks 'the (assigned) suffix is gone' '\(assigned\)'
lacks 'queued PR not Human'"'"'s turn' 'alpha#11'
lacks 'threaded PR not Human'"'"'s turn' 'alpha#12'
lacks 'red PR not Human'"'"'s turn' 'alpha#13'
lacks 'draft PR not Human'"'"'s turn' 'beta#5'
OUT=$(section "Queued (auto-merge)"); has 'queued PR listed separately' '^\| \[alpha#11\].* \| Queued PR \|'
OUT=$OUT_ALL
has 'Needs ruling lists the ready cards by default' "^Needs ruling \(ready\), showing 2 of 2$"
has 'the counts line: in scope, ready, waiting, other projects, each section' \
  "^Board: Needs ruling 3 \(2 ready, 1 waiting: --waiting, all: --all\), \+1 in other projects \(--all-rulings\); Human's 1; Claude's 10$"
first_section=$(printf '%s\n' "$OUT_ALL" | grep -E "^(Board:|Needs ruling|Human's turn|Queued|Ready:|Board \()" | head -1)
assert 'the board counts print before every GitHub bucket' [ "${first_section%% *}" = "Board:" ]
assert 'and after the counts header' \
  [ "$(printf '%s\n' "$OUT_ALL" | grep -nE '^(counts:|Needs ruling)' | head -1 | cut -d: -f1)" -lt \
    "$(printf '%s\n' "$OUT_ALL" | grep -n '^Needs ruling' | cut -d: -f1)" ]
OUT=$(section "Needs ruling")
has 'a ruling card renders, unprefixed in its own project' '^- ([0-9a-f]{18} )?\*\*Board sections\*\* — decide whether a question is a card or an issue'
has '### global is in scope everywhere' '^- 1790836842077c62eb \*\*Engine pin\*\*'
lacks 'another project'"'"'s group is out of scope' 'Give-way rule'
lacks 'a waiting card is hidden by default' 'Later'
has 'the hidden groups are counted' '^- \+1 in other projects \(worklist --all-rulings\)$'
lacks 'no issue reaches Needs ruling' 'alpha#'
OUT=$OUT_ALL

# --all-rulings: every group, each card named by its group.
run --all-rulings
has 'all rulings shows every group' '^Needs ruling \(ready\), showing 3 of 3$'
OUT=$(section "Needs ruling")
has 'a card carries its group'      '^- demo: ([0-9a-f]{18} )?\*\*Board sections\*\*'
has 'the other project is listed'   '^- colregs: ([0-9a-f]{18} )?\*\*Give-way rule\*\*'
lacks 'nothing is hidden'           'in other projects'

# --waiting and --all: the drill paths behind the counts line.
run --waiting
OUT=$(section "Needs ruling")
has 'waiting lists the card whose until: is words' '^- ([0-9a-f]{18} )?\*\*Later\*\* — decide after the migration'
lacks 'waiting hides the ready cards' 'Board sections|Engine pin'
run --brief
has 'brief carries the counts line too' '^Board: Needs ruling 3 \(2 ready, 1 waiting'
run --all
has 'all lists every in-scope ruling card' '^Needs ruling \(all\), showing 3 of 3$'
OUT=$(section "Needs ruling")
has 'all marks the waiting card' '^- \[waiting\] ([0-9a-f]{18} )?\*\*Later\*\*'
has 'all leaves a ready card unmarked' '^- 1790836842077c62eb \*\*Engine pin\*\*'
OUT=$OUT_ALL
has 'all lifts the 8-card cap on a board section' "^Board \(## Claude's, showing 10 of 10\)$"
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
lacks 'a wip salvage ref is not a stranded branch' 'wip/'
w_line=$(printf '%s\n' "$OUT_ALL" | grep -n '^Salvaged edits (wip refs)' | cut -d: -f1)
assert 'Salvaged edits sits after Stranded branches' [ "$s_line" -lt "$w_line" ]
assert 'Salvaged edits sits before Ready' [ "$w_line" -lt "$r_line" ]
OUT=$(section "Salvaged edits (wip refs)")
has 'salvage ref listed whole, in the form git fetch takes, with its age' '^\| alpha \| wip/aaaa1111-0000-0000-0000-000000000001 \| 3d old \|$'
has 'a fresh salvage ref is aged in hours' '^\| alpha \| wip/bbbb2222-0000-0000-0000-000000000002 \| [0-9]+h old \|$'
assert 'oldest salvage ref first' [ "$(printf '%s\n' "$OUT" | grep -n 'aaaa1111' | cut -d: -f1)" -lt "$(printf '%s\n' "$OUT" | grep -n 'bbbb2222' | cut -d: -f1)" ]
eq 'beta has none, so only alpha rows' 2 "$(printf '%s\n' "$OUT" | grep -c '^| alpha |')"
OUT=$OUT_ALL
has 'board heading with counts' "^Board \(## Claude's, showing 8 of 10\)$"
eq 'at most eight cards' 8 "$(printf '%s\n' "$OUT" | grep -Ec '^- ([0-9a-f]{18} )?\*\*Card ')"
lacks 'ticked card dropped' 'Ticked card'
has "Human's section shown with its count" "^Board \(## Human's, showing 1 of 1\)$"
OUT=$(section "Board (## Human's")
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
card1=$(printf '%s\n' "$OUT" | sed -n 's/^- \(.*\*\*Card 9\*\*.*\)$/\1/p')
eq 'card cut to 80 chars ending in ...' '80 ...' "$(printf '%s' "$card1" | wc -m | tr -d ' ') $(printf '%s' "$card1" | tail -c 3)"
has 'brief keeps the failing check names' 'failing: ci-gate / gate, coverage'

# --- --json ---------------------------------------------------------------------------
run --json
eq 'json exit 0' 0 "$RC"
eq 'json carries both repos' 2 "$(printf '%s' "$OUT" | jq '.records | length')"
eq "a card's repo: field routes it, not its link" 'o/alpha' "$(printf '%s' "$OUT" | jq -r '.buckets.claudes[] | select(.name == "Card 0") | .repo')"
eq 'a card without repo: routes on its github link' 'o/r' "$(printf '%s' "$OUT" | jq -r '.buckets.rulings[] | select(.name == "Give-way rule") | .repo')"
eq 'a card with neither repo: nor a github link has no repo' 'null' "$(printf '%s' "$OUT" | jq -r '.buckets.claudes[] | select(.name == "Card 1") | .repo')"
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

# --- Ready: parents, sub-issues, two repos ------------------------------------------
# alpha#50 Ready parent, children in alpha and beta; alpha#51 Ready parent, all
# children closed-or-unready; alpha#52 not Ready, with Ready child alpha#53.
sub() { # repo number title labels-json state
  jq -nc --arg r "$1" --argjson n "$2" --arg t "$3" --argjson l "$4" --arg s "$5" \
    '{number:$n, title:$t, state:$s, html_url:"https://github.com/o/\($r)/issues/\($n)", repository_url:"https://api.github.com/repos/o/\($r)",
      labels:($l|map({name:.})), body:"", updated_at:"2026-09-20T00:00:00Z"}'
}
{ sub alpha 60 "Child in alpha" '["ready"]' open; sub beta 61 "Child in beta" '["ready"]' open
  sub alpha 62 "Child blocked" '["ready","blocked"]' open; sub alpha 63 "Child closed" '["ready"]' closed; } | jq -sc . > "$FIXTURES/subs-o-alpha-50.json"
{ sub alpha 64 "Child not ready" '[]' open; } | jq -sc . > "$FIXTURES/subs-o-alpha-51.json"
jq -c '.data.repository.issues.nodes += [
    {number:50,title:"Parent two repos",url:"https://github.com/o/alpha/issues/50",labels:{nodes:[{name:"ready"}]},milestone:null,body:""},
    {number:51,title:"Parent nothing ready",url:"https://github.com/o/alpha/issues/51",labels:{nodes:[{name:"ready"}]},milestone:null,body:""},
    {number:53,title:"Orphan-ish child",url:"https://github.com/o/alpha/issues/53",labels:{nodes:[{name:"ready"}]},milestone:null,body:"",
      parent:{number:52,title:"Unlabelled parent",url:"https://github.com/o/alpha/issues/52",repository:{nameWithOwner:"o/alpha"}}},
    {number:60,title:"Child in alpha",url:"https://github.com/o/alpha/issues/60",labels:{nodes:[{name:"ready"}]},milestone:null,body:"",
      parent:{number:50,title:"Parent two repos",url:"https://github.com/o/alpha/issues/50",repository:{nameWithOwner:"o/alpha"}}}]' \
  "$FIXTURES/alpha.json" > "$FIXTURES/alpha-subs.json"
cp "$FIXTURES/alpha.json" "$FIXTURES/alpha-plain.json"; cp "$FIXTURES/alpha-subs.json" "$FIXTURES/alpha.json"
: > "$GH_LOG"; run --fresh
OUT_ALL=$OUT; OUT=$(section "Ready")
has 'a parent is a parent line, with its Ready count' '^\| \[alpha#50\].* \| Parent two repos \| parent, 2 Ready \|$'
has 'its same-repo Ready child is indented under it' '^\| \[alpha#60\].* \|   ↳ Child in alpha \|'
has 'its other-repo Ready child carries its own repo' '^\| \[beta#61\]\(https://github.com/o/beta/issues/61\) \|   ↳ Child in beta \|'
lacks 'a blocked child is not Ready' 'alpha#62'
lacks 'a closed child is not Ready' 'alpha#63'
has 'a parent with no Ready children is still a parent line' '^\| \[alpha#51\].* \| Parent nothing ready \| parent, none Ready \|$'
lacks 'its unready child is not listed' 'alpha#64'
has 'a Ready child of a non-Ready parent shows under the parent' '^\| \[alpha#52\].* \| Unlabelled parent \| parent \(not Ready\), 1 Ready \|$'
has 'and is indented under it' '^\| \[alpha#53\].* \|   ↳ Orphan-ish child \|'
assert 'no child is also a top-level Ready row' \
  [ "$(printf '%s\n' "$OUT" | grep -c 'alpha#60')" = 1 ]
has 'a childless Ready issue is still a plain row' '^\| \[alpha#23\].* \| Ready issue \|'
assert 'the child follows its parent' \
  [ "$(printf '%s\n' "$OUT" | grep -n 'alpha#50\|alpha#60\|beta#61' | cut -d: -f1 | tr '\n' ' ')" = "$(printf '%s\n' "$OUT" | grep -n 'alpha#50' | cut -d: -f1) $(( $(printf '%s\n' "$OUT" | grep -n 'alpha#50' | cut -d: -f1) + 1 )) $(( $(printf '%s\n' "$OUT" | grep -n 'alpha#50' | cut -d: -f1) + 2 )) " ]
eq 'one sub_issues call per Ready, unblocked issue' 7 "$(calls 'sub_issues')"
OUT=$OUT_ALL
run --json
eq 'json ready holds leaves, never a parent' '[]' "$(printf '%s' "$OUT" | jq -c '[.buckets.ready[] | select(.number == 50 or .number == 51 or .number == 52)]')"
eq 'json child names its parent' 'o/alpha#50' "$(printf '%s' "$OUT" | jq -r '.buckets.ready[] | select(.repo == "o/beta") | .parent')"
cp "$FIXTURES/alpha-plain.json" "$FIXTURES/alpha.json"

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

# --- board edge: no items/ ------------------------------------------------------------------
# A kanban.md beside the store is not a fallback: with no items/ the board is
# unavailable, whatever the file holds.
cp "$S/board-src.md" "$S/state/state/global/kanban.md"
mv "$I" "$S/items.bak"; run; has 'missing store named' '^Board: no items/ at'; lacks 'a kanban.md is not read' 'Engine pin'; mv "$S/items.bak" "$I"
rm -f "$S/state/state/global/kanban.md"

# --- the pickup bucket is first (dotfiles#110) ------------------------------------
run
has 'the board'"'"'s Claude cards are pickup candidates' '^Pickup, newest first$'
eq 'pickup is the first bucket' 'Pickup, newest first' \
  "$(printf '%s\n' "$OUT" | grep -nE '^(Pickup|Needs ruling|Human|Queued|Ready|Blocked|Untriaged|Stranded)' | head -1 | cut -d: -f2-)"
mkdir -p "$S/state/state/global/pickup"
printf 'status: open\nupdated: 2026-09-09T10:00:00Z\nsession: abcd1234\nmodel: claude-opus-5-5\nbranch: alpha claude/x (1 ahead, clean)\npr: none\nwhere: w\nprompt: p\n---\nFinish the thing\nlink: o/alpha#10\nmodel: opus\neffort: high\n' \
  > "$S/state/state/global/pickup/2026-09-09T10-00-abcd1234.md"
run
has 'a real item shows in worklist' 'Finish the thing'
# One line shape for both kinds: marker, title, age, model, effort, until, link.
shape() { printf '%s\n' "$OUT" | grep -E "$1" | head -1 | sed -E 's/^  (.) .{56}  (.{4})  (.{6})  (.{6})  (.{12})  [^ ]+.*$/ok/'; }
eq 'a pickup item renders in the shared shape' ok "$(shape 'Finish the thing')"
eq 'a card renders in the same shape' ok "$(shape '^  ◆ ')"
rm -rf "$S/state/state/global/pickup"

# --- the background refresh warms the ruling-link cache --brief reads ------------
printf '## Needs ruling\n### global\n- [ ] **Linked** — wait on it ([o/r#7](https://github.com/o/r/issues/7)) default: a undo: revert until: o/r#7 risk: low judgment: direction\n' > "$S/linked.md"
migrate "$S/linked.md" "$I" 500
sh "$WL" --_refresh
eq 'refresh caches the state of an until: link' issue-open "$(cut -d' ' -f2 "$XDG_CACHE_HOME/ruling-refs/o_r_7" 2>/dev/null)"
run --brief
has 'brief reads the warmed cache: the linked card waits' '^Board: Needs ruling 4 \(2 ready, 2 waiting'
rm -f "$I"/1790837501*.md

# --- a card id is a handle ----------------------------------------------------
run card 1790836842077c62eb
has 'card <id> names the section and group' '^## Needs ruling / global$'
has 'card <id> prints the card' 'Engine pin'
run card 1790836842077c62ec; eq 'an unknown id exits 1' 1 "$RC"
run card 179083684; eq 'a malformed id exits 2' 2 "$RC"
run --all-rulings
has 'a ruling card leads with its id' '^- global: 1790836842077c62eb \*\*Engine pin'
has 'a Claude card leads with its id' '^- 1790836843077c62eb \*\*Card 0'
lacks 'the trailing id field is not repeated' 'alpha id:'

# --- side task: one Claude card for an attended session -------------------------
CLAUDE_CODE_SESSION_ATTENDED=1 run --brief
has 'attended brief offers a side task' "^Side task \(Claude's queue, oldest in this repo\):$"
has 'side task names the cwd-repo card by id' '^  1790836843077c62eb Card 0$'
OUT=$(printf '%s\n' "$OUT" | sed -n '/^Side task/,/^$/p')
lacks 'a newer card in the same repo does not beat the oldest' 'Card 8'
lacks 'an older card outside the repo does not beat the cwd-repo card' 'Card 9'
has 'side task says land it or re-card it' '^  -> do it after the main work, or leave a one-line reason on the card$'
run --brief
lacks 'headless brief has no side task' 'Side task'
(cd "$S" && CLAUDE_CODE_SESSION_ATTENDED=1 sh "$WL" --brief) > "$S/side.out" 2>&1
OUT=$(cat "$S/side.out")
has 'outside a repo the side task falls back to oldest overall' "^Side task \(Claude's queue, oldest overall\):$"
has 'oldest overall is the oldest id, not the first line or the cwd-repo card' '^  1790836840077c62eb Card 9$'

# --- more items ------------------------------------------------------------------
# An item renders as a card under its owner's section; a done item is not on
# the board.
item() { # id title owner repo status brief
  printf '# %s\n\n## Brief\n%s\n\n## Log\n2026-10-03T05:00:00Z 1d68120b status=open owner=%s repo=%s parent=- model=opus effort=high\n2026-10-03T05:00:00Z 1d68120b briefed\n2026-10-03T05:00:00Z 1d68120b status=%s\n' \
    "$2" "$6" "$3" "$4" "$5" > "$I/$1.md"
}
item 1790836845aaaaaaaa 'Item task' agent o/alpha ready 'Do the stored thing.'
item 1790836846aaaaaaaa 'Stored ruling' human-ruling o/colregs ready 'Decide the stored thing.'
item 1790836847aaaaaaaa 'Finished item' agent o/alpha 'done' 'Already done.'
run --all
has 'an item is a Claude card, drawn with its title and id' '^- 1790836845aaaaaaaa \*\*Item task\*\*: Do the stored thing\. repo: o/alpha model: opus effort: high$'
lacks 'a done item is not on the board' 'Finished item'
has 'the Claude count is every agent item' "^Board \(## Claude's, showing 11 of 11\)$"
run --all-rulings
has 'a ruling item is grouped by its repo' '^- colregs: 1790836846aaaaaaaa \*\*Stored ruling\*\*'
run card 1790836845aaaaaaaa
has 'card <id> finds an item' "^## Claude's$"
run --fresh --json
eq 'json carries the item' 1 "$(printf '%s' "$OUT" | jq '[.. | strings | select(contains("1790836845aaaaaaaa"))] | length > 0 | if . then 1 else 0 end')"
rm -f "$I"/179083684[567]aaaaaaaa.md

# --- a store past the argv limit (one arg is capped near 128KB) ------------------------
awk 'BEGIN{print "## Human'"'"'s"; for(i=0;i<1500;i++) printf "- [ ] **Bulk card %d** — padding padding padding padding padding padding padding padding padding padding ([o/r#%d](https://github.com/o/r/issues/%d)) id: 17908%013d\n", i, i, i, i}' > "$S/bulk.md"
migrate "$S/bulk.md" "$I"
run --fresh --json; eq 'oversized board: json exit 0' 0 "$RC"
lacks 'oversized board: no argv overflow' 'Argument list too long'
rm -f "$I"/17908000*.md "$I"/179080[0-9]*.md

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
