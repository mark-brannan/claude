#!/usr/bin/env python3
# Tests for confer-start. Run: python3 bin/confer-start.test.py
#
# What matters: one background session per card, Remote Control on, named
# for the card's short name, with the confer hand-off as its prompt and the
# sitting's model and effort (fable, high by default); `confer_session=<uuid>`
# logged on the card; a card that already has one refused, nothing started.
# The start itself is driver-start's, tested there; the stubs are its.
import importlib.util
import shutil
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_loader("dst", loader=None)
dst = importlib.util.module_from_spec(spec)
dst.__file__ = str(HERE / "driver-start.test.py")
exec((HERE / "driver-start.test.py").read_text(), dst.__dict__)

CARD = dst.PARENT


class ConferStart(unittest.TestCase):
    # driver-start's fixture and helpers, not its tests.
    run_tool, calls, logged = dst.DriverStart.run_tool, dst.DriverStart.calls, dst.DriverStart.logged

    def setUp(self):
        dst.DriverStart.setUp(self)
        tools = self.tmp / "tools"
        shutil.copy(HERE / "confer-start", tools / "confer-start")
        (tools / "confer-start").chmod(0o755)
        self.tool = tools / "confer-start"

    def bg(self):
        return [c for c in self.calls() if c.startswith("--bg")]

    def test_starts_one_confer_with_the_hand_off(self):
        r = self.run_tool("--title", "Tag  names", CARD)
        self.assertEqual(r.returncode, 0, r.stderr)
        bg = self.bg()
        self.assertEqual(len(bg), 1)
        self.assertTrue(bg[0].startswith("--bg --remote-control Confer Tag names -n Confer Tag names "
                                         "--model fable --effort high Confer on work item %s (Tag names)" % CARD), bg[0])
        self.assertIn("work-item show %s" % CARD, bg[0])
        self.assertIn("open no curia unless the user says so", bg[0])
        self.assertIn("confer started: Confer Tag names", r.stdout)

    def test_takes_the_sittings_model_and_effort(self):
        self.run_tool("--model", "opus", "--effort", "medium", CARD)
        self.assertIn("--model opus --effort medium", self.bg()[0])

    def test_untitled_is_named_for_the_card(self):
        self.run_tool(CARD)
        self.assertIn("-n Confer %s " % CARD, self.bg()[0])

    def test_logs_confer_session(self):
        self.run_tool(CARD)
        self.assertEqual(self.logged(), ["%s confer_session=%s" % (CARD, dst.UUID)])

    def test_refuses_a_card_that_has_a_confer(self):
        self.item.write_text(dst.ITEM % ("-", "-") + "2026-11-06T10:07:00Z c116ad7b confer_session=x\n")
        r = self.run_tool(CARD)
        self.assertEqual(r.returncode, 1)
        self.assertIn("one session per yes", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_driver_session_does_not_block_a_confer(self):
        self.item.write_text(dst.ITEM % ("-", "-") + "2026-11-06T10:07:00Z c116ad7b driver_session=x\n")
        self.assertEqual(self.run_tool(CARD).returncode, 0)


if __name__ == "__main__":
    unittest.main()
