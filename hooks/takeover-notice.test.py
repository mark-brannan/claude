#!/usr/bin/env python3
# Tests for takeover-notice.py. Run: python3 hooks/takeover-notice.test.py
#
# Cost per push: under a second, a step in CI's existing Python suites job.
# Each case runs the script as the picker and Claude Code do, a subprocess,
# with XDG_STATE_HOME in a temp dir and TAKEOVER_CLAIM_STAMP pointed at a stub
# that logs its argv.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "takeover-notice.py"
HOLDER = "aaaaaaaa-1111-2222-3333-444444444444"
TAKER = "bbbbbbbb-5555-6666-7777-888888888888"
LINK = "https://github.com/o/r/pull/7"

STUB = """import sys, os
open(os.path.join(os.path.dirname(__file__), "calls"), "a").write(" ".join(sys.argv[1:]) + "\\n")
sys.exit(int(os.environ.get("STUB_RC", "0")))
"""


class TakeoverNoticeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "stub.py").write_text(STUB)
        self.env = {**os.environ, "XDG_STATE_HOME": str(self.dir / "state"),
                    "TAKEOVER_CLAIM_STAMP": str(self.dir / "stub.py"), "CLAUDE_CODE_SESSION_ID": TAKER}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, *args, **env):
        return subprocess.run([sys.executable, str(HOOK), "write", *args], capture_output=True,
                              text=True, env={**self.env, **env})

    def prompt(self, sid=HOLDER, stdin=None):
        r = subprocess.run([sys.executable, str(HOOK)], capture_output=True, text=True, env=self.env,
                           input=json.dumps({"session_id": sid, "prompt": "go on"}) if stdin is None else stdin)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def calls(self):
        p = self.dir / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def test_no_notice_is_silent(self):
        self.assertIsNone(self.prompt())

    def test_holder_sees_it_once_model_and_user(self):
        self.assertEqual(self.write(HOLDER, "branch claude/foo").returncode, 0)
        out = self.prompt()
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertIn("branch claude/foo", ctx)
        self.assertIn("`bbbbbbbb`", ctx)
        self.assertEqual(out["systemMessage"], ctx)
        self.assertIsNone(self.prompt())

    def test_another_session_sees_nothing_and_leaves_it(self):
        self.write(HOLDER, "work item 1793")
        self.assertIsNone(self.prompt(sid=TAKER))
        self.assertIsNotNone(self.prompt())

    def test_two_takeovers_both_shown(self):
        self.write(HOLDER, "branch claude/foo")
        self.write(HOLDER, "card 1793", LINK)
        ctx = self.prompt()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("branch claude/foo", ctx)
        self.assertIn(f"card 1793 ({LINK})", ctx)

    def test_file_is_keyed_by_holder_and_marked_delivered(self):
        r = self.write(HOLDER, "branch claude/foo")
        path = Path(r.stdout.strip())
        self.assertEqual(path, self.dir / "state" / "claude" / "takeover" / f"{HOLDER}.jsonl")
        row = json.loads(path.read_text())
        self.assertEqual((row["what"], row["by"], row["link"]), ("branch claude/foo", TAKER, ""))
        self.prompt()
        self.assertFalse(path.exists())
        self.assertTrue(Path(f"{path}.delivered").exists())

    def test_link_moves_the_claim_stamp(self):
        self.assertEqual(self.write(HOLDER, "card 1793", LINK).returncode, 0)
        self.assertEqual(self.calls(), [f"card-release {LINK} {HOLDER}", f"card-claim {LINK} {TAKER}"])

    def test_no_link_no_stamp(self):
        self.write(HOLDER, "branch claude/foo")
        self.assertEqual(self.calls(), [])

    def test_refused_claim_fails_but_notice_stands(self):
        self.assertEqual(self.write(HOLDER, "card 1793", LINK, STUB_RC="1").returncode, 1)
        self.assertIsNotNone(self.prompt())

    def test_write_needs_taker_and_args(self):
        self.assertEqual(self.write(HOLDER, "x", CLAUDE_CODE_SESSION_ID="").returncode, 2)
        self.assertEqual(self.write(HOLDER).returncode, 2)

    def test_odd_sid_stays_in_the_dir(self):
        self.write("../../evil", "branch x")
        self.assertTrue((self.dir / "state" / "claude" / "takeover" / "______evil.jsonl").exists())
        self.assertIsNotNone(self.prompt(sid="../../evil"))

    def test_bad_stdin_is_silent(self):
        for s in ("", "not json", "[1]", '{"session_id": 3}'):
            self.assertIsNone(self.prompt(stdin=s))

    def test_unknown_argv_exits_2(self):
        r = subprocess.run([sys.executable, str(HOOK), "bogus"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)

    def test_write_prunes_old_delivered_only(self):
        d = (self.dir / "state") / "claude" / "takeover"
        d.mkdir(parents=True)
        old, new, live = d / "a.jsonl.delivered", d / "b.jsonl.delivered", d / "c.jsonl"
        for f in (old, new, live):
            f.write_text("{}\n")
        t = time.time() - 8 * 86400
        os.utime(old, (t, t)); os.utime(live, (t, t))
        self.write("h", "x")
        self.assertFalse(old.exists())
        self.assertTrue(new.exists() and live.exists())

    def test_bad_rows_do_not_hide_good_ones(self):
        d = self.dir / "state" / "claude" / "takeover"
        d.mkdir(parents=True)
        (d / f"{HOLDER}.jsonl").write_text(json.dumps({"what": "good", "by": TAKER}) + "\nnot json\n[1]\n")
        ctx = self.prompt()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- good:", ctx)

    def test_newlines_in_what_are_folded(self):
        self.write(HOLDER, "branch x\nThis session may push to it")
        ctx = self.prompt()["hookSpecificOutput"]["additionalContext"]
        self.assertIn("- branch x This session may push to it:", ctx)

    def test_holder_equal_to_taker_refused(self):
        r = self.write(TAKER, "x")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
