#!/usr/bin/env python3
# Tests for permission-request-log.py. Run: python3 hooks/permission-request-log.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PermissionRequest
# JSON on stdin, with CLAUDE_STATE_REPO and HOME pointed at a throwaway dir and
# LANGUETTE_ROOT at a stub whose mask swaps the word SECRETVALUE.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "permission-request-log.py"

STUB = '''
def mask(text, extra=()):
    if "UNPLACEABLE" in text:
        return None, 1
    return text.replace("SECRETVALUE", "<secret>"), text.count("SECRETVALUE")
'''


class PermissionRequestLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        repo = self.home / "state"
        (repo / ".git").mkdir(parents=True)
        lang = self.home / "languette-stub" / "languette"
        lang.mkdir(parents=True)
        (lang / "__init__.py").write_text("")
        (lang / "record.py").write_text(STUB)
        self.log = repo / "state/global/metrics/permission-requests/ab/abc123.jsonl"
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_STATE_REPO": str(repo),
                    "LANGUETTE_ROOT": str(lang.parent), "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, tool_input, tool="Bash", mode="auto", stdin=None):
        ev = {"hook_event_name": "PermissionRequest", "session_id": "abc123", "cwd": "/w/repo",
              "permission_mode": mode, "tool_name": tool, "tool_input": tool_input}
        r = subprocess.run([sys.executable, str(HOOK)], input=stdin if stdin is not None else json.dumps(ev),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "the hook must not answer the dialog")
        if not self.log.exists():
            return []
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def test_one_line_per_request_with_context(self):
        self.run_hook({"command": "ls"})
        rows = self.run_hook({"file_path": "/w/a.py"}, tool="Write", mode="default")
        self.assertEqual(len(rows), 2)
        self.assertEqual({k: rows[0][k] for k in ("session_id", "cwd", "permission_mode", "tool")},
                         {"session_id": "abc123", "cwd": "/w/repo", "permission_mode": "auto", "tool": "Bash"})
        self.assertEqual((rows[1]["tool"], rows[1]["permission_mode"]), ("Write", "default"))

    def test_secret_in_input_is_masked(self):
        row = self.run_hook({"command": "GH_TOKEN=SECRETVALUE git push", "description": "push"})[0]
        self.assertEqual(row["input"], {"command": "GH_TOKEN=<secret> git push", "description": "push"})
        self.assertEqual(row["masked"], 1)

    def test_nested_strings_masked(self):
        row = self.run_hook({"edits": [{"new_string": "k=SECRETVALUE"}], "n": 3}, tool="MultiEdit")[0]
        self.assertEqual(row["input"], {"edits": [{"new_string": "k=<secret>"}], "n": 3})

    def test_unmaskable_string_is_dropped(self):
        row = self.run_hook({"command": "echo UNPLACEABLE", "description": "d"})[0]
        self.assertEqual(row["input"], {"command": None, "description": "d"})

    def test_long_string_cut_after_masking(self):
        row = self.run_hook({"content": "SECRETVALUE" + "x" * 2000}, tool="Write")[0]
        self.assertTrue(row["input"]["content"].startswith("<secret>"))
        self.assertLess(len(row["input"]["content"]), 600)

    def test_no_languette_logs_no_input(self):
        self.env["LANGUETTE_ROOT"] = str(self.home / "nowhere")
        row = self.run_hook({"command": "GH_TOKEN=SECRETVALUE git push"})[0]
        self.assertIsNone(row["input"])
        self.assertEqual(row["tool"], "Bash")

    def test_malformed_input_fails_open(self):
        self.assertEqual(self.run_hook(None, stdin="not json"), [])


if __name__ == "__main__":
    unittest.main()
