#!/usr/bin/env python3
# Tests for prt. Run: python3 bin/prt.test.py
#
# What matters: a dry run writes nothing and posts nothing; a PR another
# session or a human holds is handed off; a governing path goes to the desk;
# the cap holds; a real run finds or creates the PR's work item and logs the
# estimate on it, once per run, never a second item; a Decide line becomes one
# Needs-ruling card; spend is priced from the agent's transcript; the queue
# line is only printed unless --merge, and --merge refuses a desk PR.
# `gh` is a stub serving fixtures; every call it gets is logged.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PRT = Path(__file__).resolve().parent / "prt"
SID = "abcdef12-0000-0000-0000-000000000000"
REPO = "o/r"

STUB = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
S = os.environ["PRT_STUB"]
a = sys.argv[1:]
open(S + "/calls", "a").write(" ".join(a) + "\n")
def jq(data, prog):
    print(subprocess.run(["jq", "-r", prog], input=data, capture_output=True, text=True).stdout, end="")
prog = a[a.index("--jq") + 1] if "--jq" in a else None
if a[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": os.environ.get("STUB_REPO", "x/y")}))
elif a[:2] == ["api", "graphql"]:
    print(open(S + "/graphql.json").read())
elif a[0] == "api" and "/compare/" in a[1]:
    print("0")
elif a[0] == "api" and a[1].endswith("/comments"):
    n = a[1].split("/")[-2]
    p = S + "/comments-" + n + ".json"
    jq(open(p).read() if os.path.exists(p) else "[]", prog)
elif a[:2] == ["pr", "comment"]:
    pass
else:
    sys.exit(1)
'''


def node(n, paths=("bin/x",), labels=(), threads=(), body="", mergeable="MERGEABLE", ci="SUCCESS",
         lines=10):
    """Build a GraphQL pull-request fixture with configurable triage signals."""
    return {"number": n, "title": f"pr {n}", "url": f"https://github.com/{REPO}/pull/{n}",
            "body": body, "isDraft": False, "isCrossRepository": False, "mergeable": mergeable,
            "baseRefName": "main", "headRefName": f"b{n}", "headRefOid": f"{n:040d}",
            "additions": lines, "deletions": 0, "author": {"login": "me", "__typename": "User"},
            "files": {"totalCount": len(paths), "nodes": [{"path": p} for p in paths]},
            "labels": {"nodes": [{"name": l} for l in labels]},
            "reviewThreads": {"totalCount": len(threads), "nodes": [
                {"isResolved": False, "comments": {"nodes": [
                    {"url": f"https://github.com/{REPO}/pull/{n}#t", "author": a}]}} for a in threads]},
            "latestOpinionatedReviews": {"nodes": []},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci}}}]}}


BOT = {"login": "coderabbitai", "__typename": "Bot"}
HUMAN = {"login": "me", "__typename": "User"}
PRS = [
    node(1, lines=5),
    node(2, paths=("hooks/a.sh",), lines=20),
    node(3, labels=("blocked",)),
    node(4, threads=(HUMAN,)),
    node(5),
    node(6, threads=(BOT,), lines=30, body="## Pencil:\n- **risk** · a default\n\nmore"),
]


class PrtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Create an isolated work-item store and a gh stub serving PR fixtures."""
        cls.tmp = tempfile.TemporaryDirectory()
        T = cls.T = Path(cls.tmp.name)
        for d in ("bin", "home", "items", "stub", "tmp"):
            (T / d).mkdir()
        (T / "bin" / "gh").write_text(STUB)
        (T / "bin" / "gh").chmod(0o755)
        (T / "stub" / "graphql.json").write_text(json.dumps({"data": {"repository": {"pullRequests": {
            "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": PRS}}}}))
        stamp = f"<!-- claim-stamp sid=99999999 epoch={int(time.time())} machine=host-1 -->"
        (T / "stub" / "comments-5.json").write_text(json.dumps([{"id": 1, "body": stamp}]))
        env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        cls.env = {**env, "PATH": f"{T / 'bin'}:{os.environ['PATH']}", "HOME": str(T / "home"),
                   "PRT_STUB": str(T / "stub"), "WORK_ITEM_DIR": str(T / "items"),
                   "CLAUDE_CODE_SESSION_ID": SID, "CLAUDE_STATE_REPO": str(T / "nostate"),
                   "TMPDIR": str(T / "tmp")}

    @classmethod
    def tearDownClass(cls):
        """Remove the temporary fixtures and work items shared by the suite."""
        cls.tmp.cleanup()

    def prt(self, *args, stdin=None, code=0):
        """Run prt in the test environment, check its exit code, and return stdout."""
        p = subprocess.run([sys.executable, str(PRT), *args], env=self.env, input=stdin,
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p.stdout

    def plan(self, *args):
        """Return the fixture repository's JSON plan indexed by PR number."""
        return {f["number"]: f for f in json.loads(self.prt("--repo", REPO, "--json", *args))["prs"]}

    def writes(self):
        """Return logged gh calls that post comments or use an explicit HTTP method."""
        calls = (self.T / "stub" / "calls").read_text() if (self.T / "stub" / "calls").exists() else ""
        return [c for c in calls.splitlines() if c.startswith("pr comment") or " -X " in f" {c} "]

    def test_1_dry_run_plans_and_writes_nothing(self):
        """Check triage routing and that a dry run creates no items or GitHub writes."""
        p = self.plan("--dry-run")
        self.assertEqual(p[3]["handoff"], "labelled blocked")
        self.assertIn("non-bot", p[4]["handoff"])
        self.assertIn("claimed by 99999999", p[5]["handoff"])
        self.assertEqual(p[2]["desk"], ["hooks/"])
        self.assertEqual(p[1]["handoff"], "")
        self.assertIn("answer bot threads", p[6]["actions"])
        self.assertEqual(p[6]["pencils"], 1)
        self.assertEqual(list((self.T / "items").iterdir()), [])
        self.assertEqual(self.writes(), [])

    def test_2_cap_holds_smallest_first(self):
        """Verify the cap keeps the smallest eligible PR and defers larger ones."""
        p = self.plan("--dry-run", "--cap", "1")
        self.assertEqual([n for n, f in p.items() if not f["handoff"]], [1])
        self.assertIn("over the cap", p[2]["handoff"])

    def test_3_run_creates_one_item_per_pr_and_logs_estimates(self):
        """Verify repeated runs reuse each PR's work item and log each estimate."""
        self.plan()
        self.plan()
        items = sorted((self.T / "items").glob("*.md"))
        homes = [l.split("home=")[1].strip() for f in items for l in f.read_text().splitlines()
                 if "home=" in l]
        self.assertEqual(sorted(homes), [f"{REPO}#{n}" for n in (1, 2, 6)])
        for f in items:
            self.assertEqual(f.read_text().count("prt estimate usd="), 2)
        self.assertEqual(self.writes(), [])

    def test_4_decide_makes_one_ruling_card(self):
        """Check ruling-card fields, deduplication, and rejection of unknown kinds."""
        line = (f"- **direction** · Ship it? default: yes · undo: a revert · risk: none much · "
                f"[thread](https://github.com/{REPO}/pull/6#discussion_r1)\n")
        first = self.prt("decide", f"{REPO}#6", "-", stdin=line).strip()
        again = self.prt("decide", f"{REPO}#6", "-", stdin=line).strip()
        self.assertEqual(again, f"{first} (exists)")
        text = (self.T / "items" / f"{first}.md").read_text()
        self.assertIn("owner=human-ruling", text)
        self.assertIn("status=ready", text)
        self.assertIn(f"until: {REPO}#6 merges", text)
        self.assertIn("judgment: direction", text)
        self.prt("decide", f"{REPO}#6", "-", stdin="- **taste** · x? default: a · undo: b · risk: c",
                 code=1)

    def test_5_queue_prints_unless_merge_and_refuses_the_desk(self):
        """Require --merge to post and reject PRs with Pencil lines or desk paths."""
        out = self.prt("queue", f"{REPO}#1")
        self.assertIn("@mergifyio queue", out)
        self.assertEqual(self.writes(), [])
        self.assertIn("Pencil line(s)", self.prt("queue", f"{REPO}#6"))
        self.prt("queue", f"{REPO}#6", "--merge", code=1)
        self.prt("queue", f"{REPO}#2", "--merge", code=1)
        self.assertEqual(self.writes(), [])
        self.prt("queue", f"{REPO}#1", "--merge")
        self.assertEqual(self.writes(), [f"pr comment 1 --repo {REPO} --body @mergifyio queue"])

    def test_6_spent_logs_the_transcript_price(self):
        """Verify transcript pricing, spend logging, and refusal without a work item."""
        d = self.T / "home" / ".claude" / "projects" / "p" / SID / "subagents"
        d.mkdir(parents=True)
        usage = {"input_tokens": 1000000, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        (d / "agent-a1.jsonl").write_text(json.dumps({"type": "assistant", "message": {
            "id": "m1", "model": "claude-sonnet", "usage": usage}}) + "\n")
        self.assertEqual(self.prt("cost", "a1").split()[0], "$2.0000")
        self.prt("spent", f"{REPO}#1", "a1", "--run", "prt-x")
        text = "".join(f.read_text() for f in (self.T / "items").glob("*.md"))
        self.assertIn("cost tokens=1000000 usd=2.0 by=prt run=prt-x", text)
        self.prt("spent", f"{REPO}#4", "a1", "--run", "prt-x", code=1)

    def test_7_ruling_cards_match_complete_urls(self):
        line = "- **direction** · Ship it? default: yes · undo: a revert · risk: none much"
        created = []
        try:
            longer_pr = self.prt("decide", f"{REPO}#10", "-", stdin=line).strip()
            created.append(longer_pr)
            self.assertNotIn("Needs-ruling", self.prt("queue", f"{REPO}#1"))
            shorter_pr = self.prt("decide", f"{REPO}#1", "-", stdin=line).strip()
            created.append(shorter_pr)
            self.assertNotEqual(shorter_pr, f"{longer_pr} (exists)")
            self.assertEqual(self.prt("decide", f"{REPO}#1", "-", stdin=line).strip(),
                             f"{shorter_pr} (exists)")
            self.prt("queue", f"{REPO}#1", "--merge", code=1)
            (self.T / "items" / f"{shorter_pr}.md").unlink()
            for thread in (10, 1):
                linked = line + f" · [thread](https://github.com/{REPO}/pull/1#discussion_r{thread})"
                card = self.prt("decide", f"{REPO}#1", "-", stdin=linked).strip()
                self.assertNotIn("(exists)", card)
                created.append(card)
                self.assertEqual(self.prt("decide", f"{REPO}#1", "-", stdin=linked).strip(),
                                 f"{card} (exists)")
                self.prt("queue", f"{REPO}#1", "--merge", code=1)
        finally:
            for card in created:
                (self.T / "items" / f"{card}.md").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
