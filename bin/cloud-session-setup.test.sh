#!/bin/sh
# Tests for cloud-session-setup.sh. Run: sh bin/cloud-session-setup.test.sh
#
# A cloud VM in a scratch $HOME: the claude seed is a local clone of this
# repo's working tree, the guard seed a fake dotfiles holding the four GUARD_HOOKS, and
# `claude` a stub so the plugin step never reaches the network. Covers the
# cold install (every hook settings.json names resolves under ~/.claude, the
# harness's own files untouched), the reuse path, an upstream move, a guard
# dropped upstream (previous release kept, complete:false), and the three
# refusals. What it cannot cover is the platform: the setup-script field, the
# GitHub proxy and the attached sources -- that takes one real cloud session.
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
pass=0; fail=0
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
export HOME="$S/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
unset CLAUDE_CONFIG_DIR CLAUDE_SEED DOTFILES_SEED DOTFILES_URL YADM_DIR CLAUDE_CODE_REMOTE XDG_DATA_HOME
mkdir -p "$S/bin"; printf '#!/bin/sh\nexit 0\n' >"$S/bin/claude"; chmod +x "$S/bin/claude"
export PATH="$S/bin:$PATH"

gitq() { d=$1; shift; git -C "$d" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "$@" >/dev/null 2>&1; }
ok()   { pass=$((pass+1)); }
bad()  { fail=$((fail+1)); echo "FAIL: $1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/    /'; }
has()  { printf '%s' "$2" | grep -q -- "$1" && ok || bad "expected /$1/ in: $3" "$2"; }
check(){ if eval "$2"; then ok; else bad "$1"; fi; }

# --- upstreams: this repo as committed, and a fake dotfiles ---------------
UP_CLAUDE="$S/up-claude"; UP_DOT="$S/up-dotfiles"
# The working tree, not HEAD, so an uncommitted edit is what gets tested.
mkdir -p "$UP_CLAUDE"
(cd "$REPO" && git ls-files -co --exclude-standard -z | xargs -0 tar cf -) | tar xf - -C "$UP_CLAUDE"
gitq "$UP_CLAUDE" init -q; gitq "$UP_CLAUDE" add -A; gitq "$UP_CLAUDE" commit -q -m seed
mkdir -p "$UP_DOT/.claude/hooks"; gitq "$UP_DOT" init -q
for g in no-checkout-home no-foreign-worktree prose-budget-commit public-issue-guard; do
  printf '#!/bin/sh\n# %s\n' "$g" >"$UP_DOT/.claude/hooks/$g.sh"
done
gitq "$UP_DOT" add -A; gitq "$UP_DOT" commit -q -m guards

SEED="$HOME/.local/share/claude-seed"
git clone -q "$UP_CLAUDE" "$SEED"
export DOTFILES_URL="$UP_DOT"
run() { CLOUD_SESSION=1 sh "$SEED/bin/cloud-session-setup.sh" 2>&1; }
status() { jq -r "$1" "$HOME/.claude/.sync-status.json" 2>/dev/null; }

# The harness's own state, present before the seed ever runs.
mkdir -p "$HOME/.claude/projects/p"; echo keep >"$HOME/.claude/projects/p/x"
echo '{"local":true}' >"$HOME/.claude/settings.local.json"

# --- cold install --------------------------------------------------------
out=$(run)
has "0 missing, 0 failed" "$out" "cold install"
check "cold: complete" '[ "$(status .complete)" = true ]'
check "cold: sha is the claude seed" '[ "$(status .sha)" = "$(git -C "$SEED" rev-parse HEAD)" ]'
check "cold: guards_sha is the guard seed" \
  '[ "$(status .guards_sha)" = "$(git -C "$HOME/.local/share/dotfiles-seed" rev-parse HEAD)" ]'
check "cold: hooks is a symlink into current" \
  '[ "$(readlink "$HOME/.claude/hooks")" = "$HOME/.claude-config/current/hooks" ]'
check "cold: lib is a symlink into current" \
  '[ "$(readlink "$HOME/.claude/lib")" = "$HOME/.claude-config/current/lib" ]'
# Not the shim's fail-open None: the seeded hooks really reach lib/state.py.
check "cold: seeded lib_state imports lib/state.py" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, sys.argv[1]); import lib_state, state" "$HOME/.claude/hooks" 2>/dev/null'
check "cold: seeded lib has lock.py and gitrun.py" \
  '[ -f "$HOME/.claude/lib/lock.py" ] && [ -f "$HOME/.claude/lib/gitrun.py" ]'
# Run them, not just import them: a seed whose INSTALL dropped a helper fails here.
check "cold: seeded lib/lock.py takes a lock" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, sys.argv[1]); import lock; f = open(sys.argv[2], \"a\"); sys.exit(0 if lock.acquire(f, wait=0) else 1)" "$HOME/.claude/lib" "$HOME/.lock-probe"'
check "cold: seeded lib/gitrun.py runs git" \
  'PYTHONDONTWRITEBYTECODE=1 python3 -c "import sys; sys.path.insert(0, sys.argv[1]); import gitrun; sys.exit(0 if gitrun.run(\"--version\").returncode == 0 else 1)" "$HOME/.claude/lib"'
check "cold: settings.json linked" '[ -L "$HOME/.claude/settings.json" ] && [ -f "$HOME/.claude/settings.json" ]'
check "cold: projects/ untouched" '[ ! -L "$HOME/.claude/projects" ] && [ "$(cat "$HOME/.claude/projects/p/x")" = keep ]'
check "cold: settings.local.json untouched" '[ ! -L "$HOME/.claude/settings.local.json" ]'
check "cold: tools on ~/.local/bin" '[ -x "$HOME/.local/bin/worklist" ]'
# The one that bricks a VM if it fails: every hook settings.json runs exists.
for h in $(grep -o '\$HOME/\.claude/hooks/[A-Za-z0-9._-]*' "$REPO/settings.json" | sort -u); do
  # shellcheck disable=SC2034  # read inside check's eval
  f="$HOME${h#\$HOME}"
  check "cold: settings.json hook ${h##*/} present" '[ -f "$f" ]'
done

# --- re-run on the same SHAs reuses the release ---------------------------
out=$(run)
has "already staged" "$out" "re-run"
check "re-run: one release" '[ "$(ls "$HOME/.claude-config/releases" | wc -l)" -eq 1 ]'

# --- an upstream move lands, the old release is pruned --------------------
echo "# moved" >>"$UP_DOT/.claude/hooks/public-issue-guard.sh"
gitq "$UP_DOT" commit -q -am moved
out=$(run)
check "move: guards_sha advanced" '[ "$(status .guards_sha)" = "$(git -C "$UP_DOT" rev-parse HEAD)" ]'
check "move: new guard content live" 'grep -q moved "$HOME/.claude/hooks/public-issue-guard.sh"'
check "move: old release pruned" '[ "$(ls "$HOME/.claude-config/releases" | wc -l)" -eq 1 ]'

# --- a guard dropped upstream keeps the previous release ------------------
# shellcheck disable=SC2034  # read inside check's eval
live=$(readlink "$HOME/.claude-config/current")
gitq "$UP_DOT" rm -q .claude/hooks/no-checkout-home.sh
gitq "$UP_DOT" commit -q -m drop
out=$(run)
has "MISSING hooks/no-checkout-home.sh" "$out" "guard dropped"
check "dropped: current unchanged" '[ "$(readlink "$HOME/.claude-config/current")" = "$live" ]'
check "dropped: guard still live" '[ -f "$HOME/.claude/hooks/no-checkout-home.sh" ]'
check "dropped: complete false" '[ "$(status .complete)" = false ]'

# --- refusals -------------------------------------------------------------
out=$(sh "$SEED/bin/cloud-session-setup.sh" 2>&1)
has "SKIPPING" "$out" "no marker"
mkdir "$HOME/.claude/.git"
out=$(run)
has "REFUSING -- .* is a git checkout" "$out" "the .claude dir is a checkout"
rmdir "$HOME/.claude/.git"
mkdir -p "$HOME/.local/share/yadm/repo.git"
out=$(run)
has "yadm-managed" "$out" "yadm home"

echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
