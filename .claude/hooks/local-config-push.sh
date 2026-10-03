#!/usr/bin/env bash
# Stop hook: commit and push yadm-managed ~/.claude config changes, so a local
# edit reaches origin without anyone remembering to run dotsync/dotpush.
#
# This is R4 of the config-sync-strategy.md design (issue #17, §6.5) — the
# local half of P4. R5, the pull side, already exists as dotfiles-sync.sh's
# cron job; this is the missing push side.
#
# Local machines only: a real machine is yadm-managed and this is exactly the
# push half of that; a cloud session has no yadm repo at all, so it exits
# immediately rather than doing a pointless `command -v yadm` probe on every
# Stop of every cloud session.
#
# settings.json is excluded from the commit (reported, never committed):
# Claude Code rewrites it at runtime (anthropics/claude-code#62486), so
# auto-committing it would push runtime churn -- and occasionally runtime
# damage -- into the source of truth. A human commits it by hand.
#
# Always exits 0. A push hook that can fail a session is worse than no push
# hook.
set -ufo pipefail

[ "${CLAUDE_CODE_REMOTE:-}" = true ] && exit 0
command -v yadm >/dev/null 2>&1 || exit 0
yadm rev-parse --git-dir >/dev/null 2>&1 || exit 0
# A Stop hook runs in the session's project dir, and yadm resolves a relative
# pathspec against cwd, not $HOME -- from ~/proj, `.claude/CLAUDE.md` means
# ~/proj/.claude/CLAUDE.md. Every path below is meant relative to $HOME.
cd "$HOME" || exit 0

STATE="$HOME/.local/state/local-config-push"
mkdir -p "$STATE" 2>/dev/null || exit 0
report() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" > "$STATE/last" 2>/dev/null; }
# Anything that moved or failed is said on screen too (R6: failure never lands
# in silence); the quiet outcomes only reach $STATE/last.
say() { report "$@"; printf '{"systemMessage":"local-config-push: %s"}\n' "$*"; }

# mkdir is the portable atomic lock (macOS has no flock) -- same pattern as
# dotfiles-sync.sh, guarding against a concurrent session's Stop hook or the
# cron pull racing this push on the same working tree.
LOCK="$STATE/lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +10 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null && mkdir "$LOCK" 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

gitdir=$(yadm rev-parse --git-dir 2>/dev/null)
if [ -e "$gitdir/MERGE_HEAD" ] || [ -d "$gitdir/rebase-merge" ] || [ -d "$gitdir/rebase-apply" ]; then
  report "skipped: merge or rebase in progress, resolve by hand"; exit 0
fi

# The INSTALL list is the single source of truth for what a session's config
# is made of (cloud-session-setup.sh) -- reuse it here so this hook and the
# installer can never disagree about which .claude/ paths matter. Read from
# the installed copy under $HOME, not a checkout, since this hook has no
# reason to assume one exists.
SETUP="$HOME/.local/bin/cloud-session-setup.sh"
[ -f "$SETUP" ] || exit 0
paths=$(sed -n '/^INSTALL="$/,/^"$/p' "$SETUP" | grep '^\.claude/' | grep -v '^\.claude/settings\.json$')
[ -n "$paths" ] || exit 0

dirty=""
settings_dirty=0
while IFS= read -r p; do
  [ -n "$p" ] || continue
  [ -e "$HOME/$p" ] || continue
  if [ -n "$(yadm status --porcelain -- "$p" 2>/dev/null)" ]; then
    dirty="$dirty $p"
  fi
done <<EOF
$paths
EOF
if [ -e "$HOME/.claude/settings.json" ] \
   && [ -n "$(yadm status --porcelain -- .claude/settings.json 2>/dev/null)" ]; then
  settings_dirty=1
fi

if [ -z "$dirty" ]; then
  [ "$settings_dirty" = 1 ] && report "settings.json changed locally; not auto-committed, commit it by hand"
  exit 0
fi

# shellcheck disable=SC2086  # $dirty is a space-joined path list on purpose; -f above blocks globbing
if ! yadm add -- $dirty >/dev/null 2>&1; then
  report "skipped: yadm add failed for:$dirty"; exit 0
fi
# The pre_commit hook (secret guard) runs as configured for yadm's repo --
# this is the "in the loop" part of R4, not a separate check here.
# `-- $dirty` on the commit as well as the add: $HOME is the whole yadm
# worktree, and a bare `commit` would sweep in whatever else is staged --
# a secrets file mid `yadm add && yadm commit` by hand, say.
# shellcheck disable=SC2086
if ! yadm commit -q -m "config: local edit ($(date -u +%Y-%m-%d))" \
     -m "Co-Authored-By: Claude <noreply@anthropic.com>" -- $dirty >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  yadm reset -q -- $dirty >/dev/null 2>&1
  say "commit refused (pre_commit gate, signing, or nothing staged) for:$dirty"
  exit 0
fi

note=""
[ "$settings_dirty" = 1 ] && note=" (settings.json left uncommitted)"
if yadm push -q >/dev/null 2>&1; then
  say "pushed:$dirty$note"
elif [ "$(yadm rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)" -gt 0 ]; then
  say "committed but behind origin, run dotsync then it pushes next Stop:$dirty$note"
else
  say "committed but push failed (offline? rejected?):$dirty$note"
fi
exit 0
