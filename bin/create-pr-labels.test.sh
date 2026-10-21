#!/usr/bin/env bash
# Tests for create-pr-labels.sh. Run: bash bin/create-pr-labels.test.sh
# A stub `gh` that echoes its arguments stands in for the network.
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/create-pr-labels.sh"
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
mkdir -p "$S/bin" "$S/home/.local/share"
printf 'repoa\n' > "$S/home/.local/share/vended-repos.txt"
printf '#!/bin/sh\necho "$@"\n' > "$S/bin/gh"; chmod +x "$S/bin/gh"

out=$(HOME="$S/home" PATH="$S/bin:$PATH" sh "$SCRIPT")

for label in merge queued mixed-loops-ok epic; do
  for repo in dotfiles repoa; do
    echo "$out" | grep -q "^label create $label -R mark-brannan/$repo " || { echo "FAIL $label on $repo"; exit 1; }
  done
done
echo ok
