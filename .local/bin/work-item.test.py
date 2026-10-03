#!/usr/bin/env python3
# Tests for work-item. Run: python3 .local/bin/work-item.test.py
#
# What matters: an item is created in open and never twice; the six statuses
# move only along the pen transitions; a claim is refused while another live
# session holds the item and allowed once the holder has gone quiet; cost
# lines fold to a per-item total; points live on the brief. The steps share
# one store and run in order, so they are numbered.
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WI = Path(__file__).resolve().parent / "work-item"
A = "077c62eb-2979-4277-b798-0d0fd9e9bb8d"
B = "9a1b2c3d-0000-0000-0000-000000000000"


def run(sid, *args, stdin=None):
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": sid}
    return subprocess.run([sys.executable, str(WI), *args], env=env, input=stdin,
                          capture_output=True, text=True)


def ok(sid, *args, stdin=None):
    p = run(sid, *args, stdin=stdin)
    assert p.returncode == 0, f"work-item {' '.join(args)}: {p.returncode} {p.stderr}"
    return p.stdout.strip()


def fact(item, key):
    return dict(l.split("=", 1) for l in ok(A, "fold", item).splitlines())[key]


class WorkItemTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        T = Path(cls.tmp.name)
        cls.dir = T / "items"
        os.environ.update(WORK_ITEM_DIR=str(cls.dir), TMPDIR=str(T))
        cls.id = ok(A, "create", "--repo", "mark-brannan/dotfiles", "--model", "sonnet",
                    "--effort", "medium", "--points", "3",
                    "--brief", "Measure growth per day.", "Size the store")
        cls.f = cls.dir / f"{cls.id}.md"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def lines(self):
        return self.f.read_text().splitlines()

    def test_01_create(self):
        self.assertRegex(self.id, r"^[0-9]{10}077c62eb$", "the id is epoch seconds then the session hex")
        self.assertTrue(self.f.is_file(), "the file is named by the id")
        self.assertEqual(self.lines()[0], "# Size the store", "the title heads the file")
        log = self.lines()[self.lines().index("## Log") + 1]
        self.assertEqual(log.split(" ", 1)[1],
                         "077c62eb status=open owner=agent repo=mark-brannan/dotfiles "
                         "parent=- model=sonnet effort=medium",
                         "the first log line is status=open with the facts")
        self.assertEqual(fact(self.id, "status"), "open", "created in open")
        self.assertEqual(fact(self.id, "points"), "3", "points come from the brief")
        self.assertEqual(fact(self.id, "briefed"), "1", "a brief at create logs briefed")
        brief = self.lines()[self.lines().index("## Brief"):]
        self.assertEqual(brief[2], "Measure growth per day.", "the brief text is in the Brief section")

    def test_02_create_refusals(self):
        self.assertEqual(run(A, "create", "--id", self.id, "Again").returncode, 1,
                         "a second create of one id is refused")
        self.assertEqual(self.lines()[0], "# Size the store", "the refused create left the file alone")
        self.assertEqual(run(A, "create", "--points", "4", "Bad points").returncode, 2,
                         "points outside fibonacci refuse")
        self.assertEqual(run(A, "create", "--owner", "boss", "Bad owner").returncode, 2,
                         "an unknown owner refuses")
        self.assertEqual(run("", "create", "No session").returncode, 2, "no session id refuses")

    def test_03_open_to_ready(self):
        self.assertEqual(run(A, "claim", self.id).returncode, 1, "an open item cannot be claimed")
        self.assertEqual(run(A, "log", self.id, "status=done").returncode, 1,
                         "open -> done is not a transition")
        ok(A, "log", self.id, "status=ready")
        self.assertEqual(fact(self.id, "status"), "ready", "open -> ready")
        n = len(self.lines())
        self.assertEqual(run("", "claim", self.id).returncode, 2, "a claim with no session id refuses")
        self.assertEqual(len(self.lines()), n, "the refused claim wrote no line")

    def test_04_claim_is_held(self):
        ok(B, "claim", self.id)
        self.assertEqual(fact(self.id, "status"), "claimed", "a ready item is claimed")
        self.assertEqual(fact(self.id, "holder"), "9a1b2c3d", "the claimer holds it")
        p = run(A, "claim", self.id)
        self.assertEqual(p.returncode, 1, "a claim is refused while held")
        self.assertIn("held by 9a1b2c3d", p.stderr, "the refusal names the holder")
        self.assertEqual(run(A, "log", self.id, "status=done").returncode, 1,
                         "a non-holder cannot move a held item")
        self.assertEqual(run(A, "release", self.id).returncode, 1, "a non-holder cannot release")
        ok(A, "log", self.id, "note=looked")
        self.assertEqual(fact(self.id, "status"), "claimed", "a line without a status changes nothing")

    def test_05_blocked_and_release(self):
        ok(B, "log", self.id, "status=blocked", "until=dotfiles#1")
        self.assertEqual(fact(self.id, "holder"), "9a1b2c3d", "claimed -> blocked keeps the holder")
        self.assertEqual(fact(self.id, "until"), "dotfiles#1", "until is a fact")
        self.assertEqual(run(A, "claim", self.id).returncode, 1, "a blocked item is still held")
        ok(B, "release", self.id)
        self.assertEqual(fact(self.id, "status"), "ready", "release hands it back ready")
        self.assertEqual(fact(self.id, "holder"), "", "release clears the holder")

    def test_06_cost_and_close(self):
        ok(A, "claim", self.id)
        ok(A, "log", self.id, "cost", "tokens=812340", "usd=1.42", "by=grind")
        ok(A, "log", self.id, "status=done", "home=mark-brannan/dotfiles#481")
        ok(B, "claim", self.id)
        self.assertEqual(fact(self.id, "holder"), "9a1b2c3d",
                         "done -> claimed when acceptance finds it wanting")
        ok(B, "log", self.id, "cost", "tokens=100000", "usd=0.58", "by=pickup")
        ok(B, "log", self.id, "status=done")
        ok(B, "log", self.id, "status=closed")
        self.assertEqual(fact(self.id, "status"), "closed", "done -> closed")
        self.assertEqual(fact(self.id, "cost_tokens"), "912340", "cost lines fold to a token total")
        self.assertEqual(fact(self.id, "cost_usd"), "2", "cost lines fold to a dollar total")
        self.assertEqual(fact(self.id, "costs"), "2", "every cost line counts")
        self.assertEqual(fact(self.id, "home"), "mark-brannan/dotfiles#481", "home is a fact")
        self.assertEqual(run(A, "log", self.id, "status=ready").returncode, 1,
                         "closed -> ready is not a transition")
        ok(A, "claim", self.id)
        self.assertEqual(fact(self.id, "holder"), "077c62eb", "closed -> claimed")

    def test_07_stale_claim(self):
        # A holder that wrote nothing on the item for two hours has let go.
        # Its own id: the minted one is epoch seconds, and a fast run is still
        # in the second that minted self.id.
        old = ok(A, "create", "--id", "1700000000077c62eb", "Stale one")
        ok(A, "log", old, "status=ready")
        with open(self.dir / f"{old}.md", "a") as fh:
            fh.write("2020-01-01T00:00:00Z 9a1b2c3d status=claimed\n")
        self.assertEqual(fact(old, "holder_stale"), "yes", "an old claim folds stale")
        ok(A, "claim", old)
        self.assertEqual(fact(old, "holder"), "077c62eb", "a stale claim can be taken")
        self.assertEqual(fact(old, "holder_stale"), "no", "a fresh claim is not stale")

    def test_08_brief(self):
        ok(A, "brief", self.id, "Rewritten.")
        self.assertEqual(fact(self.id, "briefed"), "2", "a brief change logs briefed")
        self.assertEqual(fact(self.id, "points"), "3", "a brief change keeps the points")
        self.assertEqual(sum("status=closed" in l for l in self.lines()), 1,
                         "a brief change keeps the log")
        self.assertEqual(run(A, "brief", self.id, "-", stdin="line one\n## Log\n").returncode, 2,
                         "a brief cannot carry a section heading")

    def test_09_lookup(self):
        self.assertEqual(run(A, "show", "1790000000ffffffff").returncode, 1, "an unknown id is not found")
        self.assertEqual(run(A, "fold", "179000").returncode, 2, "a malformed id is refused")


if __name__ == "__main__":
    unittest.main()
