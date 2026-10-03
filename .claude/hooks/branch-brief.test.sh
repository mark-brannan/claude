#!/usr/bin/env bash
# Tests for lib-state.sh's branch_brief (dotfiles#266).
# Run: bash .claude/hooks/branch-brief.test.sh
#
# Every case builds a real repo with a real bare remote, because the whole
# point of branch_brief is that it reports what git says rather than what a
# session assumed. `gh` is stubbed on PATH: the open-PR lookup is the one
# fact that is not local, and a test that reached the network would be
# testing GitHub.
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
pass=0; fail=0

want_line() {  # <brief> <expected line> <desc>
  if grep -qxF -- "$2" <<<"$1"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL: %s\n  want line: %s\n  got:\n%s\n' "$3" "$2" "$(printf '%s' "$1" | sed 's/^/    /')"
  fi
}
want_grep() {  # <brief> <pattern> <desc>
  if grep -qE -- "$2" <<<"$1"; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL: %s\n  want match: %s\n  got:\n%s\n' "$3" "$2" "$(printf '%s' "$1" | sed 's/^/    /')"
  fi
}

# A commit carrying a gpgsig header. The signature is deliberate nonsense:
# presence is what branch_brief tests, validity is GitHub's job -- the same
# split no-unsigned-push.sh makes, and the reason a cloud VM with no
# allowed-signers file must not be told to re-sign a fine branch.
fake_signed() {  # <repo> <subject>
  local r=$1 tree parent obj
  tree=$(git -C "$r" write-tree)
  parent=$(git -C "$r" rev-parse HEAD)
  obj=$(printf 'tree %s\nparent %s\nauthor T <t@e> 1700000000 +0000\ncommitter T <t@e> 1700000000 +0000\ngpgsig -----BEGIN SSH SIGNATURE-----\n Zm9v\n -----END SSH SIGNATURE-----\n\n%s\n' \
          "$tree" "$parent" "$2" | git -C "$r" hash-object -t commit -w --stdin)
  git -C "$r" update-ref HEAD "$obj"
}

# gh stub: $GH_MODE picks what the open-PR lookup answers.
#   none -> no open PR   pr -> one open PR based on `release`   fail -> lookup broke
# Every test repo answers only from its own config. Without this the real
# machine's global user.signingkey leaks in and the "no key here" case -- the
# one that must not recommend a rebase it cannot sign -- passes on a cloud VM
# and fails on Solace's laptop.
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
mkdir -p "$SCRATCH/bin"
cat > "$SCRATCH/bin/gh" <<'GH'
#!/bin/sh
case "${GH_MODE:-none}" in
  pr)   echo release ;;
  fail) exit 1 ;;
  *)    : ;;
esac
GH
chmod +x "$SCRATCH/bin/gh"

# A git that fails one specific count on demand, so the "git could not answer"
# branches are tested rather than asserted. Corrupting a pack is the only other
# way to reach them, and a test that corrupts a repo teaches nothing about the
# code.
REAL_GIT=$(command -v git)
cat > "$SCRATCH/bin/git" <<GIT
#!/bin/sh
if [ -n "\${GIT_FAIL_MERGES:-}" ]; then
  case " \$* " in *" --merges "*) exit 128 ;; esac
fi
if [ -n "\${GIT_FAIL_LEFTRIGHT:-}" ]; then
  case " \$* " in *" --left-right "*) exit 128 ;; esac
fi
if [ -n "\${GIT_FAIL_RANGE:-}" ]; then
  case " \$* " in *" rev-list origin/"*) exit 128 ;; esac
fi
exec $REAL_GIT "\$@"
GIT
chmod +x "$SCRATCH/bin/git"
PATH="$SCRATCH/bin:$PATH"

# A fresh repo with a bare origin, one commit on main, and a `feat` branch.
new_repo() {  # <name> -> prints the worktree path
  local r="$SCRATCH/$1"
  git init -q --bare -b main "$r.git"
  git clone -q "$r.git" "$r" 2>/dev/null
  git -C "$r" config user.email t@e; git -C "$r" config user.name T
  git -C "$r" config commit.gpgsign false
  printf 'base\n' > "$r/f"; git -C "$r" add f
  git -C "$r" commit -qm base
  git -C "$r" push -q origin main
  git -C "$r" remote set-head origin -a >/dev/null
  git -C "$r" checkout -qb feat
  printf '%s' "$r"
}

# shellcheck source=lib-state.sh
. "$HOOKS/lib-state.sh"

# --- clean: signed, no conflict, no merges -> the rebase line ---------------
r=$(new_repo clean)
printf 'base\nfeat\n' > "$r/f"; git -C "$r" add f; fake_signed "$r" "feat work"
git -C "$r" checkout -q main   # the brief is about a branch, not about HEAD
out=$(branch_brief "$r" feat)
want_line "$out" 'base: main (default branch, no open PR)' 'clean: base is the default branch'
want_line "$out" 'ahead: 1' 'clean: one commit ahead'
want_line "$out" 'behind: 0' 'clean: not behind'
want_line "$out" 'conflicts: no' 'clean: no conflicts'
want_line "$out" 'unsigned: 0' 'clean: gpgsig header counts as signed'
want_line "$out" 'merges: 0' 'clean: no merge commits'
want_line "$out" 'worktrees: none' 'clean: branch held by no worktree'
want_grep "$out" '^recommend: git fetch origin main && git rebase origin/main$' \
  'clean: ends with the rebase line'

# --- conflicting against the base ------------------------------------------
r=$(new_repo conflict)
printf 'base\ntheirs\n' > "$r/f"; git -C "$r" add f; fake_signed "$r" "feat work"
git -C "$r" push -q origin "HEAD:refs/heads/scratch"   # keep feat local
git -C "$r" checkout -q main
printf 'base\nours\n' > "$r/f"; git -C "$r" add f; git -C "$r" commit -qm "main moves"
git -C "$r" push -q origin main
git -C "$r" checkout -q feat
out=$(branch_brief "$r" feat)
want_line "$out" 'conflicts: yes' 'conflicting: merge-tree reports a conflict'
want_line "$out" 'behind: 1' 'conflicting: one behind the base'
want_grep "$out" '^recommend: git merge origin/main .*never linearize' \
  'conflicting: merge, and do not linearize afterwards'

# --- a merge commit already on the branch ----------------------------------
r=$(new_repo merged)
git -C "$r" checkout -q main
printf 'base\nmain\n' > "$r/f"; git -C "$r" add f; git -C "$r" commit -qm "main moves"
git -C "$r" push -q origin main
git -C "$r" checkout -q feat
printf 'other\n' > "$r/g"; git -C "$r" add g; git -C "$r" commit -qm "feat work"
git -C "$r" merge -q --no-edit origin/main
out=$(branch_brief "$r" feat)
want_line "$out" 'merges: 1' 'merged: the merge commit is counted'
want_grep "$out" '^recommend: do not rebase and do not resign' \
  'merged: merge commits outrank every other recommendation'

# --- unsigned, with and without a key on this machine ----------------------
r=$(new_repo unsigned)
printf 'base\nfeat\n' > "$r/f"; git -C "$r" add f; git -C "$r" commit -qm "feat work"
out=$(branch_brief "$r" feat)
want_line "$out" 'unsigned: 1' 'unsigned: a commit with no gpgsig header counts'
want_grep "$out" '^recommend: cannot sign on this machine' \
  'unsigned, no key: say so rather than recommending a rebase that cannot sign'
git -C "$r" config user.signingkey /dev/null
out=$(branch_brief "$r" feat)
want_grep "$out" '^recommend: git rebase -S --force-rebase [0-9a-f]{7,}' \
  'unsigned, key here: the rebase -S line, off the merge base'
want_grep "$out" 'resign-branch\.sh feat instead' \
  'unsigned, key here: names resign-branch.sh for an already-pushed branch'

# --- the base comes from the open PR, not the default branch ---------------
r=$(new_repo stacked)
git -C "$r" push -q origin "main:refs/heads/release"
git -C "$r" fetch -q origin
printf 'base\nfeat\n' > "$r/f"; git -C "$r" add f; fake_signed "$r" "feat work"
out=$(export GH_MODE=pr; branch_brief "$r" feat)
want_line "$out" 'base: release (open PR)' 'stacked: the PR base wins over the default branch'
want_grep "$out" 'rebase origin/release$' 'stacked: the recommendation uses the PR base'
out=$(export GH_MODE=fail; branch_brief "$r" feat)
want_grep "$out" '^base: main \(assumed' \
  'lookup failed: say the base is assumed, do not pass it off as known'

# --- facts that cannot be taken say unknown, never a number ---------------
r=$(new_repo nobase)
fake_signed "$r" "feat work"
git -C "$r" update-ref -d refs/remotes/origin/main
git -C "$r" remote set-head -d origin
out=$(branch_brief "$r" feat)
want_line "$out" 'behind: unknown' 'no base ref here: unknown, not 0'
want_grep "$out" '^recommend: no base to compare against here' \
  'no base ref here: the recommendation is to fetch, not to rebase'

# --- a count that fails says unknown, and never recommends a rebase --------
# merges feeds the top of the ladder: a silent 0 there recommends a rebase
# over the branch this whole function exists to protect.
r=$(new_repo failcount)
fake_signed "$r" "feat work"
out=$(export GIT_FAIL_MERGES=1; branch_brief "$r" feat)
want_line "$out" 'merges: unknown' 'failed count: unknown, not 0'
want_grep "$out" '^recommend: count the merge commits by hand' \
  'failed merge count: never falls through to the rebase line'
out=$(export GIT_FAIL_LEFTRIGHT=1; branch_brief "$r" feat)
want_line "$out" 'ahead: unknown' 'failed ahead/behind count: unknown, not 0'
want_line "$out" 'behind: unknown' 'failed ahead/behind count: unknown both ways'
out=$(export GIT_FAIL_RANGE=1; branch_brief "$r" feat)
want_line "$out" 'unsigned: unknown' 'failed commit listing: unsigned is unknown, not 0'
want_grep "$out" '^recommend: check the signatures by hand' \
  'failed commit listing: never falls through to the rebase line'

# --- worktrees holding the branch are reported ----------------------------
r=$(new_repo held)
git -C "$r" checkout -q main
git -C "$r" worktree add -q "$SCRATCH/held wt" feat
out=$(branch_brief "$r" feat)
want_grep "$out" "^worktrees: $SCRATCH/held wt " 'held: the holding worktree is named, spaces and all'

# --- a branch that is not there is an error, not an empty brief -----------
r=$(new_repo missing)
if out=$(branch_brief "$r" nope 2>&1); then
  fail=$((fail + 1)); printf 'FAIL: missing branch returned success\n'
else
  pass=$((pass + 1))
fi
want_grep "$out" '^error: no branch nope' 'missing: says which branch and where'

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
