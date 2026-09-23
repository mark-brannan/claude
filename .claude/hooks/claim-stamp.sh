#!/bin/sh
# Writes, refreshes and removes the session claim stamp on a branch's card --
# the open PR, or the open issue that names the branch. One comment, one
# session, visible to every machine.
#
# Why a remote stamp: nothing else says which session holds a branch in a way
# a second machine can see. `no-foreign-worktree.sh` and `branch_brief` see
# local worktrees only, so two sessions on two machines could both pick up the
# same branch and neither would know until a push was rejected. Ruled by
# Solace, 2026-09-22 (dotfiles#287): stamp the card itself, so an accidental
# parallel session is visible at open, and anything deciding whether a branch
# is free has a remote claim to read rather than a clock to guess from.
# Supersedes the local-heartbeat shape proposed in dotfiles#167.
#
# The stamp is a comment, not an edit to the body. A body edit races with
# humans and with Mergify's `Depends-On:` header, and clobbering prose to say
# "someone is working here" is a bad trade; a comment is addressable by id,
# patched in place rather than re-posted, and deleted outright on release.
#
# One comment per session, keyed by session id in the marker. Two sessions on
# one card therefore leave two stamps -- which is the truth, and the exact
# state this exists to make visible. The second one prints a warning naming
# the first.
#
# CONVENIENCE, NOT A GATE: every path exits 0. No gh, no jq, gh
# unauthenticated, no card, a failed API call -- all are silent no-ops. A
# session must never be unable to start or end because a claim could not be
# written. The gates in this repo (branch-home-gate.sh, public-issue-guard.sh)
# fail closed; this one does not, deliberately.
#
# Never runs under CI: the shared PR reviewer runs Claude Code inside GitHub
# Actions with these hooks seeded from main, and a bot's checkout holds no
# claim on anything.
#
# Usage:
#   claim-stamp.sh claim   [-C <dir>] <session-id>   warn if held, then stamp
#   claim-stamp.sh refresh [-C <dir>] <session-id>   bump this session's stamp
#   claim-stamp.sh release [-C <dir>] [--scan] <session-id>
#                                                    delete this session's stamp
#   claim-stamp.sh read    [-C <dir>]                print every stamp on the card:
#       live|stale <sid8> <machine> <age>m <url>, one tab-separated line each;
#       `no card`; or `unverified: <why>` when the stamps could not be read
#   claim-stamp.sh session-start                     SessionStart hook; JSON on stdin
#
# `refresh` is the one called on every Stop, so it must be free when there is
# nothing to refresh: it reads a per-session record under TMPDIR and returns
# without a single network call when this session has not claimed anything.
# When it has, the refresh is debounced to once per CLAIM_REFRESH_SECS.
#
# PROPOSED, NOT RULED (dotfiles#287): a stamp older than CLAIM_STALE_SECS
# (default 2h) is stale -- its session died without releasing it. `claim`
# deletes stale stamps it finds, which is the only garbage collection there
# is; nothing else ever removes a comment a dead session left. Age is taken
# from the epoch in the stamp's own marker, never from the comment's
# updated_at: the stamp is the truth, the comment metadata is not.
set -u

HERE=$(cd "$(dirname "$0")" && pwd)

MARKER='<!-- claim-stamp'
STALE_SECS=${CLAIM_STALE_SECS:-7200}
REFRESH_SECS=${CLAIM_REFRESH_SECS:-300}
LABEL=${CLAIM_LABEL:-claimed}

# Bounded, always. A hook that hangs on a network call is worse than one that
# does nothing: SessionStart holds the first prompt and Stop holds the turn.
run_to() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"; else shift; "$@"; fi
}

now_epoch() { date -u +%s; }
now_iso()   { date -u +%Y-%m-%dT%H:%M:%SZ; }

# An opaque, stable per-machine token. A GitHub comment on a public repo is a
# publish, and real hostnames stay out of published text -- so the stamp
# carries a hash of the hostname, which distinguishes two machines without
# naming either.
machine_id() {
  h=$(hostname 2>/dev/null || uname -n 2>/dev/null || printf 'unknown')
  if command -v sha256sum >/dev/null 2>&1; then
    s=$(printf '%s' "$h" | sha256sum 2>/dev/null | cut -c1-6)
  elif command -v shasum >/dev/null 2>&1; then
    s=$(printf '%s' "$h" | shasum -a 256 2>/dev/null | cut -c1-6)
  else
    s=""
  fi
  printf 'host-%s' "${s:-unknown}"
}

# Per-session record: the card this session claimed, the comment it owns and
# when it last refreshed. Under TMPDIR, never under the state dir --
# stop-continuity.sh commits and pushes that, so a per-session file there
# would be repo churn in every session (the convention branch-home-gate.sh
# and pr-ownership-context.sh already use).
record_path() {
  printf '%s/claude-claim-stamp.%s' "${TMPDIR:-/tmp}" \
    "$(printf '%s' "$1" | tr -c 'A-Za-z0-9_-' '_')"
}

sid8() { printf '%s' "$1" | cut -c1-8; }

# ---------------------------------------------------------------- the card
# `pr <url>`, `issue <url>`, `none`, or `unverified: <why>` -- branch-home-gate.sh
# owns the lookup, so a claim and the Stop gate can never disagree about which
# card a branch belongs to. It is read-only in this mode and touches no marker.
card_of() {
  run_to 25 sh "$HERE/branch-home-gate.sh" --card "$1" 2>/dev/null
}

# owner repo number, from a github.com issue or pull URL. Both kinds of card
# take comments at the same endpoint, repos/O/R/issues/N/comments, so nothing
# below this line needs to know which it has.
parse_url() {
  printf '%s' "$1" | sed -nE \
    's@^https?://[^/]+/([^/]+)/([^/]+)/(pull|issues)/([0-9]+)([/?].*)?$@\1 \2 \4@p'
}

# Sets owner, repo and number from a card URL; false when it is not one.
card_parts() {
  owner=""; repo=""; number=""
  read -r owner repo number <<EOF
$(parse_url "$1")
EOF
  [ -n "$number" ]
}

# --------------------------------------------------------------- the stamp
# <id> <sid8> <epoch> <machine> on one tab-separated line per stamp found.
# Everything a caller needs to judge a claim comes out of the marker, so no
# consumer has to parse the human line.
read_stamps() {  # read_stamps <owner> <repo> <number>
  run_to 25 gh api "repos/$1/$2/issues/$3/comments" --paginate --jq '
    .[] | select(.body | test("<!-- claim-stamp "))
    | [ (.id|tostring)
      , ((.body | capture("sid=(?<v>[A-Za-z0-9_-]+)").v) // "?")
      , ((.body | capture("epoch=(?<v>[0-9]+)").v) // "0")
      , ((.body | capture("machine=(?<v>[A-Za-z0-9_-]+)").v) // "?")
      ] | @tsv' 2>/dev/null
}

stamp_body() {  # stamp_body <sid> <branch>
  cat <<EOF
$MARKER sid=$(sid8 "$1") epoch=$(now_epoch) machine=$(machine_id) -->
**Claimed:** \`$(sid8 "$1")\` · \`$2\` · \`$(machine_id)\` · $(now_iso)

A session holds this branch. The Stop hook refreshes the timestamp; \`/wrapup\`
and the archive verdict delete this comment. Older than $((STALE_SECS / 3600))h and
the claim is stale -- the session that wrote it died without releasing it.
EOF
}

post_stamp() {  # post_stamp <owner> <repo> <number> <sid> <branch> -> comment id
  jq -n --arg b "$(stamp_body "$4" "$5")" '{body:$b}' 2>/dev/null \
    | run_to 25 gh api -X POST "repos/$1/$2/issues/$3/comments" --input - \
        --jq '.id' 2>/dev/null
}

patch_stamp() {  # patch_stamp <owner> <repo> <comment-id> <sid> <branch>
  jq -n --arg b "$(stamp_body "$4" "$5")" '{body:$b}' 2>/dev/null \
    | run_to 25 gh api -X PATCH "repos/$1/$2/issues/comments/$3" --input - \
        >/dev/null 2>&1
}

delete_stamp() {  # delete_stamp <owner> <repo> <comment-id>
  run_to 25 gh api -X DELETE "repos/$1/$2/issues/comments/$3" >/dev/null 2>&1
}

# The label is the cheap filter -- `pr-label-audit --json` reports it, and a
# label query costs one search where reading every card's comments costs one
# call per card. The stamp stays the truth: a label with no stamp under it
# means a session died between the two writes, not that the branch is held.
add_label()    { run_to 25 gh api -X POST "repos/$1/$2/issues/$3/labels" \
                   -f "labels[]=$LABEL" >/dev/null 2>&1; }
remove_label() { run_to 25 gh api -X DELETE "repos/$1/$2/issues/$3/labels/$LABEL" \
                   >/dev/null 2>&1; }

# ------------------------------------------------------------- preconditions
usable() {
  [ -z "${GITHUB_ACTIONS:-}" ] || return 1
  [ -z "${CI:-}" ] || return 1
  [ "${CLAUDE_CLAIM_STAMP:-on}" != off ] || return 1
  command -v gh >/dev/null 2>&1 || return 1
  command -v jq >/dev/null 2>&1 || return 1
  return 0
}

# ------------------------------------------------------------------ actions
# Prints the warning a contested claim deserves, or nothing. Every stamp that
# is neither this session's nor stale is named, with its age in minutes, so
# the reader can tell a session that started a minute ago from one that has
# been holding the branch for an hour.
warn_held() {  # warn_held <stamps> <sid> <branch>
  _stamps=$1; _sid=$(sid8 "$2"); _branch=$3
  _now=$(now_epoch)
  printf '%s\n' "$_stamps" | while IFS="$(printf '\t')" read -r _id _s _e _m; do
    [ -n "${_id:-}" ] || continue
    [ "$_s" != "$_sid" ] || continue
    _age=$((_now - _e))
    [ "$_age" -lt "$STALE_SECS" ] || continue
    printf 'session `%s` on `%s` claimed `%s` %d minute(s) ago\n' \
      "$_s" "$_m" "$_branch" "$((_age / 60))"
  done
}

do_claim() {  # do_claim <dir> <sid>
  dir=$1; sid=$2
  usable || return 0
  branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null) || return 0
  case "$branch" in ''|HEAD|main|master) return 0 ;; esac

  card=$(card_of "$dir")
  case "$card" in
    pr\ *|issue\ *) url=${card#* } ;;
    *) return 0 ;;   # none, unverified, or nothing at all: no card to stamp
  esac
  card_parts "$url" || return 0

  stamps=$(read_stamps "$owner" "$repo" "$number") || return 0

  # Garbage-collect first: a stamp past the stale threshold belongs to a
  # session that died without releasing it, and nothing else ever removes
  # one. Doing it here rather than on a timer means the collector runs
  # exactly when someone cares -- at the moment another session asks whether
  # the branch is free.
  now=$(now_epoch)
  printf '%s\n' "$stamps" | while IFS="$(printf '\t')" read -r id s e m; do
    [ -n "${id:-}" ] || continue
    [ "$s" != "$(sid8 "$sid")" ] || continue
    [ $((now - e)) -ge "$STALE_SECS" ] || continue
    delete_stamp "$owner" "$repo" "$id"
  done

  held=$(warn_held "$stamps" "$sid" "$branch")

  # This session's own stamp, if it already has one on this card: patch it
  # rather than post a second. A session that restarts (a new SessionStart on
  # the same id) must not leave a trail of its own claims.
  mine=$(printf '%s\n' "$stamps" | awk -F'\t' -v s="$(sid8 "$sid")" '$2 == s { print $1; exit }')
  if [ -n "$mine" ]; then
    patch_stamp "$owner" "$repo" "$mine" "$sid" "$branch"
    cid=$mine
  else
    cid=$(post_stamp "$owner" "$repo" "$number" "$sid" "$branch")
  fi
  [ -n "$cid" ] || return 0
  add_label "$owner" "$repo" "$number"
  printf '%s/%s#%s\t%s\t%s\n' "$owner" "$repo" "$number" "$cid" "$(now_epoch)" \
    > "$(record_path "$sid")" 2>/dev/null

  CLAIM_HELD=$held
  CLAIM_URL=$url
  return 0
}

do_refresh() {  # do_refresh <sid> <dir>
  rec=$(record_path "$1")
  if [ ! -f "$rec" ]; then
    # Nothing claimed: free, no network. The one exception is a session that
    # the Stop hook released on an archivable turn and that then carried on
    # working -- the tombstone says so, and the branch is held again, so it is
    # claimed again. Once per resume, not per turn: do_claim rewrites the
    # record, and a claim that fails leaves the tombstone for the next turn.
    [ -f "$rec.released" ] || return 0
    do_claim "${2:-$PWD}" "$1"
    [ -f "$rec" ] && rm -f "$rec.released" 2>/dev/null
    return 0
  fi
  usable || return 0
  IFS="$(printf '\t')" read -r card cid last < "$rec" || return 0
  [ -n "${cid:-}" ] || return 0
  case "${last:-0}" in ''|*[!0-9]*) last=0 ;; esac
  [ $(( $(now_epoch) - last )) -ge "$REFRESH_SECS" ] || return 0
  owner=${card%%/*}; rest=${card#*/}; repo=${rest%%#*}; number=${rest##*#}
  branch=$(git -C "${2:-$PWD}" rev-parse --abbrev-ref HEAD 2>/dev/null || printf '?')
  patch_stamp "$owner" "$repo" "$cid" "$1" "$branch" || return 0
  printf '%s\t%s\t%s\n' "$card" "$cid" "$(now_epoch)" > "$rec" 2>/dev/null
  return 0
}

do_release() {  # do_release <dir> <sid>
  usable || return 0
  _dir=$1; _sid=$2
  rec=$(record_path "$_sid")
  owner=""; repo=""; number=""
  if [ -f "$rec" ]; then
    IFS="$(printf '\t')" read -r card cid last < "$rec"
    owner=${card%%/*}; rest=${card#*/}; repo=${rest%%#*}; number=${rest##*#}
    [ -n "${cid:-}" ] && delete_stamp "$owner" "$repo" "$cid"
    rm -f "$rec" 2>/dev/null
    # A release from the Stop hook is provisional: the session may take
    # another turn. The tombstone lets refresh re-claim then (see do_refresh);
    # a --scan release is the deliberate one (/wrapup) and leaves nothing.
    [ "${SCAN:-0}" = 1 ] && rm -f "$rec.released" 2>/dev/null || : > "$rec.released"
  elif [ "${SCAN:-0}" = 1 ]; then
    # No record -- a wiped TMPDIR, or a release from a session that did not
    # write the stamp itself. Look the card up and delete this session's
    # stamp by its marker, the only identity that survives the record.
    #
    # Behind --scan because the Stop hook releases on every archivable turn,
    # and a scan here would be a card lookup per turn for the overwhelmingly
    # common case of a session that never claimed anything. A caller that
    # knows it is worth the round trip (/wrapup, once) asks for it.
    card=$(card_of "$_dir")
    case "$card" in pr\ *|issue\ *) url=${card#* } ;; *) return 0 ;; esac
    card_parts "$url" || return 0
    read_stamps "$owner" "$repo" "$number" \
      | awk -F'\t' -v s="$(sid8 "$_sid")" '$2 == s { print $1 }' \
      | while read -r id; do [ -n "$id" ] && delete_stamp "$owner" "$repo" "$id"; done
  else
    return 0
  fi
  [ -n "$owner" ] || return 0
  # The label goes last and only when no stamp is left: a second session may
  # still hold this card, and dropping its label would hide a live claim from
  # every label-based filter.
  # Only on a lookup that actually answered: a failed read returns nothing,
  # which would read as "no stamps left" and strip the label off a card a
  # live session is still holding.
  rest=$(read_stamps "$owner" "$repo" "$number") || return 0
  [ -z "$rest" ] && remove_label "$owner" "$repo" "$number"
  return 0
}

# A lookup that failed must not read as "zero stamps": consumers deciding
# whether a worktree is free map `unverified` to unknown, an empty list to free.
do_read() {  # do_read <dir>
  usable || return 0
  card=$(card_of "$1")
  case "$card" in
    pr\ *|issue\ *) url=${card#* } ;;
    none) printf 'no card\n'; return 0 ;;
    unverified*) printf '%s\n' "$card"; return 0 ;;
    *) printf 'unverified: card lookup failed\n'; return 0 ;;
  esac
  card_parts "$url" || { printf 'unverified: bad card url %s\n' "$url"; return 0; }
  stamps=$(read_stamps "$owner" "$repo" "$number") \
    || { printf 'unverified: could not read the stamps on %s\n' "$url"; return 0; }
  now=$(now_epoch)
  printf '%s\n' "$stamps" | while IFS="$(printf '\t')" read -r id s e m; do
    [ -n "${id:-}" ] || continue
    age=$((now - e))
    if [ "$age" -ge "$STALE_SECS" ]; then state=stale; else state=live; fi
    printf '%s\t%s\t%s\t%dm\t%s\n' "$state" "$s" "$m" "$((age / 60))" "$url"
  done
}

# ------------------------------------------------------------------ dispatch
cmd=${1:-}; [ $# -gt 0 ] && shift
dir=$PWD
SCAN=0
while [ $# -gt 0 ]; do
  case "$1" in
    -C) dir=$2; shift 2 ;;
    -C*) dir=${1#-C}; shift ;;
    --scan) SCAN=1; shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done

case "$cmd" in
  claim)   [ $# -ge 1 ] || exit 0; do_claim "$dir" "$1"
           [ -n "${CLAIM_HELD:-}" ] && printf '%s\n' "$CLAIM_HELD"
           exit 0 ;;
  refresh) [ $# -ge 1 ] || exit 0; do_refresh "$1" "$dir"; exit 0 ;;
  release) [ $# -ge 1 ] || exit 0; do_release "$dir" "$1"; exit 0 ;;
  read)    do_read "$dir"; exit 0 ;;
  session-start)
    payload=$(cat 2>/dev/null) || exit 0
    command -v jq >/dev/null 2>&1 || exit 0
    sid=$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)
    scwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
    [ -n "$sid" ] || exit 0
    do_claim "${scwd:-$PWD}" "$sid"
    # Silence is the normal outcome. The only thing worth a session's context
    # is the contested case: another session is holding this branch right now.
    [ -n "${CLAIM_HELD:-}" ] || exit 0
    jq -Rn --rawfile c /dev/stdin \
      '{hookSpecificOutput:{hookEventName:"SessionStart", additionalContext:$c}}' <<EOF
## WARNING: this branch is already claimed

$CLAIM_HELD

The claim is a stamp on ${CLAIM_URL:-the card}, refreshed by that session's Stop
hook. It is not stale, so assume the other session is alive: say so to Solace in
one line, name the session and the card, and do not push to this branch until
you know the other session has let go.
EOF
    exit 0 ;;
  *) printf 'usage: claim-stamp.sh claim|refresh|release|read|session-start [-C <dir>] [<session-id>]\n' >&2
     exit 2 ;;
esac
