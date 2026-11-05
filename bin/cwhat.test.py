#!/usr/bin/env python3
# Tests for cwhat. Run: python3 bin/cwhat.test.py
#
# What matters: a card or a hand-off is found by any id form a human holds;
# the model and effort shown are the recommendation (a hand-off's body, never
# its header's session model); a driver card lists its children; a search
# keeps to live work unless asked; nothing is written to the store.
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CW = Path(__file__).resolve().parent / "cwhat"
PARENT, CHILD, DONE = "1793905381fff197bb", "1793905382406fcc69", "1793905383aaaaaaaa"


def card(d, cid, title, log, brief="A brief about zebras."):
    (d / f"{cid}.md").write_text(f"# {title}\n\n## Brief\n{brief}\n\n## Log\n{log}\n")


class Cwhat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "state"
        (root / ".git").mkdir(parents=True)
        self.g = root / "state" / "global"
        items = self.g / "items"
        (self.g / "pickup").mkdir(parents=True)
        items.mkdir()
        card(items, PARENT, "Driver batch", "2026-11-05T19:03:01Z bba7f7f1 status=open owner=agent")
        card(items, CHILD, "A. stage three",
             f"2026-11-05T19:03:02Z bba7f7f1 status=ready owner=agent parent={PARENT} model=opus effort=high\n"
             "2026-11-05T19:32:45Z d94d2d56 pr=https://github.com/o/r/pull/354\n"
             "2026-11-05T19:50:29Z d94d2d56 note=parked: not reviewed")
        card(items, DONE, "Old zebra work", "2026-11-01T00:00:00Z bba7f7f1 status=done owner=agent")
        (self.g / "pickup" / "2026-11-05T19-24-b26633aa.md").write_text(
            "status: open\nupdated: 2026-11-05T19:50:04Z\nsession: b26633aa-0000\n"
            "model: claude-fable-5-1\n---\nRun the zebra research prompt.\n"
            "link: https://example.com/doc\nmodel: opus\neffort: medium\n")
        self.env = {**os.environ, "CLAUDE_STATE_REPO": str(root), "NO_COLOR": "1"}
        self.env.pop("WORK_ITEM_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cw(self, *args):
        p = subprocess.run([sys.executable, str(CW), "--no-pager", *args], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def test_card_by_full_id_and_prefix_shows_recommendation(self):
        for key in (CHILD, CHILD[:12]):
            out = self.run_cw(key)
            self.assertIn("opus · high", out)
            self.assertIn("pull/354", out)
            self.assertIn("parked: not reviewed", out)

    def test_driver_card_lists_children_with_their_model(self):
        out = self.run_cw(PARENT)
        self.assertIn("none recorded", out)
        self.assertIn(CHILD, out)
        self.assertRegex(out, r"opus\s+high\s+ready")

    def test_handoff_by_session_uses_body_model_not_header(self):
        out = self.run_cw("b26633aa")
        self.assertIn("opus · medium", out)
        self.assertNotIn("fable · ", out)

    def test_search_is_live_only_unless_all(self):
        live = self.run_cw("zebra")
        self.assertNotIn(DONE, live)
        self.assertIn("2026-11-05T19-24-b26633aa", live)
        self.assertIn(DONE, self.run_cw("-a", "zebra"))

    def test_board_and_tools_run_and_write_nothing(self):
        before = sorted((p, p.stat().st_mtime) for p in self.g.rglob("*"))
        self.assertIn("Claude's queue: 2 cards", self.run_cw())
        self.assertIn("pickup-list", self.run_cw("tools"))
        self.assertEqual(before, sorted((p, p.stat().st_mtime) for p in self.g.rglob("*")))


if __name__ == "__main__":
    unittest.main()
