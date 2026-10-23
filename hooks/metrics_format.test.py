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
