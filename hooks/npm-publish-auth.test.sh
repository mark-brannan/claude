#!/usr/bin/env bash
# Tests for npm-publish-auth.sh. Run: bash .claude/hooks/npm-publish-auth.test.sh
#
# The hook only decides -- nothing here runs npm -- so every case is a
# payload in and a decision out.
#
# The hook reads commands through the languette plugin's scanner. LANGUETTE_ROOT
# is the languette checkout to test against (ci.yml clones it); unset, the
# user-scope plugin install this machine has. Each case runs under a scratch
# HOME whose installed_plugins.json points there.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/npm-publish-auth.sh"
pass=0
fail=0

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
REAL_PLUGINS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json"
unset CLAUDE_CONFIG_DIR
export HOME="$TMP/home"; mkdir -p "$HOME/.claude/plugins"
ROOT=${LANGUETTE_ROOT:-$(jq -r '[.plugins | to_entries[] | select(.key | startswith("languette@")) | .value[]
                                 | select(.scope == "user") | .installPath][0] // empty' "$REAL_PLUGINS" 2>/dev/null)}
printf 'x' | python3 -I "$ROOT/languette/__main__.py" scan >/dev/null 2>&1 ||
  { echo "FAIL: no languette with \`scan\` at '$ROOT' (set LANGUETTE_ROOT to a languette checkout)"; exit 1; }
plugins() {  # plugins <install path>: the scratch HOME's languette install
  jq -n --arg p "$1" '{version:2,plugins:{"languette@languette":[{scope:"user",installPath:$p}]}}' \
    > "$HOME/.claude/plugins/installed_plugins.json"
}
plugins "$ROOT"

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
denies "dry run switched off"   'npm publish --dry-run=false'
denies "dry run in another segment" 'npm pack --dry-run && npm publish'

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
allows  "a dry run needs no auth" 'npm publish --dry-run'
allows  "a dry run, compound"   'cd packages/foo && npm publish --access public --dry-run'

# --- the deny reason names the replacement, not the URL --------------------
out=$(printf '%s' "$(payload 'npm publish')" | bash "$HOOK" 2>&1)
reason=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecisionReason // ""')
if grep -q 'npm-publish-bg' <<<"$reason"; then pass=$((pass + 1))
else fail=$((fail + 1)); printf 'FAIL: deny reason should name npm-publish-bg\n  %s\n' "$reason"; fi

# --- non-Bash tools are none of its business -------------------------------
d=$(decide '{"tool_name":"Read","tool_input":{"file_path":"npm publish"}}')
if [ "$d" = allow ]; then pass=$((pass + 1))
else fail=$((fail + 1)); printf 'FAIL: non-Bash tool should be ignored, got %s\n' "$d"; fi

# --- fails open when languette's scanner is missing or can't say ----------
fails_open() {  # fails_open <desc>: under whatever plugins() set last
  local d; d=$(decide "$(payload 'npm publish')")
  if [ "$d" = allow ]; then pass=$((pass + 1))
  else fail=$((fail + 1)); printf 'FAIL: %s must fail open, got %s\n' "$1" "$d"; fi
}
rm "$HOME/.claude/plugins/installed_plugins.json"
fails_open "no installed_plugins.json"
plugins "$TMP/nowhere"
fails_open "an install path that is gone"
mkdir -p "$TMP/old/languette"
printf 'import sys\nsys.exit(2)\n' > "$TMP/old/languette/__main__.py"
plugins "$TMP/old"
fails_open "a languette with no scan subcommand"
plugins "$ROOT"

printf '\n%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
