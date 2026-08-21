#!/usr/bin/env bash
# Copy-paste source for the "Default (with tailscale)" cloud environment's
# setup-script field, per RUNBOOK.md § Create a cloud environment.
#
# The platform does not execute this file — the setup-script field only takes
# pasted text, and this variant installs tailscale before the seed exists to
# delegate to, so it can't just clone-and-delegate like
# cloud-session-setup.sh's caller does. This file is the version-controlled
# record of what's pasted; keep the two in sync by hand.
set -euo pipefail
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
  | tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
  | tee /etc/apt/sources.list.d/tailscale.list

# Full update, but don't let deadsnakes/ondrej 403s (not ours) kill the
# script via set -e — apt still refreshes every list that does succeed,
# which install needs for current package versions.
apt-get update || true
apt-get install -y tailscale openssh-client

git clone -q https://github.com/mark-brannan/dotfiles \
  "$HOME/.local/share/dotfiles-seed" 2>/dev/null
CLOUD_SESSION=1 sh "$HOME/.local/share/dotfiles-seed/.local/bin/cloud-session-setup.sh"
