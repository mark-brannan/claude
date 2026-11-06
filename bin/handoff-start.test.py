#!/usr/bin/env python3
# Tests for handoff-start. Run: python3 bin/handoff-start.test.py
#
# What matters: one background session per open item, Remote Control on,
# `/pickup <id>` as its prompt, the hand-off's model and effort when named;
# it runs in the repo's main worktree, never a linked one; the item taken
# before the launch and reopened if it fails; an item that is not open is
# refused and nothing starts. `claude` is driver-start's stub;
# `pickup-list` is a stub beside a copy of the tool.
import importlib.util
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_loader("dst", loader=None)
dst = importlib.util.module_from_spec(spec)
dst.__file__ = str(HERE / "driver-start.test.py")
exec((HERE / "driver-start.test.py").read_text(), dst.__dict__)

ID = "2026-11-06T19-27-94e9fcb0"
WHERE = "where: log/auto/e0/2026-11-06-reviewer-model-difficulty-3e94d0-e0ff1112.md\n"
NAME = "Hand-off %s: reviewer-model-difficulty" % ID
# pickup-list stub: `show` prints $STUB_PICKUP; take and open log to $STUB_PICKUP.log.
PICKUP_LIST = r'''#!/bin/sh
case "$1" in
  show) [ -f "$STUB_PICKUP" ] || { echo "no item" >&2; exit 1; }; cat "$STUB_PICKUP" ;;
  take|open) echo "$*" >> "$STUB_PICKUP.log" ;;
esac
'''
ITEM = """status: %s
session: 94e9fcb0-c89a-43c1-bfb1-0248dc3cfc6e
model: claude-opus-5-5
branch: b HEAD (clean)
where: log/auto/e0/2026-11-06-reviewer-model-difficulty-3e94d0-e0ff1112.md
---
Run pr-blockers on the PR.
link: https://github.com/o/r/pull/1
%s"""


class HandoffStart(unittest.TestCase):
    calls = dst.DriverStart.calls

    def setUp(self):
        dst.DriverStart.setUp(self)
        tools = self.tmp / "tools"
        shutil.copy(HERE / "handoff-start", tools / "handoff-start")
        shutil.copy(HERE / "driver-start", tools / "driver-start")
        (tools / "pickup-list").write_text(PICKUP_LIST)
        for n in ("handoff-start", "pickup-list"):
            (tools / n).chmod(0o755)
        self.tool = tools / "handoff-start"
        self.pickup = self.tmp / "pickup.md"
        self.env["STUB_PICKUP"] = str(self.pickup)
        self.write("open", "model: sonnet\neffort: low\n")

    def write(self, status, tail):
        self.pickup.write_text(ITEM % (status, tail))

    def run_tool(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(self.tool), "--wait", "0",
                               "--cwd", str(cwd or self.cwd), *args],
                              text=True, capture_output=True, env=self.env)

    def bg(self):
        return [c for c in self.calls() if c.startswith("--bg")]

    def bg_cwd(self):
        return Path(str(self.claude_log) + ".pwd").read_text().splitlines()[0]

    def test_starts_one_pickup_with_the_hand_offs_model(self):
        r = self.run_tool(ID)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bg(), ["--bg --remote-control %s -n %s "
                                     "--model sonnet --effort low /pickup %s" % (NAME, NAME, ID)])
        self.assertIn("claude.ai/code/session_", r.stdout)

    def test_a_title_line_in_the_body_names_the_session(self):
        self.write("open", "model: sonnet\ntitle: Check PR 415 CI\n")
        self.run_tool(ID)
        self.assertEqual(self.bg()[0].split(" -n ")[1].split(" --model")[0],
                         "Hand-off %s: Check PR 415 CI" % ID)

    def test_a_title_argument_names_the_session(self):
        self.write("open", "model: sonnet\ntitle: Check PR 415 CI\n")
        self.run_tool(ID, "--title", "Reviewer model difficulty")
        self.assertEqual(self.bg()[0].split(" -n ")[1].split(" --model")[0],
                         "Hand-off %s: Reviewer model difficulty" % ID)

    def test_no_log_names_the_session_by_id_alone(self):
        self.pickup.write_text((ITEM % ("open", "model: sonnet\n")).replace(WHERE, ""))
        self.run_tool(ID)
        self.assertEqual(self.bg()[0].split(" -n ")[1].split(" --model")[0], "Hand-off %s" % ID)

    def test_no_model_line_passes_no_model(self):
        self.write("open", "")
        self.run_tool(ID)
        self.assertNotIn("--model", self.bg()[0])

    def test_refuses_an_item_that_is_not_open(self):
        self.write("taken", "")
        r = self.run_tool(ID)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not open", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_refuses_a_card_id(self):
        self.assertEqual(self.run_tool("1793993713b81a55a7").returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_runs_in_the_main_worktree_not_a_linked_one(self):
        repo = self.tmp / "repo"
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(git + ["-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        linked = self.tmp / "linked"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(linked)], check=True)
        self.assertEqual(self.run_tool(ID, cwd=linked).returncode, 0)
        self.assertEqual(self.bg_cwd(), str(repo.resolve()))

    def test_outside_git_runs_in_cwd(self):
        self.run_tool(ID)
        self.assertEqual(self.bg_cwd(), str(self.cwd.resolve()))

    def marks(self):
        p = Path(str(self.pickup) + ".log")
        return p.read_text().splitlines() if p.exists() else []

    def test_takes_the_item_before_the_launch(self):
        self.run_tool(ID)
        self.assertEqual(self.marks(), ["take %s" % ID])

    def test_a_failing_start_reopens_and_passes_its_code(self):
        self.env["STUB_BG_RC"] = "3"
        self.assertEqual(self.run_tool(ID).returncode, 3)
        self.assertEqual(self.marks(), ["take %s" % ID, "open %s" % ID])


if __name__ == "__main__":
    unittest.main()
