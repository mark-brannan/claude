#!/usr/bin/env python3
# Tests for agent-decision. Run: python3 bin/agent-decision.test.py
#
# What matters: two calls append two entries, oldest first, each under a
# roll-style stamp heading; the same entry lands in the repo file and the
# curia's own file, never roll.md; a curia without a folder writes nothing.
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AD = Path(__file__).resolve().parent / "agent-decision"
STAMP = re.compile(r"^### \d{8}t\d{6}z$")


class AgentDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.repo, self.state = t / "repo", t / "state"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.state / ".git").mkdir(parents=True)
        self.curia = self.state / "state/global/curia/one-entry-point"
        self.curia.mkdir(parents=True)
        (self.curia / "roll.md").write_text("words\n")
        self.env = {**os.environ, "CLAUDE_STATE_REPO": str(self.state)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_ad(self, *args):
        return subprocess.run([sys.executable, str(AD), "--repo", str(self.repo), *args],
                              env=self.env, capture_output=True, text=True)

    def test_two_entries_stamped_in_both_files(self):
        a = self.run_ad("--curia", "one-entry-point", "--undo", "revert it", "--link", "[#1](u)", "first call")
        b = self.run_ad("--curia", "one-entry-point", "--link", "u\n### 20990101t000000z", "second\n  call")
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        log = (self.repo / "docs/agent_decisions.md").read_text()
        self.assertEqual(log, (self.curia / "agent_decisions.md").read_text())
        self.assertEqual((self.curia / "roll.md").read_text(), "words\n")
        self.assertTrue(log.startswith("# Agent decisions\n"))
        heads = [l for l in log.splitlines() if l.startswith("### ")]
        self.assertIn(len(heads), (1, 2))  # one when both land in the same second
        self.assertTrue(all(STAMP.match(h) for h in heads), heads)
        self.assertEqual(heads, sorted(heads))
        bullets = [l for l in log.splitlines() if l.startswith("- ")]
        self.assertEqual(bullets, ["- first call Undo: revert it ([#1](u))", "- second call (u ### 20990101t000000z)"])
        self.assertEqual(log.count("# Agent decisions"), 1)

    def test_not_a_checkout_is_refused(self):
        p = subprocess.run([sys.executable, str(AD), "--repo", self.tmp.name, "a call"],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_symlinked_log_is_refused(self):
        (self.repo / "docs").mkdir()
        (self.repo / "docs/agent_decisions.md").symlink_to(self.curia / "roll.md")
        self.assertEqual(self.run_ad("a call").returncode, 1)
        self.assertEqual((self.curia / "roll.md").read_text(), "words\n")

    def test_unknown_curia_writes_nothing(self):
        p = self.run_ad("--curia", "no-such", "a call")
        self.assertEqual(p.returncode, 1)
        self.assertFalse((self.repo / "docs/agent_decisions.md").exists())


if __name__ == "__main__":
    unittest.main()
