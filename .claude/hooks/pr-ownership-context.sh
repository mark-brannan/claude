#!/bin/sh
# Puts the "PR ownership" section of ~/.claude/rules/code.md in front of the
# session the first time it touches a pull request.
#
# Why: code.md is a path-globbed rule. It loads when a session reads or edits
# a source file, and not otherwise -- so a session that opens with `gh pr
# view`, reads the review comments and starts answering them has never seen
# the section that says answer *and resolve* the threads, never open a draft,
# never hand over red. The one-line pointer in ~/.claude/CLAUDE.md was the
# stopgap; it relies on the model noticing it, which is the failure it was
# meant to fix. This hook is the mechanical version: the text arrives because
# a PR-shaped tool call happened, not because anyone remembered.
#
# Also, on every matching call, records the PR touched (see below) so
# pr-threads-gate.sh can block the Stop while review threads are still open.
#
# Fires once per session, on the first matching call:
#   - Bash: `gh pr ...`, or `gh api ...` naming pulls / graphql / reviewThreads
#   - MCP:  any GitHub tool whose name mentions a pull request or a review
# The section is read live from code.md, so there is one source of truth and
# nothing here to keep in sync. If the file or the heading is missing, say so
# in the injected note rather than exit quietly -- a convenience hook that
# does nothing looks identical to one that never ran.
#
# CONVENIENCE: never denies, always exits 0. A missing jq or an odd payload
# must not stop a `gh` command.
set -u

# jq does the JSON encoding: the section is arbitrary markdown and a hand-rolled
# sed escape misses control characters (a stray \r from a CRLF paste would make
# the output invalid JSON and the injection would vanish without a trace).
json_str() { printf '%s' "$1" | jq -Rs .; }
note() { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","additionalContext":%s}}\n' "$(json_str "$1")"; exit 0; }

command -v jq >/dev/null 2>&1 || exit 0
payload=$(cat) || exit 0
tool=$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null) || exit 0
[ -n "$tool" ] || exit 0

case "$tool" in
  Bash)
    cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // empty' 2>/dev/null) || exit 0
    printf '%s' "$cmd" | grep -Eq \
      '(^|[^A-Za-z0-9_./-])gh[[:space:]]+(pr([[:space:]]|$)|api[[:space:]].*(pulls|graphql|reviewThreads))' \
      || exit 0
    ;;
  mcp__*github*__*)
    printf '%s' "$tool" | grep -Eqi 'pull_request|review' || exit 0
    ;;
  *) exit 0 ;;
esac

# Record which PR this call touched, every call, so pr-threads-gate.sh (Stop)
# can re-fetch its review threads before the session hands it back. The
# reminder below is text and fires once; the record is what the gate runs on.
# Lines are "repo<TAB>owner/name<TAB>number" when the call names a PR, else
# "cwd<TAB>path" and the gate asks gh which PR the branch there belongs to.
sid=$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null)
if [ -n "$sid" ]; then
  tag=$(printf '%s' "$sid" | tr -c 'A-Za-z0-9_-' '_')
  record="${TMPDIR:-/tmp}/claude-pr-threads.$tag"
  case "$tool" in
    Bash)
      repo=$(printf '%s' "$cmd" | grep -Eo -- '(^|[[:space:]])(-R|--repo)[[:space:]=]+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' | head -1 | sed 's/.*[[:space:]=]//')
      num=$(printf '%s' "$cmd" | grep -Eo 'gh[[:space:]]+pr[[:space:]]+[a-z-]+[[:space:]]+[0-9]+' | head -1 | grep -Eo '[0-9]+$')
      [ -z "$num" ] && num=$(printf '%s' "$cmd" | grep -Eo 'pulls/[0-9]+' | head -1 | grep -Eo '[0-9]+$')
      [ -z "$num" ] && num=$(printf '%s' "$cmd" | grep -Eo 'pull/[0-9]+' | head -1 | grep -Eo '[0-9]+$')
      [ -z "$repo" ] && repo=$(printf '%s' "$cmd" | grep -Eo '(repos|github\.com)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls?/' | head -1 | sed 's#^[^/]*/##; s#/pulls\?/$##; s#/pull/$##')
      cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
      if [ -n "$repo" ] && [ -n "$num" ]; then printf 'repo\t%s\t%s\n' "$repo" "$num" >> "$record" 2>/dev/null || :
      elif [ -n "$cwd" ]; then printf 'cwd\t%s\n' "$cwd" >> "$record" 2>/dev/null || :
      fi
      ;;
    *)
      line=$(printf '%s' "$payload" | jq -r '.tool_input | select(.owner and .repo and (.pullNumber // .pull_number // .number)) | "repo\t\(.owner)/\(.repo)\t\(.pullNumber // .pull_number // .number)"' 2>/dev/null)
      [ -n "$line" ] && { printf '%s\n' "$line" >> "$record" 2>/dev/null || :; }
      ;;
  esac
  # Once per session for the text. The marker lives in tmp on purpose: it should
  # die with the machine (cloud VM) or the reboot, and must never land in a
  # state repo.
  marker="${TMPDIR:-/tmp}/claude-pr-ownership-context.$tag"
  [ -e "$marker" ] && exit 0
  : > "$marker" 2>/dev/null || :
fi

rules="$HOME/.claude/rules/code.md"
[ -f "$rules" ] || note "pr-ownership-context: $rules is missing, so the PR ownership rules could not be injected. Run dotsync (or cloud-session-setup.sh); until then, treat review threads as yours to reply to AND resolve, never open a draft, never hand over red."

section=$(awk '/^## PR ownership/{p=1} p && /^## / && !/^## PR ownership/{exit} p' "$rules")
[ -n "$section" ] || note "pr-ownership-context: no '## PR ownership' heading in $rules, so the rules could not be injected. Until that is fixed: review threads are yours to reply to AND resolve, never open a draft, never hand over red."

note "PR work detected. These are the PR ownership rules from $rules, injected once per session by pr-ownership-context.sh because path-globbed rules do not load on a gh call. They apply to this PR from here on.

$section"
