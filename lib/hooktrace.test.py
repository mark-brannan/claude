#!/usr/bin/env python3
# Tests for lib/hooktrace.py. Run: python3 lib/hooktrace.test.py
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooktrace  # noqa: E402
import state  # noqa: E402


class HooktraceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.mkdir(os.path.join(self.tmp.name, ".git"))
        self.old = os.environ.get("CLAUDE_STATE_REPO")
        os.environ["CLAUDE_STATE_REPO"] = self.tmp.name
        self.sd = state.state_dir()

    def tearDown(self):
        if self.old is None:
            os.environ.pop("CLAUDE_STATE_REPO", None)
        else:
            os.environ["CLAUDE_STATE_REPO"] = self.old
        self.tmp.cleanup()

    def test_trace_writes_a_sharded_row_and_recent_reads_it(self):
        hooktrace.trace("log-commit", "main", ValueError("boom"), session_id="abc123", event="PostToolUse")
        row = json.loads(Path(f"{self.sd}/metrics/hook-errors/ab/abc123.jsonl").read_text())
        self.assertEqual((row["hook"], row["stage"], row["error"], row["event"]),
                         ("log-commit", "main", "ValueError: boom", "PostToolUse"))
        self.assertEqual(hooktrace.recent(self.sd), [row])

    def test_once_skips_a_repeat_in_the_same_session(self):
        for err in ("bad line", "bad line", "other"):
            hooktrace.trace("spend-gate", "line", ValueError(err), session_id="abc9", once=True)
        hooktrace.trace("spend-gate", "line", ValueError("bad line"), session_id="abc9")  # once=False: always
        hooktrace.trace("spend-gate", "line", ValueError("bad line"), session_id="abd0", once=True)  # another session
        rows = [json.loads(ln) for ln in Path(f"{self.sd}/metrics/hook-errors/ab/abc9.jsonl").read_text().splitlines()]
        self.assertEqual([r["error"] for r in rows], ["ValueError: bad line", "ValueError: other", "ValueError: bad line"])
        self.assertTrue(Path(f"{self.sd}/metrics/hook-errors/ab/abd0.jsonl").exists())

    def test_a_flat_file_is_still_appended_to(self):
        d = f"{self.sd}/metrics/hook-errors"
        os.makedirs(d)
        Path(f"{d}/abc.jsonl").write_text("")
        hooktrace.trace("h", "s", OSError("x"), session_id="abc")
        self.assertEqual(len(hooktrace.recent(self.sd)), 1)

    def test_error_is_cut(self):
        hooktrace.trace("h", "s", ValueError("x" * 900), session_id="zz9")
        self.assertLessEqual(len(hooktrace.recent(self.sd)[0]["error"]), hooktrace.ERROR_MAX)

    def test_unwritable_falls_back_to_stderr(self):
        # state_dir() lands on $HOME/.claude/state/global when no repo is
        # found; make that a path under a regular file so the write fails.
        blocker = os.path.join(self.tmp.name, "blocker")
        Path(blocker).write_text("")
        env = dict(os.environ)
        os.environ["CLAUDE_STATE_REPO"] = ""
        os.environ["HOME"] = blocker
        err = io.StringIO()
        try:
            with mock.patch.object(state, "state_repo", return_value=None), contextlib.redirect_stderr(err):
                hooktrace.trace("h", "s", ValueError("lost"), session_id="q")
        finally:
            os.environ["HOME"] = env["HOME"]
        self.assertIn("trace not written", err.getvalue())

    def test_recent_window_and_bad_lines(self):
        d = f"{self.sd}/metrics/hook-errors/ol"
        os.makedirs(d)
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3 * 86400))
        Path(f"{d}/old.jsonl").write_text(json.dumps({"ts": old, "hook": "h"}) + "\nnot json\n")
        hooktrace.trace("h", "s", ValueError("new"), session_id="new1")
        self.assertEqual([r["error"] for r in hooktrace.recent(self.sd)], ["ValueError: new"])
        self.assertEqual(len(hooktrace.recent(self.sd, since_seconds=10 * 86400)), 2)

    def test_summary(self):
        self.assertEqual(hooktrace.summary([]), "")
        rows = [{"hook": "a", "stage": "x", "error": "E: 1"}, {"hook": "a", "stage": "y", "error": "E: 2"},
                {"hook": "b", "stage": "z", "error": "E: 3"}]
        self.assertEqual(hooktrace.summary(rows),
                         "a x2 (latest, stage y: E: 2); b x1 (latest, stage z: E: 3)")


if __name__ == "__main__":
    unittest.main()
