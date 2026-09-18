#!/usr/bin/env bash
# Tests for prune-branches. Run: bash .local/bin/prune-branches.test.sh
# Each of the three legs (old / not on remote / gone-or-contained) is failed
# alone by one branch; dry run changes nothing; --delete removes exactly the
# candidates and the printed undo works from any cwd.
set -uo pipefail

PB="$(cd "$(dirname "$0")" && pwd)/prune-branches"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }
OLD='2020-01-01T00:00:00'   # far older than any --days
commit_old() { GIT_COMMITTER_DATE="$OLD" GIT_AUTHOR_DATE="$OLD" gitq "$1" commit -q --allow-empty -m "$2"; }
NEW="$(( $(date +%s) - 2 * 86400 )) +0000"   # two days ago: inside 14, outside 0
commit_new() { GIT_COMMITTER_DATE="$NEW" GIT_AUTHOR_DATE="$NEW" gitq "$1" commit -q --allow-empty -m "$2"; }

ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
has()  { printf '%s' "$2" | grep -q -- "$1" && ok || bad "expected /$1/ in: $3" "$2"; }
hasnt(){ printf '%s' "$2" | grep -q -- "$1" && bad "did not expect /$1/ in: $3" "$2" || ok; }

# --- a remote and a clone with one branch per rule ---------------------------
REMOTE="$S/remote.git"; git init -q --bare "$REMOTE"
R="$HOME/work"; git init -q -b main "$R"; gitq "$R" remote add origin "$REMOTE"
commit_old "$R" base; gitq "$R" push -u origin main
gitq "$R" remote set-head origin main

mk() { gitq "$R" checkout -q -b "$1" main; }

mk old-merged;        commit_old "$R" x; gitq "$R" push -u origin old-merged
                      gitq "$R" push origin --delete old-merged   # PR merged, GitHub deleted it
mk old-contained;     gitq "$R" branch --unset-upstream 2>/dev/null; # level with main, never pushed
mk old-unique;        commit_old "$R" y                             # never pushed, has work
mk old-on-remote;     commit_old "$R" z; gitq "$R" push -u origin old-on-remote
mk old-tracks-main;   gitq "$R" branch -u origin/main               # upstream is main, contained
mk old-ahead-of-main; commit_old "$R" w; gitq "$R" branch -u origin/main
mk new-merged;        commit_new "$R" v; gitq "$R" push -u origin new-merged
                      gitq "$R" push origin --delete new-merged
mk wt-clean;          commit_old "$R" c; gitq "$R" push -u origin wt-clean; gitq "$R" push origin --delete wt-clean
mk wt-dirty;          commit_old "$R" d; gitq "$R" push -u origin wt-dirty; gitq "$R" push origin --delete wt-dirty
gitq "$R" checkout -q main
gitq "$R" worktree add "$S/wt-clean" wt-clean
gitq "$R" worktree add "$S/wt-dirty" wt-dirty; echo junk > "$S/wt-dirty/junk"
gitq "$R" fetch --prune

# --- dry run -----------------------------------------------------------------
out=$("$PB" --no-fetch --repo "$R" 2>&1); rc=$?
[ "$rc" = 0 ] && ok || bad "dry run exit $rc" "$out"
has 'would delete old-merged .*upstream origin/old-merged gone'   "$out" dry
has 'would delete old-contained .*contained in origin/main'       "$out" dry
has 'would delete old-tracks-main .*contained in origin/main'     "$out" dry
has 'would delete wt-clean .*+worktree'                           "$out" dry
has 'keep old-unique -- 1 commit(s) not on any remote'            "$out" dry
has 'keep old-ahead-of-main -- 1 commit(s) not on any remote'     "$out" dry
has 'keep wt-dirty -- worktree dirty'                             "$out" dry
hasnt 'old-on-remote'                                             "$out" dry
hasnt 'new-merged'                                                "$out" dry
hasnt ' main '                                                    "$out" dry
has 'would delete 4 branch(es), kept 3'                           "$out" dry
has 'undo: git -C .* branch old-merged [0-9a-f]\{12\}'            "$out" dry
before=$(git -C "$R" for-each-ref refs/heads | wc -l)
[ "$before" = 10 ] && ok || bad "dry run changed branches: $before"

# --- --days moves the line -----------------------------------------------------
out=$("$PB" --no-fetch --repo "$R" --days 0 2>&1)
has 'would delete new-merged' "$out" days0

# --- delete ------------------------------------------------------------------
sha=$(git -C "$R" rev-parse old-merged)
out=$("$PB" --no-fetch --delete --repo "$R" 2>&1); rc=$?
undo=$(printf '%s\n' "$out" | sed -n 's/.*deleted old-merged .*undo: //p')
[ "$rc" = 0 ] && ok || bad "delete exit $rc" "$out"
has 'deleted 4 branch(es), kept 3' "$out" delete
left=$(git -C "$R" for-each-ref --format='%(refname:short)' refs/heads | sort | tr '\n' ' ')
[ "$left" = "main new-merged old-ahead-of-main old-on-remote old-unique wt-dirty " ] && ok || bad "branches after delete: $left"
[ ! -e "$S/wt-clean" ] && ok || bad "clean worktree not removed"
[ -e "$S/wt-dirty/junk" ] && ok || bad "dirty worktree was touched"
(cd / && eval "$undo" >/dev/null 2>&1) && [ "$(git -C "$R" rev-parse old-merged)" = "$sha" ] \
  && ok || bad "printed undo did not restore old-merged from an unrelated cwd: $undo"

# --- a repo that cannot be inspected is named and fails the exit ---------------
mkdir -p "$S/notrepo"
out=$("$PB" --no-fetch --repo "$S/notrepo" 2>&1); rc=$?
[ "$rc" = 1 ] && ok || bad "not-a-repo exit $rc" "$out"
has 'not a git repository' "$out" notrepo

# --- default repo set: list file + dotfiles + yadm ------------------------------
mkdir -p "$HOME/.local/share"
printf 'work\nmissing\n' > "$HOME/.local/share/vended-repos.txt"
git init -q -b main "$HOME/dotfiles"; commit_old "$HOME/dotfiles" i
YADM="$HOME/.local/share/yadm/repo.git"; git init -q --bare "$YADM"
out=$("$PB" --no-fetch 2>&1)
has 'across 3 repo(s)' "$out" default-set

echo "prune-branches: $pass passed, $fail failed"
[ "$fail" = 0 ]
