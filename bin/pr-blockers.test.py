#!/usr/bin/env python3
# Tests for pr-blockers. Run: python3 bin/pr-blockers.test.py
#
# What matters: a clean PR prints nothing and exits 0; an unsigned commit by a
# bot is named with its sha, author, reason and the resign remedy; a conflict,
# a failing check and a pending check each get a line; a BLOCKED PR nothing
# else explains gets the plain "cause not named" line; an UNKNOWN merge state
# is never clean; commit pages beyond the first are read. `gh` is a stub serving fixtures.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "pr-blockers"

STUB = r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
d = os.environ["PRB_STUB"]
if a[:2] == ["pr", "view"]:
    print(open(d + "/view.json").read())
elif a[0] == "api" and a[-1].endswith("/commits"):
    print(open(d + "/commits.json").read())
else:
    sys.exit(1)
'''


def commit(sha, verified=True, login="me", reason="valid"):
    return {"sha": sha * 40, "author": {"login": login},
            "commit": {"author": {"name": login}, "verification": {"verified": verified, "reason": reason}}}


def view(state="CLEAN", mergeable="MERGEABLE", checks=()):
    return {"mergeStateStatus": state, "mergeable": mergeable, "headRefName": "feat",
            "statusCheckRollup": list(checks)}


class Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.T = Path(cls.tmp.name)
        (cls.T / "gh").write_text(STUB)
        (cls.T / "gh").chmod(0o755)
        cls.env = {**os.environ, "PATH": f"{cls.T}:{os.environ['PATH']}", "PRB_STUB": str(cls.T)}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_tool(self, v, commits_text, ref="o/r#5"):
        (self.T / "view.json").write_text(json.dumps(v))
        (self.T / "commits.json").write_text(commits_text)
        p = subprocess.run([sys.executable, str(TOOL), ref], capture_output=True, text=True, env=self.env)
        return p.returncode, p.stdout

    def test_clean_exits_zero_and_prints_nothing(self):
        ok = {"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}
        code, out = self.run_tool(view(checks=[ok]), json.dumps([commit("a")]))
        self.assertEqual((code, out), (0, ""))

    def test_unsigned_bot_commit_is_named_with_the_remedy(self):
        bot = commit("b", verified=False, login="coderabbitai[bot]", reason="unsigned")
        code, out = self.run_tool(view("BLOCKED"), json.dumps([commit("a"), bot]))
        self.assertEqual(code, 1)
        self.assertEqual(len(out.splitlines()), 1)  # explained, so no "cause not named" line
        for want in ("bbbbbbb", "coderabbitai[bot]", "unsigned", "~/.claude/bin/resign-branch.sh feat"):
            self.assertIn(want, out)

    def test_unexplained_blocked_says_so_plainly(self):
        code, out = self.run_tool(view("BLOCKED"), json.dumps([commit("a")]))
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED, cause not named by pr-blockers", out)

    def test_conflict_failing_and_pending_checks(self):
        checks = [{"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"},
                  {"name": "slow", "status": "IN_PROGRESS", "conclusion": ""},
                  {"context": "legacy", "state": "PENDING"}]
        code, out = self.run_tool(view("DIRTY", "CONFLICTING", checks), "[]")
        self.assertEqual(code, 1)
        for want in ("merge conflict", "check failing: lint", "check pending: slow", "check pending: legacy"):
            self.assertIn(want, out)

    def test_behind_and_paginated_commits(self):
        pages = json.dumps([commit("a")]) + json.dumps([commit("c", verified=False, reason="gpgverify_unavailable")])
        code, out = self.run_tool(view("BEHIND"), pages, ref="https://github.com/o/r/pull/5")
        self.assertEqual(code, 1)
        self.assertIn("behind its base", out)
        self.assertIn("ccccccc", out)

    def test_unknown_mergeability_is_not_clean(self):
        code, out = self.run_tool(view("UNKNOWN", "UNKNOWN"), json.dumps([commit("a")]))
        self.assertEqual(code, 1)
        self.assertIn("not yet computed", out)

    def test_bad_ref_exits_two(self):
        self.assertEqual(self.run_tool(view(), "[]", ref="nonsense")[0], 2)


if __name__ == "__main__":
    unittest.main()
