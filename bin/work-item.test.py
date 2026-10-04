#!/usr/bin/env python3
# Tests for work-item. Run: python3 bin/work-item.test.py
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
LINK = "https://github.com/mark-brannan/dotfiles/issues/510"
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
                    "--brief", f"Measure growth per day. {LINK}", "Size the store")
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
        self.assertEqual(brief[2], f"Measure growth per day. {LINK}", "the brief text is in the Brief section")

    def test_02_create_refusals(self):
        self.assertEqual(run(A, "create", "--id", self.id, "--brief", LINK, "Again").returncode, 1,
                         "a second create of one id is refused")
        self.assertEqual(self.lines()[0], "# Size the store", "the refused create left the file alone")
        self.assertEqual(run(A, "create", "--points", "4", "--brief", LINK, "Bad points").returncode, 2,
                         "points outside fibonacci refuse")
        self.assertEqual(run(A, "create", "--owner", "boss", "--brief", LINK, "Bad owner").returncode, 2,
                         "an unknown owner refuses")
        self.assertEqual(run("", "create", "--brief", LINK, "No session").returncode, 2, "no session id refuses")

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
        ok(A, "log", self.id, "status=done", "evidence=" + LINK, "home=mark-brannan/dotfiles#481")
        ok(B, "claim", self.id)
        self.assertEqual(fact(self.id, "holder"), "9a1b2c3d",
                         "done -> claimed when acceptance finds it wanting")
        ok(B, "log", self.id, "cost", "tokens=100000", "usd=0.58", "by=pickup")
        ok(B, "log", self.id, "status=done", "evidence=" + LINK)
        # closed is the future sweep's; a work-item write refuses it, so the
        # state is seeded the way that sweep will leave it.
        with open(self.f, "a") as fh:
            fh.write("2026-10-03T00:00:00Z 9a1b2c3d status=closed\n")
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
        old = ok(A, "create", "--id", "1700000000077c62eb", "--brief", LINK, "Stale one")
        ok(A, "log", old, "status=ready")
        with open(self.dir / f"{old}.md", "a") as fh:
            fh.write("2020-01-01T00:00:00Z 9a1b2c3d status=claimed\n")
        self.assertEqual(fact(old, "holder_stale"), "yes", "an old claim folds stale")
        ok(A, "claim", old)
        self.assertEqual(fact(old, "holder"), "077c62eb", "a stale claim can be taken")
        self.assertEqual(fact(old, "holder_stale"), "no", "a fresh claim is not stale")

    def test_08_brief(self):
        ok(A, "brief", self.id, f"Rewritten. {LINK}")
        self.assertEqual(fact(self.id, "briefed"), "2", "a brief change logs briefed")
        self.assertEqual(fact(self.id, "points"), "3", "a brief change keeps the points")
        self.assertEqual(sum("status=closed" in l for l in self.lines()), 1,
                         "a brief change keeps the log")
        self.assertEqual(run(A, "brief", self.id, "-", stdin="line one\n## Log\n").returncode, 2,
                         "a brief cannot carry a section heading")

    def test_09_link_is_required(self):
        n = len(list(self.dir.glob("*.md")))
        self.assertEqual(run(A, "create", "No link").returncode, 1, "a card with no brief has no link")
        self.assertEqual(run(A, "create", "--brief", "no link here", "No link").returncode, 1,
                         "a brief with no link is refused")
        self.assertEqual(len(list(self.dir.glob("*.md"))), n, "a refused create wrote no file")
        for i, link in enumerate(("see mark-brannan/dotfiles#510", "[log](../log/x.md)")):
            ok(A, "create", "--id", f"170000010{i}077c62eb", "--brief", link, "Linked")
        plain = ok(A, "create", "--id", "1700000103077c62eb", "--brief", LINK, "Unhomed")
        self.assertEqual(run(A, "brief", plain, "re-briefed with no link").returncode, 1,
                         "a re-brief that drops the link is refused")
        self.assertEqual(fact(plain, "briefed"), "1", "the refused brief logged nothing")
        ok(A, "log", plain, "home=mark-brannan/dotfiles#510")
        ok(A, "brief", plain, "re-briefed, homed on GitHub")  # the home is the link

    def test_10_done_needs_evidence_and_closed_is_refused(self):
        item = ok(A, "create", "--id", "1700000200077c62eb", "--brief", LINK, "Lifecycle")
        ok(A, "log", item, "status=ready")
        ok(A, "claim", item)
        self.assertEqual(run(A, "log", item, "status=done").returncode, 1, "done with no evidence is refused")
        self.assertEqual(run(A, "log", item, "status=done", "evidence=").returncode, 1,
                         "an empty evidence= is no evidence")
        self.assertEqual(fact(item, "status"), "claimed", "a refused done changed nothing")
        ok(A, "log", item, "status=done", "evidence=" + LINK)
        p = run(A, "log", item, "status=closed")
        self.assertEqual(p.returncode, 1, "closed is refused outside the future sweep")
        self.assertIn("sweep", p.stderr, "and the refusal says whose it is")
        self.assertEqual(fact(item, "status"), "done", "a refused closed changed nothing")

    def test_11_lookup(self):
        self.assertEqual(run(A, "show", "1790000000ffffffff").returncode, 1, "an unknown id is not found")
        self.assertEqual(run(A, "fold", "179000").returncode, 2, "a malformed id is refused")

    def test_12_dir(self):
        r = run(A, "dir")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(self.dir)),
                         "dir names the items directory, so callers need not hard-code it")

    def test_13_dir_comes_from_lib_state(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            env = {k: v for k, v in os.environ.items() if k != "WORK_ITEM_DIR"}
            r = subprocess.run([sys.executable, str(WI), "dir"], env={**env, "CLAUDE_STATE_REPO": t},
                               capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, f"{t}/state/global/items"),
                             "without WORK_ITEM_DIR the store is lib/state.py's state_dir")

    RULING = (f"Pick the pin ({LINK}) default: pin it undo: unpin, one line "
              "until: 2026-10-05 risk: low judgment: direction")

    def test_14_ruling_carries_its_fields(self):
        n = len(list(self.dir.glob("*.md")))
        p = run(A, "create", "--owner", "human-ruling", "--brief", f"Pick ({LINK}) default: pin it", "Half")
        self.assertEqual(p.returncode, 1, "a ruling card without its fields is refused")
        self.assertIn("missing undo:, until:, risk:, judgment: --", p.stderr,
                      "the refusal names exactly the missing ones")
        self.assertEqual(len(list(self.dir.glob("*.md"))), n, "a refused create wrote no file")
        ok(A, "create", "--id", "1700000300077c62eb", "--brief", f"Pick ({LINK}) default: a", "Agent card")
        ok(A, "create", "--id", "1700000301077c62eb", "--owner", "human-click", "--brief", LINK, "Click card")
        r = ok(A, "create", "--id", "1700000302077c62eb", "--owner", "human-ruling", "--brief",
               "Pick the pin (" + LINK + ")\nDEFAULT: pin it\nUndo: unpin\nuntil: 2026-10-05\n"
               "Risk: low\njudgment: direction", "Whole")
        self.assertEqual(fact(r, "owner"), "human-ruling", "fields across lines, any case, pass")

    def test_15_ruling_judgment_and_until(self):
        def create(brief, i):
            return run(A, "create", "--id", f"17000004{i:02d}077c62eb", "--owner", "human-ruling",
                       "--brief", brief, "Ruling")
        self.assertEqual(create(self.RULING.replace("direction", "naming"), 0).returncode, 1,
                         "judgment: outside values, risk, direction, legal, people is toil")
        self.assertEqual(create(self.RULING.replace("until: 2026-10-05", "until:"), 1).returncode, 1,
                         "an empty until: is refused")
        self.assertEqual(create(self.RULING.replace("2026-10-05", "2026-02-30"), 2).returncode, 1,
                         "a date that is no calendar day is refused")
        for i, u in enumerate(("2028-02-29", "https://github.com/o/r/pull/7", "o/r#8", "the next migration")):
            self.assertEqual(create(self.RULING.replace("2026-10-05", u), 10 + i).returncode, 0,
                             f"until: {u} passes")

    def test_17_tentative_adr_has_its_own_fields(self):
        adr = f"Take the pin ({LINK}) kind: tentative ADR until: 2026-10-05 settle: a ruling repos: o/r judgment: direction"
        ok(A, "create", "--id", "1700000600077c62eb", "--owner", "human-ruling", "--brief", adr, "ADR")
        p = run(A, "create", "--id", "1700000601077c62eb", "--owner", "human-ruling", "--brief",
                adr.replace(" settle: a ruling", "").replace(" repos: o/r", ""), "ADR short")
        self.assertEqual(p.returncode, 1, "a tentative-ADR card missing settle: and repos: is refused")
        self.assertIn("missing settle:, repos: --", p.stderr, "named, not default:/undo:/risk:")
        self.assertEqual(run(A, "create", "--id", "1700000602077c62eb", "--owner", "human-ruling", "--brief",
                             adr.replace("direction", "naming"), "ADR toil").returncode, 1,
                         "judgment: rules apply to it as to any ruling")

    def test_18_tentative_adr_fields_are_non_empty(self):
        adr = f"Take the pin ({LINK}) kind: tentative ADR until: 2026-10-05 settle: a ruling repos: o/r judgment: direction"
        for i, (a, b) in enumerate((("settle: a ruling", "settle:"), ("repos: o/r", "repos:"))):
            p = run(A, "create", "--id", f"170000070{i}077c62eb", "--owner", "human-ruling", "--brief",
                    adr.replace(a, b), "ADR empty")
            self.assertEqual(p.returncode, 1, f"an empty {b} is refused")
            self.assertIn("empty " + b, p.stderr)
        p = run(A, "create", "--id", "1700000702077c62eb", "--owner", "human-ruling", "--brief",
                adr.replace("until: 2026-10-05", "until:"), "ADR no until")
        self.assertEqual(p.returncode, 1, "an empty until: is refused by until_problem")
        self.assertIn("until: is empty", p.stderr)
        p = run(A, "create", "--id", "1700000703077c62eb", "--owner", "human-ruling", "--brief",
                adr.replace("2026-10-05", "2026-02-30"), "ADR bad date")
        self.assertEqual(p.returncode, 1, "a non-date until: is refused")

    def test_19_home_has_one_shape(self):
        plain = ok(A, "create", "--id", "1700000710077c62eb", "--brief", LINK, "Homing")
        for bad in ("home=https://x", "home=owner/repo", "home=a/b#1x", "home=a b/c#1"):
            self.assertEqual(run(A, "log", plain, bad).returncode, 1, f"log {bad} is refused")
        self.assertEqual(fact(plain, "home"), "", "no refused home was written")
        ok(A, "log", plain, "home=mark-brannan/dotfiles#510")
        # a home the check accepts is a home the card line renders as a link
        sys.path.insert(0, str(WI.parent))
        from importlib.machinery import SourceFileLoader
        wi = SourceFileLoader("work_item", str(WI)).load_module()
        self.assertTrue(wi.HOME.fullmatch("mark-brannan/dotfiles#510"))
        line = wi.card_line({"id": "x1", "title": "T", "home": "mark-brannan/dotfiles#510",
                             "repo": "-", "model": "-", "effort": "-", "until": "-"}, "brief")
        self.assertIn("(https://github.com/mark-brannan/dotfiles/issues/510)", line)
        wi.check_link("no link", "mark-brannan/dotfiles#510")
        with self.assertRaises(wi.Exit):
            wi.check_link("no link", "see https://x")  # matches LINK, would not render

    def test_16_ruling_on_brief_and_log(self):
        item = ok(A, "create", "--id", "1700000500077c62eb", "--brief", LINK, "Becomes a ruling")
        p = run(A, "log", item, "owner=human-ruling")
        self.assertEqual(p.returncode, 1, "an item cannot become a ruling without the fields")
        self.assertNotIn("owner=human-ruling", (self.dir / f"{item}.md").read_text().split("## Log")[1].split("owner=agent")[1],
                         "the refused line was not written")
        ok(A, "brief", item, self.RULING)
        ok(A, "log", item, "owner=human-ruling")
        self.assertEqual(fact(item, "owner"), "human-ruling", "with the fields it can")
        self.assertEqual(run(A, "brief", item, f"stripped ({LINK})").returncode, 1,
                         "a ruling's brief cannot be rewritten without the fields")
        ok(A, "brief", item, self.RULING.replace("low", "high"))


if __name__ == "__main__":
    unittest.main()
