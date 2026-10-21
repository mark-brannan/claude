#!/usr/bin/env python3
# Tests for shift-report. Run: python3 bin/shift-report.test.py
# Offline: a stub gh (the GH env var), a synthetic state dir and metrics.db.
# Checks: merged / halted / parked classification, spend by issue from the
# closing PRs, the window on merge time, and the state-repo file name.
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
P = str(Path(__file__).resolve().parent / "shift-report")
spec = importlib.util.spec_from_loader("sr", importlib.machinery.SourceFileLoader("sr", P))
sr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sr)


def issue(n, title, labels, pr):
    return {"number": n, "title": title, "state": "OPEN", "labels": [{"name": x} for x in labels],
            "closedByPullRequestsReferences": [{"number": pr}]}


ISSUES = {1: issue(1, "done", [], 11), 2: issue(2, "stuck", ["needs-human"], 12), 3: issue(3, "waiting", [], 13)}
PRS = {11: {"number": 11, "state": "MERGED", "mergedAt": "2026-10-20T10:00:00Z"},
       12: {"number": 12, "state": "OPEN", "mergedAt": None},
       13: {"number": 13, "state": "OPEN", "mergedAt": None}}
STUB = ("#!/usr/bin/env python3\nimport sys, json\nI = %r\nP = %r\na = sys.argv[1:]\n"
        "print(json.dumps(I[int(a[2])] if a[:2] == ['issue', 'view'] else P[int(a[2])]))\n")


class ShiftReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        sd = self.sd = self.tmp.name
        stub = Path(sd, "gh")
        stub.write_text(STUB % (ISSUES, PRS))
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.addCleanup(os.environ.pop, "GH", None)
        os.environ["GH"] = str(stub)
        sess = Path(sd, "metrics", "sessions")
        sess.mkdir(parents=True)
        for sid, br, cost in (("s1", "claude/a", 5.0), ("s2", "claude/b", 3.0)):
            (sess / f"{sid}.json").write_text(json.dumps({
                "session_id": sid, "ended_at": "2026-10-20T09:00:00Z", "branch": br,
                "cwd": "/home/u/w", "cost_usd": cost, "commits": 1}))
        dash = Path(sd, "metrics", "dashboard")
        dash.mkdir(parents=True)
        cx = sqlite3.connect(dash / "metrics.db")
        cx.executescript(sr.load_spend().load_metrics_db().SCHEMA)
        for n, br, st, m in ((11, "claude/a", "MERGED", "2026-10-20T10:00:00Z"), (12, "claude/b", "OPEN", None)):
            cx.execute("insert into gh_items(repo, kind, number, created_at, state, merged_at, head_ref) "
                       "values (?,?,?,?,?,?,?)", ("o/r", "pr", n, "2026-10-20T08:00:00Z", st, m, br))
        cx.commit()
        cx.close()

    def run_main(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = sr.main(["--repo", "o/r", "--issues", "1,2,3", "--since", "2026-10-20",
                          "--state-dir", self.sd, *extra])
        return rc, out.getvalue()

    def test_sections_and_spend(self):
        rc, out = self.run_main("--no-write")
        self.assertEqual(rc, 0)
        sec = {s.split("\n")[0]: s for s in out.split("## ")[1:]}
        self.assertIn("#1 done", sec["Merged (1)"])
        self.assertIn("#2 stuck", sec["Halted (1)"])
        self.assertIn("#3 waiting", sec["Parked (1)"])
        self.assertIn("| #1 done | $5.00 |", out)
        self.assertIn("| #2 stuck | $3.00 |", out)
        self.assertIn("| total | $8.00 |", out)
        self.assertIn("no spend recorded: #13.", out)

    def test_bad_issues_and_pipe_title(self):
        rc, _ = self.run_main("--no-write", "--issues", "1,x")
        self.assertEqual(rc, 2)
        self.assertEqual(sr.cell("a|b"), "a\\|b")

    def test_window_excludes_merge(self):
        _, out = self.run_main("--no-write", "--until", "2026-10-20")
        self.assertIn("## Merged (0)", out)

    def test_writes_state_file(self):
        self.run_main()
        files = list(Path(self.sd, "log").glob("*-r-issues-1-2-3-shift.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("## Merged (1)", files[0].read_text())

    def test_two_shifts_same_day_keep_both_files(self):
        self.run_main()
        self.run_main("--issues", "1")
        self.assertEqual(len(list(Path(self.sd, "log").glob("*-shift.md"))), 2)


if __name__ == "__main__":
    unittest.main()
