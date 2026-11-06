#!/usr/bin/env python3
# Tests for review-subset. Run: python3 bin/review-subset.test.py
#
# The filter runs on synthetic pull requests shaped like GitHub's GraphQL
# reply; the whole tool runs once as a subprocess against a fake `gh` on PATH
# that answers per repo, so no network is touched.
#
# What matters: each of the three parts is found, and nothing else is; a
# resolved thread never shows; the round count skips the checks' briefs; a
# fixer reply must be signed and not the opener's; a repo that cannot be read
# exits 2 while the rows that were read still print.
#
# Cost per push: well under a second.
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "review-subset"
_loader = importlib.machinery.SourceFileLoader("review_subset", str(TOOL))
_spec = importlib.util.spec_from_loader("review_subset", _loader)
rs = importlib.util.module_from_spec(_spec)
_loader.exec_module(rs)

BOT = "\U0001f916"


def comment(who, body, url="https://x/c"):
    return {"author": {"login": who}, "body": body, "url": url}


def thread(*comments, resolved=False, path="bin/x", line=12):
    return {"isResolved": resolved, "path": path, "line": line, "comments": {"nodes": list(comments)}}


def pr(number, threads=(), reviews=0, labels=(), briefs=0, title="t"):
    convo = [comment("claude", "**Claude finished**") for _ in range(reviews)]
    convo += [comment("claude", "<!-- claude-review-check:arete-check -->") for _ in range(briefs)]
    convo.append(comment("coderabbitai", "summary"))
    return {"number": number, "title": title, "url": "https://x/pull/%d" % number,
            "labels": {"nodes": [{"name": n} for n in labels]},
            "comments": {"nodes": convo}, "reviewThreads": {"nodes": list(threads)}}


JUDGE = comment("claude", BOT + " [should] [judgment] Is the cap three?\nmore", "https://x/j")
NIT = comment("claude", BOT + " [nit] rename it", "https://x/n")
FIX = comment("github-actions", BOT + " Not taken by the fixer: risky path.")
AGENT_FIX = comment("mark-brannan-agent", BOT + " Fixed in abc.")
USER = comment("mark-brannan", "I disagree")


class ClassifyTest(unittest.TestCase):
    def parts(self, prs, cap=3):
        return [(r["part"], r["pr"]) for r in rs.classify("r", prs, cap)]

    def test_judgment_thread_open_at_any_round(self):
        self.assertEqual(self.parts([pr(1, [thread(JUDGE)], reviews=1)]), [("judgment", "r#1")])

    def test_resolved_judgment_is_gone(self):
        self.assertEqual(self.parts([pr(1, [thread(JUDGE, resolved=True)])]), [])

    def test_apart_needs_the_cap(self):
        prs = [pr(1, [thread(NIT, FIX)], reviews=2), pr(2, [thread(NIT, AGENT_FIX)], reviews=3)]
        self.assertEqual(self.parts(prs), [("apart", "r#2")])

    def test_briefs_are_not_rounds(self):
        self.assertEqual(rs.rounds(pr(1, reviews=2, briefs=4)), 2)
        self.assertEqual(self.parts([pr(1, [thread(NIT, FIX)], reviews=2, briefs=4)]), [])

    def test_apart_needs_a_signed_reply_from_another(self):
        own = comment("claude", BOT + " still wrong")
        prs = [pr(1, [thread(NIT)], reviews=5), pr(2, [thread(NIT, USER)], reviews=5),
               pr(3, [thread(NIT, own)], reviews=5)]
        self.assertEqual(self.parts(prs), [])

    def test_judgment_past_the_cap_listed_once(self):
        self.assertEqual(self.parts([pr(1, [thread(JUDGE, FIX)], reviews=4)]), [("judgment", "r#1")])

    def test_blocked_label(self):
        self.assertEqual(self.parts([pr(1, labels=["merge"]), pr(2, labels=["blocked"])]), [("blocked", "r#2")])

    def test_row_shape(self):
        row = rs.classify("r", [pr(7, [thread(JUDGE)], reviews=2)])[0]
        self.assertEqual(row, {"part": "judgment", "pr": "r#7", "rounds": 2, "where": "bin/x:12",
                               "what": "[should] [judgment] Is the cap three?", "url": "https://x/j"})

    def test_cap_is_a_knob(self):
        self.assertEqual(self.parts([pr(1, [thread(NIT, FIX)], reviews=1)], cap=1), [("apart", "r#1")])


FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
name = [a for a in sys.argv if a.startswith("name=")][0][5:]
replies = json.load(open(os.environ["FAKE_GH_REPLIES"]))
if name not in replies:
    sys.stderr.write("HTTP 404: Could not resolve to a Repository\n"); sys.exit(1)
print(json.dumps({"data": {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": False},
                                                          "nodes": replies[name]}}}}))
'''


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "bin").mkdir()
        gh = d / "bin" / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        replies = {"alpha": [pr(3, [thread(JUDGE)], reviews=1)],
                   "beta": [pr(9, labels=["blocked"], title="parked one")],
                   "quiet": [pr(1, [thread(NIT)], reviews=1)]}
        (d / "replies.json").write_text(json.dumps(replies))
        (d / "repos.txt").write_text("# vended\nalpha\nbeta\n\n")
        self.d = d
        self.env = dict(os.environ, PATH="%s:%s" % (d / "bin", os.environ["PATH"]),
                        FAKE_GH_REPLIES=str(d / "replies.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=self.env)

    def test_table_from_the_list(self):
        p = self.run_tool("--list", str(self.d / "repos.txt"))
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = p.stdout.splitlines()
        self.assertTrue(lines[1].startswith("judgment  alpha#3"), lines[1])
        self.assertTrue(lines[2].startswith("blocked   beta#9"), lines[2])
        self.assertIn("parked one", lines[2])
        self.assertTrue(lines[2].endswith("https://x/pull/9"))

    def test_quiet_repo_has_no_rows(self):
        p = self.run_tool("--repo", "quiet", "--json")
        self.assertEqual((p.returncode, json.loads(p.stdout)), (0, []))

    def test_unreadable_repo_exits_2_and_keeps_rows(self):
        p = self.run_tool("--repo", "alpha", "--repo", "gone", "--json")
        self.assertEqual(p.returncode, 2)
        self.assertEqual([r["pr"] for r in json.loads(p.stdout)], ["alpha#3"])
        self.assertIn("mark-brannan/gone not read", p.stderr)

    def test_missing_list_exits_2(self):
        p = self.run_tool("--list", str(self.d / "absent.txt"))
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
