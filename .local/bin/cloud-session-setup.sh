#!/bin/sh
# cloud-session-setup.sh — install a chosen subset of these dotfiles into $HOME
# on an ephemeral cloud-session VM (Ubuntu, root, ~5 min setup window).
#
# Wire it up in the environment's setup-script field:
#
#   git clone -q https://github.com/mark-brannan/dotfiles \
#     "$HOME/.local/share/dotfiles-seed" 2>/dev/null
#   CLOUD_SESSION=1 sh "$HOME/.local/share/dotfiles-seed/.local/bin/cloud-session-setup.sh"
#   exit 0
#
# Deliberately NOT yadm. This repo uses no yadm encryption (secrets are
# sops+age, and the age key never reaches a VM) and its only alternate is
# .gitconfig — which must not be installed here, because it would replace the
# session's own git identity and commit-signing config.
#
# Usage:
#   CLOUD_SESSION=1 sh cloud-session-setup.sh          install
#   sh cloud-session-setup.sh --dry-run                show what would happen,
#                                                      safe on any machine
#
# Always exits 0: a missing dotfile must never stop a session from starting.
# -f is load-bearing, not tidiness: `for glob in $SKIP_GLOBS` and
# `for path in $INSTALL` undergo pathname expansion as well as word splitting,
# so run from a directory holding a .gitconfig##default the pattern
# `.gitconfig*` silently expands to that filename and stops matching the
# literal `.gitconfig` it exists to block. -f keeps both lists literal.
set -uf

SEED="${DOTFILES_SEED:-$HOME/.local/share/dotfiles-seed}"
BACKUP="$HOME/.dotfiles-replaced"
# Versioned releases + the "current" symlink that makes an install atomic --
# see "Stage" and "Flip" below. Overridable, but on its own it is NOT a test
# harness: the Link step still writes symlinks under the real $HOME, and
# STATUS_FILE is still under it. Isolating a run means overriding $HOME.
CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude-config}"
STATUS_FILE="$HOME/.claude/.sync-status.json"
STATUS_TMP="$STATUS_FILE.$$"
DRY_RUN=no
[ "${1:-}" = "--dry-run" ] && DRY_RUN=yes

# --- what to install -----------------------------------------------------
# Repo-relative paths, files or directories, copied to the same path under
# $HOME. Expand deliberately: every line lands in every cloud session.
# Every hook that settings.json references (directly or transitively) MUST be
# listed here. settings.json now runs hooks from $HOME ONLY -- the old
# $CLAUDE_PROJECT_DIR fallback was removed because in a cloud session on a
# third-party repo it executed THAT repo's .claude/hooks/*.sh under user-scope
# trust. Fail-closed is only safe if $HOME is complete: an omission here means
# the hook silently stops running, not that a stranger's copy runs instead.
INSTALL="
.claude/settings.json
.claude/CLAUDE.md
.claude/rules/code.md
.claude/rules/writing.md
.claude/skills/card-helper/SKILL.md
.claude/skills/card-write/SKILL.md
.claude/skills/wrapup/SKILL.md
.claude/hooks/lib-state.sh
.claude/hooks/session-metrics.jq
.claude/hooks/lib-metrics-fmt.jq
.claude/hooks/session-start-continuity.sh
.claude/hooks/stop-continuity.sh
.claude/hooks/measure-git-events.sh
.claude/hooks/no-persistent-polling.sh
.claude/hooks/no-late-pr-subscribe.sh
.claude/hooks/pr-ownership-context.sh
.claude/hooks/no-draft-pr.sh
.claude/hooks/no-git-reset-hard.sh
.claude/hooks/no-unsigned-push.sh
.claude/hooks/no-git-footguns.sh
.claude/hooks/no-checkout-home.sh
.claude/hooks/no-rm-tree.sh
.claude/hooks/lib-shell-words.awk
.claude/hooks/session-start-seed-refresh.sh
.claude/hooks/guard-add-repo.sh
.claude/hooks/metrics-live.sh
.claude/hooks/metrics-rollup.sh
.claude/hooks/log-commit.sh
.claude/hooks/statusline-metrics.sh
.claude/hooks/connector-budget.sh
.claude/hooks/fixtures
.local/bin/metrics-preview.sh
"

# --- what is wholly owned by this installer -------------------------------
# Directories entirely populated by INSTALL entries below them: linked into
# $HOME as a single symlink to the staged tree rather than mirrored file by
# file. Nothing else ever writes here, so nothing is lost by treating the
# whole directory as one unit -- and a directory INSTALL later drops from
# these needs no separate prune step, because the next stage simply doesn't
# contain it (see "Stage" below).
#
# Only wholly-owned leaf directories go here. `.claude` itself must NEVER
# appear: it also holds state/, projects/, todos/ and settings.local.json,
# none of which this script put there.
OWNED_DIRS='.claude/hooks .claude/rules'

# A tripwire for OWNED_DIRS, in the same spirit as SKIP_GLOBS: these are
# shared directories that hold files this script never put there, so linking
# one as a whole would hide a stranger's files behind the symlink swap.
# `.claude` is the live example -- INSTALL names files directly under it,
# which would otherwise make it look owned, and settings.local.json, state/
# and projects/ all live there.
OWNED_NEVER='. .claude .config .local .local/bin .ssh'

# The continuity hooks read and write the private state repo
# (claude_prompts_scratch). This script cannot clone it -- a VM has no
# credentials for a private repo at setup time -- so it must be added as a
# SECOND SOURCE on the cloud environment alongside dotfiles. Without it the
# hooks still run, but they write to ~/.claude/state/global, which dies with
# the container. session-start-continuity.sh says so at the top of every
# session rather than failing quietly.

# --- what must never be installed ----------------------------------------
# A tripwire, not documentation: an INSTALL entry matching one of these is
# refused rather than copied.
#   .gitconfig*        replaces the session's git identity + signing config,
#                      and points credential.helper at a `gh` that isn't there
#   .gitignore         yadm's worktree is $HOME, so this lands as
#                      /root/.gitignore and governs unrelated repos
#   secrets/, *.sops.* ciphertext with no key on this VM to decrypt it
#   shell rc files     they return early when non-interactive (agent shells
#                      are), so they are inert here and only add surface area
SKIP_GLOBS='.gitconfig* .gitignore secrets/* *.sops.* *.bashrc *.zshrc *.zshenv *.profile *.zprofile'

say() { echo "dotfiles: $*"; }
warn() { echo "dotfiles: $*" >&2; }

# =========================================================================
# Guard 1 — refuse to touch a machine whose $HOME yadm actually manages.
# =========================================================================
# This is the load-bearing guard. Every real machine (Mac, WSL, Pi) has a yadm
# repo; an ephemeral VM never does. Checked before anything is written.
yadm_repo() {
  for d in "${YADM_DIR:-}" \
           "${XDG_DATA_HOME:-$HOME/.local/share}/yadm/repo.git" \
           "$HOME/.local/share/yadm/repo.git" \
           "$HOME/.yadm/repo.git"; do
    [ -n "$d" ] && [ -d "$d" ] && { echo "$d"; return 0; }
  done
  # yadm installed and able to resolve a repo counts even at a nonstandard path
  if command -v yadm >/dev/null 2>&1 &&
     yadm rev-parse --git-dir >/dev/null 2>&1; then
    yadm rev-parse --git-dir 2>/dev/null
    return 0
  fi
  return 1
}

if repo=$(yadm_repo); then
  warn "REFUSING — \$HOME is yadm-managed (repo: $repo)."
  warn "  This script overwrites files in place and would fight yadm."
  warn "  On a real machine use: yadm pull --rebase --autostash && yadm alt"
  exit 0
fi

# =========================================================================
# Guard 2 — require positive evidence this is an ephemeral session.
# =========================================================================
# CLOUD_SESSION=1 is set only by the environment's setup-script field, which
# exists only on cloud VMs. CLAUDE_CODE_REMOTE covers a hand-run inside a
# session, where Claude Code has already exported it.
if [ "$DRY_RUN" = no ] &&
   [ "${CLOUD_SESSION:-}" != 1 ] &&
   [ "${CLAUDE_CODE_REMOTE:-}" != true ]; then
  warn "SKIPPING — no ephemeral-session marker."
  warn "  Set CLOUD_SESSION=1 to install, or pass --dry-run to preview."
  exit 0
fi

[ -d "$SEED/.git" ] || { warn "no checkout at $SEED — nothing installed"; exit 0; }
[ "$DRY_RUN" = yes ] && say "DRY RUN — nothing will be written"

# =========================================================================
# Refresh — bring the seed checkout up to date before installing from it.
# =========================================================================
# The setup-script blob's `git clone` is a no-op once $SEED exists, and a
# cloud container is checkpointed and reused across sessions. Without this
# the seed is frozen at whatever it cloned the first time the environment
# was provisioned, so a rule edited here never reaches a session again --
# and it fails silently, exactly like the deleted-hook scar above.
#
# `pull --ff-only`, not `fetch` plus a merge of FETCH_HEAD: the latter takes
# origin's default branch whatever the seed has checked out, so testing a
# change by checking the branch out in $SEED would silently reset it to main.
# --ff-only because the VM never commits here -- anything that will not fast
# forward means the checkout is damaged, and a merge would only bury it.
# Never fatal: a proxy that blocks the fetch must still leave the session
# with the last-known-good seed rather than none at all.
if [ "$DRY_RUN" = yes ]; then
  say "would refresh $SEED (skipped: --dry-run does no network)"
elif ! out=$(git -C "$SEED" pull -q --ff-only 2>&1); then
  warn "refresh failed, installing from the existing checkout:"
  warn "  ${out:-unknown error}"
else
  say "refreshed to $(git -C "$SEED" rev-parse --short HEAD 2>/dev/null)"
fi


# =========================================================================
# Stage — build the next release in full, touching nothing under $HOME.
# =========================================================================
# T3 (partial failure -> mixed instruction set) is fixed here, not by care
# at install time: this stage either produces a complete tree or it doesn't,
# and $HOME never sees the difference until the flip below. A file dropped
# from INSTALL simply isn't copied -- no separate prune step needed, unlike
# the old per-file-copy design this replaced.
# The release name must identify its content: the flip below reuses an
# existing release rather than rebuilding it, which is only sound because a
# git SHA pins exactly what was staged. With no SHA to be had, fall back to a
# name unique to this run so that shortcut can never match a stale tree.
REV=$(git -C "$SEED" rev-parse HEAD 2>/dev/null) || REV="unknown.$$"
STAGE="$CONFIG_DIR/releases/$REV"
STAGE_TMP="$CONFIG_DIR/releases/.tmp.$$"
CURRENT_TMP="$CONFIG_DIR/.current.$$"
# A crash or interrupt mid-stage/mid-flip must never leave a half-built temp
# behind for the next run to trip over -- both names are unique to this PID.
# LOCKDIR is set only by the run that actually holds the mkdir fallback lock
# below, so this never removes a lock another run is holding.
LOCKDIR=""
trap 'rm -rf "$STAGE_TMP" "$CURRENT_TMP" "$STATUS_TMP"; [ -n "$LOCKDIR" ] && rm -rf "$LOCKDIR"; :' EXIT INT TERM

installed=0; refused=0; missing=0; failed=0; linked=0

for path in $INSTALL; do
  [ -n "$path" ] || continue

  blocked=no
  for glob in $SKIP_GLOBS; do
    # shellcheck disable=SC2254  # $glob is a pattern on purpose
    case "$path" in $glob) blocked=yes; break ;; esac
  done
  if [ "$blocked" = yes ]; then
    warn "  REFUSED $path — on the never-install list"
    refused=$((refused + 1)); continue
  fi

  src="$SEED/$path"
  if [ ! -e "$src" ]; then
    warn "  MISSING $path — not in the repo (renamed?)"
    missing=$((missing + 1)); continue
  fi

  if [ "$DRY_RUN" = yes ]; then
    say "  would stage $path"
    installed=$((installed + 1)); continue
  fi

  dst="$STAGE_TMP/$path"
  mkdir -p "$(dirname "$dst")" && cp -a "$src" "$dst" ||
    { warn "  FAILED to stage $path"; failed=$((failed + 1)); continue; }
  installed=$((installed + 1))
done

# =========================================================================
# Flip — atomically swap what "current" points to.
# =========================================================================
# The rename is the whole install: every path under $HOME that reaches its
# content through $CONFIG_DIR/current (see "Link" below) changes target in
# one filesystem operation, so a reader never sees half of $STAGE_TMP and
# half of the previous release. `mv -T` (GNU, guaranteed on the Ubuntu VMs
# this script targets) is load-bearing here -- plain `mv src dst` treats an
# existing symlink-to-directory `dst` as that directory and moves `src`
# *into* it instead of replacing it.
# One installer at a time from here on. session-start-seed-refresh.sh runs
# this on every SessionStart and a checkpointed container can host several
# sessions at once, so two runs on different SHAs can reach the flip
# together -- and the GC below deletes every release but its own, which
# without serialization is a delete of the release the other run just
# pointed `current` at. Best-effort: a VM without flock, or a lock that
# never frees, must still leave a session installable.
#
# Fail-open, but not into the race: a VM with no flock at all has nothing to
# contend with and proceeds as before, while a lock that is held and times
# out means another installer is mid-flip right now -- exactly when running
# the GC unserialized is most likely to delete the release that run just
# activated. There, ADVANCE=no: skip the flip, and link against whatever
# `current` already resolves to. 20s, not longer: this runs inside a
# SessionStart hook and an install takes well under a second, so a wait
# that long already means the holder is wedged. Nothing needs to block;
# this run simply doesn't move the release, and the next SessionStart will.
#
# No flock is not the same as nothing to contend with: a VM without it still
# runs one installer per SessionStart, so "no flock" would otherwise be the
# one path that promotes and garbage-collects unserialized. An atomic mkdir
# is the portable equivalent -- POSIX guarantees exactly one of two racing
# mkdirs succeeds -- so the fallback gets the same ADVANCE=no treatment on
# contention rather than a free pass.
LOCK="$CONFIG_DIR/.install.lock"
ADVANCE=yes
if [ "$DRY_RUN" = no ] && mkdir -p "$CONFIG_DIR" 2>/dev/null; then
  if command -v flock >/dev/null 2>&1 && : >>"$LOCK" 2>/dev/null; then
    exec 9>>"$LOCK"
    flock -w 20 9 2>/dev/null || ADVANCE=no
  else
    # The holder's pid goes inside the directory: a run killed mid-flip -- a
    # reclaimed container, a hook timeout -- leaves the lock behind with no
    # process to free it, and without this check every later session would
    # sit at ADVANCE=no forever and never advance the release again.
    held=no
    waited=0
    while [ "$waited" -le 20 ]; do
      if mkdir "$LOCK.d" 2>/dev/null; then
        held=yes
        LOCKDIR="$LOCK.d"
        echo $$ >"$LOCK.d/pid" 2>/dev/null
        break
      fi
      holder=$(cat "$LOCK.d/pid" 2>/dev/null)
      waited=$((waited + 1))
      # An empty pid means a holder that has not written it yet -- treat that
      # as live and wait, or two runs would break each other's fresh locks.
      if [ -n "$holder" ] && ! kill -0 "$holder" 2>/dev/null; then
        rm -rf "$LOCK.d"
      else
        sleep 1
      fi
    done
    [ "$held" = yes ] || ADVANCE=no
  fi
fi

flip() {
  ln -s "$STAGE" "$CURRENT_TMP" &&
    mv -T "$CURRENT_TMP" "$CONFIG_DIR/current" ||
    { warn "  FAILED to flip current to releases/$REV"; failed=$((failed + 1)); return 1; }
  say "  flipped current -> releases/$REV"
  # Superseded releases go only after the flip, never before it: every $HOME
  # symlink now resolves through the new one. Without this a checkpointed
  # container accumulates a full tree per seed commit, forever.
  set +f
  for old in "$CONFIG_DIR"/releases/*; do
    [ -d "$old" ] && [ "$old" != "$STAGE" ] && rm -rf "$old"
  done
  set -f
}

if [ "$DRY_RUN" = yes ]; then
  say "would flip $CONFIG_DIR/current -> releases/$REV"
elif [ "$ADVANCE" = no ]; then
  warn "another installer holds $LOCK — not advancing the release"
  warn "  linking against whatever $CONFIG_DIR/current already holds"
  # Only a failure if there is nothing to fall back to: an earlier release
  # still serving the session is a stale install, not an incomplete one.
  [ -e "$CONFIG_DIR/current" ] || failed=$((failed + 1))
elif [ "$missing" -gt 0 ] || [ "$failed" -gt 0 ] || [ "$refused" -gt 0 ]; then
  # A partial stage must never be activated. $HOME reaches its whole
  # instruction set through `current`, so flipping to a tree that is missing
  # a hook or a rule file does not degrade the session gracefully -- it
  # deletes that instruction. The previous release is complete; keep it.
  warn "staging incomplete ($missing missing, $failed failed, $refused refused)"
  warn "  leaving the previous release in place"
  failed=$((failed + 1))
elif [ ! -d "$STAGE_TMP" ]; then
  warn "staging produced nothing usable — leaving the previous release in place"
  failed=$((failed + 1))
elif [ -d "$STAGE" ]; then
  # The common path, not an edge case: session-start-seed-refresh.sh runs
  # this installer on EVERY SessionStart, and the seed's SHA only moves when
  # a commit lands upstream. $REV pins the content, so an existing release
  # under that name already holds exactly what was just staged -- and
  # `rm -rf "$STAGE"` to rebuild it would be a delete of the directory
  # `current` is resolving through right then, leaving every $HOME symlink
  # dangling until the mv landed and nothing at all if the run died between
  # the two. Throw the redundant copy away and re-point instead; the flip is
  # a no-op when current already points here.
  say "  release $REV already staged — reusing it"
  rm -rf "$STAGE_TMP"
  flip
else
  if mkdir -p "$CONFIG_DIR/releases" && mv "$STAGE_TMP" "$STAGE"; then
    flip
  else
    warn "  FAILED to stage releases/$REV"; failed=$((failed + 1))
  fi
fi

# =========================================================================
# Link — point $HOME at "current", once. Never needs to move again.
# =========================================================================
# Every entry INSTALL names ends up reachable at $HOME/<path>, but not as a
# copy: a symlink through $CONFIG_DIR/current, so the Flip step above is the
# only place content ever changes. A directory in OWNED_DIRS is linked once
# as a whole (so a file INSTALL later drops from it just disappears, with no
# prune step); anything else is linked individually.
# No release to point at means no linking: a symlink into a missing
# `current` is worse than the real file it would replace.
if [ "$DRY_RUN" = no ] && [ ! -e "$CONFIG_DIR/current" ]; then
  warn "no usable release at $CONFIG_DIR/current — skipping Link"
fi

link_path() {
  rel=$1
  [ "$DRY_RUN" = yes ] || [ -e "$CONFIG_DIR/current" ] || return
  dst="$HOME/$rel"
  target="$CONFIG_DIR/current/$rel"

  if [ -L "$dst" ] && [ "$(readlink "$dst")" = "$target" ]; then
    return   # already correct -- most sessions, most runs
  fi

  if [ -e "$dst" ] || [ -L "$dst" ]; then
    # A real file/dir here (or a symlink to somewhere else) is either a
    # leftover from the old copy-based installer or something else's --
    # never silently discarded, same policy as everywhere else in this
    # script: back it up, then replace it.
    if [ "$DRY_RUN" = yes ]; then
      say "  would replace $rel with a symlink (backup to ~/.dotfiles-replaced/$rel)"
      linked=$((linked + 1)); return
    fi
    mkdir -p "$BACKUP/$(dirname "$rel")" && rm -rf "${BACKUP:?}/${rel:?}" 2>/dev/null
    cp -a "$dst" "$BACKUP/$rel" || {
      warn "  FAILED to back up $rel — not linking"; failed=$((failed + 1)); return; }
    rm -rf "$dst"
  fi

  if [ "$DRY_RUN" = yes ]; then
    say "  would link $rel -> current/$rel"
    linked=$((linked + 1)); return
  fi
  mkdir -p "$(dirname "$dst")" &&
    ln -s "$target" "$dst" &&
    { say "  linked $rel -> current/$rel"; linked=$((linked + 1)); } ||
    { warn "  FAILED to link $rel"; failed=$((failed + 1)); }
}

for path in $INSTALL; do
  [ -n "$path" ] || continue
  owned=no
  for dir in $OWNED_DIRS; do
    case "$path" in
      "$dir"/*) owned=yes; break ;;
    esac
  done
  [ "$owned" = yes ] && continue   # reachable via its OWNED_DIRS symlink
  link_path "$path"
done

for dir in $OWNED_DIRS; do
  blocked=no
  for never in $OWNED_NEVER; do
    [ "$dir" = "$never" ] && { blocked=yes; break; }
  done
  if [ "$blocked" = yes ]; then
    warn "  REFUSED to link $dir — on the never-own list"
    continue
  fi
  link_path "$dir"
done

# =========================================================================
# Status — written last, so its mere presence with complete:true means the
# install actually finished (R6/T7: a missing or stale file is the signal a
# degraded session uses to say so, in the SessionStart brief).
# =========================================================================
# Report the release that is actually live, not the one this run tried to
# build: when the flip is refused above, `sha` naming the rejected revision
# would make the degraded session look current at exactly the moment the
# status file matters most.
ACTIVE=$REV
if [ "$DRY_RUN" = no ]; then
  target=$(readlink "$CONFIG_DIR/current" 2>/dev/null) || target=
  [ -n "$target" ] && ACTIVE=${target##*/}
fi

BRANCH=$(git -C "$SEED" rev-parse --abbrev-ref HEAD 2>/dev/null) || BRANCH=main
[ "$BRANCH" = HEAD ] && BRANCH=main   # detached checkout -- not expected yet, but not fatal
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
COMPLETE=true
[ "$missing" -gt 0 ] && COMPLETE=false
[ "$failed" -gt 0 ] && COMPLETE=false
[ "$refused" -gt 0 ] && COMPLETE=false   # an allowlisted entry that did not install

if [ "$DRY_RUN" = yes ]; then
  say "would write $STATUS_FILE (complete: $COMPLETE)"
else
  # Staged and renamed, not truncated in place: session-start-continuity.sh
  # reads this file, and a parallel session catching it mid-write would parse
  # an empty document and announce a DEGRADED session that isn't one.
  # The rename is gated on the write: `mv` only cares that its source
  # exists, so an unconditional one would publish a half-written temp over
  # the previous good file -- the very corruption the temp exists to avoid.
  if mkdir -p "$(dirname "$STATUS_FILE")" && cat >"$STATUS_TMP" <<EOF &&
{
  "channel": "$BRANCH",
  "tag": null,
  "sha": "$ACTIVE",
  "installed_at": "$NOW",
  "complete": $COMPLETE,
  "source": "cloud-session-setup.sh"
}
EOF
     mv -f "$STATUS_TMP" "$STATUS_FILE" 2>/dev/null; then
    :
  else
    warn "  FAILED to write $STATUS_FILE — the status below is what this run"
    warn "  intended, not what a later session will read"
    rm -f "$STATUS_TMP"
  fi
fi

say "$installed staged, $linked linked, $refused refused, $missing missing, $failed failed"
say "seed checkout: $SEED"
say "config: $CONFIG_DIR/current -> releases/$ACTIVE (complete: $COMPLETE)"
exit 0
