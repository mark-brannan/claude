#!/usr/bin/env python3
"""Tests for pr-live. Run: python3 bin/pr-live.test.py

What matters: a merged PR whose merge commit the live clone lacks is NOT
live and exits 1; once the clone has it, live and exit 0; an open PR is not
live; a repo not deployed here is live once merged; a plugin is judged by
its installed commit. A stub gh and a local bare repo; no network. Cost per
push: about a second.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "pr-live"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class PrLive(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        origin, work, self.live = root / "origin.git", root / "work", root / "live"
        git("init", "-q", "--bare", "-b", "main", str(origin))
        git("clone", "-q", str(origin), str(work))
        self.commit = lambda: (git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                   "--allow-empty", "-m", "c", cwd=work),
                               git("push", "-q", "origin", "HEAD:main", cwd=work),
                               git("rev-parse", "HEAD", cwd=work))[2]
        self.base = self.commit()
        git("clone", "-q", str(origin), str(self.live))
        self.merge = self.commit()
        self.cfg = root / "config.json"
        self.cfg.write_text(json.dumps({"live_clone": {"repos": {
            "o/deployed": {"git": ["-C", str(self.live)]},
            "o/plug": {"git": ["-C", str(self.live)], "plugin": "plug@plug"}}}}))
        self.plugins = root / "installed_plugins.json"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.env = {**os.environ, "PR_LIVE_CONFIG": str(self.cfg), "PR_LIVE_PLUGINS": str(self.plugins),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        self.gh("MERGED")

    def gh(self, state):
        out = json.dumps({"state": state, "mergeCommit": {"oid": self.merge} if state == "MERGED" else None})
        stub = self.bin / "gh"
        stub.write_text(f"#!/bin/sh\necho '{out}'\n")
        stub.chmod(0o755)

    def run_tool(self, *refs):
        p = subprocess.run([sys.executable, str(TOOL), *refs], capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout

    def test_merged_but_not_synced_is_not_live(self):
        # The live clone has not pulled since the merge: the batch must hold.
        rc, out = self.run_tool("o/deployed#1")
        self.assertEqual(rc, 1)
        self.assertIn("NOT live", out)

    def test_synced_is_live(self):
        git("pull", "-q", "--ff-only", cwd=self.live)
        self.assertEqual(self.run_tool("o/deployed#1")[0], 0)

    def test_open_is_not_live(self):
        self.gh("OPEN")
        rc, out = self.run_tool("o/deployed#1")
        self.assertEqual((rc, "not merged" in out), (1, True))

    def test_undeployed_repo_is_live_once_merged(self):
        self.assertEqual(self.run_tool("o/elsewhere#1")[0], 0)

    def test_plugin_is_judged_by_its_installed_commit(self):
        for sha, want in ((self.base, 1), (self.merge, 0)):
            self.plugins.write_text(json.dumps({"plugins": {"plug@plug": [
                {"scope": "user", "gitCommitSha": sha}]}}))
            self.assertEqual(self.run_tool("o/plug#1")[0], want, sha)

    def test_any_ref_not_live_fails_the_run(self):
        self.assertEqual(self.run_tool("o/elsewhere#1", "o/deployed#1")[0], 1)


if __name__ == "__main__":
    unittest.main()
