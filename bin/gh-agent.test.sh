#!/usr/bin/env bash
# Tests for gh-agent. Run: bash bin/gh-agent.test.sh
#
# What matters: the JWT's header and claims decode to what GitHub requires and
# its signature verifies against the key's public half; a missing key or app id
# stops with one line naming the file; a cached token is reused until five
# minutes remain, then re-minted, and never for another App, installation or
# host; the cache is mode 600; the JWT never sits on curl's command line; an
# App with several installations is not guessed at; and the final call is gh
# with GH_TOKEN set.
# No network and no real App: curl and gh are stubs, the key is throwaway.
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/gh-agent"
pass=0; fail=0
T=$(mktemp -d); export T
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/conf"
export PATH="$T/bin:$PATH"
export AGENT_BOT_DIR="$T/conf" AGENT_BOT_CACHE="$T/run/agent-bot/token" AGENT_BOT_NOW=1800000000
unset AGENT_BOT_INSTALLATION_ID AGENT_BOT_API
K=424242/only/https://api.github.com   # the cache key for this App

ok()  { pass=$((pass+1)); }
bad() { fail=$((fail+1)); echo "FAIL: $1"; }
eq()  { [ "$1" = "$2" ] && ok || bad "$3 (want '$2', got '$1')"; }

openssl genrsa -out "$T/conf/key.pem" 2048 2>/dev/null
openssl rsa -in "$T/conf/key.pem" -pubout -out "$T/pub.pem" 2>/dev/null
echo 424242 > "$T/conf/app-id"

cat > "$T/bin/gh" <<'G'
#!/bin/sh
echo "GH_TOKEN=$GH_TOKEN" > "$T/gh.seen"; printf '%s\n' "$@" >> "$T/gh.seen"
G
cat > "$T/bin/curl" <<'G'
#!/bin/sh
# Stub of the GitHub API: records "<method> <url>", argv, and the headers on stdin.
echo "$*" >> "$T/curl.argv"
method=; url=; auth=
while [ $# -gt 0 ]; do
  case $1 in -X) method=$2; shift ;; -H) [ "$2" = @- ] && auth=$(cat); shift ;; http*) url=$1 ;; esac
  shift
done
echo "$method $url" >> "$T/curl.log"; echo "$auth" >> "$T/curl.auth"
case "$method $url" in
  "GET "*/app/installations) cat "$T/installations.json" ;;
  "POST "*/access_tokens) cat "$T/token.json" ;;
  *) exit 22 ;;
esac
G
chmod +x "$T/bin/gh" "$T/bin/curl"
echo '{"token":"ghs_minted","expires_at":"2027-01-15T08:00:00Z"}' > "$T/token.json"

# shellcheck source=gh-agent
. "$SCRIPT"
set +e

# --- JWT: three parts, right header and claims, signature verifies -----------
jwt=$(build_jwt 424242 "$T/conf/key.pem")
IFS=. read -r h c s <<<"$jwt"
dec() { python3 -c 'import base64,sys; s=sys.argv[1]; sys.stdout.buffer.write(base64.urlsafe_b64decode(s+"="*(-len(s)%4)))' "$1"; }
eq "$(dec "$h")" '{"alg":"RS256","typ":"JWT"}' "header"
eq "$(dec "$c")" '{"iat":1799999940,"exp":1800000540,"iss":"424242"}' "claims: iat now-60, exp now+540, iss app id"
case $jwt in *[+/=]*) bad "jwt is base64url without padding" ;; *) ok ;; esac
dec "$s" > "$T/sig.bin"
printf '%s.%s' "$h" "$c" | openssl dgst -sha256 -verify "$T/pub.pem" -signature "$T/sig.bin" >/dev/null 2>&1
eq "$?" 0 "signature verifies against the public key"
printf '%s.%s' "$h" "x$c" | openssl dgst -sha256 -verify "$T/pub.pem" -signature "$T/sig.bin" >/dev/null 2>&1
[ "$?" -ne 0 ] && ok || bad "signature does not verify a tampered payload"

# --- missing files: one line naming the file ---------------------------------
for f in key.pem app-id; do
  mv "$T/conf/$f" "$T/$f.away"
  out=$(bash "$SCRIPT" pr list 2>&1); rc=$?
  eq "$rc" 1 "missing $f exits 1"
  eq "$(wc -l <<<"$out")" 1 "missing $f is one line"
  case $out in *"$T/conf/$f"*"register the app first"*) ok ;; *) bad "missing $f names the file and says register first: $out" ;; esac
  mv "$T/$f.away" "$T/conf/$f"
done

# --- cache: reused while more than five minutes remain -----------------------
mint_token() { echo m >> "$T/mints"; echo "$((AGENT_BOT_NOW + 3600)) ghs_$(wc -l < "$T/mints" | tr -d ' ')"; }
rm -rf "$T/run"; : > "$T/mints"
eq "$(token)" ghs_1 "first call mints"
eq "$(token)" ghs_1 "second call reuses the cache"
eq "$(wc -l < "$T/mints" | tr -d ' ')" 1 "reuse did not mint again"
eq "$(stat -c %a "$T/run/agent-bot/token")" 600 "cache file is mode 600"
printf '%s %s ghs_old\n' $((AGENT_BOT_NOW + 301)) "$K" > "$AGENT_BOT_CACHE"
eq "$(token)" ghs_old "301s left is reused"
printf '%s %s ghs_old\n' $((AGENT_BOT_NOW + 300)) "$K" > "$AGENT_BOT_CACHE"
tok=$(token)
case $tok in ghs_old) bad "300s left is re-minted" ;; *) ok ;; esac
eq "$(cut -d' ' -f3 "$AGENT_BOT_CACHE")" "$tok" "re-minted token replaces the cache entry"
eq "$(cut -d' ' -f2 "$AGENT_BOT_CACHE")" "$K" "the cache entry names its App, installation and host"
for other in "1/only/https://api.github.com" "424242/9/https://api.github.com" "424242/only/https://ghe.example"; do
  printf '%s %s ghs_foreign\n' $((AGENT_BOT_NOW + 3600)) "$other" > "$AGENT_BOT_CACHE"
  [ "$(token)" != ghs_foreign ] && ok || bad "a token cached for $other is not used"
done
printf '%s ghs_oldformat\n' $((AGENT_BOT_NOW + 3600)) > "$AGENT_BOT_CACHE"
[ "$(token)" != ghs_oldformat ] && ok || bad "a cache line with no key is not used"
printf 'garbage\n' > "$AGENT_BOT_CACHE"
case $(token) in ghs_*) ok ;; *) bad "unreadable cache falls back to a mint" ;; esac

# --- cache trust: content is data, file and directory must be ours -----------
rm -f "$T/pwned"
printf 'a[$(touch %s/pwned)] %s ghs_evil\n' "$T" "$K" > "$AGENT_BOT_CACHE"; chmod 600 "$AGENT_BOT_CACHE"
tok=$(token)
[ ! -e "$T/pwned" ] && ok || bad "a non-numeric expiry is never evaluated"
[ "$tok" != ghs_evil ] && ok || bad "a non-numeric expiry is not trusted"
printf '%s %s ghs_loose\n' $((AGENT_BOT_NOW + 3600)) "$K" > "$AGENT_BOT_CACHE"; chmod 644 "$AGENT_BOT_CACHE"
[ "$(token)" != ghs_loose ] && ok || bad "a cache that is not mode 600 is ignored"
eq "$(stat -c %a "$AGENT_BOT_CACHE")" 600 "the re-mint rewrites it as mode 600"
chmod 755 "$T/run/agent-bot"; rm -f "$AGENT_BOT_CACHE"
out=$(token 2>&1)
case $out in *"not caching"*ghs_*) ok ;; *) bad "an open cache directory is reported and not used: $out" ;; esac
[ ! -e "$AGENT_BOT_CACHE" ] && ok || bad "nothing is written into an open cache directory"
chmod 700 "$T/run/agent-bot"
chmod 755 "$T/conf"; : > "$T/mints"
(unset AGENT_BOT_CACHE XDG_RUNTIME_DIR; token >/dev/null 2>&1; token >/dev/null 2>&1)
eq "$(wc -l < "$T/mints" | tr -d ' ')" 1 "without XDG_RUNTIME_DIR, a mode-755 conf dir still caches (in its own subdirectory)"
[ -f "$T/conf/cache/token" ] && ok || bad "without XDG_RUNTIME_DIR the cache sits under AGENT_BOT_DIR/cache, not /tmp"
echo 'x"y' > "$T/conf/app-id"
out=$(token 2>&1); rc=$?
eq "$rc" 1 "a non-numeric app-id is refused"
case $out in *"numeric App ID"*) ok ;; *) bad "a non-numeric app-id says so: $out" ;; esac
echo 424242 > "$T/conf/app-id"
eq "$(unset AGENT_BOT_CACHE; XDG_RUNTIME_DIR=/run/user/1 cache_file)" "/run/user/1/agent-bot/token" "XDG_RUNTIME_DIR is used when set"

# --- env that builds URLs is checked first -----------------------------------
: > "$T/curl.log"
for bad_api in http://api.github.com https://api.github.com/x https://a.com@evil.example "https://a.com?x=" "https://host:8080" ""; do
  [ -z "$bad_api" ] && continue
  (AGENT_BOT_API=$bad_api api GET /app/installations jwt) >/dev/null 2>&1
  [ "$?" -ne 0 ] && ok || bad "AGENT_BOT_API '$bad_api' is refused"
done
for bad_id in '1/../x' '1;2' ' 7' 'x'; do
  (AGENT_BOT_INSTALLATION_ID=$bad_id installation_id jwt) >/dev/null 2>&1
  [ "$?" -ne 0 ] && ok || bad "AGENT_BOT_INSTALLATION_ID '$bad_id' is refused"
done
[ ! -s "$T/curl.log" ] && ok || bad "a refused value never reaches curl"
(AGENT_BOT_API=https://api.example.com api GET /x jwt) >/dev/null 2>&1
grep -q "https://api.example.com/x" "$T/curl.log" 2>/dev/null; eq "$?" 0 "a well-formed AGENT_BOT_API is used"

# shellcheck source=gh-agent
. "$SCRIPT"; set +e   # re-source restores the real mint_token

# --- real mint against the stub API ------------------------------------------
echo '[{"id":777}]' > "$T/installations.json"
rm -rf "$T/run"; : > "$T/curl.log"; : > "$T/curl.auth"
eq "$(mint_token)" "1800000000 ghs_minted" "mint returns the expiry epoch of 2027-01-15T08:00:00Z and the token"
eq "$(sed 's|https://[^/]*||' "$T/curl.log" | tr '\n' ' ')" "GET /app/installations POST /app/installations/777/access_tokens " "single installation is used"
case $(head -1 "$T/curl.auth") in "Authorization: Bearer "*.*.*) ok ;; *) bad "installation lookup sends the JWT as bearer" ;; esac
jwt=$(head -1 "$T/curl.auth" | sed 's/^Authorization: Bearer //')
grep -q -F -e Bearer -e "$jwt" "$T/curl.argv" && bad "the JWT is never on curl's command line" || ok

echo '[]' > "$T/installations.json"
out=$(mint_token 2>&1); rc=$?
eq "$rc" 1 "an App with no installation fails"
case $out in *"0 installations"*AGENT_BOT_INSTALLATION_ID*) ok ;; *) bad "no installation says so: $out" ;; esac

echo '[{"id":1},{"id":2}]' > "$T/installations.json"
out=$(mint_token 2>&1); rc=$?
eq "$rc" 1 "two installations without a pick fails"
case $out in *AGENT_BOT_INSTALLATION_ID*) ok ;; *) bad "two installations says how to pick: $out" ;; esac
: > "$T/curl.log"
AGENT_BOT_INSTALLATION_ID=2 mint_token >/dev/null
eq "$(grep -c access_tokens "$T/curl.log")" 1 "picked installation mints"
case $(cat "$T/curl.log") in *"/app/installations/2/access_tokens"*) ok ;; *) bad "picked installation id is used" ;; esac

mv "$T/installations.json" "$T/installations.away"
out=$(mint_token 2>&1); rc=$?
eq "$rc" 1 "a failed installation lookup fails"
case $out in *"installation lookup failed"*) ok ;; *) bad "a failed lookup says so: $out" ;; esac
case $out in *Traceback*|*"0 installations"*) bad "a failed lookup does not fall through to the parser: $out" ;; *) ok ;; esac
mv "$T/installations.away" "$T/installations.json"

echo '[{"id":777}]' > "$T/installations.json"
for body in '' '{"message":"Bad credentials"}' '{"token":"ghs bad","expires_at":"2027-01-15T08:00:00Z"}'; do
  printf '%s' "$body" > "$T/token.json"
  out=$(mint_token 2>&1); rc=$?
  eq "$rc" 1 "an unusable access_tokens reply ($body) fails"
  case $out in *Traceback*) bad "an unusable access_tokens reply has no traceback: $out" ;; *"installation 777"*) ok ;; *) bad "an unusable access_tokens reply names the installation: $out" ;; esac
done
mv "$T/token.json" "$T/token.away"
out=$(mint_token 2>&1)
case $out in *"token mint failed for installation 777"*) ok ;; *) bad "a failed access_tokens call says so: $out" ;; esac
echo '{"token":"ghs_minted","expires_at":"2027-01-15T08:00:00Z"}' > "$T/token.json"

# --- end to end: gh runs with GH_TOKEN, args untouched -----------------------
echo '[{"id":777}]' > "$T/installations.json"; rm -rf "$T/run"
bash "$SCRIPT" pr comment 5 --body "hi" >/dev/null 2>&1
eq "$(sed -n 1p "$T/gh.seen")" "GH_TOKEN=ghs_minted" "gh runs with the minted token"
eq "$(sed -n '2,$p' "$T/gh.seen" | tr '\n' ' ')" "pr comment 5 --body hi " "gh gets the caller's args"
rm -rf "$T/run"
bash -x "$SCRIPT" pr list >"$T/xtrace" 2>&1
grep -q -e ghs_minted -e Bearer "$T/xtrace" && bad "bash -x never traces the token or the JWT" || ok
bash "$SCRIPT" --agent-help | grep -q "settings/installations" && ok || bad "usage names the undo"

echo "gh-agent: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
