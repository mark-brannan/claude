#!/usr/bin/env python3
# Tests for worker-start. Run: python3 bin/worker-start.test.py
#
# What matters: a new branch starts at origin's tip, not the local one; a PR
# start lands on the PR's head branch, tracking its remote branch; a git
# refusal exits 1 before the log line; an unreadable issue does not fail it.
# gh and work-item are fakes on PATH and beside the copied script.
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

WS = Path(__file__).resolve().parent / "worker-start"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


class WorkerStartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        S = self.S = Path(self.tmp.name)
        self.env = {**os.environ, "HOME": str(S), "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update(self.env)
        git("init", "-q", "--bare", "-b", "main", "origin.git", cwd=S)
        git("clone", "-q", "origin.git", "up", cwd=S)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=S / "up")
        git("push", "-q", "origin", "HEAD:main", cwd=S / "up")
        git("clone", "-q", "origin.git", "w", cwd=S)
        # origin moves after the worker's clone: only a fetch sees "two".
        git("commit", "-q", "--allow-empty", "-m", "two", cwd=S / "up")
        git("checkout", "-q", "-b", "claude/pr-head", cwd=S / "up")
        git("commit", "-q", "--allow-empty", "-m", "pr", cwd=S / "up")
        git("push", "-q", "origin", "main", "claude/pr-head", cwd=S / "up")
        (S / "bin").mkdir()
        shutil.copy(WS, S / "bin" / "worker-start")
        self.fake("gh", 'case "$1 $2" in "pr view") echo claude/pr-head ;;'
                        ' "issue view") [ "$3" = 404 ] && exit 1; echo "issue $3 text" ;; esac')
        self.fake("work-item", f'echo "$*" >> {S}/log')
        self.env["PATH"] = f"{S / 'bin'}:{os.environ['PATH']}"

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, name, body):
        p = self.S / "bin" / name
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(0o755)

    def start(self, *args):
        return subprocess.run([str(self.S / "bin" / "worker-start"), *args], cwd=self.S / "w",
                              env=self.env, capture_output=True, text=True)

    def test_branch_from_fetched_main_prints_issue_and_logs(self):
        r = self.start("--branch", "claude/issue-7-x", "--issue", "7", "--item", "abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("issue 7 text", r.stdout)
        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.S / "w"), "two")
        self.assertEqual(git("branch", "--show-current", cwd=self.S / "w"), "claude/issue-7-x")
        self.assertEqual((self.S / "log").read_text(), "log abc dispatched\n")

    def test_branch_from_a_stacked_head(self):
        r = self.start("--branch", "claude/issue-8-y", "--from", "claude/pr-head")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.S / "w"), "pr")

    def test_pr_checks_out_its_head_tracking_the_remote(self):
        r = self.start("--pr", "12")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git("rev-parse", "--abbrev-ref", "@{u}", cwd=self.S / "w"),
                         "origin/claude/pr-head")

    def test_existing_branch_refuses_before_the_log(self):
        git("branch", "taken", cwd=self.S / "w")
        r = self.start("--branch", "taken", "--item", "abc")
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.S / "log").exists())

    def test_unreadable_issue_still_starts(self):
        r = self.start("--branch", "claude/issue-404-z", "--issue", "404")
        self.assertEqual(r.returncode, 0)
        self.assertIn("could not be read", r.stdout)


if __name__ == "__main__":
    unittest.main()
