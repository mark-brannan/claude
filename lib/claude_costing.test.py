#!/usr/bin/env python3
# Tests for lib/claude_costing. Run: python3 lib/claude_costing.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
import claude_costing as cc  # noqa: E402


def event(mid, model, **u):
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": u}}


class RatesTest(unittest.TestCase):
    def test_each_family(self):
        for model, want in (("claude-opus-5-5", (5, 25, 0.5)), ("claude-fable-5-1", (10, 50, 0.25)),
                            ("claude-fable-6", (10, 50, 1.0)), ("claude-sonnet-4-6", (3, 15, 0.3)),
                            ("claude-sonnet-5-5", (2, 10, 0.2)), ("claude-haiku-5-5", (1, 5, 0.1))):
            r = cc.rates(model)
            self.assertEqual((r["input"], r["output"]), want[:2], model)
            self.assertAlmostEqual(r["cache_read"], want[2], msg=model)

    def test_an_unknown_model_prices_at_the_top_tier(self):
        for model in ("mystery", "", None):
            self.assertEqual(cc.rates(model)["output"], 50)


class PriceTest(unittest.TestCase):
    def test_repeated_blocks_of_one_message_count_once(self):
        msgs = {}
        for _ in range(3):
            cc.add_usage(event("m1", "claude-opus-5-5", output_tokens=1_000_000), msgs)
        self.assertAlmostEqual(cc.price(msgs), 25)

    def test_cache_writes_by_ttl_and_reads(self):
        msgs = {}
        cc.add_usage(event("m", "claude-opus-5-5", cache_creation_input_tokens=3_000_000,
                           cache_read_input_tokens=1_000_000,
                           cache_creation={"ephemeral_1h_input_tokens": 1_000_000}), msgs)
        # 2M unsplit-or-5m at 1.25x $5, 1M 1h at 2x $5, 1M read at $0.50
        self.assertAlmostEqual(cc.price(msgs), 12.5 + 10 + 0.5)

    def test_session_spend_counts_subagents_and_context_is_the_last_call(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "s.jsonl"
            main.write_text("\n".join(json.dumps(e) for e in (
                event("a", "claude-haiku-5", input_tokens=1_000_000),
                event("b", "claude-haiku-5", input_tokens=10, cache_read_input_tokens=5))) + "\n")
            sub = Path(d) / "s" / "subagents" / "agent-x.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text(json.dumps(event("c", "claude-opus-5-5", output_tokens=1_000_000)) + "\n")
            for start in (main, sub):  # a sub-agent's path walks up to the session's
                usd, ctx = cc.session_spend(str(start))
                self.assertAlmostEqual(usd, 1 + 25, places=4)
                self.assertEqual(ctx, 15)

    def test_share_of_week(self):
        self.assertAlmostEqual(cc.share_of_week(100, 2000), 5.0)


class ShellTest(unittest.TestCase):
    def test_rates_from_the_command_line(self):
        out = subprocess.run([sys.executable, str(LIB / "claude_costing"), "rates", "fable-5-1"],
                             capture_output=True, text=True, check=True, cwd=os.sep).stdout
        self.assertEqual(out.split(), ["10", "50", "0.25"])


class JqTest(unittest.TestCase):
    def test_session_metrics_prices_from_the_same_table(self):
        jqf = LIB.parent / "hooks" / "session-metrics.jq"
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.jsonl"
            t.write_text(json.dumps(event("m", "claude-fable-5-1", output_tokens=1_000_000,
                                          cache_read_input_tokens=1_000_000)) + "\n")
            p = subprocess.run(["jq", "-s", "--arg", "sid", "x", "--arg", "repo", "r", "--arg", "branch", "b",
                                "--arg", "now", "t", "--arg", "cwd", "/", "-f", str(jqf), str(t)],
                               capture_output=True, text=True, cwd=os.sep)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertAlmostEqual(json.loads(p.stdout)["session"]["cost_usd"], 50.25)


if __name__ == "__main__":
    unittest.main()
