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
import json
import os
import re
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
        for f in ("state.py", "gitrun.py", "atomic.py", "jsonl.py"):
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
        # A fake hook dir: branch-home-gate.sh says "home" and names the
        # branch's card; the claims come from an items/ store, as work-item
        # reads them.
        self.FAKE = self.T / "hooks"
        self.FAKE.mkdir()
        gate = self.FAKE / "branch-home-gate.sh"
        gate.write_text('#!/bin/sh\nif [ "$1" = --card ]; then echo "pr https://github.com/o/r/pull/1"; '
                        'else echo "home: pr https://github.com/o/r/pull/1"; fi\n')
        gate.chmod(0o755)
        self.SL = self.T / "sl-items"
        os.environ["WORK_ITEM_DIR"] = str(self.SL)
        os.environ["WORK_ITEM_BIN"] = str(Path(__file__).resolve().parent.parent / "bin" / "work-item")
        self.NOW = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def slitem(self, id_, status, holder, log_time, brief):
        self.SL.mkdir(exist_ok=True)
        (self.SL / f"{id_}.md").write_text(
            f"# T\n\n## Brief\n{brief}\n\n## Log\n{log_time} 1d68120b status=open owner=agent repo=- parent=- model=- effort=-\n"
            f"{log_time} {holder} status={status}\n")

    def reasons(self, sid):
        return self.state.archivable_reasons(str(self.WT), "feature", sid, str(self.FAKE))

    def test_session_live(self):
        item = "1790836870aaaaaaaa"
        # no items/ at all: archivable
        self.assertEqual(self.reasons("abcd1234"), "", "no item store -> archivable")
        # another session's live claim on an item naming the branch's card: blocks
        self.slitem(item, "claimed", "deadbeef", self.NOW, "Fix it. https://github.com/o/r/pull/1")
        self.assertIn("session live", self.reasons("abcd1234"), "other session's live claim -> session live")
        # the card named as owner/repo#n (a home= fact's drawing) blocks too
        self.slitem(item, "claimed", "deadbeef", self.NOW, "Fix it. See o/r#1.")
        self.assertIn("session live", self.reasons("abcd1234"), "claim naming o/r#1 -> session live")
        # the caller's own claim does not block its own archival
        self.assertEqual(self.reasons("deadbeef"), "", "own live claim is excluded")
        # a claim on an item that names some other card: does not block
        self.slitem(item, "claimed", "deadbeef", self.NOW, "Other. https://github.com/o/r/pull/2")
        self.assertEqual(self.reasons("abcd1234"), "", "claim on another card -> archivable")
        # card 1 is not card 12 or 100, by URL or by o/r#n
        for brief in ("Other. https://github.com/o/r/pull/12", "Other. o/r#12", "Other. o/r#100 and o/r#1000"):
            self.slitem(item, "claimed", "deadbeef", self.NOW, brief)
            self.assertEqual(self.reasons("abcd1234"), "", f"{brief!r} does not name card 1")
        # ...but a later, exact mention still does
        self.slitem(item, "claimed", "deadbeef", self.NOW, "Other. o/r#12, then o/r#1.")
        self.assertIn("session live", self.reasons("abcd1234"), "a second mention that is exact blocks")
        # a stale claim (the holder's newest line is old): does not block
        self.slitem(item, "claimed", "deadbeef", "2026-09-01T00:00:00Z", "Fix it. https://github.com/o/r/pull/1")
        self.assertEqual(self.reasons("abcd1234"), "", "stale claim -> archivable")
        # an item named for the card but not claimed: does not block
        self.slitem(item, "ready", "deadbeef", self.NOW, "Fix it. https://github.com/o/r/pull/1")
        self.assertEqual(self.reasons("abcd1234"), "", "unclaimed item -> archivable")
        # no session id given (a sweep, not a session): a live claim from anyone blocks
        self.slitem(item, "claimed", "deadbeef", self.NOW, "Fix it. https://github.com/o/r/pull/1")
        self.assertIn("session live", self.reasons(""), "no self sid, live claim -> session live")

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


class DayDecisionsTest(Base):
    """The machine-wide decision store (dotfiles#301), in a scratch state repo."""

    def setUp(self):
        super().setUp()
        repo = self.T / "state-repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        self.DAYF = repo / "state" / "global" / "metrics" / "day-decisions.json"
        self.lock = Path(f"{self.DAYF}.lock")

    def day(self, *a):
        return self.state.day_decisions(*a)

    def hold(self):
        self.lock.mkdir(parents=True)
        (self.lock / "meta").write_text(f"pid={os.getpid()}\nhostname={os.uname().nodename}\n")

    def test_the_day(self):
        self.assertEqual(self.day("sess-a", 7, 1, 1000, 10800), (7, 1), "first call seeds the day")
        self.assertEqual(self.day("sess-b", 13, 2, 1100, 10800), (20, 3), "a second session sums")
        # The hook fires on every prompt, so a running total would multiply.
        self.assertEqual(self.day("sess-a", 11, 1, 1200, 10800), (24, 3), "same session is idempotent")
        self.assertEqual(self.day("sess-b", 14, 2, 11000, 10800), (25, 3), "gap under the limit keeps the day")
        self.assertEqual(self.day("sess-b", 4, 0, 30000, 10800), (4, 0), "gap past the limit resets")
        self.assertEqual(list(json.loads(self.DAYF.read_text())["sessions"]), ["sess-b"],
                         "reset drops the other sessions' contributions")
        self.assertEqual(self.day("sess-c", 5, 5, 30100, 10800), (9, 5), "junk rides beside the total")
        self.hold()
        self.assertEqual(self.day("sess-d", 99, 0, 30200, 10800), (9, 5), "contended lock writes nothing")
        shutil.rmtree(self.lock)
        self.day("sess-e", 1, 0, 30300, 10800)
        self.assertFalse(self.lock.exists(), "a call leaves no lock dir behind")

    def test_the_read_happens_inside_the_lock(self):
        # A stand-in lock writes another session's entry the moment it is taken:
        # a read before the lock would overwrite that entry.
        def lock(_d):
            self.DAYF.parent.mkdir(parents=True, exist_ok=True)
            self.DAYF.write_text('{"last_prompt": 40000, "sessions": {"sess-x": {"total": 6, "junk": 1}}}')
            return True
        real = self.state.state_lock, self.state.state_unlock
        self.state.state_lock, self.state.state_unlock = lock, lambda: None
        try:
            self.assertEqual(self.day("sess-y", 2, 0, 40100, 10800), (8, 1))
        finally:
            self.state.state_lock, self.state.state_unlock = real

    def test_interleaved_callers(self):
        self.day("sess-p", 6, 1, 41000, 10800)
        self.hold()
        self.assertEqual(self.day("sess-q", 9, 2, 41100, 10800), (6, 1), "lock held: the second caller writes nothing")
        shutil.rmtree(self.lock)
        self.assertEqual(self.day("sess-q", 9, 2, 41200, 10800), (15, 3), "lock free: the second caller lands on top")

    def test_no_store_no_lock(self):
        self.hold()
        self.assertEqual(self.day("sess-r", 3, 0, 41300, 10800), (0, 0))

    def test_no_metrics_dir_raises(self):
        bad = self.T / "bad-repo"
        (bad / ".git").mkdir(parents=True)
        (bad / "state" / "global").mkdir(parents=True)
        (bad / "state" / "global" / "metrics").touch()
        os.environ["CLAUDE_STATE_REPO"] = str(bad)
        with self.assertRaises(OSError, msg="the caller reports it; no number is made up"):
            self.day("sess-s", 3, 0, 41400, 10800)


class StopNoticeTest(Base):
    """buffered_state and verdict_explain: the lines under the Stop's 📦."""

    def setUp(self):
        super().setUp()
        self.SR = self.T / "state-repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.SR)], check=True)
        (self.SR / "state" / "global" / "metrics").mkdir(parents=True)
        (self.SR / "README").touch()
        gitq(self.SR, "add", "README")
        gitq(self.SR, "commit", "-q", "-m", "init")
        (self.SR / "state" / "global" / "metrics" / "live.json").touch()
        self.WT = self.T / "work"
        subprocess.run(["git", "init", "-q", "-b", "feature", str(self.WT)], check=True)
        os.environ["CLAUDE_STATE_REPO"] = str(self.SR)

    def test_buffered_state(self):
        bs = self.state.buffered_state
        lead = "→ buffered in the state repo, not committed yet (the next Stop commits it): "
        (self.SR / "state" / "global" / "pickup").mkdir()
        (self.SR / "state" / "global" / "pickup" / "h.md").touch()
        self.assertEqual(bs(str(self.SR)), lead + "pickup/h.md, + 1 metrics file",
                         "names the hand-off, counts the metrics")
        shutil.rmtree(self.SR / "state" / "global" / "pickup")
        (self.SR / "state" / "global" / "metrics" / "two.json").touch()
        self.assertEqual(bs(str(self.SR)), lead + "+ 2 metrics files", "metrics alone are a count")
        (self.WT / "state").mkdir()
        (self.WT / "state" / "x").touch()
        self.assertEqual(bs(str(self.WT)), "", "silent outside the state repo")
        gitq(self.SR, "add", "state/")
        gitq(self.SR, "commit", "-q", "-m", "state")
        self.assertEqual(bs(str(self.SR)), "", "silent when state/ is committed")

    def test_verdict_explain(self):
        ve = self.state.verdict_explain
        tail = "Normal mid-task: the agent commits them when the work lands. Archive the worktree only after that."
        for n in "abcd":
            (self.WT / n).touch()
        self.assertEqual(ve("not archivable: worktree dirty", str(self.WT)),
                         f"→ worktree dirty: 4 uncommitted file(s) (a, b, c, +1 more). {tail}",
                         "names three files and counts the rest")
        for n in "abcd":
            (self.WT / n).unlink()
        (self.WT / "my file").touch()
        self.assertEqual(ve("not archivable: worktree dirty", str(self.WT)),
                         f"→ worktree dirty: 1 uncommitted file(s) (my file). {tail}",
                         "a name with a space prints unquoted")
        self.assertEqual(ve("not archivable: worktree dirty"),
                         f"→ worktree dirty: uncommitted files in this worktree. {tail}",
                         "without the tree, no file list")
        self.assertEqual(len(ve("not archivable: worktree dirty, 2 commit(s) unpushed").split("\n")), 2,
                         "two reasons, one line each")
        self.assertEqual(ve("not archivable: something no explanation knows"), "", "an unknown reason has none")


class GitEventTest(Base):
    def test_matches_a_git_state_change_only(self):
        hit = lambda s: re.search(self.state.GIT_EVENT_RE, s) is not None  # noqa: E731
        for s in ("git commit -m x", "git push -u origin b", "gh pr create", "merge_pull_request"):
            self.assertTrue(hit(s), s)
        for s in ("git status", "git add -A", "ls -la", "git log", "gitcommit"):
            self.assertFalse(hit(s), s)


if __name__ == "__main__":
    unittest.main()
