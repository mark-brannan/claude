#!/usr/bin/env bash
# Tests for github-mcp-headers. Run: bash bin/github-mcp-headers.test.sh
# What matters: whatever shape the env file's token line takes, the output is
# one line of valid JSON carrying the bare token, or a clear error and no output.
set -uo pipefail
H="$(cd "$(dirname "$0")" && pwd)/github-mcp-headers"
pass=0; fail=0
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.config/secrets"
F="$T/.config/secrets/github-token.env"
ok() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }
run() { HOME="$T" bash "$H" 2>/dev/null; }
want='{"Authorization":"Bearer ghp_abc123"}'

printf 'GITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\n' > "$F"; ok 'plain value' "$want" "$(run)"
printf 'GITHUB_PERSONAL_ACCESS_TOKEN="ghp_abc123"\n' > "$F"; ok 'double-quoted value' "$want" "$(run)"
printf "GITHUB_PERSONAL_ACCESS_TOKEN='ghp_abc123'\n" > "$F"; ok 'single-quoted value' "$want" "$(run)"
printf 'export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\n' > "$F"; ok 'export prefix' "$want" "$(run)"
printf 'GITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\r\n' > "$F"; ok 'CRLF line ending' "$want" "$(run)"
printf 'OTHER=x\r\nGITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\r\n' > "$F"; ok 'CRLF on a line before the token line' "$want" "$(run)"
printf 'OTHER=x\nGITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\nGITHUB_PERSONAL_ACCESS_TOKEN=ghp_second\n' > "$F"
ok 'two matching lines give the first, on one line' "$want" "$(run)"
ok 'the output is one line' 1 "$(HOME="$T" bash "$H" 2>/dev/null | wc -l)"
if command -v python3 >/dev/null; then
  ok 'the output parses as JSON' ghp_abc123 "$(run | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["Authorization"].split()[1])')"
fi

printf 'OTHER=x\n' > "$F"; HOME="$T" bash "$H" >"$T/out" 2>"$T/err"; rc=$?
ok 'no token line fails' 1 "$rc"; ok 'no token line prints nothing' 0 "$(wc -c < "$T/out")"
ok 'no token line says so' 1 "$(grep -c 'no token in' "$T/err")"
printf 'GITHUB_PERSONAL_ACCESS_TOKEN=\n' > "$F"; HOME="$T" bash "$H" >/dev/null 2>&1; ok 'empty value fails' 1 $?
rm -f "$F"; HOME="$T" bash "$H" >"$T/out" 2>"$T/err"; rc=$?
ok 'missing file fails' 1 "$rc"; ok 'missing file says so plainly' 1 "$(grep -c 'no readable' "$T/err")"

# The agent App: its token when its secret is there, loud failure when the mint fails.
mkdir -p "$T/bin"; cp "$H" "$T/bin/github-mcp-headers"; A="$T/bin/github-mcp-headers"
printf '#!/bin/sh\n[ "$*" = "auth token" ] || exit 2\n[ -f "%s/mint-fails" ] && { echo "gh-agent: token mint failed" >&2; exit 1; }\necho ghs_app.tok-1\n' "$T" > "$T/bin/gh-agent"
chmod +x "$T/bin/gh-agent"; printf 'GITHUB_PERSONAL_ACCESS_TOKEN=ghp_abc123\n' > "$F"
: > "$T/.config/secrets/agent-bot.env"
ok 'the App secret present: the App token' '{"Authorization":"Bearer ghs_app.tok-1"}' "$(HOME="$T" bash "$A" 2>/dev/null)"
ok 'AGENT_BOT_OFF=1 keeps the PAT' "$want" "$(HOME="$T" AGENT_BOT_OFF=1 bash "$A" 2>/dev/null)"
: > "$T/mint-fails"; HOME="$T" bash "$A" >"$T/out" 2>"$T/err"; rc=$?
ok 'a failed mint fails' 1 "$rc"; ok 'a failed mint prints no header, not the PAT' 0 "$(wc -c < "$T/out")"
ok 'a failed mint says so' 1 "$(grep -c "agent App's token mint failed" "$T/err")"
rm -f "$T/.config/secrets/agent-bot.env"; ok 'no App secret: the PAT' "$want" "$(HOME="$T" bash "$A" 2>/dev/null)"

printf '%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
