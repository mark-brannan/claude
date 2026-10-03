#!/usr/bin/env bash
# Tests for npm-publish-bg. Run: bash .local/bin/npm-publish-bg.test.sh
#
# A stub `npm` on PATH stands in for the real CLI -- it prints whatever the
# case needs and exits -- so the round trip (background, watch the log,
# notify out of band, report the pid) runs without touching a registry.
# A stub `notify-send` records what the notifier was handed, which is how
# the "the URL goes out of band and never to stdout" claim is checked.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/npm-publish-bg"
pass=0
fail=0

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STUB="$WORK/bin"
mkdir -p "$STUB"
export PATH="$STUB:$PATH"
export NPM_PUBLISH_BG_WAIT=3

NOTIFY_LOG="$WORK/notified"
cat >"$STUB/notify-send" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >>"$NOTIFY_LOG"
EOF
chmod +x "$STUB/notify-send"

stub_npm() {  # stub_npm <script body for the publish case>
  cat >"$STUB/npm" <<EOF
#!/bin/sh
[ "\$1" = publish ] || exit 0
$1
EOF
  chmod +x "$STUB/npm"
}

ok()   { pass=$((pass + 1)); }
bad()  { fail=$((fail + 1)); printf 'FAIL: %s\n  %s\n' "$1" "${2-}"; }

run() {  # run <cwd> [args...] -> sets OUT, RC; fresh state + notify log
  local dir=$1; shift
  : >"$NOTIFY_LOG"
  : "${NPM_PUBLISH_BG_STATE:=$WORK/state}"
  export NPM_PUBLISH_BG_STATE
  mkdir -p "$dir"
  OUT=$(cd "$dir" && "$SCRIPT" "$@" 2>&1)
  RC=$?
}

# --- an auth URL is pushed out of band, never returned on stdout ----------
URL='https://www.npmjs.com/auth/cli/deadbeef-0000'
stub_npm "sleep 0.2; echo 'npm notice Authenticate your account at:'; echo '$URL'; sleep 5"
run "$WORK/pkg-a"
[ "$RC" = 0 ] || bad "publish with auth URL should exit 0" "rc=$RC out=$OUT"
[ "$RC" = 0 ] && ok

if grep -q "$URL" <<<"$OUT"; then
  bad "the auth URL must never reach stdout" "$OUT"
else ok; fi

if grep -q "$URL" "$NOTIFY_LOG"; then ok
else bad "the auth URL should reach the notifier" "$(cat "$NOTIFY_LOG")"; fi

if grep -q 'running in the background' <<<"$OUT"; then ok
else bad "stdout should report the background run" "$OUT"; fi

# --- npm's own domain wins over an unrelated URL printed first ------------
stub_npm "echo 'npm notice registry https://registry.example.invalid/'; echo '$URL'; sleep 5"
run "$WORK/pkg-b"
if grep -q "$URL" "$NOTIFY_LOG" && ! grep -q 'example.invalid' "$NOTIFY_LOG"; then ok
else bad "npmjs.com URL should be preferred over an earlier unrelated one" "$(cat "$NOTIFY_LOG")"; fi

# --- no URL at all: still reports, does not hang past the wait window -----
stub_npm "sleep 0.2; echo '+ pkg@1.0.0'"
run "$WORK/pkg-c"
if [ "$RC" = 0 ]; then ok; else bad "a publish needing no approval should exit 0" "rc=$RC"; fi
if grep -q 'No approval URL' <<<"$OUT"; then ok
else bad "stdout should say no approval URL appeared" "$OUT"; fi

# --- one publish per directory -------------------------------------------
stub_npm "sleep 30"
run "$WORK/pkg-d"
if [ "$RC" = 0 ]; then ok; else bad "first publish should start" "rc=$RC"; fi
first_pid=$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)

run "$WORK/pkg-d"
if [ "$RC" != 0 ] && grep -q 'already running' <<<"$OUT"; then ok
else bad "a second publish from the same cwd should be refused" "rc=$RC out=$OUT"; fi
[ -n "$first_pid" ] && kill "$first_pid" 2>/dev/null

# --- a dead pid's lock is reclaimed --------------------------------------
stub_npm "sleep 0.2; echo '+ pkg@1.0.0'"
run "$WORK/pkg-e"
sleep 1  # let it finish so its pid is gone
run "$WORK/pkg-e"
if [ "$RC" = 0 ]; then ok
else bad "a lock whose process has died should be reclaimed" "rc=$RC out=$OUT"; fi

# --- a different directory is not blocked by another's lock --------------
stub_npm "sleep 30"
run "$WORK/pkg-f"
held=$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)
run "$WORK/pkg-g"
if [ "$RC" = 0 ]; then ok
else bad "a lock is per-directory, not global" "rc=$RC out=$OUT"; fi
[ -n "$held" ] && kill "$held" 2>/dev/null

# --- the lock claim is atomic under concurrency ---------------------------
# Eight wrappers start at once in one directory. Exactly one may report a
# started publish; a check-then-write lock lets several through here.
stub_npm "sleep 20"
: >"$NOTIFY_LOG"
export NPM_PUBLISH_BG_STATE="$WORK/state-race"
mkdir -p "$WORK/pkg-race"
RACE_OUT="$WORK/race-out"
rm -rf "$RACE_OUT"; mkdir -p "$RACE_OUT"
for i in $(seq 1 8); do
  ( cd "$WORK/pkg-race" && "$SCRIPT" >"$RACE_OUT/$i.out" 2>&1; echo $? >"$RACE_OUT/$i.rc" ) &
done
wait
winners=$(grep -l '^0$' "$RACE_OUT"/*.rc 2>/dev/null | wc -l)
if [ "$winners" = 1 ]; then ok
else bad "exactly one of eight concurrent publishes should win the lock" "winners=$winners"; fi
raced=$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)
[ -n "$raced" ] && kill "$raced" 2>/dev/null

# --- what a hard-killed publish leaves behind -----------------------------
# Under flock the lock is held by the publish itself, so SIGKILL releases it
# and the next caller simply proceeds. The mkdir fallback macOS takes cannot
# do that -- the directory outlives the process -- so it refuses and names
# the one command that clears it. Both are checked; neither may let a second
# publish start while one is genuinely running.
for impl in flock mkdir; do
  export NPM_PUBLISH_BG_LOCK=$impl
  export NPM_PUBLISH_BG_STATE="$WORK/state-kill-$impl"
  stub_npm "exec sleep 30"  # one process, as real npm is
  run "$WORK/pkg-kill-$impl"
  kill -9 "$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)" 2>/dev/null
  sleep 0.3
  stub_npm "sleep 0.2; echo '+ pkg@1.0.0'"
  run "$WORK/pkg-kill-$impl"
  if [ "$impl" = flock ]; then
    if [ "$RC" = 0 ]; then ok
    else bad "[flock] a hard-killed holder should leave no lock behind" "rc=$RC out=$OUT"; fi
  else
    if [ "$RC" != 0 ] && grep -q 'rmdir' <<<"$OUT"; then ok
    else bad "[mkdir] a stranded lock should name the command that clears it" "rc=$RC out=$OUT"; fi
  fi
done

# --- concurrent callers racing a dead holder ------------------------------
# The case a pid-liveness lock gets wrong: several callers agree the recorded
# holder is dead and each reclaims, so each believes it holds the lock. What
# must never happen is two winners -- flock yields exactly one, the mkdir
# fallback yields none and waits to be cleared by hand.
for impl in flock mkdir; do
  export NPM_PUBLISH_BG_LOCK=$impl
  export NPM_PUBLISH_BG_STATE="$WORK/state-dead-$impl"
  stub_npm "exec sleep 30"  # one process, as real npm is
  mkdir -p "$WORK/pkg-dead-$impl"
  ( cd "$WORK/pkg-dead-$impl" && "$SCRIPT" >/dev/null 2>&1 )
  kill -9 "$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)" 2>/dev/null
  sleep 0.3
  DEAD_OUT="$WORK/dead-$impl"; rm -rf "$DEAD_OUT"; mkdir -p "$DEAD_OUT"
  for i in $(seq 1 8); do
    ( cd "$WORK/pkg-dead-$impl" && "$SCRIPT" >/dev/null 2>&1; echo $? >"$DEAD_OUT/$i.rc" ) &
  done
  wait
  w=$(grep -l '^0$' "$DEAD_OUT"/*.rc 2>/dev/null | wc -l)
  want=1; [ "$impl" = mkdir ] && want=0
  if [ "$w" = "$want" ]; then ok
  else bad "[$impl] wanted $want winner(s) of eight against a dead holder" "winners=$w"; fi
  kill "$(cat "$NPM_PUBLISH_BG_STATE"/*.pid 2>/dev/null | head -n1)" 2>/dev/null
done
unset NPM_PUBLISH_BG_LOCK NPM_PUBLISH_BG_STATE

# --- a lock claimed but never handed to a child is not stranded -----------
# The window between claiming the lock and the child taking ownership of it.
# Forced here by making the logfile path a directory, so the redirect that
# opens it fails; under the mkdir fallback nothing but the trap gives the
# lock back, and a lock stranded there has no pid to name in its message.
export NPM_PUBLISH_BG_LOCK=mkdir
export NPM_PUBLISH_BG_STATE="$WORK/state-strand"
mkdir -p "$NPM_PUBLISH_BG_STATE" "$WORK/pkg-strand"
strand_key=$(cd "$WORK/pkg-strand" && pwd | cksum | cut -d' ' -f1)
mkdir -p "$NPM_PUBLISH_BG_STATE/$strand_key.log"   # a directory: `: >` will fail
stub_npm "sleep 0.2; echo '+ pkg@1.0.0'"
run "$WORK/pkg-strand"
if [ "$RC" != 0 ]; then ok
else bad "an unwritable logfile should fail the run" "rc=$RC out=$OUT"; fi
if [ ! -d "$NPM_PUBLISH_BG_STATE/$strand_key.lockdir" ]; then ok
else bad "a lock claimed but never handed off must be released" "lockdir survived"; fi

# ...and with the obstruction gone the next run simply proceeds.
rmdir "$NPM_PUBLISH_BG_STATE/$strand_key.log"
run "$WORK/pkg-strand"
if [ "$RC" = 0 ]; then ok
else bad "the next run should proceed once the lock was released" "rc=$RC out=$OUT"; fi
unset NPM_PUBLISH_BG_LOCK NPM_PUBLISH_BG_STATE

# --- the log holds a live credential: owner-only --------------------------
mode() { stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null; }
stub_npm "sleep 0.2; echo '+ pkg@1.0.0'"
export NPM_PUBLISH_BG_STATE="$WORK/state-perm"
run "$WORK/pkg-perm"
log=$(find "$NPM_PUBLISH_BG_STATE" -name '*.log' 2>/dev/null | head -n1)
if [ "$(mode "$log")" = 600 ]; then ok
else bad "the logfile carries the approval URL and must be owner-only" "mode=$(mode "$log")"; fi
if [ "$(mode "$NPM_PUBLISH_BG_STATE")" = 700 ]; then ok
else bad "the state directory must be owner-only" "mode=$(mode "$NPM_PUBLISH_BG_STATE")"; fi

# --- extra arguments reach npm -------------------------------------------
ARGS_LOG="$WORK/args"
stub_npm "printf '%s\n' \"\$*\" >'$ARGS_LOG'; echo '+ pkg@1.0.0'"
run "$WORK/pkg-h" --access public --tag next
sleep 0.5
if grep -q -- '--access public --tag next' "$ARGS_LOG" 2>/dev/null; then ok
else bad "arguments should be passed through to npm publish" "$(cat "$ARGS_LOG" 2>/dev/null)"; fi

# --- no npm on PATH: a clear failure, not a silent success ----------------
rm -f "$STUB/npm"
mkdir -p "$WORK/pkg-i"
OLD=$PATH
PATH=$STUB:/nonexistent-for-this-test
OUT=$( cd "$WORK/pkg-i" && "$SCRIPT" 2>&1 )
RC=$?
PATH=$OLD
if [ "$RC" != 0 ] && grep -q 'not on PATH' <<<"$OUT"; then ok
else bad "missing npm should fail loudly" "rc=$RC out=$OUT"; fi

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
