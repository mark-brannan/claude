#!/usr/bin/env python3
# Tests for clone-sync.py. Run: python3 hooks/clone-sync.test.py
#
# Cost per push: a few seconds, a step in CI's existing tool-tests job. Each
# case builds a bare remote, the user's top-level clone and an agent's second
# clone that pushes to main, then fires the hook and reads the top clone back.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "clone-sync.py"
GITENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], check=check, capture_output=True,
                          text=True, env=GITENV)


class CloneSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.remote, self.top, self.agent = root / "r.git", root / "top", root / "agent"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.remote))
        git(root, "clone", "-q", str(self.remote), str(self.top))
        self.write(self.top, "a.txt", "a\n")
        self.write(self.top, "b.txt", "b\n")
        git(self.top, "add", "a.txt", "b.txt")
        git(self.top, "commit", "-qm", "base")
        git(self.top, "push", "-q", "origin", "main")
        git(self.top, "remote", "set-head", "origin", "main")
        git(root, "clone", "-q", str(self.remote), str(self.agent))
        self.cfg = root / "config.json"
        self.policy("keep")

    def tearDown(self):
        self.tmp.cleanup()

    def policy(self, p):
        self.cfg.write_text(json.dumps({"clone_sync": {"clones": {str(self.top): p}}}))

    def write(self, repo, name, text):
        (repo / name).write_text(text)

    def land(self, name="a.txt", text="upstream\n"):
        """The agent changes name and pushes it to main."""
        self.write(self.agent, name, text)
        git(self.agent, "commit", "-qam", f"change {name}")
        git(self.agent, "push", "-q", "origin", "main")

    def fire(self, event="PostToolUse", cwd=None, command="git push origin HEAD:main", **extra):
        ev = {"hook_event_name": event, "cwd": str(cwd or self.top), "tool_name": "Bash",
              "tool_input": {"command": command}, **extra}
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev), text=True,
                           capture_output=True, env={**GITENV, "CLONE_SYNC_CONFIG": str(self.cfg)})
        return json.loads(p.stdout) if p.stdout.strip() else None

    def head(self, repo):
        return git(repo, "rev-parse", "HEAD").stdout.strip()

    def clean_state(self):
        """No rebase or merge left half-done in the top clone."""
        gd = Path(git(self.top, "rev-parse", "--absolute-git-dir").stdout.strip())
        return not any((gd / m).exists() for m in ("rebase-merge", "rebase-apply", "MERGE_HEAD"))

    def test_clean_clone_fast_forwards_after_a_push(self):
        self.land()
        out = self.fire()
        self.assertEqual(self.head(self.top), self.head(self.agent))
        self.assertIn("fast-forward", out["systemMessage"])

    def test_merge_from_a_worktree_of_the_clone_syncs_it(self):
        wt = Path(self.tmp.name) / "wt"
        git(self.top, "worktree", "add", "-q", "-b", "feature", str(wt))
        self.land()
        self.fire(cwd=wt, command="gh pr merge 7 --squash")
        self.assertEqual(self.head(self.top), self.head(self.agent))

    def test_unrelated_command_does_nothing(self):
        self.land()
        before = self.head(self.top)
        self.assertIsNone(self.fire(command="git status"))
        self.assertEqual(self.head(self.top), before)

    def test_another_repo_does_not_touch_the_clone(self):
        other = Path(self.tmp.name) / "other"
        git(Path(self.tmp.name), "init", "-q", str(other))
        self.land()
        before = self.head(self.top)
        self.fire(cwd=other)
        self.assertEqual(self.head(self.top), before)

    def test_mcp_merge_naming_the_repo_syncs(self):
        git(self.top, "remote", "set-url", "origin", "https://github.com/o/r.git")
        git(self.top, "config", "url." + str(self.remote) + ".insteadOf", "https://github.com/o/r.git")
        self.land()
        self.fire(cwd="/", tool_name="mcp__github-pat__merge_pull_request",
                  tool_input={"owner": "o", "repo": "r", "pullNumber": 1})
        self.assertEqual(self.head(self.top), self.head(self.agent))

    def test_stop_catches_an_auto_merge_that_landed_later(self):
        self.land()
        self.fire(event="Stop")
        self.assertEqual(self.head(self.top), self.head(self.agent))

    def test_disjoint_uncommitted_edits_survive(self):
        self.write(self.top, "b.txt", "mine\n")
        self.land("a.txt")
        self.fire()
        self.assertEqual(self.head(self.top), self.head(self.agent))
        self.assertEqual((self.top / "b.txt").read_text(), "mine\n")

    def test_keep_policy_leaves_clashing_edits_alone(self):
        self.write(self.top, "a.txt", "mine\n")
        self.land("a.txt")
        before = self.head(self.top)
        out = self.fire()
        self.assertEqual(self.head(self.top), before)
        self.assertEqual((self.top / "a.txt").read_text(), "mine\n")
        self.assertIn("a.txt", out["systemMessage"])

    def test_upstream_policy_takes_upstream_and_keeps_a_backup(self):
        self.policy("upstream")
        self.write(self.top, "a.txt", "mine\n")
        self.land("a.txt")
        self.fire()
        self.assertEqual(self.head(self.top), self.head(self.agent))
        self.assertEqual((self.top / "a.txt").read_text(), "upstream\n")
        refs = git(self.top, "for-each-ref", "--format=%(refname)", "refs/clone-sync").stdout.split()
        self.assertEqual(len(refs), 1)
        self.assertEqual(git(self.top, "show", f"{refs[0]}:a.txt").stdout, "mine\n")

    def test_local_commit_is_rebased_onto_upstream(self):
        self.write(self.top, "b.txt", "local\n")
        git(self.top, "commit", "-qam", "local")
        self.land("a.txt")
        self.fire()
        log = git(self.top, "log", "--format=%s", "-2").stdout.split("\n")[:2]
        self.assertEqual(log, ["local", "change a.txt"])

    def test_conflicting_local_commit_aborts_and_leaves_the_clone_as_it_was(self):
        self.write(self.top, "a.txt", "local\n")
        git(self.top, "commit", "-qam", "local")
        before = self.head(self.top)
        self.land("a.txt")
        out = self.fire()
        self.assertEqual(self.head(self.top), before)
        self.assertTrue(self.clean_state())
        self.assertIn("aborted", out["systemMessage"])

    def test_clone_on_another_branch_is_left_alone(self):
        git(self.top, "switch", "-qc", "play")
        self.land()
        before = self.head(self.top)
        self.assertIsNone(self.fire())
        self.assertEqual(self.head(self.top), before)

    def test_half_done_merge_is_reported_not_touched(self):
        self.write(self.top, "a.txt", "local\n")
        git(self.top, "commit", "-qam", "local")
        self.land("a.txt")
        git(self.top, "fetch", "-q")
        git(self.top, "merge", "-q", "origin/main", check=False)
        out = self.fire()
        self.assertIn("half-done", out["systemMessage"])
        gd = Path(git(self.top, "rev-parse", "--absolute-git-dir").stdout.strip())
        self.assertTrue((gd / "MERGE_HEAD").exists())

    def test_already_current_says_nothing(self):
        self.assertIsNone(self.fire())


if __name__ == "__main__":
    unittest.main()
