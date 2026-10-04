#!/usr/bin/env python3
# Tests for scoping-lock. Run: python3 bin/scoping-lock.test.py
#
# What matters: a second session refuses and names the holder, on this
# machine and from another; the holder's own re-take keeps the original time,
# so it never extends the lease; check reads the clock; a lapsed lock is
# retaken by its holder or taken over by another, saying whose it was;
# release never removes another's lock. The steps share one origin and run
# in order, so they are numbered.
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SL = Path(__file__).resolve().parent / "scoping-lock"
D = "state/global/curia/q"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class ScopingLockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        S = cls.S = Path(cls.tmp.name)
        (S / "home").mkdir()
        cls.env = {**os.environ, "HOME": str(S / "home"), "GIT_CONFIG_GLOBAL": "/dev/null",
                   "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        os.environ.update(cls.env)
        git("init", "-q", "--bare", "-b", "main", "origin.git", cwd=S)
        git("clone", "-q", "origin.git", "a", cwd=S)
        (S / "a" / D).mkdir(parents=True)
        (S / "a" / D / "digest.md").write_text("record\n")
        for args in (["add", "."], ["commit", "-qm", "init"], ["push", "-q", "origin", "HEAD:main"],
                     ["branch", "-q", "-u", "origin/main"]):
            git(*args, cwd=S / "a")
        git("clone", "-q", "origin.git", "b", cwd=S)
        # c clones a copy of origin frozen before any lock, so its sync sees none.
        git("clone", "-q", "--bare", "origin.git", "stale.git", cwd=S)
        git("clone", "-q", "stale.git", "c", cwd=S)
        cls.record = str(S / "a" / D / "digest.md")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_sl(self, repo, *args, lease=None, cwd=None, exe=None):
        env = {**self.env, "CLAUDE_STATE_REPO": str(self.S / repo)}
        if lease is not None:
            env["SCOPING_LOCK_STALE_SECS"] = str(lease)
        p = subprocess.run([sys.executable, exe or str(SL), *args], env=env, cwd=cwd,
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr

    def lock(self):
        return (self.S / "a" / D / "LOCK").read_text()

    def test_01_read_of(self):
        rc, out = self.run_sl("a", "read-of", self.record)
        self.assertRegex(out.strip(), r"^[0-9a-f]{7,}$")
        type(self).read_at = out.strip()
        with open(self.record, "a") as f:
            f.write("edit\n")
        self.assertIn("+dirty", self.run_sl("a", "read-of", self.record)[1], "an edited record is marked")
        git("checkout", "-q", "--", f"{D}/digest.md", cwd=self.S / "a")

    def test_02_first_take(self):
        self.assertEqual("free", self.run_sl("a", "read", D)[1].strip())
        self.assertIn("taken:", self.run_sl("a", "take", D, "sid-one", self.record)[1])
        line = self.lock()
        self.assertRegex(line, rf"^sid-one [0-9T:-]+Z {re.escape(self.read_at)}\n$",
                         "one line: session, time, the record commit taken after the sync")
        shown = subprocess.run(["git", "show", f"origin/main:{D}/LOCK"], cwd=self.S / "a",
                               capture_output=True, text=True).stdout
        self.assertEqual(line, shown, "the lock reached origin")
        self.assertIn("live sid-one", self.run_sl("a", "read", D)[1])
        type(self).line = line

    def test_03_others_refuse(self):
        for repo, sid in (("a", "sid-two"), ("b", "sid-three")):
            rc, out = self.run_sl(repo, "take", D, sid, "x")
            self.assertEqual(1, rc, f"{sid} on {repo} refuses")
            self.assertIn("held: sid-one", out, "and names the holder")

    def test_04_lost_race_fails_closed(self):
        # c syncs from a copy older than the lock, then its push is rejected.
        # It must leave no unpushed lock commit, which would wedge every later push.
        c = self.S / "c"
        git("remote", "set-url", "--push", "origin", str(self.S / "origin.git"), cwd=c)
        pre = subprocess.run(["git", "rev-parse", "HEAD"], cwd=c, capture_output=True, text=True).stdout
        rc, _ = self.run_sl("c", "take", D, "sid-race", "x")
        self.assertEqual(2, rc)
        self.assertEqual(pre, subprocess.run(["git", "rev-parse", "HEAD"], cwd=c,
                                             capture_output=True, text=True).stdout)

    def test_05_own_retake_keeps_the_lease(self):
        time.sleep(1)
        rc, out = self.run_sl("a", "take", D, "sid-one", self.read_at)
        self.assertEqual(0, rc)
        self.assertIn("kept, 0m of 25m", out)
        self.assertEqual(self.line, self.lock(), "the original time stays, so the lease never extends")
        self.assertIn("read moved:", self.run_sl("a", "take", D, "sid-one", "other-read")[1])
        self.run_sl("a", "take", D, "sid-one", self.read_at)

    def test_06_check(self):
        self.assertEqual((0, "ours 0m of 25m\n"), self.run_sl("a", "check", D, "sid-one"))
        self.assertEqual((1, "held sid-one 0m\n"), self.run_sl("a", "check", D, "sid-two"))
        self.assertEqual((3, "lapsed 0m\n"), self.run_sl("a", "check", D, "sid-one", lease=0))
        self.assertIn("retaken:", self.run_sl("a", "take", D, "sid-one", self.read_at, lease=0)[1])

    def test_07_release_is_the_holders_alone(self):
        rc, _ = self.run_sl("b", "release", D, "sid-three")
        self.assertEqual(1, rc)
        self.assertTrue((self.S / "a" / D / "LOCK").is_file())

    def test_08_lapsed_lock_is_taken_over(self):
        rc, out = self.run_sl("b", "take", D, "sid-three", "x", lease=0)
        self.assertEqual(0, rc)
        self.assertIn("stale: sid-one", out, "and says whose it was")
        self.assertIn("released:", self.run_sl("b", "release", D, "sid-three")[1])
        git("pull", "-q", "--rebase", cwd=self.S / "a")
        self.assertEqual("free", self.run_sl("a", "read", D)[1].strip(), "released everywhere")

    def test_09_relative_invocation(self):
        rc, _ = self.run_sl("a", "take", "state/global/curia/r", "sid-rel", self.record,
                            cwd=SL.parent, exe="./scoping-lock")
        self.assertEqual(0, rc)

    def test_10_fails_closed(self):
        self.assertEqual(2, self.run_sl("none", "take", D, "s", "x")[0], "no state repo")
        git("remote", "set-url", "origin", str(self.S / "gone.git"), cwd=self.S / "a")
        self.assertEqual(2, self.run_sl("a", "take", D, "sid-four", "x")[0], "an unreachable origin")

    def test_11_finds_the_repo_where_lib_state_sh_does(self):
        # $HOME/src is on lib-state.sh's search path, never on the old
        # private one ($CLAUDE_STATE_REPO or ~/claude_prompts_scratch only).
        home = self.S / "home11"
        git("clone", "-q", str(self.S / "origin.git"), str(home / "src" / "claude_prompts_scratch"), cwd=self.S)
        env = {k: v for k, v in self.env.items() if k != "CLAUDE_STATE_REPO"}
        p = subprocess.run([sys.executable, str(SL), "read", D], env={**env, "HOME": str(home)},
                           capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)


if __name__ == "__main__":
    unittest.main()
