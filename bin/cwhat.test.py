#!/usr/bin/env python3
# Tests for cwhat. Run: python3 bin/cwhat.test.py
#
# What matters: a card or a hand-off is found by any id form a human holds;
# the model and effort shown are the recommendation (a hand-off's body, never
# its header's session model); a driver card lists its children; a search
# keeps to live work unless asked; nothing is written to the store. A curia
# is found by a loose id; the docket splits ready from waiting; a scoping
# target never started, or left half-done, is marked, and a held lock shown.
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CW = Path(__file__).resolve().parent / "cwhat"
PARENT, CHILD, DONE = "1793905381fff197bb", "1793905382406fcc69", "1793905383aaaaaaaa"
ASK, ASKED = "1793905390bbbbbbbb", "1793905391cccccccc"
WAIT = "1793905392dddddddd"
OLD_SID = "deadbeef-0000-4000-8000-000000000000"
LONG = " ".join(f"word{i}" for i in range(400))


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
        card(items, DONE, "Old zebra work", "2026-11-01T00:00:00Z bba7f7f1 status=done owner=agent",
             brief=LONG)
        card(items, ASK, "Pick a licence", "2026-11-05T00:00:00Z bba7f7f1 status=ready owner=human-ruling")
        card(items, ASKED, "Pick a colour", "2026-11-04T00:00:00Z bba7f7f1 status=done owner=human-ruling")
        card(items, WAIT, "Pick a boat name", "2026-11-05T00:00:00Z bba7f7f1 status=ready owner=human-ruling",
             brief="until: 2999-01-01, when the hull is built")
        (self.g / "agora" / "briefs").mkdir(parents=True)
        (self.g / "agora" / "briefs" / f"{ASK}.md").write_text("Licence brief.\n")
        cur = self.g / "curia"
        for cid, status in (("hooks-guards", "open"), ("chart-data", "settled")):
            (cur / cid).mkdir(parents=True)
            (cur / cid / "digest.md").write_text(
                f"# Curia: the {cid} question\n\n- opened: 2026-10-01\n- status: {status}\n\n"
                "## Open questions\n\n<!-- - not a question -->\n"
                f"1. **Q-{cid}:** which way,\n   continued here.\n\n## Notes\n- not a question\n")
        (cur / "hooks-guards" / "LIVE").write_text(f"{OLD_SID} 2026-11-05T18:52:33Z\n")
        (cur / "no-digest").mkdir()
        (cur / "chart-data" / "inputs").mkdir()
        (cur / "chart-data" / "inputs" / "2026-11-04-scoping-proposal.md").write_text("# P\n")
        sc = self.g / "scoping"
        for t in ("repo-o-done", "repo-o-held", "repo-o-empty"):
            (sc / t).mkdir(parents=True)
        (sc / "repo-o-done" / "2026-10-01-scoping-proposal.md").write_text("# P\n\n## Filed\n- 1\n")
        (sc / "repo-o-held" / "2026-10-02-scoping-proposal.md").write_text("# P\n\n## Filed\n- 1\n")
        (sc / "repo-o-held" / "LOCK").write_text(f"{OLD_SID} 2026-10-02T00:00:00Z abc123\n")
        (sc / "repo-o-empty" / "LOCK").write_text(f"{OLD_SID} 2026-10-02T00:00:00Z abc123\n")
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
        run_with = next(l for l in out.splitlines() if l.startswith("run with:"))
        self.assertNotRegex(run_with, r"opus|sonnet|fable|haiku")
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
        board = self.run_cw()
        self.assertIn(ASK, board)
        self.assertNotIn(ASKED, board)
        self.assertIn(ASKED, self.run_cw("-a"))
        self.assertIn("pickup-list", self.run_cw("tools"))
        for sub in ("curia", "agora", "scoping"):
            self.run_cw(sub)
        self.assertEqual(before, sorted((p, p.stat().st_mtime) for p in self.g.rglob("*")))


    def test_prefix_matching_several_cards_shows_each(self):
        out = self.run_cw("1793905")
        for cid in (PARENT, CHILD, DONE):
            self.assertIn(cid, out)

    def test_verbose_shows_the_whole_brief(self):
        self.assertNotIn("word399", self.run_cw(DONE))
        self.assertIn("word399", self.run_cw("-v", DONE))

    def line_of(self, out, key):
        return next(l for l in out.splitlines() if key in l)

    def test_curia_list_names_every_curia_with_a_digest(self):
        out = self.run_cw("curia")
        self.assertIn("hooks-guards", out)
        self.assertIn("chart-data", out)
        self.assertNotIn("no-digest", out)
        self.assertIn("settled", self.line_of(out, "chart-data"))

    def test_curia_by_loose_id_shows_its_open_questions_and_sitting(self):
        for key in ("hooks-guards", "hooks", "guards", "hoks-guard"):
            out = self.run_cw("curia", key)
            self.assertIn("Q-hooks-guards", out)
            self.assertIn("continued here", out)
            self.assertIn("2026-11-05T18:52:33Z", out)
            self.assertNotIn("Q-chart-data", out)
            self.assertNotIn("not a question", out)

    def test_agora_splits_ready_from_waiting_and_links_briefs(self):
        out = self.run_cw("agora")
        self.assertLess(out.index(ASK), out.index(WAIT))
        self.assertNotIn(ASKED, out)
        self.assertIn(f"briefs/{ASK}.md", out)
        self.assertNotIn(f"briefs/{WAIT}.md", out)
        self.assertNotIn(CHILD, out)
        self.assertEqual(out, self.run_cw("docket"))

    def test_scoping_marks_stale_locks_and_unfinished_targets(self):
        out = self.run_cw("scoping")
        done, held, empty = (self.line_of(out, t) for t in ("repo-o-done", "repo-o-held", "repo-o-empty"))
        self.assertNotRegex(done, "never started|half-done")
        self.assertIn("half-done", held)
        self.assertIn("stale deadbeef", held)
        self.assertIn("never started", empty)
        self.assertIn("half-done", self.line_of(out, "chart-data"))

    def test_search_flag_searches_even_a_subcommand_word(self):
        self.assertNotIn("hooks-guards", self.run_cw("-s", "curia"))
        self.assertIn(ASK, self.run_cw("-s", "licence"))
        self.assertIn(ASK, self.run_cw("licence"))


if __name__ == "__main__":
    unittest.main()
