#!/usr/bin/env bash
# Tests for npm-publish-auth.sh. Run: bash .claude/hooks/npm-publish-auth.test.sh
#
# The hook only decides -- nothing here runs npm -- so every case is a
# payload in and a decision out.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/npm-publish-auth.sh"
pass=0
fail=0

payload() {  # payload <command>
  jq -n --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'
}

decide() {  # decide <json> [hook path] -> the decision; "allow" when silent
  local out
  out=$(printf '%s' "$1" | bash "${2:-$HOOK}" 2>&1)
  [ -n "$out" ] || { echo allow; return; }
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null ||
    echo allow
}

allows() {  # allows <desc> <command>
  local d; d=$(decide "$(payload "$2")")
  if [ "$d" = allow ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL (want allow, got %s): %s\n  %s\n' "$d" "$1" "$2"; fi
}

denies() {  # denies <desc> <command>
  local d; d=$(decide "$(payload "$2")")
  if [ "$d" = deny ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL (want deny, got %s): %s\n  %s\n' "$d" "$1" "$2"; fi
}

# --- matches ---------------------------------------------------------------
denies "plain"                  'npm publish'
denies "with flags"             'npm publish --access public --tag next'
denies "compound"               'cd packages/foo && npm publish'
denies "nested sh -c"           "sh -c 'npm publish'"
denies "absolute path"          '/usr/local/bin/npm publish'
denies "after a semicolon"      'npm run build; npm publish'

# --- non-matches -----------------------------------------------------------
allows  "npm install"           'npm install'
allows  "a script named publish" 'npm run publish'
allows  "npm view"              'npm view left-pad dist-tags'
allows  "the wrapper itself"    'npm-publish-bg --access public'
allows  "prose in a commit"     'git commit -m "document that npm publish is wrapped"'
allows  "prose in a PR body"    "gh pr create --title x --body 'run npm publish by hand'"
allows  "a heredoc mentioning it" 'cat <<EOF > notes.md
then run npm publish
EOF'
allows  "another tool entirely" 'yarn publish'

# --- the deny reason names the replacement, not the URL --------------------
out=$(printf '%s' "$(payload 'npm publish')" | bash "$HOOK" 2>&1)
reason=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // ""')
if grep -q 'npm-publish-bg' <<<"$reason"; then pass=$((pass + 1))
else fail=$((fail + 1)); printf 'FAIL: deny reason should name npm-publish-bg\n  %s\n' "$reason"; fi

# --- non-Bash tools are none of its business -------------------------------
d=$(decide '{"tool_name":"Read","tool_input":{"file_path":"npm publish"}}')
if [ "$d" = allow ]; then pass=$((pass + 1))
else fail=$((fail + 1)); printf 'FAIL: non-Bash tool should be ignored, got %s\n' "$d"; fi

# --- fails open when the shared scanner is missing -------------------------
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$HOOK" "$TMP/"
d=$(decide "$(payload 'npm publish')" "$TMP/npm-publish-auth.sh")
if [ "$d" = allow ]; then pass=$((pass + 1))
else fail=$((fail + 1)); printf 'FAIL: a missing lib-shell-words.awk must fail open, got %s\n' "$d"; fi

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
