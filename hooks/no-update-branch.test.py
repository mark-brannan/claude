#!/usr/bin/env python3
# Tests for no-update-branch.py. Run: python3 hooks/no-update-branch.test.py
#
# The cases that matter are the false positives. This hook is documented in
# RUNBOOK.md and argued about in PR comments, so the command it denies will
# appear verbatim inside commit messages and `gh pr comment` bodies -- which
# is precisely how a substring-matching sibling hook blocked its own
# documentation twice in one session.
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "no-update-branch.py"


def run(payload):
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    if not p.stdout.strip():
        return "allow"
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]


def bash(cmd):
    return {"tool_name": "Bash", "tool_input": {"command": cmd}}


DENY = [
    ("rebase form", 'gh pr update-branch 226 --rebase'),
    ("merge form", 'gh pr update-branch 226'),
    ("with --repo", 'gh pr update-branch 226 --repo mark-brannan/dotfiles --rebase'),
    ("after a separator", 'git fetch origin && gh pr update-branch 226 --rebase'),
    ("absolute path invocation", '/usr/bin/gh pr update-branch 226'),
    # An agent capturing output is the realistic shape here, not an attacker.
    ("command substitution", 'out=$(gh pr update-branch 226 --rebase 2>&1); echo "$out"'),
    ("subshell", '(gh pr update-branch 226 --rebase)'),
    ("backtick substitution", 'out=`gh pr update-branch 226`'),
]

ALLOW = [
    # the documentation trap
    ("mentioned in a commit message", 'git commit -m "never use gh pr update-branch --rebase here"'),
    ("mentioned in a PR comment body", "gh pr comment 226 --body 'do not run gh pr update-branch'"),
    ("mentioned in a heredoc-ish quoted string",
     'printf "%s" "gh pr update-branch --rebase strips signatures"'),
    # neighbouring commands
    ("other pr subcommand", 'gh pr view 226 --json mergeStateStatus'),
    ("pr checks", 'gh pr checks 226'),
    ("the sanctioned remedy", 'resign-branch.sh claude/foo'),
    ("word merely ending in gh", 'high pr update-branch'),
    ("unrelated command", 'git status'),
    ("empty command", ''),
]


class NoUpdateBranchTest(unittest.TestCase):
    def test_denies(self):
        for desc, cmd in DENY:
            with self.subTest(desc):
                self.assertEqual(run(bash(cmd)), "deny")

    def test_allows(self):
        for desc, cmd in ALLOW:
            with self.subTest(desc):
                self.assertEqual(run(bash(cmd)), "allow")

    def test_mcp_tool_form(self):
        self.assertEqual(run({"tool_name": "mcp__github__update_pull_request_branch",
                              "tool_input": {"pullNumber": 226}}), "deny")

    def test_reason_names_this_hook_and_remedy(self):
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(bash("gh pr update-branch 1")),
                           capture_output=True, text=True)
        reason = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("no-update-branch.py", reason)
        self.assertIn("resign-branch.sh <branch>", reason)


if __name__ == "__main__":
    unittest.main()
