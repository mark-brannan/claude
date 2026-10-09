#!/usr/bin/env bash
# Tests for release-subagent-branch.sh. Run: bash hooks/release-subagent-branch.test.sh
#
# Each case builds a repo with a bare remote and a sub-agent worktree where
# the Agent tool puts one, fires SubagentStop at it, and reads back whether
# the worktree still holds its branch.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/release-subagent-branch.sh"
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
pass=0
fail=0

# setup <id>: prints the repo path; the worktree is on branch work-<id>,
# pushed, clean.
setup() {
  local id=$1 r
  r="$SCRATCH/repo-$id"
  git init -q --bare "$SCRATCH/remote-$id.git"
  git init -q -b main "$r"
  git -C "$r" commit -q --allow-empty -m init
  git -C "$r" remote add origin "$SCRATCH/remote-$id.git"
  git -C "$r" push -q origin main
  git -C "$r" worktree add -q -b "work-$id" "$r/.claude/worktrees/agent-$id"
  git -C "$r/.claude/worktrees/agent-$id" commit -q --allow-empty -m work
  git -C "$r/.claude/worktrees/agent-$id" push -q origin "work-$id"
  printf '%s' "$r"
}

fire() { # fire <cwd> <agent_id> [transcript]
  jq -n --arg c "$1" --arg a "$2" --arg t "${3:-}" \
    '{hook_event_name:"SubagentStop",cwd:$c,agent_id:$a}
     + (if $t == "" then {} else {agent_transcript_path:$t} end)' |
    bash "$HOOK"
}

check() { # check <want: held|released> <desc> <worktree>
  local got=released
  git -C "$3" symbolic-ref -q HEAD >/dev/null && got=held
  if [ "$got" = "$1" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL (want %s, got %s): %s\n' "$1" "$got" "$2"
  fi
}

# --- releases -----------------------------------------------------------------
r=$(setup a1)
fire "$r" a1
check released 'clean and pushed' "$r/.claude/worktrees/agent-a1"

r=$(setup a2)
other=$(mktemp -d "$SCRATCH/elsewhere.XXXX")
printf '{"cwd":"%s"}\n' "$r/.claude/worktrees/agent-a2" >"$SCRATCH/t2.jsonl"
fire "$other" a2 "$SCRATCH/t2.jsonl"
check released 'found by its transcript when the parent sits in another repo' \
  "$r/.claude/worktrees/agent-a2"

# --- keeps the branch -----------------------------------------------------------
r=$(setup b1)
git -C "$r/.claude/worktrees/agent-b1" commit -q --allow-empty -m unpushed
fire "$r" b1
check held 'a commit not on any remote' "$r/.claude/worktrees/agent-b1"

r=$(setup b2)
echo x >"$r/.claude/worktrees/agent-b2/new.txt"
fire "$r" b2
check held 'an untracked file' "$r/.claude/worktrees/agent-b2"

r=$(setup b3)
echo x >"$r/.claude/worktrees/agent-b3/f.txt"
git -C "$r/.claude/worktrees/agent-b3" add f.txt
fire "$r" b3
check held 'a staged change' "$r/.claude/worktrees/agent-b3"

r=$(setup b4)
fire "$r" other-id
check held 'another agent stopping leaves this one alone' "$r/.claude/worktrees/agent-b4"

r=$(setup b5)
fire "$r" 'b5/../../x'
check held 'an agent_id that is not a plain name' "$r/.claude/worktrees/agent-b5"

# --- quiet no-ops ---------------------------------------------------------------
r=$(setup c1)
fire "$r" c1
out=$(fire "$r" c1 2>&1)
rc=$?
if [ "$rc" = 0 ] && [ -z "$out" ]; then pass=$((pass + 1)); else
  fail=$((fail + 1))
  printf 'FAIL: second stop on a detached worktree printed %q, exit %s\n' "$out" "$rc"
fi
out=$(printf '{}' | bash "$HOOK" 2>&1)
rc=$?
if [ "$rc" = 0 ] && [ -z "$out" ]; then pass=$((pass + 1)); else
  fail=$((fail + 1))
  printf 'FAIL: empty payload printed %q, exit %s\n' "$out" "$rc"
fi

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
