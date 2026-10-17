#!/usr/bin/env python3
# Tests for pr-blockers-prompt.py. Run: python3 hooks/pr-blockers-prompt.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed UserPromptSubmit
# JSON, with PR_BLOCKERS_BIN pointed at a stub that answers per PR ref.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "pr-blockers-prompt.py"

STUB = """#!/bin/sh
case "$1" in
  o/r#1) echo 'unresolved review thread at a.md:3 by claude: "x"; fix: answer or act on it, then resolve the thread'
         echo 'merge conflict with main; fix: merge'; exit 1 ;;
  o/r#2) exit 0 ;;
  o/r#3) echo 'pr-blockers: gh pr view: not found' >&2; exit 2 ;;
  *) echo "called $1" >> "$(dirname "$0")/calls"; exit 0 ;;
esac
"""


class PromptHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stub = Path(self.tmp.name) / "pr-blockers"
        self.stub.write_text(STUB)
        self.stub.chmod(0o755)
        self.env = {**os.environ, "PR_BLOCKERS_BIN": str(self.stub)}

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, prompt):
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"prompt": prompt}),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def calls(self):
        p = Path(self.tmp.name) / "calls"
        return p.read_text().split("\n")[:-1] if p.exists() else []

    def test_no_pr_named_runs_nothing(self):
        self.assertIsNone(self.hook("fix the flaky test in #12"))
        self.assertEqual(self.calls(), [])

    def test_blocked_pr_puts_threads_first_as_numbered_items(self):
        out = self.hook("fixup https://github.com/o/r/pull/1")
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("1. unresolved review thread at a.md:3", ctx)
        self.assertIn("2. merge conflict", ctx)
        self.assertLess(ctx.index("unresolved review thread"), ctx.index("merge conflict"))
        self.assertIn("unresolved review thread at a.md:3", out["systemMessage"])

    def test_clear_and_unreadable_both_say_so(self):
        ctx = self.hook("o/r#2 and o/r#3")["hookSpecificOutput"]["additionalContext"]
        self.assertIn("o/r#2: nothing blocks it", ctx)
        self.assertIn("could not read o/r#3", ctx)
        self.assertIn("not found", ctx)

    def test_url_and_short_ref_to_same_pr_run_once_and_cap_holds(self):
        self.hook("https://github.com/x/y/pull/9 x/y#9 a/b#1 a/b#2 a/b#3")
        self.assertEqual(sorted(self.calls()), ["called a/b#1", "called a/b#2", "called x/y#9"])

    def test_missing_binary_is_a_line_not_silence(self):
        self.env["PR_BLOCKERS_BIN"] = str(Path(self.tmp.name) / "nope")
        self.env["HOME"] = self.tmp.name
        out = self.hook("o/r#1")
        self.assertIn("o/r#1", out["hookSpecificOutput"]["additionalContext"])

    def test_bad_payload_exits_zero_silently(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json",
                           capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
