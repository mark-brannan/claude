#!/bin/sh
# Tests for prune-wip-refs. Run: sh .local/bin/prune-wip-refs.test.sh
#
# Each of the two safe-to-drop legs is exercised alone (checkpoint says
# landed -- by content, and by a merged PR; old + patch-equivalent) beside
# the cases that must be kept (checkpoint present but not landed, old but
# real unpublished work, fresh with no checkpoint, an ambiguous checkpoint
# match) -- dry run changes nothing, --delete removes exactly the
# candidates, and the printed undo recreates the ref.
set -u

PB="$(cd "$(dirname "$0")" && pwd)/prune-wip-refs"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { d=$1; shift; git -C "$d" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "$@" >/dev/null 2>&1; }
OLD='2020-01-01T00:00:00'   # far older than any --days
commit_old() { GIT_COMMITTER_DATE="$OLD" GIT_AUTHOR_DATE="$OLD" gitq "$1" commit -q --allow-empty -m "$2"; }
NEW="$(( $(date +%s) - 2 * 86400 )) +0000"   # two days ago: inside 14, outside 0
commit_new() { GIT_COMMITTER_DATE="$NEW" GIT_AUTHOR_DATE="$NEW" gitq "$1" commit -q --allow-empty -m "$2"; }

ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
has()  { printf '%s' "$2" | grep -q -- "$1" && ok || bad "expected /$1/ in: $3" "$2"; }
hasnt(){ printf '%s' "$2" | grep -q -- "$1" && bad "did not expect /$1/ in: $3" "$2" || ok; }

# --- a fake gh, for the PR-merged leg: feature-b's PR is the only merged one
mkdir -p "$S/bin"
cat > "$S/bin/gh" <<'EOF'
#!/bin/sh
[ "$1 $2 $3" = "pr view feature-b" ] && echo https://github.com/example/repo/pull/1
exit 0
EOF
chmod +x "$S/bin/gh"
export PATH="$S/bin:$PATH"

# --- a remote and a clone --------------------------------------------------
REMOTE="$S/remote.git"; git init -q --bare "$REMOTE"
R="$HOME/work"; git init -q -b main "$R"; gitq "$R" remote add origin "$REMOTE"
commit_old "$R" base; gitq "$R" push -u origin main
gitq "$R" remote set-head origin main

mkfile() { printf '%s' "$2" > "$R/$3"; gitq "$R" add "$3"; }

# push_wip <sid> <parent-branch> <content> <date-env-fn> -- commits <content>
# to work.txt on top of <parent-branch>'s tip and pushes it straight to
# refs/heads/wip/<sid>, exactly the shape sc_salvage leaves: a commit whose
# parent is a real branch tip, never itself a local branch.
push_wip() {
  sid=$1 parent=$2 content=$3 datefn=$4
  gitq "$R" checkout -q "$parent"
  mkfile "$R" "$content" work.txt
  "$datefn" "$R" "wip: session ${sid} at Stop"
  sha=$(git -C "$R" rev-parse HEAD)
  gitq "$R" push -f origin "HEAD:refs/heads/wip/$sid"
  gitq "$R" checkout -q "$parent"
  gitq "$R" reset -q --hard "origin/$parent"
  printf '%s' "$sha"
}

ckpt_dir="$HOME/claude_prompts_scratch/state/global/log/auto"
mkdir -p "$ckpt_dir"
git init -q -b main "$HOME/claude_prompts_scratch" >/dev/null 2>&1
# Fixture shape matches a real stop-continuity.sh checkpoint's ## Resume
# block: a markdown list, `- link: <url>`, not `**link:**` (dotfiles#357
# review: the old fixture matched the code's old, wrong regex instead of a
# real checkpoint).
write_ckpt() {
  file=$1 branch=$2 sid=$3 link=${4:-}
  {
    printf '# Auto-checkpoint — work @ `%s`\n\n' "$branch"
    printf '**Verdict:** archivable\n\n'
    printf -- '- session `%s` · claude-opus-5 · started 2026-09-22T00:00:00Z\n' "$sid"
    if [ -n "$link" ]; then
      printf '\n## Resume\n\n- next: fixture line.\n- link: %s\n- model: sonnet\n- effort: low\n' "$link"
    fi
  } > "$ckpt_dir/$file"
}

# --- branches each wip ref snapshots ---------------------------------------
gitq "$R" checkout -q -b feature-a main; commit_old "$R" a1; gitq "$R" push -u origin feature-a
gitq "$R" checkout -q -b feature-b main; commit_old "$R" b1; gitq "$R" push -u origin feature-b
gitq "$R" checkout -q -b feature-c main; commit_old "$R" c1; gitq "$R" push -u origin feature-c

# 1) content-landed: wip's diff is byte-identical to what feature-a carries now.
sid_landed=11111111-0000-0000-0000-000000000001
push_wip "$sid_landed" feature-a "same-content" commit_new >/dev/null
gitq "$R" checkout -q feature-a; mkfile "$R" "same-content" work.txt; commit_new "$R" "real fix"
gitq "$R" push origin feature-a
write_ckpt "landed.md" feature-a "$sid_landed"

# 2) PR-merged: checkpoint's branch never caught up, but its PR (per the
# fake gh) has merged.
sid_pr=22222222-0000-0000-0000-000000000002
push_wip "$sid_pr" feature-b "never-landed" commit_new >/dev/null
write_ckpt "pr-merged.md" feature-b "$sid_pr" "https://github.com/example/repo/pull/1"

# 3) checkpoint present, branch not caught up, fresh: kept -- even though its
# Resume link is feature-b's merged PR, the shape a review session leaves.
sid_notyet=33333333-0000-0000-0000-000000000003
push_wip "$sid_notyet" feature-c "still-only-in-wip" commit_new >/dev/null
write_ckpt "notyet.md" feature-c "$sid_notyet" "https://github.com/example/repo/pull/1"

# 4) no checkpoint, old, patch-equivalent to main (squash-merge shape).
sid_squash=44444444-0000-0000-0000-000000000004
sha_squash=$(push_wip "$sid_squash" main "squash-content" commit_old)
gitq "$R" checkout -q main
mkfile "$R" "squash-content" work.txt
gitq "$R" commit -q -m "squash: $sid_squash (simulated merge)"
gitq "$R" push origin main

# 5) no checkpoint, old, real unpublished diff: kept.
sid_realold=55555555-0000-0000-0000-000000000005
push_wip "$sid_realold" main "unique-old-content" commit_old >/dev/null

# 6) no checkpoint, fresh: kept.
sid_fresh=66666666-0000-0000-0000-000000000006
push_wip "$sid_fresh" main "unique-fresh-content" commit_new >/dev/null

# 7) ambiguous checkpoint match: two files claim the same session.
sid_ambig=77777777-0000-0000-0000-000000000007
push_wip "$sid_ambig" main "ambiguous-content" commit_new >/dev/null
write_ckpt "ambig-1.md" feature-a "$sid_ambig"
write_ckpt "ambig-2.md" feature-b "$sid_ambig"

gitq "$R" checkout -q main
gitq "$R" fetch --prune -q

# --- dry run ----------------------------------------------------------------
out=$("$PB" --no-fetch --repo "$R" 2>&1); rc=$?
[ "$rc" = 0 ] && ok || bad "dry run exit $rc" "$out"
has "would delete wip/$sid_landed .*content already on origin/feature-a"      "$out" dry
has "would delete wip/$sid_pr .*PR merged (https://github.com/example/repo/pull/1)" "$out" dry
has "would delete wip/$sid_squash .*patch-equivalent to origin/main"          "$out" dry
has "keep wip/$sid_notyet -- .*not landed"                                    "$out" dry
has "keep wip/$sid_realold -- .*not landed"                                   "$out" dry
has "keep wip/$sid_fresh -- .*not landed"                                     "$out" dry
has "keep wip/$sid_ambig -- .*ambiguous: 2 checkpoints"                       "$out" dry
has 'would delete 3 wip ref(s), kept 4'                                       "$out" dry
has "undo: git -C .* push origin $sha_squash:refs/heads/wip/$sid_squash"      "$out" dry

remote_wip_count() { git -C "$REMOTE" for-each-ref 'refs/heads/wip/*' | wc -l | tr -d ' '; }
[ "$(remote_wip_count)" = 7 ] && ok || bad "dry run deleted a ref" "$(remote_wip_count)"

# --- delete -------------------------------------------------------------------
out=$("$PB" --no-fetch --delete --repo "$R" 2>&1); rc=$?
[ "$rc" = 0 ] && ok || bad "delete exit $rc" "$out"
has 'deleted 3 wip ref(s), kept 4' "$out" delete
[ "$(remote_wip_count)" = 4 ] && ok || bad "wrong number of wip refs left" "$(remote_wip_count)"
git -C "$REMOTE" rev-parse --verify -q "refs/heads/wip/$sid_notyet" >/dev/null 2>&1 && ok || bad "kept ref was deleted: $sid_notyet"

undo=$(printf '%s\n' "$out" | sed -n "s/.*deleted wip\/$sid_squash .*undo: //p")
(cd / && eval "$undo" >/dev/null 2>&1)
[ "$(git -C "$REMOTE" rev-parse "refs/heads/wip/$sid_squash")" = "$sha_squash" ] \
  && ok || bad "printed undo did not restore wip/$sid_squash: $undo"

# --- a repo that cannot be inspected is named and fails the exit ---------------
mkdir -p "$S/notrepo"
out=$("$PB" --no-fetch --repo "$S/notrepo" 2>&1); rc=$?
[ "$rc" = 1 ] && ok || bad "not-a-repo exit $rc" "$out"
has 'not a git repository' "$out" notrepo

# --- --days moves the age floor for the patch-equivalence leg -----------------
sid_days=88888888-0000-0000-0000-000000000008
push_wip "$sid_days" main "days-content" commit_new >/dev/null
gitq "$R" checkout -q main
mkfile "$R" "days-content" work.txt
gitq "$R" commit -q -m "squash: $sid_days (simulated merge, recent)"
gitq "$R" push origin main
gitq "$R" fetch --prune -q
out=$("$PB" --no-fetch --repo "$R" --days 0 2>&1)
has "would delete wip/$sid_days .*patch-equivalent to origin/main" "$out" days0
out=$("$PB" --no-fetch --repo "$R" 2>&1)
has "keep wip/$sid_days" "$out" days-default

echo "prune-wip-refs: $pass passed, $fail failed"
[ "$fail" = 0 ]
