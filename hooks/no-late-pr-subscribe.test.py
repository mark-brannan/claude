#!/usr/bin/env python3
# Tests for no-late-pr-subscribe.py. Run: python3 hooks/no-late-pr-subscribe.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case writes a transcript whose last assistant usage block carries a
# chosen context size and runs the hook as Claude Code does, a subprocess fed
# the PreToolUse payload. NO_LATE_PR_SUBSCRIBE_HOOK names another script to
# drive the same way (the parity run against the old shell hook used it); a
# .sh runs under bash.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("NO_LATE_PR_SUBSCRIBE_HOOK")
            or Path(__file__).resolve().parent / "no-late-pr-subscribe.py").resolve()


def usage_line(inp=0, read=0, create=0):
    return json.dumps({"type": "assistant", "message": {"usage": {
        "input_tokens": inp, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create}}})


class NoLatePrSubscribeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, lines=None, payload=None, **env):
        if payload is None:
            t = self.dir / "t.jsonl"
            t.write_text("\n".join(lines or []) + "\n")
            payload = json.dumps({"transcript_path": str(t)})
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        return subprocess.run(cmd, input=payload, capture_output=True, text=True,
                              env={**self.env, **env})

    def denied(self, p):
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        self.assertEqual(out["permissionDecision"], "deny")
        return out["permissionDecisionReason"]

    def allowed(self, p):
        self.assertEqual((p.returncode, p.stdout.strip()), (0, ""))

    def test_under_threshold_allows(self):
        # default limit: min(60% of 200k = 120k, 200k - 60k = 140k) = 120k
        self.allowed(self.run_hook([usage_line(1000, 100000, 10000)]))

    def test_at_threshold_denies_and_names_the_numbers(self):
        reason = self.denied(self.run_hook([usage_line(1000, 100000, 19000)]))
        self.assertIn("~120k tokens", reason)
        self.assertIn("~120k watch threshold (60% of a 200k window)", reason)

    def test_sums_the_three_fields_of_the_largest_block(self):
        lines = [usage_line(0, 130000, 0), usage_line(5, 10, 10)]
        self.denied(self.run_hook(lines))

    def test_non_assistant_and_usage_less_lines_are_ignored(self):
        lines = [json.dumps({"type": "user", "message": {"usage": {"input_tokens": 999999}}}),
                 json.dumps({"type": "assistant", "message": {}}), usage_line(10)]
        self.allowed(self.run_hook(lines))

    def test_headroom_floor_binds_on_a_small_window(self):
        # window 100k: 60% = 60k, but 100k - 60k floor = 40k binds
        p = self.run_hook([usage_line(0, 45000, 0)], CLAUDE_PR_WATCH_CONTEXT_WINDOW="100000")
        self.assertIn("~40k watch threshold", self.denied(p))

    def test_explicit_token_limit_wins_and_drops_the_basis(self):
        p = self.run_hook([usage_line(0, 5000, 0)], CLAUDE_PR_WATCH_TOKEN_LIMIT="4000")
        reason = self.denied(p)
        self.assertIn("~4k watch threshold.", reason)
        self.assertNotIn("window)", reason)

    def test_token_limit_wins_over_a_non_numeric_window(self):
        p = self.run_hook([usage_line(0, 5000, 0)], CLAUDE_PR_WATCH_TOKEN_LIMIT="4000",
                          CLAUDE_PR_WATCH_CONTEXT_WINDOW="abc")
        self.assertIn("~4k watch threshold.", self.denied(p))

    def test_zero_limit_disables(self):
        self.allowed(self.run_hook([usage_line(0, 999999, 0)], CLAUDE_PR_WATCH_TOKEN_LIMIT="0"))

    def test_larger_window_raises_the_limit(self):
        self.allowed(self.run_hook([usage_line(0, 200000, 0)], CLAUDE_PR_WATCH_CONTEXT_WINDOW="1000000"))

    def test_only_the_tail_is_scanned(self):
        lines = [usage_line(0, 500000, 0)] + [json.dumps({"type": "user"})] * 500
        self.allowed(self.run_hook(lines))

    def test_fails_open(self):
        self.allowed(self.run_hook(payload="{}"))
        self.allowed(self.run_hook(payload="not json"))
        self.allowed(self.run_hook(payload=json.dumps({"transcript_path": str(self.dir / "none")})))
        self.allowed(self.run_hook(["{broken", usage_line(0, 500000, 0)]))


if __name__ == "__main__":
    unittest.main()
