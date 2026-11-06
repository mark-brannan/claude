#!/usr/bin/env python3
# Tests for driver-start. Run: python3 bin/driver-start.test.py
#
# What matters: one background session per parent, with Remote Control on and
# `/pickup <parent>` as its prompt, in --cwd; the parent's model and effort
# passed when its create line names them; `driver_session=<uuid>` logged on
# the parent; a parent that already has one refused, and nothing started; the
# claude.ai/code link read from the session's output and printed, or said
# missing without failing; a failing `claude --bg` passes its code through.
# `claude` and `work-item` are stubs; the tool runs from a copy beside the
# work-item stub, as it finds its own work-item.
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "driver-start"
PARENT = "17939595623168262a"
NAME = "Driver %s: hooks-guards-languette-batch-6-children 2026-11-06" % PARENT
UUID = "3aa1df25-b265-443b-8cc2-40e2313ef52c"

# claude stub: logs argv and cwd; --bg prints what the real one prints;
# `agents --json` lists the session; `logs` prints the link, ANSI-wrapped,
# unless $STUB_NO_LINK is set; $STUB_BG_RC makes --bg fail.
CLAUDE = r'''#!/bin/sh
printf '%s\n' "$*" >> "$STUB_LOG"
pwd -P >> "$STUB_LOG.pwd"
case "$1" in
  --bg)
    [ -n "$STUB_BG_RC" ] && { echo "boom" >&2; exit "$STUB_BG_RC"; }
    printf 'Starting background service\342\200\246\nbackgrounded \302\267 3aa1df25\n  claude agents             list sessions\n' ;;
  agents) echo '[{"id": "0000aaaa", "sessionId": "x"}, {"id": "3aa1df25", "sessionId": "3aa1df25-b265-443b-8cc2-40e2313ef52c"}]' ;;
  logs) [ -z "$STUB_NO_LINK" ] && printf '\033[1m/remote-control is active \302\267 at \033[4mhttps://claude.ai/code/session_01YKXwAD8LvCtzSVyNvDgUcb\033[0m\n' ;;
esac
exit 0
'''

# work-item stub: `show` prints $STUB_ITEM; `log` appends to $STUB_ITEM.log.
WORK_ITEM = r'''#!/bin/sh
case "$1" in
  show) [ -f "$STUB_ITEM" ] || { echo "no such item" >&2; exit 1; }; cat "$STUB_ITEM" ;;
  log) shift; echo "$*" >> "$STUB_ITEM.log"; [ -z "$STUB_LOG_RC" ] || exit "$STUB_LOG_RC" ;;
esac
'''

ITEM = """# Drive the 2026-11-06 hooks-guards + languette batch: 6 children

## Brief
The driver brief. https://example.com/plan

## Log
2026-11-06T10:06:02Z c116ad7b status=open owner=agent repo=mark-brannan/claude parent=- model=%s effort=%s
2026-11-06T10:06:03Z c116ad7b status=ready
2026-11-06T10:06:03Z c116ad7b driver=workflow
"""


class DriverStart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        tools, stubs = self.tmp / "tools", self.tmp / "stubs"
        tools.mkdir()
        stubs.mkdir()
        shutil.copy(TOOL, tools / "driver-start")
        (tools / "work-item").write_text(WORK_ITEM)
        (stubs / "claude").write_text(CLAUDE)
        for p in (tools / "work-item", stubs / "claude", tools / "driver-start"):
            p.chmod(0o755)
        self.tool = tools / "driver-start"
        self.cwd = self.tmp / "here"
        self.cwd.mkdir()
        self.item = self.tmp / "item.md"
        self.item.write_text(ITEM % ("-", "-"))
        self.claude_log = self.tmp / "claude.log"
        self.env = dict(os.environ, PATH="%s:%s" % (stubs, os.environ["PATH"]),
                        STUB_LOG=str(self.claude_log), STUB_ITEM=str(self.item))

    def run_tool(self, *args, **env):
        return subprocess.run([sys.executable, str(self.tool), "--cwd", str(self.cwd), "--wait", "0", *args],
                              text=True, capture_output=True, env=dict(self.env, **env))

    def calls(self):
        return self.claude_log.read_text().splitlines() if self.claude_log.exists() else []

    def logged(self):
        p = Path(str(self.item) + ".log")
        return p.read_text().splitlines() if p.exists() else []

    def test_starts_one_background_driver_with_remote_control(self):
        r = self.run_tool(PARENT)
        self.assertEqual(r.returncode, 0, r.stderr)
        bg = [c for c in self.calls() if c.startswith("--bg")]
        self.assertEqual(bg, ["--bg --remote-control %s -n %s /pickup %s" % (NAME, NAME, PARENT)])
        self.assertEqual(Path(str(self.claude_log) + ".pwd").read_text().splitlines()[0], str(self.cwd.resolve()))

    def test_logs_the_full_session_id_on_the_parent(self):
        self.run_tool(PARENT)
        self.assertEqual(self.logged(), ["%s driver_session=%s" % (PARENT, UUID)])

    def test_prints_how_to_attach(self):
        out = self.run_tool(PARENT).stdout
        self.assertIn("driver started: %s, session %s" % (NAME, UUID), out)
        self.assertIn('Claude Desktop: the session list, "%s"' % NAME, out)
        self.assertIn("https://claude.ai/code/session_01YKXwAD8LvCtzSVyNvDgUcb\n", out)
        self.assertIn("claude attach 3aa1df25", out)

    def test_about_names_the_session(self):
        self.run_tool("--about", "Hooks-guards curia + languette", PARENT)
        bg = [c for c in self.calls() if c.startswith("--bg")][0]
        self.assertIn("-n Driver %s: hooks-guards-curia-languette 2026-11-06 /pickup" % PARENT, bg)

    def test_a_long_title_is_cut_at_a_word(self):
        self.item.write_text(ITEM.replace("hooks-guards + languette batch: 6 children",
                                          "every open issue in the signalk-noaa repo, oldest first") % ("-", "-"))
        self.run_tool(PARENT)
        bg = [c for c in self.calls() if c.startswith("--bg")][0]
        self.assertIn("-n Driver %s: every-open-issue-in-the-signalk-noaa 2026-11-06 /pickup" % PARENT, bg)

    def test_a_missing_link_is_said_not_failed(self):
        r = self.run_tool(PARENT, STUB_NO_LINK="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("(no link yet)", r.stdout)

    def test_passes_the_parents_model_and_effort(self):
        self.item.write_text(ITEM % ("opus", "high"))
        self.run_tool(PARENT)
        bg = [c for c in self.calls() if c.startswith("--bg")][0]
        self.assertIn("--model opus --effort high /pickup", bg)

    def test_refuses_a_parent_that_has_a_driver(self):
        self.item.write_text(ITEM % ("-", "-") + "2026-11-06T10:07:00Z c116ad7b driver_session=%s\n" % UUID)
        r = self.run_tool(PARENT)
        self.assertEqual(r.returncode, 1)
        self.assertIn("one driver per yes", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.logged(), [])

    def test_refuses_an_unreadable_parent(self):
        self.item.unlink()
        r = self.run_tool(PARENT)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot read work item", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_bad_id_is_usage(self):
        r = self.run_tool("not an id")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_a_failing_bg_passes_its_code_and_logs_nothing(self):
        r = self.run_tool(PARENT, STUB_BG_RC="3")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.logged(), [])

    def test_an_unlogged_driver_still_prints_attach_and_exits_1(self):
        r = self.run_tool(PARENT, STUB_LOG_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("claude attach 3aa1df25", r.stdout)
        self.assertIn("driver_session not logged", r.stderr)


if __name__ == "__main__":
    unittest.main()
