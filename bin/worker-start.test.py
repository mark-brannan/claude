#!/usr/bin/env python3
# Tests for worker-start. Run: python3 bin/worker-start.test.py
#
# What matters: --new cuts claude/<slug> from origin/main (or --base), in the
# repo or in a new worktree; --head and --pr check out the remote head, a
# worktree one detached; the issue or PR is read last; a failing step stops
# the run with its code. A real git repo with a local "origin"; gh is a stub.
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "worker-start"

GH = '''#!/bin/sh
echo "gh $*" >> "$GH_LOG"
case "$1 $2" in "pr view") case "$*" in *headRefName*) [ -f "$GH_LOG.fork" ] && echo "true feature" || echo "false feature" ;; esac ;; esac
exit 0
'''


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout


class WorkerStart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        origin, self.repo = self.tmp / "origin", self.tmp / "repo"
        sh("git", "init", "-q", "-b", "main", str(origin))
        sh("git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
           "commit", "-q", "--allow-empty", "-m", "root")
        sh("git", "-C", str(origin), "branch", "feature")
        sh("git", "clone", "-q", str(origin), str(self.repo))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(GH)
        (bindir / "gh").chmod(0o755)
        self.log = self.tmp / "gh.log"
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), GH_LOG=str(self.log))

    def run_tool(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), *args],
                              env=self.env, text=True, capture_output=True, cwd=cwd)

    def branch(self, where=None):
        return sh("git", "-C", str(where or self.repo), "rev-parse", "--abbrev-ref", "HEAD").strip()

    def gh_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_new_cuts_claude_branch_and_reads_issue(self):
        r = self.run_tool("--new", "fix-x", "--issue", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(), "claude/fix-x")
        self.assertEqual(self.gh_calls(), ["gh issue view 7 --comments"])
        self.assertIn("$ git -C", r.stdout)

    def test_new_in_worktree(self):
        wt = self.tmp / "wt"
        r = self.run_tool("--new", "fix-y", "--worktree", str(wt))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(wt), "claude/fix-y")
        self.assertEqual(self.branch(), "main")

    def test_head_checks_out_remote_branch(self):
        r = self.run_tool("--head", "feature")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(), "feature")
        self.assertEqual(sh("git", "-C", str(self.repo), "rev-parse", "HEAD"),
                         sh("git", "-C", str(self.repo), "rev-parse", "origin/feature"))

    def test_pr_in_worktree_is_detached_and_prints_pr(self):
        wt = self.tmp / "wt"
        r = self.run_tool("--pr", "5", "--worktree", str(wt))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(wt), "HEAD")
        self.assertEqual(self.gh_calls()[-1], "gh pr view 5 --comments")

    def test_relative_worktree_is_the_callers_not_the_repos(self):
        r = self.run_tool("--new", "fix-r", "--worktree", "wt", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "wt").is_dir())
        self.assertFalse((self.repo / "wt").exists())

    def test_gh_runs_in_the_repo_whatever_the_callers_cwd(self):
        r = self.run_tool("--new", "fix-c", "--issue", "7", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_failing_step_stops_the_run(self):
        r = self.run_tool("--new", "fix-z", "--base", "origin/nope", "--issue", "7")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("worker-start: failed", r.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_existing_local_branch_is_not_reset(self):
        sh("git", "-C", str(self.repo), "branch", "feature", "origin/main")
        self.assertNotEqual(self.run_tool("--head", "feature").returncode, 0)

    def test_fork_pr_is_refused(self):
        Path(str(self.log) + ".fork").write_text("")
        self.assertEqual(self.run_tool("--pr", "5").returncode, 2)

    def test_dash_argument_is_refused(self):
        self.assertEqual(self.run_tool("--new", "--exec=x").returncode, 2)

    def test_base_without_new_is_refused(self):
        self.assertEqual(self.run_tool("--head", "feature", "--base", "origin/x").returncode, 2)


if __name__ == "__main__":
    unittest.main()
