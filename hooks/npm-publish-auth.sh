#!/usr/bin/env bash
# PreToolUse hook: a Bash call running `npm publish` directly is denied and
# pointed at `npm-publish-bg`, which does the same publish but pushes the
# browser-2FA approval URL to the user out of band.
#
# Why: the user's npm account uses browser passkey 2FA (see ~/.claude/rules/code.md,
# "Publishing"). `npm publish` prints the approval URL mid-run, and that URL
# is one of the strings the harness redacts from a Bash tool result before it
# reaches Claude -- so a plain `npm publish` leaves Claude unable to read the
# URL or relay it, and the publish sits waiting on an approval nobody was
# told about. `npm-publish-bg` routes the URL to a notification and the
# terminal instead. The rule for that lives in code.md; this hook is its
# enforcement, because a rule that competes with "just run the command" loses
# often enough to matter.
#
# This hook only ever decides. It does not run the publish itself: a hook
# that executed the command it was handed would bypass every other
# PreToolUse guard in the chain (their deny would be advice about something
# already done) and would run in the hook's working directory rather than
# the tool's. Denying and letting the model re-issue one command through the
# normal Bash path keeps both properties.
#
# Convenience, not a gate: missing jq, python3 or the languette plugin, a
# languette too old to have `scan`, a command its scanner refuses, or a
# payload that won't parse, exits 0 and the publish proceeds exactly as
# before.
set -uo pipefail

command -v jq      >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
# The languette plugin's scanner, at the user-scope install Claude Code
# records in installed_plugins.json (a hook in settings.json gets no
# CLAUDE_PLUGIN_ROOT; that is set only for the plugin's own hooks).
ROOT=$(jq -r '[.plugins | to_entries[] | select(.key | startswith("languette@")) | .value[]
               | select(.scope == "user") | .installPath][0] // empty' \
       "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugins/installed_plugins.json" 2>/dev/null)
SCAN="$ROOT/languette/__main__.py"
[ -n "$ROOT" ] && [ -r "$SCAN" ] || exit 0

input=$(cat) || exit 0
[ "$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null)" = Bash ] || exit 0

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -n "$cmd" ] || exit 0

# Structural match, not a substring test: a segment -- top level, or nested
# inside a quoted `sh -c`/`eval` body -- whose command word is npm and whose
# first non-flag argument is `publish`. languette's scanner is the one the
# plugin's guards read commands with, so a commit message or PR body that
# merely *mentions* "npm publish" does not match. `npm-publish-bg` is a
# different command word and never matches either.
#
# `publish` is looked for as the first non-flag argument, so a global option
# that takes a separate value first (`npm --loglevel warn publish`) is not
# matched -- resolving that would need a table of which npm flags consume the
# next word. Fail open is the right side to miss on: the publish then runs
# as it did before this hook existed.
#
# `--dry-run` is let through: it packs and reports without contacting the
# registry's auth, so there is no URL to lose, and /npm-first-publish has the
# agent run it as a precondition.
#
# Each line from the scanner is one npm segment, its words from npm on:
# {"nested":false,"words":["w:npm","w:publish","w:--tag","w:next"]}, where
# "q:" marks a quoted word holding whitespace.
segs=$(printf '%s' "$cmd" | python3 -I "$SCAN" scan --command '(^|/)npm$' 2>/dev/null) || exit 0
match=$(printf '%s' "$segs" | jq -rs 'any(.[]; .words[1:] as $a
  | ([$a[] | select(startswith("w:-") | not)][0] == "w:publish")
    and (any($a[]; . == "w:--dry-run" or . == "w:--dry-run=true") | not))
  | if . then "MATCH" else empty end' 2>/dev/null)
[ "$match" = MATCH ] || exit 0

jq -cn --arg r "Blocked by ~/.claude/hooks/npm-publish-auth.sh: run \`npm-publish-bg\` instead of \`npm publish\` -- same arguments, same directory. The user's npm account uses browser passkey 2FA, and the approval URL npm prints is redacted from your tool result before you see it, so a plain publish stalls on an approval nobody was told about. npm-publish-bg runs the publish detached and pushes that URL to the user directly (browser, notification, terminal); you will never see it, by design, so don't ask for it or try to print it. It returns a pid and a logfile -- tail the log, and confirm with \`npm view <pkg> dist-tags\`. See ~/.claude/rules/code.md, 'Publishing'." \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0
