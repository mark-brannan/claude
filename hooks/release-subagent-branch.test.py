#!/usr/bin/env python3
# Tests for release-subagent-branch.py. Run: python3 hooks/release-subagent-branch.test.py
#
# Cost per push: a second or two, a step in CI's existing tool-tests job.
# Each case builds a repo with a bare remote and a sub-agent worktree where
# the Agent tool puts one, fires SubagentStop at it, and reads back whether
# the worktree still holds its branch. RELEASE_SUBAGENT_BRANCH_HOOK names
# another script to drive the same way (the parity run against the old shell
# hook used it); a .sh runs under bash.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("RELEASE_SUBAGENT_BRANCH_HOOK")
            or Path(__file__).resolve().parent / "release-subagent-branch.py").resolve()
GITENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=GITENV)


class ReleaseSubagentBranchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def setup_repo(self, ident):
        """The repo path; its worktree is on branch work-<ident>, pushed, clean."""
        r = self.root / f"repo-{ident}"
        remote = self.root / f"remote-{ident}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=GITENV)
        subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=GITENV)
        git(r, "commit", "-q", "--allow-empty", "-m", "init")
        git(r, "remote", "add", "origin", str(remote))
        git(r, "push", "-q", "origin", "main")
        wt = self.wt(r, ident)
        git(r, "worktree", "add", "-q", "-b", f"work-{ident}", str(wt))
        git(wt, "commit", "-q", "--allow-empty", "-m", "work")
        git(wt, "push", "-q", "origin", f"work-{ident}")
        return r

    @staticmethod
    def wt(repo, ident):
        return repo / ".claude" / "worktrees" / f"agent-{ident}"

    def fire(self, cwd, agent_id, transcript=None, raw=None):
        ev = raw if raw is not None else json.dumps(
            {"hook_event_name": "SubagentStop", "cwd": str(cwd), "agent_id": agent_id,
             **({"agent_transcript_path": str(transcript)} if transcript else {})})
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        return subprocess.run(cmd, input=ev, capture_output=True, text=True, env=GITENV)

    def held(self, wt):
        return subprocess.run(["git", "-C", str(wt), "symbolic-ref", "-q", "HEAD"],
                              capture_output=True, env=GITENV).returncode == 0

    def test_releases_clean_and_pushed(self):
        r = self.setup_repo("a1")
        self.fire(r, "a1")
        self.assertFalse(self.held(self.wt(r, "a1")))

    def test_found_by_transcript_when_parent_sits_elsewhere(self):
        r = self.setup_repo("a2")
        other = self.root / "elsewhere"
        other.mkdir()
        t = self.root / "t2.jsonl"
        t.write_text(json.dumps({"cwd": str(self.wt(r, "a2"))}, separators=(",", ":")) + "\n")
        self.fire(other, "a2", t)
        self.assertFalse(self.held(self.wt(r, "a2")))

    def test_keeps_branch_with_unpushed_commit(self):
        r = self.setup_repo("b1")
        git(self.wt(r, "b1"), "commit", "-q", "--allow-empty", "-m", "unpushed")
        self.fire(r, "b1")
        self.assertTrue(self.held(self.wt(r, "b1")))

    def test_keeps_branch_with_untracked_file(self):
        r = self.setup_repo("b2")
        (self.wt(r, "b2") / "new.txt").write_text("x")
        self.fire(r, "b2")
        self.assertTrue(self.held(self.wt(r, "b2")))

    def test_keeps_branch_with_staged_change(self):
        r = self.setup_repo("b3")
        (self.wt(r, "b3") / "f.txt").write_text("x")
        git(self.wt(r, "b3"), "add", "f.txt")
        self.fire(r, "b3")
        self.assertTrue(self.held(self.wt(r, "b3")))

    def test_another_agent_stopping_leaves_this_one_alone(self):
        r = self.setup_repo("b4")
        self.fire(r, "other-id")
        self.assertTrue(self.held(self.wt(r, "b4")))

    def test_agent_id_that_is_not_a_plain_name(self):
        r = self.setup_repo("b5")
        self.fire(r, "b5/../../x")
        self.assertTrue(self.held(self.wt(r, "b5")))

    def test_second_stop_on_detached_worktree_is_silent(self):
        r = self.setup_repo("c1")
        self.fire(r, "c1")
        p = self.fire(r, "c1")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))

    def test_empty_and_garbage_payloads_are_silent(self):
        for raw in ("{}", "", "not json", "[1]"):
            p = self.fire(self.root, "x", raw=raw)
            self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""), raw)


if __name__ == "__main__":
    unittest.main()
