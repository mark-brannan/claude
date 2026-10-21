#!/usr/bin/env bash
# Tests for scratch-mirror.sh. Run: bash hooks/scratch-mirror.test.sh
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/scratch-mirror.sh"
pass=0; fail=0
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

ok() { if eval "$2"; then pass=$((pass + 1)); else fail=$((fail + 1)); printf 'FAIL: %s\n' "$1"; fi; }
run() { jq -n --arg f "$1" --arg c "$2" '{tool_name:"Write",tool_input:{file_path:$f},cwd:$c}' | bash "$HOOK" 2>&1; }

export CLAUDE_STATE_REPO="$T/state"
git init -q "$CLAUDE_STATE_REPO"; mkdir -p "$CLAUDE_STATE_REPO/global/foo/bar"
DOC="$CLAUDE_STATE_REPO/global/foo/bar/2026-10-20-foo-bar.md"
printf '# v1\n' > "$DOC"; printf 'x\n' > "$CLAUDE_STATE_REPO/global/notes.txt"
WORK="$T/work"; git init -q "$WORK"; mkdir -p "$WORK/sub"

out=$(run "$DOC" "$WORK")
ok 'a state-repo doc is copied flat into .scratch' '[ "$(cat "$WORK/.scratch/2026-10-20-foo-bar.md")" = "# v1" ]'
ok 'and the model is told the link to give' 'grep -q "\[2026-10-20-foo-bar.md\](.scratch/2026-10-20-foo-bar.md)" <<<"$out"'
ok '.scratch/ is excluded from git' '[ -z "$(git -C "$WORK" status --porcelain)" ]'
run "$DOC" "$WORK" >/dev/null
ok 'the exclude line is written once' '[ "$(grep -cx ".scratch/" "$WORK/.git/info/exclude")" = 1 ]'

printf '# v2\n' > "$DOC"; run "$DOC" "$WORK" >/dev/null
ok 'an edit refreshes the copy' '[ "$(cat "$WORK/.scratch/2026-10-20-foo-bar.md")" = "# v2" ]'

out=$(run "$DOC" "$WORK/sub")
ok 'the link is relative to the session directory' 'grep -q "(../.scratch/2026-10-20-foo-bar.md)" <<<"$out"'

out=$(run "$CLAUDE_STATE_REPO/global/notes.txt" "$WORK")
ok 'other file types are left alone' '[ -z "$out" ] && [ ! -e "$WORK/.scratch/notes.txt" ]'
printf 'a\n' > "$WORK/local.md"; out=$(run "$WORK/local.md" "$WORK")
ok 'files outside the state repo are left alone' '[ -z "$out" ]'
out=$(run "$DOC" "$CLAUDE_STATE_REPO")
ok 'a session in the state repo itself gets nothing' '[ -z "$out" ] && [ ! -e "$CLAUDE_STATE_REPO/.scratch" ]'
out=$(run "$DOC" "$T")
ok 'a session outside any repo gets nothing' '[ -z "$out" ]'

printf '%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
