#!/bin/sh
# Puts the "PR ownership" section of ~/.claude/rules/code.md in front of the
# session the first time it touches a pull request.
#
# Why: code.md is a path-globbed rule. It loads when a session reads or edits
# a source file, and not otherwise -- so a session that opens with `gh pr
# view`, reads the review comments and starts answering them has never seen
# the section that says answer *and resolve* the threads and never hand over
# red. The one-line pointer in ~/.claude/CLAUDE.md was the
# stopgap; it relies on the model noticing it, which is the failure it was
# meant to fix. This hook is the mechanical version: the text arrives because
# a PR-shaped tool call happened, not because anyone remembered.
#
# Also, on every matching call, records the PR touched (see below) so
# pr-threads-gate.sh can block the Stop while review threads are still open.
#
# Fires once per session, on the first matching call:
#   - Bash: `gh pr ...`, or `gh api ...` naming pulls / graphql / reviewThreads
#   - Bash: `mergify stack push/checkout/sync`, `mergify queue ...`, or
#     `mergify merge ...` -- the mergify CLI plugin creates and merges PRs
#     without ever calling gh, so a session working a PR only through it used
#     to leave the record empty and the Stop gate silently found nothing.
#     2026-09-08.
#   - MCP:  any GitHub tool whose name mentions a pull request or a review
# The section is read live from code.md, so there is one source of truth and
# nothing here to keep in sync. If the file or the heading is missing, say so
# in the injected note rather than exit quietly -- a convenience hook that
# does nothing looks identical to one that never ran.
#
# CONVENIENCE: never denies, always exits 0. A missing jq or an odd payload
# must not stop a `gh` command.
#
# The repo/number extraction works clause-by-clause on a compound Bash call
# (split on ; & |), not on the command as one string. 2026-09-08: pairing the
# first repo match and the first number match found *anywhere* in the string
# let a call that named an issue and a PR in one line (or two PRs) fabricate
# a repo#number neither clause actually queried -- the Stop gate then blocked
# on a PR that never existed.
#
# dotfiles#224: a "repo" line also carries a third field, read or work. A
# bare `gh pr view/checks/diff/list`, or a `gh api` call that isn't a mutating
# HTTP method (-X/--method POST|PUT|PATCH|DELETE) or a graphql `mutation`, is
# a read -- it goes in the record (so the reminder text still fires, and the
# call is not invisible) but pr-threads-gate.sh does not gate the Stop on it.
# Everything else naming `gh pr` (create, edit, comment, merge, ready,
# review, close, reopen, ... -- an unrecognized subcommand defaults to work,
# same fail-closed instinct as the gate itself) is work, and so is
# `gh-resolve-thread` (the resolveReviewThread wrapper). Reading someone
# else's PR for evidence must not put its threads on this session's Stop; a
# session that actually worked a PR -- created it, commented, merged it,
# resolved a thread on it, or pushed to it -- still cannot leave it red.
# `cwd` lines are unaffected: they resolve to the PR of the branch this
# session's worktree holds, which is gate-worthy on identity alone (rule a of
# #224), whatever kind of call produced the entry.
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
    # The mergify half is restricted to a real command position (start of
    # string, or after a separator: ; & | ( or a backtick) so "echo mergify
    # merge" or "true # mergify merge" -- mergify named but not run -- don't
    # falsely record a cwd and trip the Stop gate on an unrelated PR.
    printf '%s' "$cmd" | grep -Eq \
      '(^|[^A-Za-z0-9_./-])gh[[:space:]]+(pr([[:space:]]|$)|api[[:space:]].*(pulls|graphql|reviewThreads))|(^|[^A-Za-z0-9_./-])gh-resolve-thread([[:space:]]|$)|(^|[;&|(`])[[:space:]]*mergify[[:space:]]+(stack[[:space:]]+(push|checkout|sync)([[:space:]]|$)|(queue|merge)([[:space:]]|$))' \
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
      cwd=$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null)
      if printf '%s' "$cmd" | grep -Eq '(^|[;&|(`])[[:space:]]*mergify[[:space:]]'; then
        # mergify never names owner/repo/number on the command line -- it
        # infers the PR from the current branch, so cwd is the only handle.
        # Best-effort like the record writes below: a full disk or a race on
        # the tmp file must not fail the mergify command that triggered this.
        [ -n "$cwd" ] && { printf 'cwd\t%s\n' "$cwd" >> "$record" 2>/dev/null || :; }
      else
        # A single Bash call is often several gh invocations joined by ; && ||
        # | or a newline (a subagent checking issue #73 and PR #80 in one
        # command is exactly this shape). Extracting repo and number
        # independently with `head -1` over the *whole* string pairs the
        # first repo found with the first number found even when they came
        # from different clauses -- fabricating a repo#number this call never
        # actually queried. So: split into clauses first, and only record a
        # pair pulled from the *same* clause. A clause naming `issues/NNN`
        # and not `pulls`/`pull/` never contributes a number, so an issue
        # reference can no longer borrow a PR's repo (or vice versa).
        # dotfiles#224 follow-up: a clause that names the *same* repo#number
        # as one already locked in must still be inspected for kind -- a
        # read-then-work pair on one PR in a single compound command (`gh pr
        # diff 42 -R o/r; gh pr comment 42 -R o/r --body ...`) must record
        # work, not read. So repo+number lock in on the first clause that
        # supplies them (never fabricated across clauses -- see above), but
        # the loop keeps scanning every remaining clause; only a clause
        # matching that same pair can change `kind`, and only upward
        # (read -> work, never work -> read).
        repo=""; num=""; kind=""
        clauses=$(printf '%s' "$cmd" | tr ';&|' '\n')
        old_ifs=$IFS; IFS='
'
        for clause in $clauses; do
          IFS=$old_ifs
          c_repo=$(printf '%s' "$clause" | grep -Eo -- '(^|[[:space:]])(-R|--repo)[[:space:]=]+[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' | head -1 | sed 's/.*[[:space:]=]//')
          c_num=$(printf '%s' "$clause" | grep -Eo 'gh[[:space:]]+pr[[:space:]]+[a-z-]+[[:space:]]+[0-9]+' | head -1 | grep -Eo '[0-9]+$')
          [ -z "$c_num" ] && c_num=$(printf '%s' "$clause" | grep -Eo 'pulls/[0-9]+' | head -1 | grep -Eo '[0-9]+$')
          [ -z "$c_num" ] && c_num=$(printf '%s' "$clause" | grep -Eo 'pull/[0-9]+' | head -1 | grep -Eo '[0-9]+$')
          [ -z "$c_repo" ] && c_repo=$(printf '%s' "$clause" | grep -Eo '(repos|github\.com)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls?/' | head -1 | sed 's#^[^/]*/##; s#/pulls\?/$##; s#/pull/$##')
          if [ -n "$c_repo" ] && [ -n "$c_num" ] && { [ -z "$repo" ] || { [ "$c_repo" = "$repo" ] && [ "$c_num" = "$num" ]; }; }; then
            # dotfiles#224: read vs work, decided from the same clause that
            # supplied the repo+number. `gh pr view/checks/diff/list` is a
            # pure read; any other `gh pr` subcommand (create, edit, comment,
            # merge, ready, review, or one this hook doesn't know about) is
            # work by default -- fail closed, like the gate itself. A `gh
            # api` call (the only other source of a repo+number pair) is work
            # only if it names a mutating HTTP method or a graphql mutation.
            if printf '%s' "$clause" | grep -Eq '(^|[^A-Za-z0-9_./-])gh[[:space:]]+pr[[:space:]]+(view|checks|diff|list)([[:space:]]|$)'; then
              c_kind="read"
            elif printf '%s' "$clause" | grep -Eq '(^|[^A-Za-z0-9_./-])gh[[:space:]]+pr([[:space:]]|$)'; then
              c_kind="work"
            elif printf '%s' "$clause" | grep -Eiq -- '(^|[[:space:]])(-X|--method)[[:space:]=]+(POST|PUT|PATCH|DELETE)' || printf '%s' "$clause" | grep -Eiq 'mutation[[:space:]]*\('; then
              c_kind="work"
            else
              c_kind="read"
            fi
            if [ -z "$repo" ]; then
              repo=$c_repo; num=$c_num; kind=$c_kind
            elif [ "$c_kind" = "work" ]; then
              kind="work"
            fi
          fi
          IFS='
'
        done
        IFS=$old_ifs
        if [ -n "$repo" ] && [ -n "$num" ]; then printf 'repo\t%s\t%s\t%s\n' "$repo" "$num" "$kind" >> "$record" 2>/dev/null || :
        elif [ -n "$cwd" ]; then printf 'cwd\t%s\n' "$cwd" >> "$record" 2>/dev/null || :
        fi
      fi
      ;;
    *)
      # dotfiles#224: same read/work split as the Bash case, by name -- an
      # MCP tool named ...read/...get/...list/...search is a read; anything
      # else (create, merge, comment, review, resolve, ...) is work.
      kind="work"
      printf '%s' "$tool" | grep -Eqi '(^|_)(read|get|list|search)($|_)' && kind="read"
      line=$(printf '%s' "$payload" | jq -r --arg kind "$kind" '.tool_input | select(.owner and .repo and (.pullNumber // .pull_number // .number)) | "repo\t\(.owner)/\(.repo)\t\(.pullNumber // .pull_number // .number)\t\($kind)"' 2>/dev/null)
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
[ -f "$rules" ] || note "pr-ownership-context: $rules is missing, so the PR ownership rules could not be injected. Run dotsync (or cloud-session-setup.sh); until then, treat review threads as yours to reply to AND resolve, and never hand over red."

section=$(awk '/^## PR ownership/{p=1} p && /^## / && !/^## PR ownership/{exit} p' "$rules")
[ -n "$section" ] || note "pr-ownership-context: no '## PR ownership' heading in $rules, so the rules could not be injected. Until that is fixed: review threads are yours to reply to AND resolve, and never hand over red."

note "PR work detected. These are the PR ownership rules from $rules, injected once per session by pr-ownership-context.sh because path-globbed rules do not load on a gh call. They apply to this PR from here on.

$section"
