#!/usr/bin/env python3
# Tests for spend-gate.py. Run: python3 hooks/spend-gate.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job,
# so no new job and nothing drawn from the account's concurrent-job cap.
# Each case runs the hook as Claude Code does, a subprocess fed PreToolUse
# JSON on stdin, against a throwaway transcript.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "spend-gate.py"
ENV_KEYS = ("SPEND_GATE_USD", "SPEND_GATE_TOKENS", "SPEND_GATE_HANDOFF")


def assistant(mid, model="claude-sonnet-5", inp=0, out=0, read=0, write=0, w1h=0):
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": {
        "input_tokens": inp, "output_tokens": out,
        "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
        "cache_creation": {"ephemeral_5m_input_tokens": write - w1h,
                           "ephemeral_1h_input_tokens": w1h}}}}


class SpendGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.transcript = Path(self.tmp.name) / "t.jsonl"
        # Sonnet at $2 / $10 per 1M. Message a: 100k cache read ($0.02) and a
        # 100k 1-hour cache write ($0.40); it arrives twice (two content blocks,
        # same usage) and must count once. Message b: 1M output ($10.00) on
        # 150k of context, 149,990 of it a cache read ($0.03). Total $10.45;
        # the last call's context is 150k.
        a = assistant("msg_a", read=100_000, write=100_000, w1h=100_000)
        b = assistant("msg_b", inp=10, out=1_000_000, read=150_000 - 10)
        lines = [{"type": "user", "message": {"content": "go"}}, a, a, b,
                 {"type": "user", "message": {"content": [{"type": "tool_result"}]}}]
        self.transcript.write_text("".join(json.dumps(x) + "\n" for x in lines))

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, tool, tool_input, transcript=None, **env):
        e = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
        e.update(env)
        payload = {"session_id": "s", "transcript_path": str(transcript or self.transcript),
                   "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                           capture_output=True, text=True, env=e, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        if not p.stdout.strip():
            return "allow", None, p.stderr
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "PreToolUse")
        return out["permissionDecision"], out["permissionDecisionReason"], p.stderr

    BASH = ("Bash", {"command": "git push"})
    OTHER_WRITE = ("Write", {"file_path": "/w/src/app.py", "content": "x"})
    HANDOFF_WRITE = ("Write", {"file_path": "/w/HANDOFF.md", "content": "done: a; next: b"})

    def test_unset_line_is_a_no_op(self):
        for tool in (self.BASH, self.OTHER_WRITE):
            d, _, err = self.run_hook(*tool)
            self.assertEqual(d, "allow")
            self.assertEqual(err, "")
        # inert even when the transcript is missing: no note, nothing read
        d, _, err = self.run_hook(*self.BASH, transcript="/nonexistent/t.jsonl")
        self.assertEqual((d, err), ("allow", ""))

    def test_below_the_lines_allows(self):
        d, _, _ = self.run_hook(*self.BASH, SPEND_GATE_USD="10.46", SPEND_GATE_TOKENS="150001")
        self.assertEqual(d, "allow")

    def test_past_the_spend_line(self):
        d, reason, _ = self.run_hook(*self.BASH, SPEND_GATE_USD="10.45")
        self.assertEqual(d, "deny")
        self.assertEqual(reason, "Past the line: $10.45 of $10.45 (spend). Every tool is "
                         "denied except one Write to HANDOFF.md. Write the hand-off (what is "
                         "done, what is next, how to resume) there and end the turn.")
        self.assertEqual(self.run_hook(*self.OTHER_WRITE, SPEND_GATE_USD="5")[0], "deny")
        self.assertEqual(self.run_hook("Edit", {"file_path": "/w/HANDOFF.md"},
                                       SPEND_GATE_USD="5")[0], "deny")
        self.assertEqual(self.run_hook(*self.HANDOFF_WRITE, SPEND_GATE_USD="5")[0], "allow")

    def test_past_the_context_line(self):
        d, reason, _ = self.run_hook(*self.BASH, SPEND_GATE_TOKENS="150000")
        self.assertEqual(d, "deny")
        self.assertIn("Past the line: 150k of 150k tokens (context).", reason)
        self.assertEqual(self.run_hook(*self.OTHER_WRITE, SPEND_GATE_TOKENS="100000")[0], "deny")
        self.assertEqual(self.run_hook(*self.HANDOFF_WRITE, SPEND_GATE_TOKENS="100000")[0], "allow")

    def test_both_lines_named_when_both_set(self):
        _, reason, _ = self.run_hook(*self.BASH, SPEND_GATE_USD="20", SPEND_GATE_TOKENS="100000")
        self.assertIn("$10.45 of $20.00 (spend) / 150k of 100k tokens (context)", reason)

    def test_handoff_file_is_configurable(self):
        env = {"SPEND_GATE_USD": "5", "SPEND_GATE_HANDOFF": "NEXT.md"}
        self.assertEqual(self.run_hook(*self.HANDOFF_WRITE, **env)[0], "deny")
        d, reason, _ = self.run_hook("Write", {"file_path": "/w/NEXT.md"}, **env)
        self.assertEqual(d, "allow")
        self.assertIn("Write to NEXT.md", self.run_hook(*self.BASH, **env)[1])

    def test_missing_transcript_allows_with_a_note(self):
        d, _, err = self.run_hook(*self.BASH, transcript="/nonexistent/t.jsonl",
                                  SPEND_GATE_USD="0.01")
        self.assertEqual(d, "allow")
        self.assertIn("spend-gate: cannot read the transcript", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_unreadable_transcript_allows_with_a_note(self):
        d, _, err = self.run_hook(*self.BASH, transcript=self.tmp.name, SPEND_GATE_USD="0.01")
        self.assertEqual(d, "allow")
        self.assertIn("cannot read the transcript", err)

    def test_a_line_that_is_not_a_number_is_ignored(self):
        d, _, err = self.run_hook(*self.BASH, SPEND_GATE_USD="five")
        self.assertEqual(d, "allow")
        self.assertIn("SPEND_GATE_USD='five' is not a number", err)

    def test_model_prices(self):
        # 1M output tokens on each model: opus $25, fable $50, haiku $5,
        # an unknown name at Sonnet's $10.
        for model, usd in (("claude-opus-5-5", 25), ("claude-fable-5-1", 50),
                           ("claude-haiku-5", 5), ("mystery", 10)):
            self.transcript.write_text(json.dumps(assistant("m", model, out=1_000_000)) + "\n")
            self.assertEqual(self.run_hook(*self.BASH, SPEND_GATE_USD=str(usd))[0], "deny", model)
            self.assertEqual(self.run_hook(*self.BASH, SPEND_GATE_USD=str(usd + 0.01))[0],
                             "allow", model)


class WrapperTest(unittest.TestCase):
    """settings.json's wrapper, run by sh against a HOME with and without the hook."""

    @classmethod
    def setUpClass(cls):
        settings = json.loads((HOOK.parent.parent / "settings.json").read_text())
        cls.cmd = next(h["command"] for e in settings["hooks"]["PreToolUse"]
                       for h in e["hooks"] if "spend-gate.py" in h["command"])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.transcript = self.home / "t.jsonl"
        self.transcript.write_text(json.dumps(assistant("m", out=1_000_000)) + "\n")  # $10

    def tearDown(self):
        self.tmp.cleanup()

    def run_wrapper(self, tool, tool_input, **env):
        e = {k: v for k, v in os.environ.items() if k not in ENV_KEYS}
        e.update(env, HOME=str(self.home))
        payload = {"transcript_path": str(self.transcript), "hook_event_name": "PreToolUse",
                   "tool_name": tool, "tool_input": tool_input}
        p = subprocess.run(["sh", "-c", self.cmd], input=json.dumps(payload),
                           capture_output=True, text=True, env=e, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]

    def install_hook(self):
        d = self.home / ".claude" / "hooks"
        d.mkdir(parents=True)
        (d / "spend-gate.py").write_text(HOOK.read_text())

    def test_hook_missing_and_no_line_allows(self):
        self.assertEqual(self.run_wrapper("Bash", {"command": "ls"}), "allow")

    def test_hook_missing_with_a_line_denies_all_but_the_handoff_write(self):
        self.assertEqual(self.run_wrapper("Bash", {"command": "ls"}, SPEND_GATE_USD="100"), "deny")
        self.assertEqual(self.run_wrapper("Write", {"file_path": "/w/a.py"},
                                          SPEND_GATE_TOKENS="5"), "deny")
        self.assertEqual(self.run_wrapper("Write", {"file_path": "/w/HANDOFF.md", "content": "x"},
                                          SPEND_GATE_USD="100"), "allow")
        self.assertEqual(self.run_wrapper("Write", {"file_path": "/w/NEXT.md"}, SPEND_GATE_USD="1",
                                          SPEND_GATE_HANDOFF="NEXT.md"), "allow")

    def test_hook_crashing_with_a_line_denies_all_but_the_handoff_write(self):
        d = self.home / ".claude" / "hooks"
        d.mkdir(parents=True)
        (d / "spend-gate.py").write_text("raise SystemExit(1)\n")
        self.assertEqual(self.run_wrapper("Bash", {"command": "ls"}, SPEND_GATE_USD="100"), "deny")
        self.assertEqual(self.run_wrapper("Write", {"file_path": "/w/HANDOFF.md"},
                                          SPEND_GATE_USD="100"), "allow")

    def test_hook_present_decides(self):
        self.install_hook()
        self.assertEqual(self.run_wrapper("Bash", {"command": "ls"}, SPEND_GATE_USD="20"), "allow")
        self.assertEqual(self.run_wrapper("Bash", {"command": "ls"}, SPEND_GATE_USD="5"), "deny")
        self.assertEqual(self.run_wrapper("Write", {"file_path": "/w/HANDOFF.md"},
                                          SPEND_GATE_USD="5"), "allow")


if __name__ == "__main__":
    unittest.main()
