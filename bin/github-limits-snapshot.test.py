#!/usr/bin/env python3
# Tests for github-limits-snapshot. Run: python3 bin/github-limits-snapshot.test.py
# Offline: a scratch git repo with no GitHub remote, so github-limits cannot measure it.
import json
import os
import subprocess
import sys
import tempfile
import importlib.machinery
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "github-limits-snapshot"


def load_tool():
    loader = importlib.machinery.SourceFileLoader("github_limits_snapshot", str(TOOL))
    spec = importlib.util.spec_from_loader("github_limits_snapshot", loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Snapshot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_STATE_REPO": ""}

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True,
                              env=self.env, timeout=30)

    def test_no_state_repo_exits_2_and_writes_nothing(self):
        snap = load_tool()
        with mock.patch.object(snap.state, "state_repo", return_value=None), \
             mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(snap.main([]), 2)
        self.assertFalse((self.home / ".local/state/github-limits").exists())

    def test_unmeasurable_repo_exits_3_and_writes_nothing(self):
        p = self.run_tool(str(self.home))
        self.assertEqual(p.returncode, 3)
        self.assertFalse((self.home / ".local/state/github-limits/snapshots.jsonl").exists())

    def test_reading_is_appended_per_run(self):
        repo = self.home / "r"
        repo.mkdir()
        bindir = self.home / "bin"
        bindir.mkdir()
        gh = bindir / "gh"  # stub: every API call answers with the same small payload
        gh.write_text('#!/bin/sh\ncase "$2" in\n  rate_limit) echo \'{"resources":{"core":{"used":1,"limit":5000},'
                      '"graphql":{"used":1,"limit":5000},"search":{"used":1,"limit":30}}}\';;\n'
                      '  *activity*) echo "[]";;\n  *) echo \'{"size":2048}\';;\nesac\n')
        gh.chmod(0o755)
        self.env["PATH"] = f"{bindir}:{os.environ['PATH']}"
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        (repo / "f").write_text("x")
        git("add", "f")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
        git("remote", "add", "origin", "https://github.com/example/example.git")
        for _ in range(2):
            self.assertEqual(self.run_tool(str(repo)).returncode, 0)
        lines = (self.home / ".local/state/github-limits/snapshots.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("rows", json.loads(lines[0]))


if __name__ == "__main__":
    unittest.main()
