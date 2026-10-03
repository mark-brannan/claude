#!/usr/bin/env sh

# Ensure the fleet's triage labels exist on every vended repo.
# Idempotent: gh exits non-zero on "already exists"

set -u
OWNER=${OWNER:-mark-brannan}
REPOS="dotfiles symphony $(tr -d '\r' < ~/.local/share/vended-repos.txt | grep -v '^[[:space:]]*$')"
LABELS='
awaiting-human|8250DF|Green and thread-free: it is your turn
ready|1D76DB|Agent-startable: grind will pull this
claimed|6A737D|A session holds this branch; see the claim stamp on the card
churn-ok|FBCA04|Waives the churn-diff gate (human-applied only)
fixup-hard|D93F0B|A fixer session gave up; needs a bigger session or a human
blocked|B60205|Waiting on something; body carries the Blocked by line
'

ensure() { # ensure <repo> <label> <color> <desc>
  if gh label create "$2" -R "$OWNER/$1" --color "$3" -d "$4" >/dev/null 2>&1; then
    echo "created  $1  $2"
  elif gh label list -R "$OWNER/$1" --json name -q '.[].name' 2>/dev/null | grep -qx "$2"; then
    echo "present  $1  $2"
  else
    echo "FAILED   $1  $2" >&2
  fi
}

for r in $REPOS; do
  printf '%s\n' "$LABELS" | grep -v '^[[:space:]]*$' | while IFS='|' read -r n c d; do
    ensure "$r" "$n" "$c" "$d"
  done
done
