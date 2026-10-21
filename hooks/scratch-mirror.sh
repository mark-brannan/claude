#!/usr/bin/env bash
# PostToolUse Edit|Write|MultiEdit: when a readable document (.md, .mmd,
# .svg, .html) is written in the state repo from a session rooted in another
# repo, copy it flat into that repo's git-ignored .scratch/ and tell the
# model to link the copy. The app's file pane opens only files inside the
# session's own folder, and follows no symlinks, so a link into the state
# repo shows the user nothing.
#
# Silent on the quiet path: every line printed here is charged to the session.
set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/lib-state.sh"

command -v jq >/dev/null 2>&1 || exit 0
input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null) || exit 0
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null) || exit 0
case "$file" in *.md|*.mmd|*.svg|*.html) ;; *) exit 0 ;; esac
[ -f "$file" ] && [ -n "$cwd" ] || exit 0

sr=$(state_repo 2>/dev/null) || exit 0
sr=$(realpath "$sr"); file=$(realpath "$file")
case "$file" in "$sr"/*) ;; *) exit 0 ;; esac

top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || exit 0
[ "$(realpath "$top")" = "$sr" ] && exit 0

# Flat, by file name: the state repo's tree means nothing to the reader.
# A repo that brings its own .scratch (a symlink, or tracked files) is not
# ours to write into: a copy there could land outside the repo or be committed.
dir="$top/.scratch"; dest="$dir/$(basename "$file")"
{ [ -L "$dir" ] || [ -L "$dest" ]; } && exit 0
[ -n "$(git -C "$top" ls-files -- .scratch)" ] && exit 0
mkdir -p "$dir" || exit 0
excl="$(git -C "$top" rev-parse --path-format=absolute --git-common-dir)/info/exclude"
grep -qx '.scratch/' "$excl" 2>/dev/null || { mkdir -p "${excl%/*}"; echo '.scratch/' >> "$excl"; }
[ -e "$dir/.gitignore" ] || printf '*\n' > "$dir/.gitignore"
git -C "$top" check-ignore -q "$dest" || exit 0
cp --remove-destination "$file" "$dest" || exit 0

rel=$(realpath --relative-to="$cwd" "$dest")
jq -n --arg ctx "Copied for the user to open: $rel. Link the user to [$(basename "$file")]($rel), never to the state-repo path; the copy refreshes on each Write or Edit of the original." \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
