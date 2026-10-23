#!/usr/bin/env python3
# Tests for guard-add-repo.py. Run: python3 hooks/guard-add-repo.test.py
#
# Cost per push: well under a second, a step in CI's Python test suites.
# GUARD_ADD_REPO_HOOK names another script to drive through the same command
# line (the parity run against the old shell hook used it; a .sh runs under bash).
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("GUARD_ADD_REPO_HOOK") or Path(__file__).resolve().parent / "guard-add-repo.py").resolve()


def run(payload):
    cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run(cmd, input=raw, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout


def add_repo(owner, repo):
    return {"tool_name": "mcp__claude-code-remote__add_repo", "tool_input": {"owner": owner, "repo": repo}}


class GuardAddRepoTest(unittest.TestCase):
    def test_state_repo_is_allowed(self):
        rc, out = run(add_repo("mark-brannan", "claude_prompts_scratch"))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), {"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "allow",
            "permissionDecisionReason": "continuity state repo -- standing allow"}})

    def test_every_other_repo_falls_through(self):
        for owner, repo in [("mark-brannan", "claude"), ("someone-else", "claude_prompts_scratch"),
                            ("mark-brannan", "claude_prompts_scratch2"), ("Mark-Brannan", "claude_prompts_scratch"),
                            ("", ""), ("mark-brannan", "")]:
            with self.subTest(owner=owner, repo=repo):
                self.assertEqual(run(add_repo(owner, repo)), (0, ""))

    def test_missing_or_odd_input_falls_through(self):
        for payload in [{}, {"tool_input": {}}, {"tool_input": None}, {"tool_input": "x"},
                        {"tool_input": {"owner": 1, "repo": 2}}, "", "not json", "[]"]:
            with self.subTest(payload=payload):
                self.assertEqual(run(payload), (0, ""))


if __name__ == "__main__":
    unittest.main()
