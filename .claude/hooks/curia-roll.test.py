#!/usr/bin/env python3
# Tests for curia-roll.py. Run: python3 .claude/hooks/curia-roll.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job,
# so no new job and nothing drawn from the account's concurrent-job cap.
# Each case runs the hook as Claude Code does, a subprocess fed event JSON on
# stdin, against a throwaway state repo named by CLAUDE_STATE_REPO.
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "curia-roll.py"
SID = "3554281d-fda5-4810-9e67-8117eb8e7006"
OTHER = "29ff522d-c4ec-4b34-bf83-e7a010fb6c1e"
ENTRY = re.compile(r"\n### (\d{8}t\d{6}z)\n(`{3,})\n(.*?)\n\2\n", re.S)


class CuriaRollTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".git").mkdir()
        self.curia = self.repo / "state" / "global" / "curia"

    def tearDown(self):
        self.tmp.cleanup()

    def sitting(self, cid, live, moved=True):
        d = self.curia / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / "LIVE").write_text(live)
        if moved:
            (d / "digest.md").write_text("# digest\n")
        return d

    def run_hook(self, payload):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        env = dict(os.environ, CLAUDE_STATE_REPO=str(self.repo))
        return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env)

    def prompt(self, text, sid=SID, field="prompt"):
        r = self.run_hook({"session_id": sid, field: text, "hook_event_name": "UserPromptSubmit"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def entries(self, cid):
        return ENTRY.findall((self.curia / cid / "roll.md").read_text())

    def test_appends_one_stamped_entry_for_the_live_session(self):
        self.sitting("one-entry-point", f"{SID} 2026-10-02T05:00:00Z\n")
        self.prompt("yes, make it so")
        [(stamp, _, body)] = self.entries("one-entry-point")
        self.assertEqual(body, "yes, make it so")
        self.assertRegex(stamp, r"\A\d{8}t\d{6}z\Z")

    def test_live_with_a_session_prefix_still_matches(self):
        self.sitting("hook-guards", f"session {SID} 2026-10-02T03:17:35Z\n")
        self.prompt("hi")
        self.assertEqual(len(self.entries("hook-guards")), 1)

    def test_headings_and_backticks_survive_byte_for_byte(self):
        self.sitting("c", f"{SID} t\n")
        text = '### not a stamp\n```sh\nrun ````x````\n```\n<pasted_content id="353c">\n## h\n</pasted_content>\n\n'
        self.prompt(text)
        [(_, fence, body)] = self.entries("c")
        self.assertEqual((fence, body), ("`````", text))

    def test_never_touches_what_is_there(self):
        d = self.sitting("c", f"{SID} t\n")
        before = "# roll\n\n### 20261001t000000z\n```\nold words\n```\n"
        (d / "roll.md").write_text(before)
        self.prompt("first")
        self.prompt("second")
        after = (d / "roll.md").read_text()
        self.assertTrue(after.startswith(before))
        self.assertEqual([e[2] for e in self.entries("c")], ["old words", "first", "second"])

    def test_other_session_and_no_live_are_silent(self):
        self.sitting("c", f"{OTHER} t\n")
        self.sitting("d", "", moved=True)
        (self.curia / "e").mkdir()
        self.prompt("hi")
        self.assertFalse(any(self.curia.glob("*/roll.md")))

    def test_unmoved_curia_keeps_its_curated_roll(self):
        d = self.sitting("c", f"{SID} t\n", moved=False)
        (d / "roll.md").write_text("# curated\n")
        self.prompt("hi")
        self.assertEqual((d / "roll.md").read_text(), "# curated\n")

    def test_the_opening_curia_prompt_is_recorded_before_live_exists(self):
        self.sitting("c", "")
        self.sitting("unmoved", "", moved=False)
        self.prompt("/curia c and my opening words")
        self.prompt("/curia unmoved")
        self.prompt("/curia no-such-curia")
        self.assertEqual([e[2] for e in self.entries("c")], ["/curia c and my opening words"])
        self.assertEqual([p.parent.name for p in self.curia.glob("*/roll.md")], ["c"])

    def test_a_resumed_sitting_records_its_opening_prompt_once(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt("/curia c")
        self.assertEqual(len(self.entries("c")), 1)

    def test_user_input_field_is_read_too(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt("from the docs' field name", field="user_input")
        self.assertEqual(self.entries("c")[0][2], "from the docs' field name")

    def test_two_sessions_both_named_in_live_interleave_whole_entries(self):
        self.sitting("c", f"{SID} t\n{OTHER} t\n")
        self.prompt("from one")
        self.prompt("from two", sid=OTHER)
        self.assertEqual([e[2] for e in self.entries("c")], ["from one", "from two"])

    def test_bad_input_and_unwritable_roll_exit_zero_silently(self):
        for payload in ("", "not json", "[]", {"session_id": SID}, {"prompt": "x"}):
            r = self.run_hook(payload)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        d = self.sitting("c", f"{SID} t\n")
        (d / "roll.md").mkdir()
        self.prompt("x")

    def test_no_state_repo_is_silent(self):
        env = dict(os.environ, CLAUDE_STATE_REPO="", HOME=self.tmp.name)
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": SID, "prompt": "x"}),
                           capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main(verbosity=1)
