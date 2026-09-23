#!/usr/bin/env bash
# Tests for lib-state.sh's archivable_reasons(), focused on the session-live
# check (dotfiles#167).
#
# The dirty/unpushed/home checks predate this file and are exercised
# end-to-end by stop-continuity.test.sh and metrics-live.test.sh already;
# what's new and untested elsewhere is the claim-stamp liveness gate, so
# that's what this covers. Every case below starts from a worktree that is
# clean, pushed and homed -- reasons empty before the live check runs at
# all -- so a pass here isolates the new behavior from the old.
set -uo pipefail

HOOKS="$(cd "$(dirname "$0")" && pwd)"
pass=0; fail=0
SCRATCH=$(mktemp -d); trap 'rm -rf "$SCRATCH"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

gitq() { git -C "$1" -c user.name=t -c user.email=t@example.invalid -c commit.gpgsign=false "${@:2}" >/dev/null 2>&1; }

# --- a clean, pushed, homed worktree ------------------------------------------
ORIGIN="$SCRATCH/origin.git"; git init -q --bare "$ORIGIN" >/dev/null 2>&1
WT="$SCRATCH/work"; gitq "$SCRATCH" init -q -b feature "$WT"
printf 'x\n' > "$WT/f"
gitq "$WT" add f
gitq "$WT" commit -q -m init
gitq "$WT" remote add origin "$ORIGIN"
gitq "$WT" push -q -u origin feature

# --- a fake HOOK_DIR: branch-home-gate.sh always says "home", claim-stamp.sh
# is swapped per case ------------------------------------------------------
FAKE="$SCRATCH/hooks"; mkdir -p "$FAKE"
cat > "$FAKE/branch-home-gate.sh" <<'EOF'
#!/bin/sh
echo "home: pr https://github.com/o/r/pull/1"
EOF
chmod +x "$FAKE/branch-home-gate.sh"

set_claim_stamp() {  # set_claim_stamp <read-output>
  cat > "$FAKE/claim-stamp.sh" <<EOF
#!/bin/sh
[ "\$1" = read ] || exit 0
cat <<'STAMPS'
$1
STAMPS
EOF
  chmod +x "$FAKE/claim-stamp.sh"
}

run_reasons() {  # run_reasons <self-sid>
  HOOK_DIR="$FAKE" bash -c '
    . "'"$HOOKS"'/lib-state.sh"
    archivable_reasons "'"$WT"'" feature "'"$1"'"
  '
}

check() {  # check <name> <self-sid> <want-contains|empty>
  name=$1; sid=$2; want=$3
  got=$(run_reasons "$sid")
  case "$want" in
    '') if [ -z "$got" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $name: want empty, got [$got]"; fi ;;
    *)  case "$got" in
          *"$want"*) pass=$((pass+1)) ;;
          *) fail=$((fail+1)); echo "FAIL $name: want to contain [$want], got [$got]" ;;
        esac ;;
  esac
}

# no claim-stamp.sh at all: behaves exactly as before this change (empty)
rm -f "$FAKE/claim-stamp.sh"
check "no claim-stamp.sh -> archivable" abcd1234 ""

# a live stamp belonging to someone else: blocks
set_claim_stamp "$(printf 'live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1')"
check "other session's fresh stamp -> session live" abcd1234 "session live"

# the caller's own stamp, fresh: does not block its own archival
check "own fresh stamp is excluded" deadbeef ""

# a stale stamp: does not block
set_claim_stamp "$(printf 'stale\tdeadbeef\thost-aa1\t180m\thttps://github.com/o/r/pull/1')"
check "stale stamp -> archivable" abcd1234 ""

# no card / no stamps at all (claim-stamp prints nothing): does not block
set_claim_stamp ""
check "no stamps -> archivable" abcd1234 ""

# no session id given (a sweep, not a session): a fresh stamp from anyone,
# including one that happens to share no sid, still blocks
set_claim_stamp "$(printf 'live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1')"
check "no self sid, fresh stamp -> session live" "" "session live"

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
