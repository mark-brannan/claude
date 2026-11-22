#!/usr/bin/env bash
# Tests for bdd-test. Run: bash bin/bdd-test.test.sh
# What matters: the venv lives outside the repo and is overridable; --venv
# prints it without creating or installing anything.
set -uo pipefail
B="$(cd "$(dirname "$0")" && pwd)/bdd-test"
pass=0; fail=0
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
ok() { if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); printf 'FAIL: %s\n  want [%s]\n  got  [%s]\n' "$1" "$2" "$3"; fi; }

ok 'default venv is under the home, not the repo' "$HOME/.local/share/claude-bdd-venv" "$(sh "$B" --venv)"
ok 'BDD_TEST_VENV overrides it' "$T/v" "$(BDD_TEST_VENV="$T/v" sh "$B" --venv)"
ok '--venv creates nothing' 0 "$([ -e "$T/v" ] && echo 1 || echo 0)"
printf '%s passed, %s failed\n' "$pass" "$fail"; [ "$fail" -eq 0 ]
