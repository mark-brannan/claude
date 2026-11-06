#!/usr/bin/env python3
# Tests for metrics_format.py: its fields, and a byte-for-byte parity check
# against the lib-metrics-fmt.jq defs. Parity is the point: the move out of
# shell must not change one glyph of what is on screen.
# Run: python3 hooks/metrics_format.test.py
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import metrics_format as mf  # noqa: E402


class FieldsTest(unittest.TestCase):
    def test_turns(self):
        self.assertEqual(mf.fmt_turns(3, 41), "⇢ 3 ⚙ 41")
        self.assertEqual(mf.fmt_turns(0, 0), "⇢ 0 ⚙ 0")
        self.assertEqual(mf.fmt_turns(), "⇢ 0 ⚙ 0")

    def test_work(self):
        self.assertEqual(mf.fmt_work(0, 0, 0), "")
        self.assertEqual(mf.fmt_work(), "")
        self.assertEqual(mf.fmt_work(0, 1, 0), "⎇ 1~")
        self.assertEqual(mf.fmt_work(2, 0, 0), "⎇ 2c")
        self.assertEqual(mf.fmt_work(0, 0, 3), "⎇ 3↑unpushed  ← not safe to kill")
        self.assertEqual(mf.fmt_work(2, 1, 3), "⎇ 2c1~3↑unpushed  ← not safe to kill")

    USD = [(None, ""), ("2.39", ""), (True, ""), (0, "$0.00"), (0.0, "$0.00"), (-1, "$0.00"),
           (0.0001, "<$0.01"), (0.004, "<$0.01"), (0.005, "$0.01"), (0.01, "$0.01"),
           (0.1, "$0.10"), (2.39, "$2.39"), (2.394, "$2.39"), (2.396, "$2.40"), (7, "$7.00"),
           (99.99, "$99.99"), (99.996, "$100"), (100, "$100"), (123.45, "$123"),
           (123.5, "$124"), (1234.4, "$1234")]

    F = "\u2007"
    USD_FIXED = [(None, F * 7), (0, f"${F*2}0.00"), (0.004, f"{F}<$0.01"), (2.39, f"${F*2}2.39"),
                 (123, "$123.00"), (999.994, "$999.99"), (999.998, f"${F*2}1.0k"), (1234.5, f"${F*2}1.2k"), (12345, f"${F*3}12k")]
    TOKENS_FIXED = [(0, F * 3 + "0"), (10, F * 2 + "10"), (46000, F + "46k"), (999999, "999k"),
                    (1_200_000, "1.2M"), (12_000_000, F + "12M")]

    def test_fixed_widths(self):
        for cost, want in self.USD_FIXED:
            self.assertEqual(mf.fmt_usd_fixed(cost), want, cost)
            self.assertEqual(len(mf.fmt_usd_fixed(cost)), 7, cost)
        for n, want in self.TOKENS_FIXED:
            self.assertEqual(mf.fmt_tokens_fixed(n), want, n)

    def test_usd(self):
        for cost, want in self.USD:
            self.assertEqual(mf.fmt_usd(cost), want, cost)

    @unittest.skipUnless(shutil.which("jq"), "no jq")
    def test_usd_parity_with_jq_def(self):
        for cost, _ in self.USD:
            cache = json.dumps({"cost_usd": cost} if cost is not None else {})
            jq = subprocess.run(["jq", "-r", "-L", HERE, 'include "lib-metrics-fmt"; usd // ""'],
                                input=cache, capture_output=True, text=True, check=True).stdout.rstrip("\n")
            self.assertEqual(mf.fmt_usd(cost), jq, cost)

    @unittest.skipUnless(shutil.which("jq"), "no jq")
    def test_row_carries_dollars_after_the_ratio(self):
        cache = json.dumps({"repo": "claude", "branch": "main", "output_tokens": 11000,
                            "context_peak": 128000, "cost_usd": 2.39,
                            "decisions": {"total": 0, "scoping": 0, "inline": 0, "gate": 0},
                            "user_turns": 3, "tool_calls": 31, "commits": 0, "dirty": 0, "unpushed": 0})
        row = subprocess.run(["jq", "-r", "-L", HERE, 'include "lib-metrics-fmt"; row'],
                             input=cache, capture_output=True, text=True, check=True).stdout
        self.assertIn(" 11k/128k $2.39 ⚖ 0[0/0/0] ", row)

    @unittest.skipUnless(shutil.which("jq"), "no jq")
    def test_parity_with_jq_defs(self):
        for c in [(0, 0, 0, 0, 0), (3, 41, 0, 1, 0), (7, 42, 2, 1, 3), (1, 59, 5, 0, 0), (9, 9, 0, 0, 4)]:
            turns, tools, commits, dirty, unpushed = c
            cache = json.dumps({"user_turns": turns, "tool_calls": tools, "commits": commits,
                                "dirty": dirty, "unpushed": unpushed})
            jq = subprocess.run(
                ["jq", "-r", "-L", HERE, 'include "lib-metrics-fmt"; '
                 'turns + ((work // "") as $w | if $w == "" then "" else " " + $w end)'],
                input=cache, capture_output=True, text=True, check=True).stdout.rstrip("\n")
            w = mf.fmt_work(commits, dirty, unpushed)
            mine = mf.fmt_turns(turns, tools) + (f" {w}" if w else "")
            self.assertEqual(mine, jq, c)


if __name__ == "__main__":
    unittest.main()
