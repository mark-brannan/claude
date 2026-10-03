#!/usr/bin/env bash
# Tests for local-config-push.sh. Run: bash hooks/local-config-push.test.sh
#
# Builds a throwaway fake $HOME with a plain git repo standing in for yadm
# (a `yadm` shim on PATH that forwards every subcommand to `git`), so the
# hook's yadm calls exercise real git behavior without touching the real
# machine's yadm-managed $HOME. Each case gets its own temp dir holding the
# fake home and its bare origin; all of them are removed on exit.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/local-config-push.sh"
pass=0
fail=0
tmpdirs=()
trap 'rm -rf "${tmpdirs[@]}"' EXIT

check() {
  local desc=$1 got=$2 want=$3
  if [ "$got" = "$want" ]; then
    pass=$((pass + 1))
  else
    fail=$((fail + 1))
    printf 'FAIL: %s (want %q, got %q)\n' "$desc" "$want" "$got"
  fi
}

# Prints "<home>|<bin>|<origin>".
setup_home() {
  local t d bin origin
  t=$(mktemp -d)
  tmpdirs+=("$t")
  d="$t/home"; bin="$t/bin"; origin="$t/origin.git"
  mkdir -p "$bin" "$d/.claude/hooks" "$d/.claude/rules" "$d/.claude/bin"
  cat > "$bin/yadm" <<'SHIM'
#!/bin/sh
exec git "$@"
SHIM
  chmod +x "$bin/yadm"

  git -C "$d" init -q -b main
  git -C "$d" config user.email test@example.com
  git -C "$d" config user.name Test
  git -C "$d" config commit.gpgsign false

  cat > "$d/.claude/bin/cloud-session-setup.sh" <<'INSTALL'
INSTALL="
.claude/settings.json
.claude/CLAUDE.md
.claude/rules/code.md
"
INSTALL
  echo '{}' > "$d/.claude/settings.json"
  echo '# orders' > "$d/.claude/CLAUDE.md"
  echo '# code' > "$d/.claude/rules/code.md"
  git -C "$d" add -A >/dev/null
  git -C "$d" commit -q -m init >/dev/null

  # A bare "origin" so `yadm push` has somewhere real to land.
  git init -q --bare -b main "$origin"
  git -C "$d" remote add origin "$origin"
  git -C "$d" push -q -u origin main >/dev/null 2>&1

  echo "$d|$bin|$origin"
}

# run_hook <home> <bin> <cwd> [VAR=value ...]  -- prints the hook's stdout.
run_hook() {
  local home=$1 bin=$2 cwd=$3; shift 3
  (cd "$cwd" && env -i HOME="$home" PATH="$bin:/usr/bin:/bin" "$@" bash "$HOOK")
}
last_report() { cut -d' ' -f2- "$1/.local/state/local-config-push/last" 2>/dev/null; }

# --- clean tree: no commit, nothing said --------------------------------------
IFS='|' read -r home bin origin <<<"$(setup_home)"
out=$(run_hook "$home" "$bin" "$home")
check "clean tree makes no commit" "$(git -C "$home" rev-list --count HEAD)" "1"
check "clean tree says nothing" "$out" ""

# --- CLAUDE.md dirty: committed and pushed, excluding settings.json ------------
IFS='|' read -r home bin origin <<<"$(setup_home)"
echo '# changed' >> "$home/.claude/CLAUDE.md"
echo '{"changed":true}' > "$home/.claude/settings.json"
out=$(run_hook "$home" "$bin" "$home")
check "dirty CLAUDE.md + settings.json: exactly one new commit" "$(git -C "$home" rev-list --count HEAD)" "2"
check "the commit reached origin" "$(git -C "$origin" rev-list --count main)" "2"
in_commit=$(git -C "$home" show --stat --format= HEAD | grep -c 'settings.json' || true)
check "settings.json not part of the commit" "$in_commit" "0"
check "settings.json left uncommitted" "$([ -n "$(git -C "$home" status --porcelain -- .claude/settings.json)" ] && echo yes || echo no)" "yes"
check "report names the push" "$(last_report "$home")" "pushed: .claude/CLAUDE.md (settings.json left uncommitted)"
check "push is said on screen" "$(printf '%s' "$out" | grep -c '"systemMessage":"local-config-push: pushed:')" "1"

# --- something else already staged by hand stays out of the commit -----------
IFS='|' read -r home bin origin <<<"$(setup_home)"
echo 'export SECRET=1' > "$home/.zshrc"
git -C "$home" add .zshrc
echo '# changed' >> "$home/.claude/CLAUDE.md"
run_hook "$home" "$bin" "$home" >/dev/null
check "hand-staged file: the config commit still happens" "$(git -C "$home" rev-list --count HEAD)" "2"
check "hand-staged file is not in the commit" "$(git -C "$home" show --stat --format= HEAD | grep -c '\.zshrc' || true)" "0"
check "hand-staged file is still staged afterwards" "$(git -C "$home" diff --cached --name-only)" ".zshrc"

# --- run from a project dir with its own .claude/: $HOME's copy still wins -----
# yadm resolves a relative pathspec against cwd; a Stop hook runs in the project.
IFS='|' read -r home bin origin <<<"$(setup_home)"
mkdir -p "$home/proj/.claude"
echo '# project orders' > "$home/proj/.claude/CLAUDE.md"
echo '# changed' >> "$home/.claude/CLAUDE.md"
run_hook "$home" "$bin" "$home/proj" >/dev/null
check "from a project dir: \$HOME's CLAUDE.md is committed" "$(git -C "$home" rev-list --count HEAD)" "2"
check "from a project dir: the project's file is not" "$(git -C "$home" show --stat --format= HEAD | grep -c 'proj/' || true)" "0"

# --- push fails: commit stays, failure is said ---------------------------------
IFS='|' read -r home bin origin <<<"$(setup_home)"
echo '# changed' >> "$home/.claude/CLAUDE.md"
git -C "$home" remote set-url origin "$home/nowhere.git"
out=$(run_hook "$home" "$bin" "$home")
check "push failure keeps the local commit" "$(git -C "$home" rev-list --count HEAD)" "2"
check "push failure is reported" "$(last_report "$home" | cut -d: -f1)" "committed but push failed (offline? rejected?)"
check "push failure is said on screen" "$(printf '%s' "$out" | grep -c '"systemMessage"')" "1"

# --- CLAUDE_CODE_REMOTE=true: hook is a no-op ---------------------------------
IFS='|' read -r home bin origin <<<"$(setup_home)"
echo '# changed' >> "$home/.claude/CLAUDE.md"
run_hook "$home" "$bin" "$home" CLAUDE_CODE_REMOTE=true >/dev/null
check "CLAUDE_CODE_REMOTE=true skips entirely" "$(git -C "$home" rev-list --count HEAD)" "1"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
