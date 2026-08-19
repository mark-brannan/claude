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
DRY_RUN=no
[ "${1:-}" = "--dry-run" ] && DRY_RUN=yes

# --- what to install -----------------------------------------------------
# Repo-relative paths, files or directories, copied to the same path under
# $HOME. Expand deliberately: every line lands in every cloud session.
INSTALL="
.claude/settings.json
.claude/CLAUDE.md
.claude/rules/code.md
.claude/rules/writing.md
.claude/hooks/no-persistent-polling.sh
.claude/hooks/log-decisions.sh
.claude/hooks/measure-cherry-pick.sh
"

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
# Overwrite policy
# =========================================================================
# Overwriting is the point on an ephemeral VM, but it is never silent and
# never irreversible within the session:
#   missing      -> install
#   identical    -> no-op
#   symlink      -> refuse (that is yadm-alt or another manager's file)
#   differs      -> copy the old one to ~/.dotfiles-replaced/, then overwrite
install_file() {
  src=$1; rel=$2; dst="$HOME/$rel"

  if [ -L "$dst" ]; then
    warn "  REFUSED $rel — destination is a symlink, left alone"
    refused=$((refused + 1)); return
  fi

  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then
    same=$((same + 1)); return
  fi

  if [ -e "$dst" ]; then
    if [ "$DRY_RUN" = yes ]; then
      say "  would REPLACE $rel (backup to ~/.dotfiles-replaced/$rel)"
    else
      mkdir -p "$BACKUP/$(dirname "$rel")" && cp -a "$dst" "$BACKUP/$rel" || {
        warn "  FAILED to back up $rel — not overwriting"
        failed=$((failed + 1)); return
      }
      cp -a "$src" "$dst" &&
        say "  replaced $rel (old copy: ~/.dotfiles-replaced/$rel)" ||
        { warn "  FAILED $rel"; failed=$((failed + 1)); return; }
    fi
    replaced=$((replaced + 1))
  else
    if [ "$DRY_RUN" = yes ]; then
      say "  would install $rel"
    else
      mkdir -p "$(dirname "$dst")" && cp -a "$src" "$dst" ||
        { warn "  FAILED $rel"; failed=$((failed + 1)); return; }
      say "  installed $rel"
    fi
    installed=$((installed + 1))
  fi
}

installed=0; replaced=0; same=0; refused=0; missing=0; failed=0

# Flatten INSTALL (which may name directories) to one src<TAB>relpath per line
# in a temp file. A file, not a pipe: `find | while` would run the loop in a
# subshell and every counter above would be discarded at the end of it.
TAB=$(printf '\t')
LIST=$(mktemp) || exit 0
trap 'rm -f "$LIST"' EXIT INT TERM

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

  if [ -d "$src" ]; then
    # walk the tree so the policy applies per file, not as a blanket copy
    find "$src" -type f -exec printf '%s\t%s\n' '{}' "$path" \; >>"$LIST"
  else
    printf '%s\t%s\n' "$src" "$path" >>"$LIST"
  fi
done

while IFS="$TAB" read -r src path; do
  [ -n "${src:-}" ] || continue
  case "$src" in
    "$SEED/$path") rel=$path ;;                    # single file
    *)             rel="$path/${src#"$SEED/$path/"}" ;;  # file within a dir
  esac
  install_file "$src" "$rel"
done <"$LIST"

say "$installed installed, $replaced replaced, $same unchanged, $refused refused, $missing missing, $failed failed"
say "seed checkout: $SEED"
exit 0
