#!/usr/bin/env python3
# Tests for statusline-metrics.py. Run: python3 hooks/statusline-metrics.test.py
#
# Cost per push: about 2 seconds, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed the statusLine
# JSON on stdin, with HOME pointed at a throwaway dir. STATUSLINE_HOOK names
# another script to drive through the same command line (the parity run
# against the old shell hook used it); a .sh runs under bash.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("STATUSLINE_HOOK") or Path(__file__).resolve().parent / "statusline-metrics.py").resolve()

CACHE = {
    "repo": "claude", "branch": "claude/some-very-long-branch-name-here",
    "decisions": {"total": 3, "scoping": 1, "inline": 1, "gate": 1},
    "output_tokens": 12345, "context_peak": 150000, "last_event": "",
    "friction": {"total": 0, "correction": 0, "override": 0, "rebuke": 0},
    "blocked": {"total": 0}, "user_turns": 7, "tool_calls": 40,
    "commits": 1, "dirty": 2, "unpushed": 0,
    "elapsed_seconds": 3700, "active_seconds": 1500,
}


class StatuslineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GIT_"))}
        self.env.update(HOME=str(self.home))
        self.state = self.home / "claude_prompts_scratch"
        (self.state / ".git").mkdir(parents=True)
        self.live = self.state / "state/global/metrics/live"

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self, sid, data):
        p = self.live / sid[:2] / f"{sid}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        t = time.time() + 3600  # fresh for the staleness check, so no recompute
        os.utime(p, (t, t))

    def run_hook(self, ev):
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        raw = ev if isinstance(ev, str) else json.dumps(ev)
        return subprocess.run(cmd, input=raw.encode(), capture_output=True, env=self.env, cwd=str(self.home))

    def out(self, ev):
        p = self.run_hook(ev)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.decode("utf-8")

    def test_no_session_id_prints_nothing(self):
        self.assertEqual(self.out({"model": {}}), "")

    def test_garbage_stdin_prints_nothing(self):
        self.assertEqual(self.out("not json"), "")
        self.assertEqual(self.out(""), "")

    def test_no_cache_warming_up_with_model(self):
        self.assertEqual(self.out({"session_id": "abcd1", "model": {"display_name": "Opus"}}),
                         "Opus  ⛁ warming up")

    def test_no_cache_no_model(self):
        self.assertEqual(self.out({"session_id": "abcd1"}), "⛁ warming up")

    def test_cache_renders_row(self):
        self.cache("abcd2", CACHE)
        got = self.out({"session_id": "abcd2", "model": {"display_name": "Opus"}})
        self.assertEqual(got, "Opus  ◆ claude@claude/some-very-lo… 12k/150k ⚖ 3[1/1/1] ⚡ 0[0/0/0] "
                              " ⏱25m⟳ 1h01 ⇢ 7 ⚙ 40 ⎇ 1c2~\n")

    def test_unpushed_and_blocked_and_question(self):
        self.cache("abcd3", dict(CACHE, unpushed=2, last_event="question", blocked={"total": 4}))
        got = self.out({"session_id": "abcd3"})
        self.assertIn("⚖ 3+1?[1/1/1]", got)
        self.assertIn("⛔ 4", got)
        self.assertIn("⎇ 1c2~2↑unpushed  ← not safe to kill", got)

    def test_old_cache_without_fields_warms_up(self):
        self.cache("abcd4", {"repo": "r", "branch": "b"})
        self.assertEqual(self.out({"session_id": "abcd4"}), "⛁ warming up")

    def test_truncated_cache_warms_up(self):
        self.cache("abcd5", '{"decisions": {"total"')
        self.assertEqual(self.out({"session_id": "abcd5"}), "⛁ warming up")

    def test_clean_tree_and_no_time_drop_fields(self):
        c = dict(CACHE, commits=0, dirty=0)
        del c["elapsed_seconds"]
        self.cache("abcd6", c)
        got = self.out({"session_id": "abcd6"})
        self.assertEqual(got, "◆ claude@claude/some-very-lo… 12k/150k ⚖ 3[1/1/1] ⚡ 0[0/0/0] ⇢ 7 ⚙ 40\n")


if __name__ == "__main__":
    unittest.main()
