#!/usr/bin/env bash
# PreToolUse hook: a Bash call running `npm publish` directly is denied and
# pointed at `npm-publish-bg`, which does the same publish but pushes the
# browser-2FA approval URL to Solace out of band.
#
# Why: her npm account uses browser passkey 2FA (see ~/.claude/rules/code.md,
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
# Convenience, not a gate: missing jq/awk/the shared scanner, or a payload
# that won't parse, exits 0 and the publish proceeds exactly as before.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
LIB="$HERE/lib-shell-words.awk"

command -v jq  >/dev/null 2>&1 || exit 0
command -v awk >/dev/null 2>&1 || exit 0
[ -r "$LIB" ] || exit 0

input=$(cat) || exit 0
[ "$(printf '%s' "$input" | jq -r '.tool_name // ""' 2>/dev/null)" = Bash ] || exit 0

cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -n "$cmd" ] || exit 0

# Structural match, not a substring test: a segment -- top level, or nested
# inside a quoted `sh -c`/`eval` body -- whose command word is npm and whose
# first non-flag argument is `publish`. The shared scanner is the one whose
# false positives the no-*.sh family already fixed, so a commit message or
# PR body that merely *mentions* "npm publish" does not match. `npm-publish-bg`
# is a different command word and never matches either.
#
# `publish` is looked for as the first non-flag argument, so a global option
# that takes a separate value first (`npm --loglevel warn publish`) is not
# matched -- resolving that would need a table of which npm flags consume the
# next word. Fail open is the right side to miss on: the publish then runs
# as it did before this hook existed.
match=$(printf '%s\n' "$cmd" | awk "$(cat "$LIB")"'
function is_publish(a, b,   i) {
  for (i = a; i <= b; i++) {
    if (k[i] != "w") return 0
    if (w[i] ~ /^-/) continue
    return w[i] == "publish"
  }
  return 0
}
function segment(a, b, nested,   c) {
  c = cmd_index(w, k, a, b, "(^|/)npm$", nested, "")
  if (c && is_publish(c + 1, b)) { print "MATCH"; exit }
}
{ buf = buf $0 "\n" }
END {
  buf = strip_heredocs(buf)
  nt = texts_of(buf, texts, nested)
  for (x = 1; x <= nt; x++) {
    n = scan(texts[x], w, k, q)
    a = 1
    for (i = 1; i <= n + 1; i++) {
      if (i <= n && k[i] != ";") continue
      if (a < i) segment(a, i - 1, nested[x])
      a = i + 1
    }
  }
}' 2>/dev/null)
[ "$match" = MATCH ] || exit 0

jq -cn --arg r "Blocked by ~/.claude/hooks/npm-publish-auth.sh: run \`npm-publish-bg\` instead of \`npm publish\` -- same arguments, same directory. Solace's npm account uses browser passkey 2FA, and the approval URL npm prints is redacted from your tool result before you see it, so a plain publish stalls on an approval nobody was told about. npm-publish-bg runs the publish detached and pushes that URL to her directly (notification and terminal); you will never see it, by design, so don't ask her for it or try to print it. It returns a pid and a logfile -- tail the log, and confirm with \`npm view <pkg> dist-tags\`. See ~/.claude/rules/code.md, 'Publishing'." \
  '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
exit 0
