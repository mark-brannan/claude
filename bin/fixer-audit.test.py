#!/usr/bin/env python3
# Tests for fixer-audit. Run: python3 bin/fixer-audit.test.py
# Offline: the GraphQL read is injected.
import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "fixer-audit"
spec = importlib.util.spec_from_loader("fixer_audit", importlib.machinery.SourceFileLoader("fixer_audit", str(TOOL)))
fa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
SINCE = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
SIGN = "🤖 claude-fixer · claude-haiku-5-5 · low · run 99"


def commit(oid, when, body="- https://github.com/o/r/pull/1#discussion_r1\n\nClaude-Fixer-Run: 99"):
    return {"commit": {"oid": oid, "committedDate": when, "messageHeadline": "fix: apply 1 easy review finding(s)",
                       "messageBody": body, "url": "https://github.com/o/r/commit/" + oid}}


def comment(url, body, when="2026-11-05T10:00:00Z"):
    return {"url": url, "body": body, "createdAt": when, "author": {"login": "x"}}


def pr(n, updated, commits=(), threads=()):
    return {"number": n, "title": "t", "url": "u", "updatedAt": updated,
            "commits": {"nodes": list(commits)},
            "reviewThreads": {"nodes": [{"isResolved": r, "comments": {"nodes": list(cs)}} for r, cs in threads]}}


def page(prs, more=False):
    return {"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": more, "endCursor": "c"}, "nodes": prs}}}}


class PureTest(unittest.TestCase):
    def test_trailer_marks_a_fixer_commit(self):
        self.assertTrue(fa.is_fixer_commit("fix: x\n\n- u\n\nClaude-Fixer-Run: 12\nCo-Authored-By: a"))
        self.assertFalse(fa.is_fixer_commit("fix: x\n\nmentions Claude-Fixer-Run: in prose"))
        self.assertFalse(fa.is_fixer_commit(""))

    def test_rejection_needs_signature_and_word(self):
        self.assertTrue(fa.is_rejection("Rejected: the finding is moot.\n\n" + SIGN))
        self.assertFalse(fa.is_rejection("Fixed (suggestion applied)\n\n" + SIGN))
        self.assertFalse(fa.is_rejection("I rejected this."))
        self.assertFalse(fa.is_rejection("Unrejected\n" + SIGN))

    def test_reason_drops_signature_and_cuts(self):
        self.assertEqual(fa.reason("Rejected: moot.\n\n" + SIGN), "Rejected: moot.")
        self.assertTrue(fa.reason("Rejected " + "x" * 400).endswith("…"))


class CollectTest(unittest.TestCase):
    def test_rows_inside_window_only(self):
        p = pr(1, "2026-11-05T00:00:00Z",
               commits=[commit("a" * 7, "2026-11-04T00:00:00Z"), commit("b" * 7, "2026-10-01T00:00:00Z"),
                        {"commit": {"oid": "c", "committedDate": "2026-11-04T00:00:00Z", "messageHeadline": "feat",
                                    "messageBody": "", "url": "cu"}}],
               threads=[(True, [comment("f", "[easy] finding"), comment("r1", "Rejected: moot\n" + SIGN)]),
                        (False, [comment("f2", "Rejected as a word in the finding itself\n" + SIGN)]),
                        (False, [comment("f3", "x"), comment("r2", "Rejected\n" + SIGN, "2026-10-01T00:00:00Z")]),
                        (False, [comment("f4", "x"), comment("r3", "Fixed (suggestion applied)\n" + SIGN)])])
        rows, note = fa.collect("o/r", SINCE, lambda repo, after: page([p]))
        self.assertEqual(note, "")
        self.assertEqual(sorted((r["kind"], r["url"]) for r in rows),
                         [("commit", "https://github.com/o/r/commit/aaaaaaa"), ("rejection", "r1")])
        rej = [r for r in rows if r["kind"] == "rejection"][0]
        self.assertTrue(rej["resolved"])
        self.assertIn("1 thread)", [r for r in rows if r["kind"] == "commit"][0]["detail"])

    def test_stops_at_first_old_pr_and_pages(self):
        calls = []

        def fetch(repo, after):
            calls.append(after)
            if after is None:
                return page([pr(2, "2026-11-05T00:00:00Z", [commit("d" * 7, "2026-11-05T00:00:00Z")])], more=True)
            return page([pr(3, "2026-10-01T00:00:00Z", [commit("e" * 7, "2026-11-05T00:00:00Z")])], more=True)
        rows, note = fa.collect("o/r", SINCE, fetch)
        self.assertEqual(calls, [None, "c"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(note, "")

    def test_page_cap_is_reported(self):
        rows, note = fa.collect("o/r", SINCE, lambda repo, after: page([pr(1, "2026-11-05T00:00:00Z")], more=True))
        self.assertIn("stopped after", note)

    def test_missing_repo_raises(self):
        with self.assertRaises(RuntimeError):
            fa.collect("o/r", SINCE, lambda repo, after: {"data": {"repository": None}, "errors": [{"message": "Not found"}]})


class MainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repos = os.path.join(self.tmp.name, "repos.txt")
        Path(self.repos).write_text("alpha\nbeta\n# comment\n\nother/gamma\n")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, argv, fetch):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fa.main(argv, fetch=fetch, now=NOW)
        return rc, out.getvalue(), err.getvalue()

    def test_read_repos_qualifies_bare_names(self):
        self.assertEqual(fa.read_repos(self.repos), ["mark-brannan/alpha", "mark-brannan/beta", "other/gamma"])

    def test_report_counts_and_failed_repo(self):
        def fetch(repo, after):
            if repo.endswith("beta"):
                raise RuntimeError("HTTP 502")
            if repo.endswith("gamma"):
                return page([])
            return page([pr(7, "2026-11-05T00:00:00Z", [commit("f" * 7, "2026-11-05T00:00:00Z")],
                            [(False, [comment("f", "x"), comment("r", "Rejected | moot\n" + SIGN)])])])
        rc, out, _ = self.run_main(["--repos", self.repos, "--date", "2026-11-06"], fetch)
        self.assertEqual(rc, 1)
        self.assertIn("# Fixer audit, 2026-11-06", out)
        self.assertIn("**1 fixer commit, 1 rejection.**", out)
        self.assertIn("Repos read: 2 of 3", out)
        self.assertIn("mark-brannan/beta: could not be read: HTTP 502", out)
        self.assertIn("| mark-brannan/alpha | 1 | 1 |", out)
        self.assertIn("Rejected \\| moot", out)
        self.assertIn("(thread open)", out)

    def test_empty_week(self):
        rc, out, _ = self.run_main(["--repos", self.repos], lambda repo, after: page([]))
        self.assertEqual(rc, 0)
        self.assertIn("**0 fixer commits, 0 rejections.**", out)
        self.assertIn("No rows.", out)

    def test_write_goes_under_reports(self):
        root = os.path.join(self.tmp.name, "state")
        os.makedirs(os.path.join(root, ".git"))
        os.environ["CLAUDE_STATE_REPO"] = root
        try:
            rc, out, _ = self.run_main(["--repos", self.repos, "--date", "2026-11-06", "--write"],
                                       lambda repo, after: page([]))
        finally:
            del os.environ["CLAUDE_STATE_REPO"]
        want = os.path.join(root, "reports", "fixer-audit-2026-11-06.md")
        self.assertEqual(out.strip(), want)
        self.assertIn("# Fixer audit", Path(want).read_text())

    def test_usage_errors(self):
        for argv in (["--days", "0"], ["--bogus"], ["--date", "nope", "--repos", self.repos],
                     ["--repos", os.path.join(self.tmp.name, "missing")]):
            rc, _, _ = self.run_main(argv, lambda repo, after: page([]))
            self.assertEqual(rc, 2, argv)

    def test_json(self):
        rc, out, _ = self.run_main(["--repos", self.repos, "--json"], lambda repo, after: page([]))
        self.assertEqual(rc, 0)
        self.assertIn('"rows": []', out)


if __name__ == "__main__":
    unittest.main()
