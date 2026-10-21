#!/usr/bin/env bash
# Tests for create-pr-labels.sh. Run: bash bin/create-pr-labels.test.sh
# A stub `gh` on PATH records every label create; no network, no live repo.
set -uo pipefail
SCRIPT="$(cd "$(dirname "$0")" && pwd)/create-pr-labels.sh"
S=$(mktemp -d); trap 'rm -rf "$S"' EXIT
mkdir -p "$S/bin" "$S/home/.local/share"
printf 'repoa\n' > "$S/home/.local/share/vended-repos.txt"
cat > "$S/bin/gh" <<'EOF'
#!/bin/sh
[ "$1 $2" = "label create" ] && echo "$*" >> "$GH_LOG"
exit 0
EOF
chmod +x "$S/bin/gh"
export GH_LOG="$S/log"; : > "$GH_LOG"
HOME="$S/home" PATH="$S/bin:$PATH" OWNER=testowner sh "$SCRIPT" >/dev/null 2>&1

pass=0; fail=0
check() { # check <name> <pattern>
  if grep -Eq -- "$2" "$GH_LOG"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL $1"; fi
}
check "auto lane created on a vended repo" '^label create lane-auto -R testowner/repoa --color 0E8A16 -d .*autonomous lane'
check "gated lane created on a vended repo" '^label create lane-gated -R testowner/repoa --color BFD4F2 -d .*gated lane'
check "gated lane created on dotfiles too" '^label create lane-gated -R testowner/dotfiles '
check "existing labels still created" '^label create ready -R testowner/repoa '
n=$(grep -c ' lane-' "$GH_LOG")
if [ "$n" -eq 6 ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL expected 6 lane creates, got $n"; fi
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
