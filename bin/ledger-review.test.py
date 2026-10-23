#!/usr/bin/env python3
# Tests for ledger-review. Run: python3 bin/ledger-review.test.py
#
# Fixture text only, never the live state repo: the three ledger line formats,
# the fourth (mark before a date) they fall back to, the Superseded skip, the
# fields, and the overdue review.
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "ledger-review"
spec = importlib.util.spec_from_loader("ledger_review", importlib.machinery.SourceFileLoader("ledger_review", str(TOOL)))
lr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lr)

TODAY = date(2026, 10, 22)

# The hooks-guards form: date, who, mark, then the ruling in bold.
HEAD = """\
**Widget names**

- 2026-10-07, the user, pen, third sitting ([roll.md#20261007t082113z](roll.md#20261007t082113z)): **widgets are named noun-first.**
- 2026-10-07, the user, pencil, third sitting: **held names as pencil defaults**, the pen ruling above stands.
- 2026-10-01, the user, second sitting (pen, "pen, and a note"): **six widgets ship on**.
- 2026-09-30, the user (neither pen nor pencil stated), first sitting: **the README lede is two lines**.
"""

# The easy-grind form: the ruling, then the mark after the last em dash.
TAIL = """\
**Opening (2026-10-08)**

- The widget queue drains nightly. — pen, 2026-10-08, [other/roll.md#20261008t231732z](../other/roll.md#20261008t231732z)
- A queue: pencil nears pen with every commit. — pencil, 2026-10-07, [roll.md#20261007t000000z](roll.md#20261007t000000z)
- Sorting is a pass inside the drain, "in pen if you like". — unmarked, 2026-09-27, [roll.md#20260927t203312z](roll.md#20260927t203312z)
"""

# The chart-data form: the mark first, who and date in brackets.
LEAD = """\
**What the widget vends**

- pen (the user, 2026-10-15): one widget resource type. [roll.md#20261015t034318z](roll.md#20261015t034318z)
- pencil (the user, 2026-10-15): the ranking is next (the question it waited on is settled, pen above).
- pencil, tentatively pen (the user, 2026-10-22): three widget tiers.
"""


class MarkTest(unittest.TestCase):
    def marks(self, text):
        return [lr.mark(line) for line in text.splitlines() if line.startswith("- ")]

    def test_head_format(self):
        self.assertEqual(self.marks(HEAD), ["pen", "pencil", "pen", None])

    def test_tail_format(self):
        self.assertEqual(self.marks(TAIL), ["pen", "pencil", "unmarked"])

    def test_lead_format(self):
        self.assertEqual(self.marks(LEAD), ["pen", "pencil", "pencil"])

    def test_mark_before_a_date(self):
        self.assertEqual(lr.mark("- A label on large widgets. pen (lint, 2026-10-17), the user; built in #7."), "pen")
        self.assertIsNone(lr.mark("- The widget named → widget is in pen — [digest](inputs/2026-10-03-digest.md)"))

    def test_pen_only_in_a_quote_is_not_a_mark(self):
        self.assertIsNone(lr.mark('- The user said "this is pen" and moved on.'))


class ReviewTest(unittest.TestCase):
    def test_counts_pen_lines_in_each_format_as_missing(self):
        pens, found = lr.review(HEAD + "\n" + TAIL + "\n" + LEAD, TODAY)
        self.assertEqual(pens, 4)
        self.assertEqual([f["kind"] for f in found], ["missing"] * 4)
        self.assertEqual([f["line"] for f in found], [3, 5, 10, 16])

    def test_superseded_lines_are_skipped_until_the_next_heading(self):
        text = ("**Superseded**\n\n- pen (the user, 2026-10-01): replaced by the line above.\n\n"
                "## Widget budget (2026-10-21)\n\n- pen (the user, 2026-10-21): the budget is higher.\n")
        pens, found = lr.review(text, TODAY)
        self.assertEqual((pens, [f["line"] for f in found]), (1, [7]))

    def test_comment_block_is_not_read(self):
        text = "<!-- The ledger.\n- pen (the user, 2026-10-01): an example in a comment.\n-->\n"
        self.assertEqual(lr.review(text, TODAY), (0, []))

    def test_either_field_clears_missing(self):
        text = ("- pen (the user, 2026-10-15): a guard. embedded: hooks/no-x.sh (2026-10-20)\n"
                "- pen (the user, 2026-10-15): a count. effective when: 3 reversals 5 → 1 by 2027-01-01;"
                " effective: pending, review 2027-01-01\n")
        self.assertEqual(lr.review(text, TODAY), (2, []))

    def test_overdue_review(self):
        text = ("- pen (the user, 2026-09-01): a count. effective when: 9 asks 300 → 100 by 2026-10-01;"
                " effective: pending, review 2026-10-01\n"
                "- pen (the user, 2026-09-01): another. effective when: 2 x 4 → 1 by 2026-10-22;"
                " effective: pending, review 2026-10-22\n")
        pens, found = lr.review(text, TODAY)
        self.assertEqual(pens, 2)
        self.assertEqual([(f["line"], f["kind"], f.get("review")) for f in found], [(1, "overdue", "2026-10-01")])


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / ".git").mkdir()
        for name, text in (("hooks-guards", HEAD), ("chart-data", LEAD)):
            d = root / "state" / "global" / "curia" / name
            d.mkdir(parents=True)
            (d / "decided.md").write_text(text, encoding="utf-8")
        self.env = dict(os.environ, CLAUDE_STATE_REPO=str(root))

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], env=self.env, capture_output=True, text=True)

    def test_table_groups_by_curia_and_totals(self):
        p = self.run_tool()
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines[0].startswith("curia"))
        self.assertTrue(lines[1].startswith("chart-data"))
        self.assertTrue(lines[2].startswith("hooks-guards"))
        self.assertTrue(lines[3].startswith(" "))
        self.assertEqual(lines[-1], "total: 3 pen lines in 2 ledgers; 3 with neither embedded nor effective when;"
                                    " 0 reviews overdue")

    def test_json(self):
        out = json.loads(self.run_tool("--json").stdout)
        self.assertEqual(out["total"], {"pen": 3, "missing": 3, "overdue": 0})
        self.assertEqual(out["curiae"]["chart-data"]["findings"][0]["line"], 3)

    def test_no_state_repo_exits_3(self):
        self.env["CLAUDE_STATE_REPO"] = os.path.join(self.tmp.name, "absent")
        self.env["HOME"] = self.tmp.name + "/nohome"
        p = self.run_tool()
        self.assertEqual(p.returncode, 3)


if __name__ == "__main__":
    unittest.main()
