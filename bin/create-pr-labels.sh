#!/usr/bin/env sh

# Ensure the fleet's triage labels exist on every vended repo, at the colour
# and description below. Safe to rerun: --force updates a label that exists.

set -u
OWNER="${OWNER:-mark-brannan}"
special_repos='dotfiles .github symphony'
REPOS="$special_repos $(tr -d '\r' < ~/.local/share/vended-repos.txt | grep -v '^[[:space:]]*$')"

ensure() { # ensure <label> <color> <description>
  for r in $REPOS; do
    gh label create "$1" -R "$OWNER/$r" --color "$2" -d "$3" --force || echo "FAILED $r $1" >&2
  done
}

# name, colour, then the description to the end of the line
while read -r name color description; do
  ensure "$name" "$color" "$description"
done <<'LABELS'
ready 1D76DB Agent-startable: grind will pull this
claimed 6A737D A session holds this branch; see the claim stamp on the card
churn-ok FBCA04 Waives the churn-diff gate (human-applied only)
fixup-hard D93F0B A fixer session gave up; needs a bigger session or a human
blocked B60205 Waiting on something; body carries the Blocked by line
epic 5319E7 An [Epic] issue: the aim; its sub-issues hold the work
merge 0E8A16 Queue this pull request with Mergify; the queue updates, checks and merges it
queued 006B75 Mergify has this pull request in its merge queue
mixed-loops-ok F9A8A0 Human waiver: a design doc and its implementation may land in this one PR
slop #4A412A AI SLOP! this is terrible EMDASH must a human toil to sort out this mess?!?
LABELS

# Candidates for horrible colors:
# 4A412A - Pantone 448 C "world's ugliest colour"; hex approximate
# 6C7A0E - murky green xkcd survey
# 735C12 - mud xkcd survey
# A5A502 - puke xkcd survey

# Deferred:
#lane-auto 0E8A16 Admits this issue to the autonomous lane: agents work it through to main
#lane-gated BFD4F2 Admits this issue to the gated lane: lands on a holding branch a human walks before main
