#!/usr/bin/env python3
"""Tests for session-start-sync-status.py. Run: python3 hooks/session-start-sync-status.test.py

What matters: silent when ~/.claude is current and the sync did not skip it;
the sync's status line, in valid JSON, when the clone is behind or skipped;
silent and exit 0 with no clone or no sync script.

A scratch HOME holds a real clone of a local bare repo (no network) and a
stub dotfiles-sync.sh that prints a canned status. Cost per push: under a
second.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "session-start-sync-status.py"


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class SyncStatus(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.home = root / "home"
        self.origin = root / "origin.git"
        self.work = root / "work"
        git("init", "-q", "--bare", "-b", "main", str(self.origin))
        git("clone", "-q", str(self.origin), str(self.work))
        self.commit()
        self.clone = self.home / ".claude"
        self.home.mkdir()
        git("clone", "-q", str(self.origin), str(self.clone))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(HOME=str(self.home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.status("2026-10-22T08:55:05Z level with origin/main; claude: level with origin/main")

    def commit(self):
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c", cwd=self.work)
        git("push", "-q", "origin", "HEAD:main", cwd=self.work)

    def status(self, line):
        sync = self.home / ".local/bin/dotfiles-sync.sh"
        sync.parent.mkdir(parents=True, exist_ok=True)
        sync.write_text(f"#!/bin/sh\n[ \"$1\" = --status ] && echo '{line}'\nexit 0\n")

    def run_hook(self):
        p = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stderr, "")
        return json.loads(p.stdout) if p.stdout.strip() else None

    def test_current_is_silent(self):
        self.assertIsNone(self.run_hook())

    def test_behind_reports_count_and_status(self):
        self.commit()
        self.commit()
        git("fetch", "-q", cwd=self.clone)
        out = self.run_hook()
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        text = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("2 commit(s) behind origin/main", text)
        self.assertIn("claude: level with origin/main", text)
        self.assertEqual(out["systemMessage"], text)

    def test_behind_unfetched_is_silent(self):
        # No network call: a commit the clone has not fetched is not seen.
        self.commit()
        self.assertIsNone(self.run_hook())

    def test_skipped_reports_status(self):
        line = "t level; claude: skipped: 3 behind, fast-forward refused by dirty files: settings.json"
        self.status(line)
        text = self.run_hook()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("skipped by the last sync", text)
        self.assertIn(line, text)

    def test_yadm_skip_alone_is_silent(self):
        self.status("t skipped: merge or rebase in progress; claude: level with origin/main")
        self.assertIsNone(self.run_hook())

    def test_never_run_and_behind(self):
        self.status("never run")
        self.commit()
        git("fetch", "-q", cwd=self.clone)
        self.assertIn("never run", self.run_hook()["systemMessage"])

    def test_no_sync_script_is_silent(self):
        (self.home / ".local/bin/dotfiles-sync.sh").unlink()
        self.commit()
        git("fetch", "-q", cwd=self.clone)
        self.assertIsNone(self.run_hook())

    def test_no_clone_is_silent(self):
        subprocess.run(["rm", "-rf", str(self.clone / ".git")], check=True)
        self.assertIsNone(self.run_hook())

# Runs the hook named by argv[1] as Claude Code would, after the patch in
# argv[2], so a test can make it crash where no input could.
# The patch can name boom, which raises RuntimeError("boom").
WRAP = """import os, runpy, sys
def boom(*a, **k):
    raise RuntimeError("boom")
hook, patch = sys.argv.pop(1), sys.argv.pop(1)
sys.path.insert(0, os.path.dirname(hook))
exec(patch)
runpy.run_path(hook, run_name="__main__")
"""


class CrashIsTraced(unittest.TestCase):
    def test_a_crash_is_traced_not_sent_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude/.git").mkdir(parents=True)
            (home / ".local/bin").mkdir(parents=True)
            (home / ".local/bin/dotfiles-sync.sh").write_text("")
            (home / "state/.git").mkdir(parents=True)
            env = {**os.environ, "HOME": tmp, "CLAUDE_STATE_REPO": str(home / "state"), "CLAUDE_CODE_SESSION_ID": "ab3"}
            r = subprocess.run([sys.executable, "-c", WRAP, str(HOOK), "import subprocess; subprocess.run = boom"],
                               capture_output=True, text=True, env=env)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            row = json.loads((home / "state/state/global/metrics/hook-errors/ab/ab3.jsonl").read_text())
            self.assertEqual((row["hook"], row["event"], row["stage"], row["error"]),
                             ("session-start-sync-status", "SessionStart", "main", "RuntimeError: boom"))


if __name__ == "__main__":
    unittest.main()
