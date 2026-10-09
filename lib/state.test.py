#!/usr/bin/env python3
# Tests for lib/state.py. Run: python3 lib/state.test.py
#
# What matters: the lookup's search path (an explicit CLAUDE_STATE_REPO
# wins, a machine with no repo gets the local fallback); the archivable
# answer's session-live gate (dotfiles#167), its carve-outs and its home
# line; the mkdir locks (dotfiles#161) that bash takes too; and the small
# formatters. These are the cases lib-state.test.sh held for the functions
# that moved here; lib/state-parity.test.py holds the two languages equal.
#
# Cost per push: about a second and a half (one deliberate lock wait), a
# step in CI's existing tool-tests job, so no new job and nothing drawn
# from the account's concurrent-job cap.
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent / "state.py"
sys.path.insert(0, str(LIB.parent))
# These are checked before $HOME; a machine that has one cannot exercise the
# no-repo fallback.
CLOUD = ("/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch")
GITENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def load(path):
    spec = importlib.util.spec_from_file_location("state_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gitq(d, *args):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args], env={**os.environ, **GITENV},
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.T = Path(self.tmp.name)
        self.env = dict(os.environ)
        os.environ["HOME"] = str(self.T / "home")
        os.environ.pop("CLAUDE_STATE_REPO", None)
        os.environ.update(GITENV)
        self.state = load(LIB)

    def tearDown(self):
        self.state.state_unlock()
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()


class LookupTest(Base):
    def test_explicit_repo_wins(self):
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        self.assertEqual(self.state.state_repo(), str(repo))
        self.assertEqual(self.state.state_dir(), f"{repo}/state/global")
        self.assertTrue(self.state.state_is_repo())

    def test_home_path_is_on_the_search_path(self):
        repo = self.T / "home" / "src" / "claude_prompts_scratch"
        (repo / ".git").mkdir(parents=True)
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        self.assertEqual(self.state.state_repo(), str(repo))

    def test_no_repo_falls_back_locally(self):
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        self.assertIsNone(self.state.state_repo())
        self.assertFalse(self.state.state_is_repo())
        self.assertEqual(self.state.state_dir(), f"{self.T}/home/.claude/state/global")

    def test_answers_without_lib_state_sh(self):
        # It used to shell out to hooks/lib-state.sh; a lib/ on its own must
        # answer now.
        (self.T / "lib").mkdir()
        for f in ("state.py", "gitrun.py"):
            shutil.copy(LIB.parent / f, self.T / "lib" / f)
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        sys.path.insert(0, str(self.T / "lib"))
        try:
            self.assertEqual(load(self.T / "lib" / "state.py").state_dir(), f"{repo}/state/global")
        finally:
            sys.path.remove(str(self.T / "lib"))

    # --- state_shard_path: per-session files split by the id's first two chars
    def test_shard_path(self):
        sp, SH = self.state.state_shard_path, str(self.T / "shard")
        os.makedirs(SH)
        self.assertEqual(sp(SH, "3fa9-01.json", "3fa9-01"), f"{SH}/3f/3fa9-01.json",
                         "a new file goes under the first two chars of the id")
        self.assertEqual(sp(SH, "2026-01-02-repo-3fa9.md", "3fa9-01"), f"{SH}/3f/2026-01-02-repo-3fa9.md",
                         "the name need not start with the id")
        Path(SH, "3fa9-01.json").touch()
        self.assertEqual(sp(SH, "3fa9-01.json", "3fa9-01"), f"{SH}/3fa9-01.json",
                         "a file still at the flat path is used where it is")
        self.assertEqual(sp(SH, "x.json", ""), f"{SH}/_/x.json", "an empty id goes under _, never the dir itself")

    # --- decision_rate ---------------------------------------------------------
    def test_decision_rate(self):
        dr = self.state.decision_rate
        self.assertEqual(dr(3, 4200), "3 decisions in 1h10 (2.6/h)")
        self.assertEqual(dr(1, 1800), "1 decision in 0h30 (2.0/h)", "singular")
        self.assertEqual(dr(3, 0), "", "no clock, no line")


class ArchivableTest(Base):
    """archivable_reasons over a clean, pushed, homed worktree, so reasons are
    empty before the live check runs at all and a pass isolates it."""

    def setUp(self):
        super().setUp()
        origin = self.T / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
        self.WT = self.T / "work"
        subprocess.run(["git", "init", "-q", "-b", "feature", str(self.WT)], check=True)
        (self.WT / "f").write_text("x\n")
        gitq(self.WT, "add", "f")
        gitq(self.WT, "commit", "-q", "-m", "init")
        gitq(self.WT, "remote", "add", "origin", str(origin))
        gitq(self.WT, "push", "-q", "-u", "origin", "feature")
        self.origin = origin
        # A fake hook dir: branch-home-gate.sh always says "home",
        # claim-stamp.sh is swapped per case.
        self.FAKE = self.T / "hooks"
        self.FAKE.mkdir()
        gate = self.FAKE / "branch-home-gate.sh"
        gate.write_text('#!/bin/sh\necho "home: pr https://github.com/o/r/pull/1"\n')
        gate.chmod(0o755)

    def claim_stamp(self, out):
        cs = self.FAKE / "claim-stamp.sh"
        cs.write_text(f"#!/bin/sh\n[ \"$1\" = read ] || exit 0\ncat <<'STAMPS'\n{out}\nSTAMPS\n")
        cs.chmod(0o755)

    def reasons(self, sid):
        return self.state.archivable_reasons(str(self.WT), "feature", sid, str(self.FAKE))

    def test_session_live(self):
        # no claim-stamp.sh at all: behaves exactly as before the check (empty)
        self.assertEqual(self.reasons("abcd1234"), "", "no claim-stamp.sh -> archivable")
        # a live stamp belonging to someone else: blocks
        self.claim_stamp("live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1")
        self.assertIn("session live", self.reasons("abcd1234"), "other session's fresh stamp -> session live")
        # the caller's own stamp, fresh: does not block its own archival
        self.assertEqual(self.reasons("deadbeef"), "", "own fresh stamp is excluded")
        # a stale stamp: does not block
        self.claim_stamp("stale\tdeadbeef\thost-aa1\t180m\thttps://github.com/o/r/pull/1")
        self.assertEqual(self.reasons("abcd1234"), "", "stale stamp -> archivable")
        # no card / no stamps at all (claim-stamp prints nothing): does not block
        self.claim_stamp("")
        self.assertEqual(self.reasons("abcd1234"), "", "no stamps -> archivable")
        # no session id given (a sweep, not a session): a fresh stamp from
        # anyone still blocks
        self.claim_stamp("live\tdeadbeef\thost-aa1\t2m\thttps://github.com/o/r/pull/1")
        self.assertIn("session live", self.reasons(""), "no self sid, fresh stamp -> session live")

    def test_home_line_comes_back(self):
        # The Stop hook's pickup item reuses the verdict's gh answer instead
        # of asking again (PR #388, design pass).
        self.assertEqual(self.state.archivable(str(self.WT), "feature", "abcd1234", str(self.FAKE)),
                         ("", "home: pr https://github.com/o/r/pull/1"))
        (self.WT / "dirt").touch()
        self.assertEqual(self.state.archivable(str(self.WT), "feature", "abcd1234", str(self.FAKE)),
                         ("worktree dirty", None), "a dirty tree never pays for the home check")

    # --- unpushed_state: a commit on a differently-named remote branch -------
    # `mergify stack push` leaves @{u} at origin/main and pushes to
    # stack/<name>; counting @{u}..HEAD called that pushed commit unpushed.
    def test_unpushed_state_stack(self):
        STK = self.T / "stack"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(STK)], capture_output=True)
        gitq(STK, "checkout", "-q", "-b", "main", "origin/feature")
        gitq(STK, "push", "-q", "-u", "origin", "main")
        gitq(STK, "checkout", "-q", "-b", "local-stack")
        gitq(STK, "branch", "-q", "-u", "origin/main")
        (STK / "g").write_text("y\n")
        gitq(STK, "add", "g")
        gitq(STK, "commit", "-q", "-m", "stacked")
        ust = self.state.unpushed_state
        self.assertEqual(ust(str(STK), "local-stack"), "ahead 1", "commit on no remote branch, @{u}=main: ahead 1")
        gitq(STK, "push", "-q", "origin", "local-stack:refs/heads/wip/sid")
        self.assertEqual(ust(str(STK), "local-stack"), "ahead 1", "same commit only on a wip/ salvage ref: still ahead 1")
        gitq(STK, "push", "-q", "origin", "local-stack:refs/heads/stack/x")
        self.assertEqual(ust(str(STK), "local-stack"), "ahead 0", "same commit on stack/x, @{u} still main: ahead 0")
        gitq(STK, "branch", "-q", "--unset-upstream")
        self.assertEqual(ust(str(STK), "local-stack"), "safe", "no upstream, commit on a remote branch: safe")

    # --- dirty_paths: the state repo's own state/ is the hooks' to commit ----
    def test_dirty_paths(self):
        SR = self.T / "state-repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(SR)], check=True)
        (SR / "state" / "global" / "metrics").mkdir(parents=True)
        (SR / "README").touch()
        gitq(SR, "add", "README")
        gitq(SR, "commit", "-q", "-m", "init")
        (SR / "state" / "global" / "metrics" / "live.json").touch()
        os.environ["CLAUDE_STATE_REPO"] = str(SR)
        dp = self.state.dirty_paths
        self.assertEqual(dp(str(SR)), "", "hook-written state/ in the state repo is not dirt")
        (SR / "notes.txt").touch()
        self.assertEqual(dp(str(SR)), "?? notes.txt\n", "anything else in the state repo still is")
        (self.WT / "state").mkdir()
        (self.WT / "state" / "x").touch()
        self.assertEqual(dp(str(self.WT)), "?? state/\n", "state/ in any other repo still is")


class LockTest(Base):
    def setUp(self):
        super().setUp()
        self.LOCK = str(self.T / "x.lock")
        self.host = os.uname().nodename

    def hold(self, pid, host=None):
        os.makedirs(self.LOCK)
        Path(self.LOCK, "meta").write_text(f"pid={pid}\nhostname={host or self.host}\n")

    def test_acquire_writes_the_shells_meta_and_unlock_releases(self):
        self.assertTrue(self.state.state_lock(self.LOCK), "plain acquire succeeds")
        self.assertEqual(Path(self.LOCK, "meta").read_text(), f"pid={os.getpid()}\nhostname={self.host}\n")
        self.state.state_unlock()
        self.assertFalse(os.path.exists(self.LOCK), "unlock releases (dir gone after)")

    def test_contended_live_pid_fails(self):
        self.hold(os.getpid())
        self.assertFalse(self.state.state_lock(self.LOCK))

    def test_wait_gives_up_past_its_budget(self):
        # state_lock_wait is the portable `flock -w`: it gives up on a live
        # holder after its budget, and takes a lock freed while it waits.
        self.hold(os.getpid())
        self.assertFalse(self.state.state_lock_wait(self.LOCK, 0))

    def test_wait_takes_a_lock_freed_mid_wait(self):
        self.hold(os.getpid())
        t = threading.Timer(0.5, shutil.rmtree, (self.LOCK,))
        t.start()
        self.assertTrue(self.state.state_lock_wait(self.LOCK, 5))
        t.join()
        self.assertIn(f"pid={os.getpid()}\n", Path(self.LOCK, "meta").read_text())

    def test_stale_dead_pid_same_host_is_reclaimed(self):
        self.hold(999999999)
        self.assertTrue(self.state.state_lock(self.LOCK))
        self.assertIn(f"pid={os.getpid()}\n", Path(self.LOCK, "meta").read_text())

    def test_dead_pid_on_another_host_is_not_reclaimed(self):
        self.hold(999999999, host="some-other-host")
        self.assertFalse(self.state.state_lock(self.LOCK))

    # dotfiles#161: a kill between mkdir and the meta write leaves a lock dir
    # with no meta at all -- no pid to check stale-reclaim's usual way. Age
    # of the dir itself is the only signal left, so one older than
    # STATE_LOCK_STALE_SECS must reclaim, and a dir that just appeared
    # (another state_lock plausibly still mid-acquire) must not.
    def test_meta_less_lock_aged_past_threshold_is_reclaimed(self):
        os.makedirs(self.LOCK)
        old = time.time() - 30
        os.utime(self.LOCK, (old, old))
        self.assertTrue(self.state.state_lock(self.LOCK))
        self.assertIn(f"pid={os.getpid()}\n", Path(self.LOCK, "meta").read_text())

    def test_fresh_meta_less_lock_is_not_reclaimed(self):
        os.makedirs(self.LOCK)
        self.assertFalse(self.state.state_lock(self.LOCK))

    def test_push_lock_path_is_the_shells(self):
        os.environ["TMPDIR"] = str(self.T)
        self.assertEqual(load(LIB).STATE_PUSH_LOCK, f"{self.T}/claude-state-push.lock.d")
        os.environ.pop("TMPDIR")
        self.assertEqual(load(LIB).STATE_PUSH_LOCK, "/tmp/claude-state-push.lock.d")


if __name__ == "__main__":
    unittest.main()
