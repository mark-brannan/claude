#!/usr/bin/env bash
# Tests for resign-branch.sh. Run: bash .local/bin/resign-branch.test.sh
#
# What matters: the rebase target is the PR's base (a stacked PR stays
# stacked), the orphan guard sees every clone of the repo on the machine and
# stops when it can't, a foreign author email is caught by whole-line match,
# and an unanswerable base lookup refuses rather than guesses. Everything runs
# against a local bare "origin" with a throwaway ssh key; gh and yadm are faked.
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/resign-branch.sh"
pass=0; fail=0
T=$(mktemp -d); export T
trap 'chmod -R u+rwx "$T" 2>/dev/null; rm -rf "$T"' EXIT
mkdir -p "$T/home" "$T/bin"
export HOME="$T/home" GIT_CONFIG_GLOBAL="$T/gitconfig" PATH="$T/bin:$PATH"
unset GIT_CONFIG_COUNT
ssh-keygen -q -t ed25519 -N '' -f "$T/key" -C test
cat > "$GIT_CONFIG_GLOBAL" <<G
[user]
	name = Test User
	email = me@example.com
	signingkey = $T/key.pub
[gpg]
	format = ssh
[commit]
	gpgsign = true
[init]
	defaultBranch = main
G
# gh: --head/--json baseRefName queries answer from gh.out, --base from
# gh.children, --json number (the Head:-line PR lookup) from gh.pr-number,
# --json body from gh.pr-body, and `pr edit ... --body <text>` captures
# <text> into gh.edit-body so a test can inspect what would have been
# written; gh.rc forces a failure of every gh call.
cat > "$T/bin/gh" <<'G'
#!/bin/sh
rc=$(cat "$T/gh.rc" 2>/dev/null || echo 0); [ "$rc" -eq 0 ] || { echo "gh: boom" >&2; exit "$rc"; }
case "$*" in
  *"pr edit"*)
    want_body=0
    for a in "$@"; do
      if [ "$want_body" = 1 ]; then printf '%s' "$a" > "$T/gh.edit-body"; want_body=0; fi
      [ "$a" = "--body" ] && want_body=1
    done
    ;;
  *"--head"*"--json number"*) cat "$T/gh.pr-number" 2>/dev/null ;;
  *"--base"*"--json number"*) cat "$T/gh.children" 2>/dev/null ;;
  *"--json body"*) cat "$T/gh.pr-body" 2>/dev/null ;;
  *--head*) cat "$T/gh.out" 2>/dev/null ;;
  *--base*) cat "$T/gh.children" 2>/dev/null ;;
esac
G
cat > "$T/bin/yadm" <<'G'
#!/bin/sh
[ "$1 $2" = "introspect repo" ] && { printf '%s\n' "$T/yadm-repo.git"; exit 0; }; exit 1
G
chmod +x "$T/bin/gh" "$T/bin/yadm"
: > "$T/gh.out"; : > "$T/gh.children"; : > "$T/gh.pr-number"; : > "$T/gh.pr-body"; : > "$T/gh.edit-body"

# --- fixture: origin, a work clone, and two more clones standing in for
# ~/dotfiles/.git and the yadm repo -------------------------------------------
git init -q --bare "$T/origin.git"
git clone -q "$T/origin.git" "$T/work" 2>/dev/null
W="$T/work"
git -C "$W" commit -q --allow-empty -m root && git -C "$W" push -q origin main
git -C "$W" remote set-head origin main
git -C "$W" checkout -q -b feat-a && echo a > "$W/a" && git -C "$W" add a && git -C "$W" commit -q -m "feat-a 1" && git -C "$W" push -q origin feat-a
git -C "$W" checkout -q -b feat-b && echo b > "$W/b" && git -C "$W" add b && git -C "$W" commit -q -m "feat-b 1"
git -C "$W" -c commit.gpgsign=false commit -q --amend --author="Not Me <notme@example.com>" --no-edit
git -C "$W" push -q origin feat-b
git -C "$W" checkout -q main && echo m > "$W/m" && git -C "$W" add m && git -C "$W" commit -q -m "main 2" && git -C "$W" push -q origin main
git clone -q "$T/origin.git" "$HOME/dotfiles" 2>/dev/null
git clone -q "$T/origin.git" "$T/yadm-wt" 2>/dev/null && mv "$T/yadm-wt/.git" "$T/yadm-repo.git"
git -C "$W" fetch -q origin

run() { rc=0; out=$(cd "$W" && "$SCRIPT" "$@" 2>&1) || rc=$?; }
ok()   { n=$1; shift; if "$@"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $n"; printf '%s\n' "$out" | sed 's/^/    /'; fi; }
has()  { case "$out" in *"$2"*) ok "$1" true ;; *) ok "$1" false ;; esac; }

# --- 1. stacked PR: rebases onto the PR's base, not main; foreign author caught ---
echo feat-a > "$T/gh.out"; echo 99 > "$T/gh.children"
run feat-b
ok  'stacked: exits 0' [ $rc -eq 0 ]
has 'stacked: rebase target is the base branch' 'rebasing onto origin/feat-a'
has 'stacked: whole-line email match sees notme@' '1 not authored as me@example.com'
has 'stacked: warns about the PR stacked on this one' 'base of open PR(s) 99'
git -C "$W" fetch -q origin
ok  'stacked: rewritten tip still sits on feat-a' [ "$(git -C "$W" log -1 --format=%s origin/feat-b~1)" = "feat-a 1" ]
ok  'stacked: tip reauthored to local email' [ "$(git -C "$W" log -1 --format=%ae origin/feat-b)" = me@example.com ]
ok  'stacked: parent branch untouched' [ "$(git -C "$W" rev-parse origin/feat-a)" = "$(git -C "$W" rev-parse origin/feat-b~1)" ]

# --- 2. no open PR: falls back to the default branch, says so ---
: > "$T/gh.out"; : > "$T/gh.children"
run feat-a
ok  'no PR: exits 0' [ $rc -eq 0 ]
has 'no PR: names the fallback' 'no open PR for feat-a; rebasing onto the default branch origin/main'
git -C "$W" fetch -q origin
ok  'no PR: rebased onto main' [ "$(git -C "$W" log -1 --format=%s origin/feat-a~1)" = "main 2" ]

# --- 3. orphan guard sees the second clone ---
git --git-dir="$T/yadm-repo.git" fetch -q origin
git --git-dir="$T/yadm-repo.git" branch -q feat-a origin/feat-a
(cd "$T" && git --git-dir="$T/yadm-repo.git" worktree add -q "$T/yadm-tmp" feat-a)
git -C "$T/yadm-tmp" -c commit.gpgsign=false commit -q --allow-empty -m "unpushed in yadm clone"
(cd "$T" && git --git-dir="$T/yadm-repo.git" worktree remove --force "$T/yadm-tmp")
echo m2 >> "$W/m" && git -C "$W" commit -q -am "main 3" && git -C "$W" push -q origin main
run feat-a
ok  'orphan in other clone: refuses' [ $rc -eq 1 ]
has 'orphan in other clone: names the clone' "feat-a in $T/yadm-repo.git has 1 commit(s) not on origin/feat-a"
ok  'orphan in other clone: remote untouched' [ "$(git -C "$W" log -1 --format=%s origin/feat-a~1)" = "main 2" ]
git --git-dir="$T/yadm-repo.git" branch -q -f feat-a origin/feat-a

# --- 4. gh unusable: refuse with the override named; override works ---
echo 1 > "$T/gh.rc"
run feat-a
ok  'gh broken: refuses' [ $rc -eq 1 ]
has 'gh broken: names RESIGN_BASE' 'Set RESIGN_BASE=<branch>'
rc=0; out=$(cd "$W" && RESIGN_BASE=main "$SCRIPT" feat-a 2>&1) || rc=$?
ok  'RESIGN_BASE: exits 0 with gh broken' [ $rc -eq 0 ]
has 'RESIGN_BASE: rebases onto the named base' 'rebasing onto origin/main'
echo 0 > "$T/gh.rc"

# --- 5. a matching clone that can't be read is a hard stop ---
chmod 000 "$T/yadm-repo.git"
run feat-a
ok  'unreadable clone: refuses' [ $rc -eq 1 ]
has 'unreadable clone: says which and why' "$T/yadm-repo.git exists but can't be entered"
chmod 755 "$T/yadm-repo.git"

# --- 6. two open PRs with this head: refuse, list the bases ---
printf 'main\nfeat-a\n' > "$T/gh.out"
run feat-b
ok  'ambiguous PRs: refuses' [ $rc -eq 1 ]
has 'ambiguous PRs: lists bases' '2 open PRs have head feat-b, with bases: main feat-a'
: > "$T/gh.out"

# --- 7. a clone of a different repo at the candidate path is ignored ---
git -C "$HOME/dotfiles" remote set-url origin "$T/other.git"
git --git-dir="$HOME/dotfiles/.git" branch -q feat-a origin/feat-a 2>/dev/null || true
run feat-a
ok  'foreign clone: ignored, run completes' [ $rc -eq 0 ]
has 'foreign clone: nothing to do' 'nothing to do'

# --- 8. norm_url treats SCP-style, https:// and ssh:// forms of the same
# repo as equal -- otherwise two clones of the same GitHub repo on
# different protocols take the "different repo" skip path in case 7 above,
# silently defeating the orphan guard.
norm_url() {
  u=${1%/}; u=${u%.git}
  case "$u" in
    *://*) u=${u#*://}; u=${u#*@} ;;
    *@*:*) u=${u#*@}; u=$(printf '%s' "$u" | sed 's/:/\//') ;;
    *:*) u=$(printf '%s' "$u" | sed 's/:/\//') ;;
  esac
  printf '%s\n' "$u"
}
a=$(norm_url "git@github.com:mark-brannan/dotfiles.git")
b=$(norm_url "https://github.com/mark-brannan/dotfiles.git")
c=$(norm_url "ssh://git@github.com/mark-brannan/dotfiles")
ok 'norm_url: scp-style and https:// match' [ "$a" = "$b" ]
ok 'norm_url: scp-style and ssh:// match' [ "$a" = "$c" ]

# --- 9. after a real push, the open PR's body gets a Head: <sha> line --
# added when missing, replaced when already there; nothing touched when no
# PR is open (dotfiles#286) ---------------------------------------------
mk_unsigned_branch() {  # mk_unsigned_branch <name>
  git -C "$W" checkout -q main
  git -C "$W" checkout -q -b "$1"
  echo x > "$W/$1.txt" && git -C "$W" add "$1.txt" && git -C "$W" commit -q -m "$1 1"
  git -C "$W" -c commit.gpgsign=false commit -q --amend --allow-empty --no-edit
  git -C "$W" push -q origin "$1"
}
: > "$T/gh.out"; : > "$T/gh.children"

mk_unsigned_branch feat-headmissing
echo 7 > "$T/gh.pr-number"
printf 'what and why\n' > "$T/gh.pr-body"
: > "$T/gh.edit-body"
run feat-headmissing
git -C "$W" fetch -q origin
newsha=$(git -C "$W" rev-parse origin/feat-headmissing)
ok 'head-sha: exits 0' [ $rc -eq 0 ]
ok 'head-sha: appends Head: line when missing' \
  [ "$(cat "$T/gh.edit-body" 2>/dev/null)" = "$(printf 'what and why\n\nHead: %s\n' "$newsha")" ]

mk_unsigned_branch feat-headreplace
echo 8 > "$T/gh.pr-number"
printf 'what and why\n\nHead: deadbeef\n' > "$T/gh.pr-body"
: > "$T/gh.edit-body"
run feat-headreplace
git -C "$W" fetch -q origin
newsha=$(git -C "$W" rev-parse origin/feat-headreplace)
ok 'head-sha: replaces an existing Head: line' \
  [ "$(cat "$T/gh.edit-body" 2>/dev/null)" = "$(printf 'what and why\n\nHead: %s\n' "$newsha")" ]

mk_unsigned_branch feat-nopr
: > "$T/gh.pr-number"
: > "$T/gh.edit-body"
run feat-nopr
ok 'head-sha: no open PR, nothing edited' [ ! -s "$T/gh.edit-body" ]
: > "$T/gh.pr-number"; : > "$T/gh.pr-body"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
