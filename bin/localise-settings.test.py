#!/usr/bin/env python3
# Tests for localise-settings. Run: python3 bin/localise-settings.test.py
#
# What matters: the terms path follows the state repo where there is one, even
# when the list is missing from it (that guard should deny loudly); with no
# state repo the option is gone, not left naming another machine's path; other
# options survive; an unreadable file is exit 2 with the original untouched.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LS = Path(__file__).resolve().parent / "localise-settings"
REPO = Path(__file__).resolve().parent.parent / "settings.json"


class LocaliseSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.settings = Path(self.tmp.name) / "settings.json"
        self.settings.write_text(REPO.read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def run_it(self, state_repo=None):
        # A HOME of its own and only CLAUDE_STATE_REPO: no search path finds the host's repo.
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home)}
        if state_repo:
            env["CLAUDE_STATE_REPO"] = str(state_repo)
        r = subprocess.run([sys.executable, str(LS), str(self.settings)],
                           env=env, capture_output=True, text=True)
        return r, json.loads(self.settings.read_text())

    def options(self, s):
        return s["pluginConfigs"]["languette@languette"]["options"]

    def test_state_repo_with_the_list_names_it(self):
        st = Path(self.tmp.name) / "state"
        (st / ".git").mkdir(parents=True)
        (st / "redacted-terms.tsv").write_text("term\treplacement\n")
        (st / "blocked-terms.tsv").write_text("term\n")
        r, s = self.run_it(st)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.options(s)["redacted_terms_file"], f"{st}/redacted-terms.tsv")
        self.assertEqual(self.options(s)["blocked_terms_file"], f"{st}/blocked-terms.tsv")

    def test_state_repo_without_the_list_still_names_it(self):
        st = Path(self.tmp.name) / "state"
        (st / ".git").mkdir(parents=True)
        r, s = self.run_it(st)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.options(s)["redacted_terms_file"], f"{st}/redacted-terms.tsv")
        self.assertEqual(self.options(s)["blocked_terms_file"], f"{st}/blocked-terms.tsv")

    def test_no_state_repo_drops_the_option_and_says_so(self):
        r, s = self.run_it()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("redacted_terms_file", self.options(s))
        self.assertNotIn("blocked_terms_file", self.options(s))
        self.assertIn("guard-private-terms is off", r.stdout)

    def test_other_options_and_prose_budget(self):
        before = self.options(json.loads(REPO.read_text()))
        r, s = self.run_it()
        self.assertEqual({k: v for k, v in before.items() if not k.endswith("_terms_file")}, self.options(s))
        self.assertEqual(s["env"]["PROSE_BUDGET"], f"{self.home}/.claude/bin/prose-budget")

    def test_unreadable_is_exit_2_and_untouched(self):
        self.settings.write_text("{not json")
        r = subprocess.run([sys.executable, str(LS), str(self.settings)],
                           env={"PATH": os.environ["PATH"], "HOME": str(self.home)},
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.settings.read_text(), "{not json")


if __name__ == "__main__":
    unittest.main()
