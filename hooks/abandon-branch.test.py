#!/usr/bin/env python3
# Tests for abandon-branch.py. Run: python3 hooks/abandon-branch.test.py
#
# Deletes on both sides when it can confirm the remote side, refuses in
# $HOME, refuses the branch of an open PR, and never deletes the local
# branch on an indeterminate remote check (network/auth failure, not a
# confirmed absence).
#
# `gh` is stubbed on PATH throughout -- no test here reaches the network,
# and a test that did would pass or fail on whatever PRs happened to be
# open. The default stub reports no open PRs at all.
#
# Cost per push: a few seconds; one subprocess and a few local repos per case.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPT = Path(os.environ.get("ABANDON_BRANCH_HOOK") or Path(__file__).resolve().parent / "abandon-branch.py").resolve()

GH_STUB = """#!/bin/sh
[ -n "${GH_FAIL:-}" ] && exit 1
printf '%s\\n' "${GH_PRS:-[]}"
"""


def pr(number, title, base, head):
    return {"number": number, "title": title, "baseRefName": base, "headRefName": head}


class AbandonBranchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        s = self.s = Path(self.tmp.name).resolve()
        self.home = s / "home"
        self.home.mkdir()
        (s / "tmp").mkdir()
        self.stub = s / "stub"
        self.stub.mkdir()
        gh = self.stub / "gh"
        gh.write_text(GH_STUB)
        gh.chmod(0o755)
        self.origin = s / "origin.git"
        self.work = s / "work"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GH_"))}
        self.env.update(HOME=str(self.home), TMPDIR=str(s / "tmp"), GIT_CONFIG_GLOBAL="/dev/null",
                        GIT_CONFIG_NOSYSTEM="1", GH_PRS="[]",
                        PATH=f"{self.stub}{os.pathsep}{os.environ['PATH']}")

    def tearDown(self):
        self.tmp.cleanup()

    def g(self, *args, check=True):
        p = subprocess.run(["git", "-C", str(self.work), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                            "-c", "commit.gpgsign=false", *args],
                           capture_output=True, text=True, env=self.env)
        if check and p.returncode:
            raise AssertionError(p.stderr)
        return p

    def setup_repo(self, branch, pushed=True):
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True, env=self.env)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True, env=self.env)
        self.g("remote", "add", "origin", str(self.origin))
        (self.work / "f").write_text("one\n")
        self.g("add", "--", "f")
        self.g("commit", "-m", "one")
        self.g("push", "-u", "origin", "main")
        self.g("checkout", "-b", branch)
        (self.work / "g").write_text("two\n")
        self.g("add", "--", "g")
        self.g("commit", "-m", "two")
        if pushed:
            self.g("push", "-u", "origin", branch)

    def run_hook(self, *args, env=None):
        e = dict(self.env, **(env or {}))
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=e)

    def has_local(self, branch):
        return self.g("rev-parse", "--verify", branch, check=False).returncode == 0

    def has_remote(self, branch):
        return bool(self.g("ls-remote", "--heads", "origin", branch, check=False).stdout.strip())

    def head(self):
        return self.g("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def test_deletes_both_sides_when_remote_reachable(self):
        self.setup_repo("claude/gone")
        p = self.run_hook("-C", str(self.work))
        self.assertFalse(self.has_local("claude/gone"))
        self.assertEqual(self.head(), "HEAD")  # detached, work still reachable
        self.assertFalse(self.has_remote("claude/gone"))
        self.assertIn("abandoned `claude/gone`", p.stdout)
        self.assertEqual(p.returncode, 0)

    def test_never_pushed_branch_local_only(self):
        self.setup_repo("claude/local", pushed=False)
        p = self.run_hook("-C", str(self.work), "claude/local")
        self.assertFalse(self.has_local("claude/local"))
        self.assertIn("not on the remote", p.stdout)

    def test_unreachable_remote_keeps_local(self):
        self.setup_repo("claude/unreachable")
        self.g("remote", "set-url", "origin", str(self.s / "no-such-remote.git"))
        p = self.run_hook("-C", str(self.work))
        self.assertEqual(self.head(), "claude/unreachable")
        self.assertIn("could not verify remote", p.stdout)

    def test_refuses_in_home(self):
        self.setup_repo("claude/athome")
        p = self.run_hook("-C", str(self.work), env={"HOME": str(self.work)})
        self.assertIn("refused", p.stderr)
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(self.has_local("claude/athome"))

    def test_refuses_main_and_detached_head(self):
        self.setup_repo("claude/x")
        self.assertNotEqual(self.run_hook("-C", str(self.work), "main").returncode, 0)
        self.g("checkout", "--detach")
        self.assertNotEqual(self.run_hook("-C", str(self.work)).returncode, 0)

    def test_not_a_repo_and_unknown_option(self):
        self.assertEqual(self.run_hook("-C", str(self.s / "tmp")).returncode, 1)
        self.assertEqual(self.run_hook("--bogus").returncode, 2)

    def test_refuses_base_of_open_pr(self):
        self.setup_repo("claude/based")
        prs = json.dumps([pr(1, "stacked change", "claude/based", "claude/stacked-one")])
        p = self.run_hook("-C", str(self.work), env={"GH_PRS": prs})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("refused", p.stderr)
        self.assertIn("#1", p.stderr)
        self.assertTrue(self.has_local("claude/based"))
        self.assertTrue(self.has_remote("claude/based"))

    def test_refuses_head_of_open_pr(self):
        self.setup_repo("claude/headed")
        prs = json.dumps([pr(2, "the change itself", "main", "claude/headed")])
        p = self.run_hook("-C", str(self.work), env={"GH_PRS": prs})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("#2", p.stderr)
        self.assertTrue(self.has_local("claude/headed"))

    def test_fails_closed_without_gh(self):
        # A PATH with only git linked in, so gh is genuinely unresolvable
        # rather than just absent from the stub dir.
        nogh = self.s / "nogh-bin"
        nogh.mkdir()
        (nogh / "git").symlink_to(shutil.which("git"))
        self.setup_repo("claude/nogh")
        p = self.run_hook("-C", str(self.work), env={"PATH": str(nogh)})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("could not check open PRs", p.stderr)
        self.assertTrue(self.has_local("claude/nogh"))

    def test_fails_closed_when_pr_list_unreadable(self):
        self.setup_repo("claude/ghfails")
        p = self.run_hook("-C", str(self.work), env={"GH_FAIL": "1"})
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("could not check open PRs", p.stderr)
        self.assertTrue(self.has_local("claude/ghfails"))

    def test_fails_closed_on_truncated_list(self):
        self.setup_repo("claude/many")
        prs = json.dumps([pr(i, "t", "main", f"x{i}") for i in range(1000)])
        p = self.run_hook("-C", str(self.work), env={"GH_PRS": prs})
        self.assertNotEqual(p.returncode, 0)
        self.assertTrue(self.has_local("claude/many"))

    def test_local_only_branch_needs_no_pr_check(self):
        self.setup_repo("claude/localonly", pushed=False)
        self.run_hook("-C", str(self.work), "claude/localonly", env={"GH_FAIL": "1"})
        self.assertFalse(self.has_local("claude/localonly"))

    def test_unrelated_open_pr_does_not_block(self):
        self.setup_repo("claude/clear")
        prs = json.dumps([pr(9, "unrelated", "main", "claude/elsewhere")])
        p = self.run_hook("-C", str(self.work), env={"GH_PRS": prs})
        self.assertFalse(self.has_local("claude/clear"))
        self.assertIn("abandoned `claude/clear`", p.stdout)


if __name__ == "__main__":
    unittest.main()
