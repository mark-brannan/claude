#!/usr/bin/env python3
# Tests for languette-options-check. Run: python3 bin/languette-options-check.test.py
# Offline: plugin.json is a fixture file, never fetched.
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent / "languette-options-check"
PLUGIN = {"userConfig": {"guard_worktrees": {}, "private_repos": {}}}


def run(options, anticipated=None, plugin=PLUGIN):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "s.json").write_text(json.dumps(
            {"pluginConfigs": {"languette@languette": {"options": options}}}))
        (d / "p.json").write_text(json.dumps(plugin))
        (d / "a.txt").write_text(anticipated or "")
        return subprocess.run(
            [sys.executable, str(CHECK), "--settings", str(d / "s.json"),
             "--plugin-json", str(d / "p.json"), "--anticipated", str(d / "a.txt")],
            capture_output=True, text=True)


class T(unittest.TestCase):
    def test_defined_keys_pass(self):
        self.assertEqual(run({"guard_worktrees": True, "private_repos": "x"}).returncode, 0)

    def test_bogus_key_fails_and_is_named(self):
        r = run({"guard_worktrees": True, "no_foreign_worktree": True})
        self.assertEqual(r.returncode, 1)
        self.assertIn("no_foreign_worktree", r.stdout)

    def test_anticipated_key_passes(self):
        r = run({"guard_secrets": True}, anticipated="# pen\nguard_secrets  # q17\n")
        self.assertEqual(r.returncode, 0)

    def test_unreadable_input_is_exit_2(self):
        r = subprocess.run([sys.executable, str(CHECK), "--settings", "/nonexistent"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
