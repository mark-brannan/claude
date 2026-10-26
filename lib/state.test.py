#!/usr/bin/env python3
# Tests for lib/state.py. Run: python3 lib/state.test.py
#
# What matters: the lookup's search path (an explicit CLAUDE_STATE_REPO
# wins, a machine with no repo gets the local fallback); the archivable
# answer's session-live gate (dotfiles#167), its carve-outs and its home
# line; the mkdir locks (dotfiles#161) that bash takes too; the small
# formatters; and, through the command line the shell tools call, work
# records, the work-item store, ruling readiness and branch_brief.
#
# Cost per push: a few seconds (one deliberate lock wait, real git repos), a
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
from unittest import mock
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

    def test_a_lib_dir_on_its_own_answers(self):
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

    # --- the command line: stdout and exit codes the shell functions had -----
    def cli(self, *args):
        p = subprocess.run([sys.executable, str(LIB), *args], capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        return p.returncode, p.stdout, p.stderr

    def test_cli_with_a_repo(self):
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        self.assertEqual(self.cli("state_repo")[:2], (0, str(repo)), "no trailing newline")
        self.assertEqual(self.cli("state_dir")[:2], (0, f"{repo}/state/global"))
        self.assertEqual(self.cli("state_shard_path", "/d", "ab1.json", "ab1")[:2], (0, "/d/ab/ab1.json"))
        self.assertEqual(self.cli("state_shard_path", "/d", "x.json", "")[:2], (0, "/d/_/x.json"))

    def test_cli_without_a_repo(self):
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        self.assertEqual(self.cli("state_repo")[:2], (1, ""), "state_repo returned 1 and printed nothing")
        self.assertEqual(self.cli("state_dir")[:2], (0, f"{self.T}/home/.claude/state/global"))

    def test_cli_usage_errors(self):
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli("nope")[0], 2)
        self.assertEqual(self.cli("state_shard_path", "/d")[0], 2)

    def test_cli_predicate_exit_codes(self):
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        self.assertEqual(self.cli("state_is_repo")[:2], (0, ""))
        os.environ["CLAUDE_STATE_REPO"] = str(self.T / "none")
        if not any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.assertEqual(self.cli("state_is_repo")[:2], (1, ""))
        self.assertEqual(self.cli("state_is_repo", "extra")[0], 2)

    def test_cli_error_inside_a_function_is_not_a_usage_error(self):
        mod = self.state
        def boom(a):
            raise TypeError("inner")
        mod.CLI["boom"] = boom
        try:
            with self.assertRaises(TypeError):
                mod.main(["boom", "x"])
            self.assertEqual(mod.main(["boom"]), 2)
        finally:
            del mod.CLI["boom"]

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

    # --- names_branch, items_dir, board_union: branch-home-gate.py's board ----
    def test_names_branch(self):
        nb = self.state.names_branch
        self.assertTrue(nb("the work is on claude/homed, then", "claude/homed"), "a trailing comma is stripped")
        self.assertFalse(nb("on claude/homed.", "claude/homed"), "a period is a branch character, as in the shell")
        self.assertTrue(nb("on `claude/homed`, then", "claude/homed"))
        self.assertFalse(nb("on claude/homed-extra", "claude/homed"), "a longer branch is not this one")
        self.assertFalse(nb("on xclaude/homed", "claude/homed"))
        self.assertFalse(nb("anything", ""), "no branch is never named")

    def test_items_dir_and_board_union(self):
        os.environ["CLAUDE_STATE_REPO"] = str(self.T / "sr")
        (self.T / "sr" / ".git").mkdir(parents=True)
        os.environ.pop("WORK_ITEM_DIR", None)
        self.assertEqual(self.state.items_dir(), f"{self.T}/sr/state/global/items")
        d = self.T / "items"
        os.environ["WORK_ITEM_DIR"] = str(d)
        self.assertEqual(self.state.items_dir(), str(d))
        self.assertEqual(self.state.board_union(), "", "no store, no board")
        d.mkdir()
        os.environ["WORK_ITEM_BIN"] = str(LIB.parent.parent / "bin" / "work-item")
        (d / "1790000000aaaaaaaa.md").write_text(
            "# T\n\n## Brief\nOn `claude/x`.\n\n## Log\n2026-10-03T05:00:00Z 1d68120b status=open owner=agent "
            "repo=- parent=- model=- effort=-\n")
        board = self.state.board_union()
        self.assertTrue(board.startswith("## Claude's\n- [ ] "), board)
        self.assertTrue(self.state.names_branch(board, "claude/x"))

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
        # A fake hook dir: branch-home-gate.py says "home" and names the
        # branch's card; the claims come from an items/ store, as work-item
        # reads them.
        self.FAKE = self.T / "hooks"
        self.FAKE.mkdir()
        gate = self.FAKE / "branch-home-gate.py"
        gate.write_text('import sys\nprint("pr https://github.com/o/r/pull/1" if sys.argv[1] == "--card" '
                        'else "home: pr https://github.com/o/r/pull/1")\n')
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

    def test_push_locked_refuses_a_held_lock_and_runs_then_releases_a_free_one(self):
        self.state.STATE_PUSH_LOCK = self.LOCK
        self.hold(os.getpid())
        orig = self.state.state_lock_wait
        with mock.patch.object(self.state, "state_lock_wait", lambda d, secs: orig(d, 0)):
            self.assertEqual(self.state.push_locked("exit 0")[0], 1)
        shutil.rmtree(self.LOCK)
        self.assertEqual(self.state.push_locked("exit 3"), (3, ""))
        self.assertFalse(os.path.exists(self.LOCK), "the lock is released after the command")

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


# --- through the command line, as the shell tools call it ---------------------
def cli(*args, env=None, stdin=None, lib=LIB):
    p = subprocess.run([sys.executable, str(lib), *args], capture_output=True, text=True, input=stdin,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(env or {})})
    return p.returncode, p.stdout, p.stderr


def script(path, text):
    path.write_text(text)
    path.chmod(0o755)
    return path


class WorkRecordTest(Base):
    """A pickup item and a card read into one record shape: kind title status
    until claim model effort link id updated."""

    def wr(self, *args, claims=""):
        return cli("work_record", *args, env={"WORK_CLAIMS": claims})[1].rstrip("\n").replace("\x1f", "|")

    def test_pickup_item_body_lines_win(self):
        f = self.T / "2026-09-09T10-00-abcd1234.md"
        f.write_text("status: open\nupdated: 2026-09-09T10:00:00Z\nmodel: claude-sonnet-5\n"
                     "pr: https://github.com/o/r/pull/7\n---\n\nFinish the thing\n"
                     "link: https://github.com/o/r/issues/3\nmodel: Opus\neffort: high\n")
        self.assertEqual(self.wr(str(f)), "pickup|Finish the thing|open|||opus|high|https://github.com/o/r/issues/3"
                                          "|2026-09-09T10-00-abcd1234|2026-09-09T10:00:00Z")

    def test_bare_item_falls_back_to_the_header_model(self):
        f = self.T / "2026-09-10T10-00-00000000.md"
        f.write_text("status: taken\nupdated: 2026-09-10T10:00:00Z\nmodel: claude-sonnet-5\npr: none\n---\n")
        self.assertEqual(self.wr(str(f)), "pickup||taken|||sonnet|||2026-09-10T10-00-00000000|2026-09-10T10:00:00Z")

    def test_card_fields(self):
        self.assertEqual(
            self.wr("- [ ] **Fix the gate** -- see [o/r#8](https://github.com/o/r/issues/8) model: opus effort: high"
                    " until: o/r#9 merges", "2026-09-11T00:00:00Z"),
            "card|Fix the gate|open|o/r#9 merges||opus|high|https://github.com/o/r/issues/8"
            "|https://github.com/o/r/issues/8|2026-09-11T00:00:00Z")
        self.assertEqual(self.wr("- [ ] tidy the docs ([log](log/2026-09-01.md))"),
                         "card|tidy the docs (log)|open|||||log/2026-09-01.md|log/2026-09-01.md|",
                         "title from its link text, absent fields empty")

    def test_claims(self):
        card = "- [ ] **Held** ([x](https://example.invalid/h))"
        live = "live\tabcd1234\thost-x\t3m\thttps://example.invalid/h\nlive\teeeeeeee\thost-y\t1m\thttps://example.invalid/other"
        self.assertEqual(self.wr(card, claims=live),
                         "card|Held|taken||abcd1234|||https://example.invalid/h|https://example.invalid/h|")
        self.assertEqual(self.wr(card, claims="stale\tabcd1234\thost-x\t300m\thttps://example.invalid/h").split("|")[2],
                         "open", "a stale claim leaves it open")

    def test_same_field_count_for_both_kinds(self):
        f = self.T / "a.md"
        f.write_text("status: open\n---\nT\n")
        self.assertEqual(len(self.wr(str(f)).split("|")), 10)
        self.assertEqual(len(self.wr("- [ ] **A** ([x](https://example.invalid/a))").split("|")), 10)

    def test_work_records_reads_cards_from_stdin_then_files(self):
        f = self.T / "p.md"
        f.write_text("status: open\n---\nPicked\n")
        out = cli("work_records", "--cards", str(f), env={"WORK_CLAIMS": ""},
                  stdin="2026-01-01T00:00:00Z\t- [ ] **C** ([x](https://example.invalid/c))\n")[1]
        self.assertEqual([ln.split("\x1f")[0] for ln in out.splitlines()], ["card", "pickup"])
        self.assertEqual(out.splitlines()[0].split("\x1f")[9], "2026-01-01T00:00:00Z")


class StoreTest(Base):
    """The work-item store is the whole board: a kanban.md beside it is never
    opened, and an item's claim is its log's."""
    WI = str(LIB.parent.parent / "bin" / "work-item")

    def setUp(self):
        super().setUp()
        self.items = self.T / "ki" / "items"
        self.items.mkdir(parents=True)
        (self.T / "ki" / "kanban.md").write_text(
            "# Board\n\n## Claude's\n\n- [ ] **Old** ([x](https://example.invalid/o)) id: 1790836860aaaaaaaa\n")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for args in (("1790836861aaaaaaaa", "Old moved", "agent", "-", "ready", "**Old moved** -- an item id: 1790836861aaaaaaaa"),
                     ("1790836862aaaaaaaa", "Stored ruling", "human-ruling", "o/colregs", "ready", "Decide it."),
                     ("1790836863aaaaaaaa", "Blocked one", "agent", "-", "blocked", "Waits."),
                     ("1790836864aaaaaaaa", "Held one", "agent", "-", "claimed", "Held.", now, "abcd1234"),
                     ("1790836865aaaaaaaa", "Stale hold", "agent", "-", "claimed", "Let go.", "2026-09-01T00:00:00Z", "eeeeeeee"),
                     ("1790836866aaaaaaaa", "Done one", "agent", "-", "done", "Over."),
                     ("1790836867aaaaaaaa", "Click it", "human-click", "-", "ready", "In the UI.")):
            self.item(*args)

    def item(self, id_, title, owner, repo, status, brief, at="2026-10-03T05:00:00Z", holder="1d68120b"):
        (self.items / f"{id_}.md").write_text(
            f"# {title}\n\n## Brief\n{brief}\n\n## Log\n{at} 1d68120b status=open owner={owner} repo={repo} "
            f"parent=- model=- effort=-\n{at} {holder} status={status}\n")

    def st(self, *args, items=None, stdin=None, **env):
        return cli(*args, stdin=stdin, env={"WORK_ITEM_DIR": str(items or self.items), "WORK_ITEM_BIN": self.WI,
                                            "HOOK_DIR": "/nonexistent", **env})

    def test_claude_cards_are_the_agents_ready_and_claimed_items(self):
        out = self.st("claude_cards")[1]
        titles = [re.sub(r"^(- \[ \] )?(\*\*[^*]+\*\*).*", r"\2", ln.split("\t", 1)[1]) for ln in out.splitlines()]
        self.assertEqual(titles, ["**Old moved**", "**Held one**", "**Stale hold**"])
        self.assertEqual(out.splitlines()[0].split("\t")[0], "2026-10-03T05:00:00Z", "updated is the newest log line")

    def test_board_card(self):
        self.assertEqual(self.st("board_card", "1790836862aaaaaaaa")[1],
                         "Needs ruling\tcolregs\t- [ ] **Stored ruling**: Decide it. repo: o/colregs id: 1790836862aaaaaaaa\n")
        self.assertEqual(self.st("board_card", "1790836861aaaaaaaa")[1].split("\t")[0], "Claude's")
        self.assertEqual(self.st("board_card", "1790836866aaaaaaaa")[1].split("\t")[0], "Done", "the done queue too")
        self.assertEqual(self.st("board_card", "1790836860aaaaaaaa")[:2], (1, ""), "a kanban.md card is not found")

    def test_board_union_is_the_items_by_section(self):
        heads = [ln for ln in self.st("board_union")[1].splitlines() if ln.startswith("##")]
        self.assertEqual(heads, ["## Needs ruling", "### colregs", "## Human's", "## Claude's"])

    def test_an_items_claim_is_its_logs(self):
        def rec(title):
            cards = "".join(ln + "\n" for ln in self.st("claude_cards")[1].splitlines() if title in ln)
            os.environ.pop("WORK_CLAIMS", None)  # unset: work_records loads the claims itself
            return self.st("work_records", "--cards", stdin=cards)[1].split("\x1f")
        self.assertEqual(rec("Held one")[2:5:2], ["taken", "abcd1234"])
        self.assertEqual(rec("Stale hold")[2:5:2], ["open", ""])

    def test_done_rows_are_the_done_items_only(self):
        self.assertEqual([ln.split("\t")[0] for ln in self.st("done_rows")[1].splitlines()], ["1790836866aaaaaaaa"])

    def test_no_items_dir_is_an_empty_board(self):
        none = self.T / "none"
        for fn in ("claude_cards", "board_union", "item_rows"):
            self.assertEqual(self.st(fn, items=none)[:2], (0, ""), fn)

    def test_an_empty_store_is_healthy(self):
        empty = self.T / "empty"
        empty.mkdir()
        self.assertEqual(self.st("item_rows", items=empty), (0, "", ""))
        self.assertEqual(self.st("done_rows", items=empty), (0, "", ""))

    def test_a_store_that_cannot_be_read_exits_3_with_the_cause(self):
        broken = script(self.T / "broken", "import sys\nprint('python exploded', file=sys.stderr)\nsys.exit(4)\n")
        for fn in ("item_rows", "done_rows", "done_board"):
            rc, out, err = self.st(fn, WORK_ITEM_BIN=str(broken))
            self.assertEqual((rc, out), (3, ""), fn)
            self.assertEqual(err, f"BROKEN STORE -- work-item list failed (exit 4): python exploded\n", fn)

    def test_a_missing_work_item_is_a_broken_store(self):
        lib = self.T / "lib"
        lib.mkdir()
        for f in ("state.py", "gitrun.py", "atomic.py", "jsonl.py"):
            shutil.copy(LIB.parent / f, lib / f)
        rc, _, err = cli("item_rows", lib=lib / "state.py",
                         env={"WORK_ITEM_DIR": str(self.items), "WORK_ITEM_BIN": "", "HOOK_DIR": "", "HOME": "/nonexistent"})
        self.assertEqual((rc, err), (3, "BROKEN STORE -- work-item not found\n"))

    def test_primed_rows_are_read_instead_of_listing(self):
        f = self.T / "rows"
        f.write_text("1790836899aaaaaaaa\tagent\tready\t\t2026-01-01T00:00:00Z\t-\t- [ ] **Primed**\n")
        self.assertEqual(self.st("claude_cards", ITEM_ROWS_FILE=str(f))[1], "2026-01-01T00:00:00Z\t- [ ] **Primed**\n")

    def test_the_default_store_is_items_in_the_state_dir(self):
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        self.assertEqual(cli("items_dir", env={"WORK_ITEM_DIR": "", "CLAUDE_STATE_REPO": str(repo)})[1],
                         f"{repo}/state/global/items")


class RulingReadinessTest(Base):
    """gh is faked: the reply for ref n is read from state.<n>, every call logged."""

    def setUp(self):
        super().setUp()
        self.rr = self.T / "rr"
        (self.rr / "bin").mkdir(parents=True)
        script(self.rr / "bin" / "gh", '#!/bin/sh\nn=""; for a in "$@"; do case $a in n=*) n=${a#n=} ;; esac; done\n'
               f'echo "$n" >> "{self.rr}/gh.log"\n[ -f "{self.rr}/state.$n" ] && cat "{self.rr}/state.$n" || exit 1\n')
        (self.rr / "gh.log").write_text("")

    def ready(self, card, **env):
        return cli("ruling_readiness", card, env={"PATH": f"{self.rr}/bin:{os.environ['PATH']}",
                                                  "XDG_CACHE_HOME": str(self.rr / "cache"),
                                                  "RULING_TODAY": "2026-10-01", **env})[1].strip()

    def test_dates_and_words(self):
        for card, want in (("x until: 2026-09-12 (2.2, before 1.8 risk: y", "ready"),
                           ("x until: 2026-10-01. risk: y", "ready"),
                           ("x until: 2026-10-05 risk: y", "waiting"),
                           ("x until: M6 card, 2026-09-30 judgment: risk", "ready"),
                           ("x until: the next session rooted in dotfiles risk: z", "waiting"),
                           ("x until: before #15 or #16 is picked up risk: z", "waiting"),
                           ("x kind: tentative ADR settle: y", "ready"),
                           ("x until: next week risk: 2026-01-01 outage", "waiting")):
            self.assertEqual(self.ready(card), want, card)

    def test_links(self):
        for n, st in ((1, "pr-open"), (2, "issue-open"), (3, "issue-inflight"), (4, "issue-closed")):
            (self.rr / f"state.{n}").write_text(st)
        for card, want in (("x until: https://github.com/o/r/pull/1 risk: y", "ready"),
                           ("x until: [o/r#2](https://github.com/o/r/issues/2) risk: y", "waiting"),
                           ("x until: o/r#3 risk: y", "ready"),
                           ("x until: o/r#4 risk: y", "ready"),
                           ("x until: o/r#5 risk: y", "ready")):
            self.assertEqual(self.ready(card), want, card)
        (self.rr / "state.2").write_text("pr-merged")
        self.assertEqual(self.ready("x until: o/r#2 risk: y"), "waiting", "a cached state is reused within the TTL")
        self.ready("x until: o/r#5 risk: y")
        self.assertEqual((self.rr / "gh.log").read_text().split(), ["1", "2", "3", "4", "5", "5"],
                         "gh asked once per ref, failures not cached")
        (self.rr / "gh.log").write_text("")
        self.assertEqual(self.ready("x until: o/r#2 risk: y", RULING_REF_TTL="0", RULING_REF_CACHE_ONLY="1"),
                         "waiting", "cache-only takes a stale entry")
        self.assertEqual(self.ready("x until: o/r#6 risk: y", RULING_REF_CACHE_ONLY="1"), "ready")
        self.assertEqual((self.rr / "gh.log").read_text(), "", "cache-only never calls gh")
        self.assertEqual(self.ready("x until: o/r#2 risk: y", RULING_REF_TTL="0"), "ready", "past the TTL gh is asked again")

    def test_until_on_a_later_line(self):
        self.assertEqual(self.ready("x risk: y\n  until: 2026-10-05"), "waiting")

    def test_rulings_ready_many_in_one_call(self):
        out = cli("rulings_ready", stdin="global\tx until: 2026-10-05 risk: y\n\ncolregs\tx kind: z\n",
                  env={"RULING_TODAY": "2026-10-01", "RULING_REF_CACHE_ONLY": "1"})[1]
        self.assertEqual(out, "waiting\tglobal\tx until: 2026-10-05 risk: y\nready\tcolregs\tx kind: z\n")


class BranchBriefTest(Base):
    """Every case builds a real repo with a real bare remote: branch_brief
    reports what git says. gh is stubbed (GH_MODE none, pr -> one open PR on
    `release`, fail), and git fails one count on demand, so the "git could
    not answer" branches are tested rather than asserted."""

    def setUp(self):
        super().setUp()
        os.environ["GIT_CONFIG_SYSTEM"] = "/dev/null"
        b = self.T / "bin"
        b.mkdir()
        script(b / "gh", '#!/bin/sh\ncase "${GH_MODE:-none}" in pr) echo release ;; fail) exit 1 ;; *) : ;; esac\n')
        script(b / "git", '#!/bin/sh\n'
               'if [ -n "${GIT_FAIL_MERGES:-}" ]; then case " $* " in *" --merges "*) exit 128 ;; esac; fi\n'
               'if [ -n "${GIT_FAIL_LEFTRIGHT:-}" ]; then case " $* " in *" --left-right "*) exit 128 ;; esac; fi\n'
               'if [ -n "${GIT_FAIL_RANGE:-}" ]; then case " $* " in *" rev-list origin/"*) exit 128 ;; esac; fi\n'
               f'exec {shutil.which("git")} "$@"\n')
        os.environ["PATH"] = f"{b}:{os.environ['PATH']}"

    def g(self, r, *args):
        return subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True, text=True).stdout.strip()

    def new_repo(self, name):
        r = self.T / name
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", f"{r}.git"], check=True)
        subprocess.run(["git", "clone", "-q", f"{r}.git", str(r)], check=True, capture_output=True)
        for k, v in (("user.email", "t@e"), ("user.name", "T"), ("commit.gpgsign", "false")):
            self.g(r, "config", k, v)
        self.commit(r, "base\n", "base")
        self.g(r, "push", "-q", "origin", "main")
        self.g(r, "remote", "set-head", "origin", "-a")
        self.g(r, "checkout", "-qb", "feat")
        return r

    def commit(self, r, text, msg, path="f"):
        (r / path).write_text(text)
        self.g(r, "add", path)
        self.g(r, "commit", "-qm", msg)

    def fake_signed(self, r, subject, text=None):
        """A commit carrying a gpgsig header: presence is what branch_brief
        tests, validity is GitHub's job."""
        if text is not None:
            (r / "f").write_text(text)
            self.g(r, "add", "f")
        obj = subprocess.run(["git", "-C", str(r), "hash-object", "-t", "commit", "-w", "--stdin"], check=True,
                             capture_output=True, text=True, input=(
            f"tree {self.g(r, 'write-tree')}\nparent {self.g(r, 'rev-parse', 'HEAD')}\n"
            "author T <t@e> 1700000000 +0000\ncommitter T <t@e> 1700000000 +0000\n"
            "gpgsig -----BEGIN SSH SIGNATURE-----\n Zm9v\n -----END SSH SIGNATURE-----\n\n" f"{subject}\n")).stdout.strip()
        self.g(r, "update-ref", "HEAD", obj)

    def brief(self, r, br="feat", **env):
        rc, out, _ = cli("branch_brief", str(r), br, env=env)
        return rc, out.splitlines()

    def rec(self, lines):
        return next(ln for ln in lines if ln.startswith("recommend: "))

    def test_clean_branch_needs_nothing_on_the_base(self):
        r = self.new_repo("clean")
        self.fake_signed(r, "feat work", "base\nfeat\n")
        self.g(r, "checkout", "-q", "main")  # the brief is about a branch, not HEAD
        rc, out = self.brief(r)
        self.assertEqual(rc, 0)
        for ln in ("base: main (default branch, no open PR)", "ahead: 1", "behind: 0", "conflicts: no",
                   "unsigned: 0", "merges: 0", "worktrees: none"):
            self.assertIn(ln, out)
        self.assertRegex(self.rec(out), r"^recommend: nothing on the base -- .*behind origin/main is left as is")

    def test_conflicting_branch_merges_and_never_linearizes(self):
        r = self.new_repo("conflict")
        self.fake_signed(r, "feat work", "base\ntheirs\n")
        self.g(r, "push", "-q", "origin", "HEAD:refs/heads/scratch")
        self.g(r, "checkout", "-q", "main")
        self.commit(r, "base\nours\n", "main moves")
        self.g(r, "push", "-q", "origin", "main")
        self.g(r, "checkout", "-q", "feat")
        out = self.brief(r)[1]
        self.assertIn("conflicts: yes", out)
        self.assertIn("behind: 1", out)
        self.assertRegex(self.rec(out), r"^recommend: git merge origin/main .*never linearize")

    def test_merge_commits_outrank_everything(self):
        r = self.new_repo("merged")
        self.g(r, "checkout", "-q", "main")
        self.commit(r, "base\nmain\n", "main moves")
        self.g(r, "push", "-q", "origin", "main")
        self.g(r, "checkout", "-q", "feat")
        self.commit(r, "other\n", "feat work", path="g")
        self.g(r, "merge", "-q", "--no-edit", "origin/main")
        out = self.brief(r)[1]
        self.assertIn("merges: 1", out)
        self.assertRegex(self.rec(out), r"^recommend: do not rebase and do not resign")
        self.assertIn("cannot be re-signed without losing the merge", self.rec(out))

    def test_unsigned_with_and_without_a_key(self):
        r = self.new_repo("unsigned")
        self.commit(r, "base\nfeat\n", "feat work")
        out = self.brief(r)[1]
        self.assertIn("unsigned: 1", out)
        self.assertRegex(self.rec(out), r"^recommend: cannot sign on this machine")
        self.g(r, "config", "user.signingkey", "/dev/null")
        out = self.brief(r)[1]
        self.assertRegex(self.rec(out), r"^recommend: git rebase -S --force-rebase [0-9a-f]{7,}")
        self.assertIn("git push --force-with-lease", self.rec(out))

    def test_the_base_comes_from_the_open_pr(self):
        r = self.new_repo("stacked")
        self.g(r, "push", "-q", "origin", "main:refs/heads/release")
        self.g(r, "fetch", "-q", "origin")
        self.fake_signed(r, "feat work", "base\nfeat\n")
        out = self.brief(r, GH_MODE="pr")[1]
        self.assertIn("base: release (open PR)", out)
        self.assertIn("behind origin/release is left as is", self.rec(out))
        out = self.brief(r, GH_MODE="fail")[1]
        self.assertTrue(any(ln.startswith("base: main (assumed") for ln in out), out)

    def test_no_base_ref_is_unknown_never_zero(self):
        r = self.new_repo("nobase")
        self.fake_signed(r, "feat work")
        self.g(r, "update-ref", "-d", "refs/remotes/origin/main")
        self.g(r, "remote", "set-head", "-d", "origin")
        out = self.brief(r)[1]
        self.assertIn("behind: unknown", out)
        self.assertRegex(self.rec(out), r"^recommend: no base to compare against here")

    def test_a_failed_count_is_unknown_and_never_recommends_a_rebase(self):
        r = self.new_repo("failcount")
        self.fake_signed(r, "feat work")
        out = self.brief(r, GIT_FAIL_MERGES="1")[1]
        self.assertIn("merges: unknown", out)
        self.assertRegex(self.rec(out), r"^recommend: count the merge commits by hand")
        out = self.brief(r, GIT_FAIL_LEFTRIGHT="1")[1]
        self.assertIn("ahead: unknown", out)
        self.assertIn("behind: unknown", out)
        out = self.brief(r, GIT_FAIL_RANGE="1")[1]
        self.assertIn("unsigned: unknown", out)
        self.assertRegex(self.rec(out), r"^recommend: check the signatures by hand")

    def test_worktrees_holding_the_branch_are_named(self):
        r = self.new_repo("held")
        self.g(r, "checkout", "-q", "main")
        self.g(r, "worktree", "add", "-q", str(self.T / "held wt"), "feat")
        out = self.brief(r)[1]
        self.assertTrue(any(ln.startswith(f"worktrees: {self.T}/held wt ") for ln in out), out)

    def test_a_missing_branch_is_an_error(self):
        r = self.new_repo("missing")
        rc, out = self.brief(r, br="nope")
        self.assertEqual(rc, 1)
        self.assertTrue(out[0].startswith("error: no branch nope"), out)


if __name__ == "__main__":
    unittest.main()
