#!/usr/bin/env bash
# Tests for gh-agent. Run: bash bin/gh-agent.test.sh
#
# What matters: the JWT's header and claims decode to what GitHub requires and
# its signature verifies against the key's public half; a missing key or app id
# stops with one line naming the file; a cached token is reused until five
# minutes remain, then re-minted; the cache is mode 600; an App with several
# installations is not guessed at; and the final call is gh with GH_TOKEN set.
# No network and no real App: curl and gh are stubs, the key is throwaway.
set -uo pipefail

SCRIPT="$(cd "$(dirname "$0")" && pwd)/gh-agent"
pass=0; fail=0
T=$(mktemp -d); export T
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/conf"
export PATH="$T/bin:$PATH"
export AGENT_BOT_DIR="$T/conf" AGENT_BOT_CACHE="$T/run/agent-bot/token" AGENT_BOT_NOW=1800000000
unset AGENT_BOT_INSTALLATION_ID

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
# Stub of the GitHub API: records "<method> <url>" and the bearer header.
method=; url=; auth=
while [ $# -gt 0 ]; do
  case $1 in -X) method=$2; shift ;; -H) case $2 in Authorization*) auth=$2 ;; esac; shift ;; http*) url=$1 ;; esac
  shift
done
echo "$method $url" >> "$T/curl.log"; echo "$auth" >> "$T/curl.auth"
case "$method $url" in
  "GET "*/app/installations) cat "$T/installations.json" ;;
  "POST "*/access_tokens) echo '{"token":"ghs_minted","expires_at":"2027-01-15T08:00:00Z"}' ;;
  *) exit 22 ;;
esac
G
chmod +x "$T/bin/gh" "$T/bin/curl"

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
printf '%s ghs_old\n' $((AGENT_BOT_NOW + 301)) > "$AGENT_BOT_CACHE"
eq "$(token)" ghs_old "301s left is reused"
printf '%s ghs_old\n' $((AGENT_BOT_NOW + 300)) > "$AGENT_BOT_CACHE"
tok=$(token)
case $tok in ghs_old) bad "300s left is re-minted" ;; *) ok ;; esac
eq "$(cut -d' ' -f2 "$AGENT_BOT_CACHE")" "$tok" "re-minted token replaces the cache entry"
printf 'garbage\n' > "$AGENT_BOT_CACHE"
case $(token) in ghs_*) ok ;; *) bad "unreadable cache falls back to a mint" ;; esac
# shellcheck source=gh-agent
. "$SCRIPT"; set +e   # re-source restores the real mint_token

# --- real mint against the stub API ------------------------------------------
echo '[{"id":777}]' > "$T/installations.json"
rm -rf "$T/run"; : > "$T/curl.log"
eq "$(mint_token)" "$(( $(python3 -c 'import calendar,time;print(calendar.timegm(time.strptime("2027-01-15T08:00:00Z","%Y-%m-%dT%H:%M:%SZ")))') )) ghs_minted" "mint returns expiry and token"
eq "$(sed 's|https://[^/]*||' "$T/curl.log" | tr '\n' ' ')" "GET /app/installations POST /app/installations/777/access_tokens " "single installation is used"
case $(head -1 "$T/curl.auth") in "Authorization: Bearer "*.*.*) ok ;; *) bad "installation lookup sends the JWT as bearer" ;; esac

echo '[{"id":1},{"id":2}]' > "$T/installations.json"
out=$(mint_token 2>&1); rc=$?
eq "$rc" 1 "two installations without a pick fails"
case $out in *AGENT_BOT_INSTALLATION_ID*) ok ;; *) bad "two installations says how to pick: $out" ;; esac
: > "$T/curl.log"
AGENT_BOT_INSTALLATION_ID=2 mint_token >/dev/null
eq "$(grep -c access_tokens "$T/curl.log")" 1 "picked installation mints"
case $(cat "$T/curl.log") in *"/app/installations/2/access_tokens"*) ok ;; *) bad "picked installation id is used" ;; esac

# --- end to end: gh runs with GH_TOKEN, args untouched -----------------------
echo '[{"id":777}]' > "$T/installations.json"; rm -rf "$T/run"
bash "$SCRIPT" pr comment 5 --body "hi" >/dev/null 2>&1
eq "$(sed -n 1p "$T/gh.seen")" "GH_TOKEN=ghs_minted" "gh runs with the minted token"
eq "$(sed -n '2,$p' "$T/gh.seen" | tr '\n' ' ')" "pr comment 5 --body hi " "gh gets the caller's args"
bash "$SCRIPT" --agent-help | grep -q "settings/installations" && ok || bad "usage names the undo"

echo "gh-agent: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
