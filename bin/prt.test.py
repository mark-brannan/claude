#!/usr/bin/env python3
# Tests for prt. Run: python3 bin/prt.test.py
#
# What matters: a dry run writes nothing and posts nothing; a PR another
# session, run or human holds is handed off, and so is one whose claim could
# not be read; a governing path goes to the desk, the agents' own pencil log
# does not; the cap holds; a launch claims each worked PR before writing
# anything for it, and a PR it cannot claim gets nothing written; a second
# run finds the first one's PRs claimed; the scope is a repo, a project, or
# the checkout's project by default; a Decide line becomes one Needs-ruling
# card, and pull/1 is not pull/12; spend is priced from the agent's
# transcript and recorded as one critical-review row; the queue line is only printed unless --merge, and --merge
# refuses a desk PR; clean removes only the prt-* worktrees nothing claims.
# `gh` is a stub serving fixtures; every call it gets is logged.
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

PRT = Path(__file__).resolve().parent / "prt"
CS = Path(__file__).resolve().parent.parent / "hooks" / "claim-stamp.sh"
SID = "abcdef12-0000-0000-0000-000000000000"
REPO = "o/r"

STUB = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
S = os.environ["PRT_STUB"]
a = sys.argv[1:]
open(S + "/calls", "a").write(" ".join(a) + "\n")
def arg(flag):
    return a[a.index(flag) + 1] if flag in a else None
def fixture(name, default):
    p = os.path.join(S, name)
    return open(p).read() if os.path.exists(p) else default
def emit(data):
    prog = arg("--jq")
    if prog is None:
        print(data)
    else:
        print(subprocess.run(["jq", "-r", prog], input=data, capture_output=True, text=True).stdout, end="")
if a[:2] == ["repo", "view"]:
    if "repositoryTopics" in a:
        print(json.dumps({"repositoryTopics": [{"name": t} for t in os.environ.get("STUB_TOPICS", "").split()]}))
    else:
        print(json.dumps({"nameWithOwner": os.environ.get("STUB_REPO", "x/y")}))
elif a[:2] == ["repo", "list"]:
    print(fixture("topic-" + arg("--topic") + ".json", "[]") if "--topic" in a else fixture("repos.json", "[]"))
elif a[:2] == ["repo", "clone"]:
    subprocess.run(["git", "init", "-q", a[3]], check=True)
elif a[:2] == ["search", "prs"]:
    print(fixture("search.json", "[]"))
elif a[:2] == ["api", "user"]:
    print("o")
elif a[:2] == ["api", "graphql"]:
    name = next(x[5:] for x in a if x.startswith("name="))
    print(fixture("graphql-" + name + ".json", ""))
elif a[0] == "api" and "/compare/" in a[1]:
    print("0")
elif a[0] == "api" and "-X" in a:
    path = next(x for x in a if x.startswith("repos/"))
    if arg("-X") == "POST" and path.endswith("/comments"):
        sys.stdin.read()
        emit('{"id": 777}')
elif a[0] == "api" and a[1].endswith("/comments"):
    emit(fixture("comments-" + a[1].split("/")[-2] + ".json", "[]"))
elif a[:2] == ["pr", "comment"]:
    pass
elif a[:2] == ["pr", "view"]:
    print(fixture("view-" + a[2] + ".json", '{"mergeStateStatus": "CLEAN", "mergeable": "MERGEABLE", "headRefName": "b", "statusCheckRollup": []}'))
elif a[0] == "api" and a[-1].endswith("/commits"):
    print(fixture("commits-pr-" + a[-1].split("/")[-2] + ".json", "[]"))
else:
    sys.exit(1)
'''


def node(n, paths=("bin/x",), labels=(), threads=(), body="", mergeable="MERGEABLE", ci="SUCCESS",
         lines=10, repo=REPO, auto=None, thread_total=None):
    """Build a GraphQL pull-request fixture with configurable triage signals."""
    return {"number": n, "title": f"pr {n}", "url": f"https://github.com/{repo}/pull/{n}",
            "body": body, "isDraft": False, "isCrossRepository": False, "mergeable": mergeable,
            "autoMergeRequest": auto,
            "baseRefName": "main", "headRefName": f"b{n}", "headRefOid": f"{n:040d}",
            "additions": lines, "deletions": 0, "author": {"login": "me", "__typename": "User"},
            "files": {"totalCount": len(paths), "nodes": [{"path": p} for p in paths]},
            "labels": {"nodes": [{"name": l} for l in labels]},
            "reviewThreads": {"totalCount": len(threads) if thread_total is None else thread_total,
                              "nodes": [{"isResolved": False, "comments": {"nodes": [
                                  {"url": f"https://github.com/{repo}/pull/{n}#t", "author": a}]}}
                                  for a in threads]},
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
    node(7, auto={"enabledBy": {"login": "me"}}),
    node(8, thread_total=101),
    node(9, paths=("docs/agent_decisions.md",), lines=11),
    node(10, paths=("skills/x/decided.md",), lines=12),
]


def page(nodes):
    return json.dumps({"data": {"repository": {"pullRequests": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}})


class PrtTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Create an isolated work-item store and a gh stub serving PR fixtures."""
        cls.tmp = tempfile.TemporaryDirectory()
        T = cls.T = Path(cls.tmp.name)
        for d in ("bin", "home", "items", "stub", "tmp", "cache", "wt"):
            (T / d).mkdir()
        (T / "bin" / "gh").write_text(STUB)
        (T / "bin" / "gh").chmod(0o755)
        (T / "stub" / "graphql-r.json").write_text(page(PRS))
        (T / "stub" / "graphql-s.json").write_text(page([node(1, repo="o/s", lines=3)]))
        (T / "stub" / "topic-project-p.json").write_text(json.dumps([{"name": "r"}, {"name": "s"}]))
        stamp = f"<!-- claim-stamp sid=99999999 epoch={int(time.time())} machine=host-1 -->"
        (T / "stub" / "comments-5.json").write_text(json.dumps([{"id": 1, "body": stamp}]))
        env = {k: v for k, v in os.environ.items()
               if k not in ("CI", "GITHUB_ACTIONS", "CLAUDE_CLAIM_STAMP", "XDG_CACHE_HOME")}
        cls.env = {**env, "PATH": f"{T / 'bin'}:{os.environ['PATH']}", "HOME": str(T / "home"),
                   "PRT_STUB": str(T / "stub"), "WORK_ITEM_DIR": str(T / "items"),
                   "CLAUDE_CODE_SESSION_ID": SID, "CLAUDE_STATE_REPO": str(T / "nostate"),
                   "TMPDIR": str(T / "tmp"), "XDG_CACHE_HOME": str(T / "cache")}

    @classmethod
    def tearDownClass(cls):
        """Remove the temporary fixtures and work items shared by the suite."""
        cls.tmp.cleanup()

    def prt(self, *args, stdin=None, code=0, env=None):
        """Run prt in the test environment, check its exit code, and return stdout."""
        p = subprocess.run([sys.executable, str(PRT), *args], env={**self.env, **(env or {})},
                           input=stdin, capture_output=True, text=True)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p.stdout

    def plan(self, *args, env=None, by_ref=False):
        """Return the JSON plan's PRs, by number or by owner/repo#n."""
        out = json.loads(self.prt(*args, "--json", env=env))
        return {(f["ref"] if by_ref else f["number"]): f for g in out["repos"] for f in g["prs"]}

    def calls(self):
        p = self.T / "stub" / "calls"
        return p.read_text().splitlines() if p.exists() else []

    def writes(self):
        """Return logged gh calls that post, clone, or use an explicit HTTP method."""
        return [c for c in self.calls() if c.startswith(("pr comment", "repo clone"))
                or " -X " in f" {c} "]

    def test_01_dry_run_plans_and_writes_nothing(self):
        p = self.plan("--repo", REPO, "--dry-run")
        self.assertEqual(p[3]["handoff"], "labelled blocked")
        self.assertIn("non-bot", p[4]["handoff"])
        self.assertIn("claimed by 99999999", p[5]["handoff"])
        self.assertEqual(p[7]["handoff"], "auto-merge armed by me")
        self.assertIn("threads unread", p[8]["handoff"])
        self.assertEqual(p[2]["desk"], ["hooks/"])
        self.assertEqual(p[9]["desk"], [])
        self.assertEqual(p[10]["desk"], ["decided.md"])
        self.assertEqual(p[1]["handoff"], "")
        self.assertEqual(p[1]["start_sha"], f"{1:040d}")
        self.assertIsNone(p[1]["sid"])
        self.assertIn("answer bot threads", p[6]["actions"])
        self.assertEqual(p[6]["pencils"], 1)
        self.assertEqual(list((self.T / "items").iterdir()), [])
        self.assertEqual(self.writes(), [])

    def test_02_cap_holds_smallest_first(self):
        p = self.plan("--repo", REPO, "--dry-run", "--cap", "1")
        self.assertEqual([n for n, f in p.items() if not f["handoff"]], [1])
        self.assertIn("over the cap", p[2]["handoff"])

    def test_03_a_claim_read_that_says_nothing_hands_off(self):
        p = self.plan("--repo", REPO, "--dry-run", env={"CLAUDE_CLAIM_STAMP": "off"})
        self.assertEqual(p[1]["handoff"], "unverified: claim-stamp gave no answer")

    def test_04_project_scope_and_the_default(self):
        out = self.prt("--project", "p", "--owner", "o", "--dry-run")
        self.assertIn(" in 2 repos", out.splitlines()[0])
        self.assertIn("  s#1 ", out)
        self.assertIn("  r#1 ", out)
        self.assertLess(out.index("o/r · clone"), out.index("o/s · clone"))
        self.assertIn("(cloned at launch)", out)
        # Which repos, not whose claims: the claim reads are switched off.
        quick = {"STUB_REPO": REPO, "CLAUDE_CLAIM_STAMP": "off"}
        both = self.plan("--dry-run", by_ref=True, env={**quick, "STUB_TOPICS": "project-p"})
        self.assertEqual(sorted({f["repo"] for f in both.values()}), ["o/r", "o/s"])
        alone = self.plan("--dry-run", by_ref=True, env=quick)
        self.assertEqual({f["repo"] for f in alone.values()}, {"o/r"})
        self.assertEqual(self.writes(), [])

    def test_05_launch_claims_first_and_a_second_run_finds_them_claimed(self):
        subprocess.run(["sh", str(CS), "card-claim", f"https://github.com/{REPO}/pull/1", "f" * 32],
                       env=self.env, check=True, capture_output=True)
        before = len(self.writes())
        first = self.plan("--repo", REPO)
        self.assertTrue(first[1]["handoff"].startswith("claimed: "), first[1]["handoff"])
        self.assertIsNone(first[1]["sid"])
        worked = sorted(n for n, f in first.items() if not f["handoff"])
        self.assertEqual(worked, [2, 6, 9, 10])
        for n in worked:
            self.assertRegex(first[n]["sid"], r"^[0-9a-f]{32}$")
            self.assertEqual(first[n]["start_sha"], f"{n:040d}")
            self.assertEqual(first[n]["clone"], str(self.T / "cache" / "prt" / "o" / "r"))
        self.assertEqual(len({first[n]["sid"][:8] for n in worked}), len(worked))
        posted = [c for c in self.writes()[before:] if "/comments" in c]
        self.assertEqual(sorted(int(c.split("issues/")[1].split("/")[0]) for c in posted), worked)
        second = self.plan("--repo", REPO)
        self.assertTrue(all(f["handoff"] for f in second.values()))
        self.assertTrue(second[2]["handoff"].startswith("claimed: "))
        items = sorted((self.T / "items").glob("*.md"))
        homes = [l.split("home=")[1].strip() for f in items for l in f.read_text().splitlines()
                 if "home=" in l]
        self.assertEqual(sorted(homes), sorted(f"{REPO}#{n}" for n in worked))
        for f in items:
            self.assertEqual(f.read_text().count("prt estimate usd="), 1)
        self.prt("release", f"{REPO}#2", first[2]["sid"])
        self.assertEqual(self.plan("--repo", REPO, "--dry-run")[2]["handoff"], "")
        # A store error releases the claim just taken instead of holding it for 2h.
        frozen = [self.T / "items", *(self.T / "items").glob("*.md")]
        for f in frozen:
            f.chmod(0o500 if f.is_dir() else 0o400)
        try:
            third = self.plan("--repo", REPO)
        finally:
            for f in frozen:
                f.chmod(0o700 if f.is_dir() else 0o600)
        self.assertTrue(third[2]["handoff"].startswith("store write failed, claim released"), third[2]["handoff"])
        self.assertIsNone(third[2]["sid"])
        self.assertEqual(self.plan("--repo", REPO, "--dry-run")[2]["handoff"], "")

    def test_06_decide_makes_one_ruling_card(self):
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

    def test_07_decide_tells_pull_1_from_pull_12(self):
        line = "- **risk** · The same question? default: a · undo: b · risk: c\n"
        twelve = self.prt("decide", f"{REPO}#12", "-", stdin=line).strip()
        self.assertNotIn("Needs-ruling", self.prt("queue", f"{REPO}#1"))  # #12's card is not #1's
        one = self.prt("decide", f"{REPO}#1", "-", stdin=line).strip()
        self.assertNotIn("exists", one)
        self.assertNotEqual(one, twelve)
        # The same boundary holds for a thread: discussion_r1 is not _r10.
        for thread in (10, 1):
            linked = line.strip() + f" · [thread](https://github.com/{REPO}/pull/1#discussion_r{thread})"
            card = self.prt("decide", f"{REPO}#1", "-", stdin=linked).strip()
            self.assertNotIn("(exists)", card)
            self.assertEqual(self.prt("decide", f"{REPO}#1", "-", stdin=linked).strip(),
                             f"{card} (exists)")

    def test_08_queue_prints_unless_merge_and_refuses_the_desk(self):
        before = len(self.writes())
        out = self.prt("queue", f"{REPO}#1")
        self.assertIn("@mergifyio queue", out)
        self.assertIn("Pencil line(s)", self.prt("queue", f"{REPO}#6"))
        self.prt("queue", f"{REPO}#6", "--merge", code=1)
        self.prt("queue", f"{REPO}#2", "--merge", code=1)
        self.assertEqual(self.writes()[before:], [])
        self.prt("queue", f"{REPO}#5", "--merge", code=1)
        self.prt("queue", f"{REPO}#1", "--merge", code=1)  # test_07 carded #1
        self.assertEqual(self.writes()[before:], [])
        self.prt("queue", f"{REPO}#9", "--merge")
        self.assertEqual(self.writes()[before:], [f"pr comment 9 --repo {REPO} --body @mergifyio queue"])

    def test_08b_queue_names_what_pr_blockers_finds(self):
        stub = self.T / "stub" / "commits-pr-1.json"
        stub.write_text(json.dumps([{"sha": "d" * 40, "author": {"login": "coderabbitai[bot]"}, "commit": {
            "author": {"name": "x"}, "verification": {"verified": False, "reason": "unsigned"}}}]))
        try:
            out = self.prt("queue", f"{REPO}#1")
            self.assertIn("unsigned commit ddddddd by coderabbitai[bot]", out)
            self.assertIn("resign-branch.sh b", out)
        finally:
            stub.unlink()
        self.assertNotIn("unsigned", self.prt("queue", f"{REPO}#1"))

    def test_08c_queue_refuses_when_pr_blockers_cannot_read_the_pr(self):
        stub = self.T / "stub" / "commits-pr-1.json"
        stub.write_text("not json")  # pr-blockers dies on it; that must not read as "no blockers"
        try:
            self.assertIn("pr-blockers could not read the PR", self.prt("queue", f"{REPO}#1"))
            self.prt("queue", f"{REPO}#1", "--merge", code=1)
        finally:
            stub.unlink()

    def test_09_spent_logs_the_transcript_price(self):
        d = self.T / "home" / ".claude" / "projects" / "p" / SID / "subagents"
        d.mkdir(parents=True)
        usage = {"input_tokens": 1000000, "output_tokens": 0, "cache_read_input_tokens": 0,
                 "cache_creation_input_tokens": 0}
        (d / "agent-a1.jsonl").write_text(json.dumps({"type": "assistant", "effort": "high", "message": {
            "id": "m1", "model": "claude-sonnet", "usage": usage, "content": [
                {"type": "text", "text": "**Fixed**\n- one `abc`\n\n**Look at**\n- None.\n\n"
                                         "**Pencil**\n- **risk** · a\n- **direction** · b\n\n**Decide**\n"}]}})
            + "\n")
        self.assertEqual(self.prt("cost", "a1").split()[0], "$2.0000")
        self.prt("spent", f"{REPO}#2", "a1", "--run", "prt-x")
        self.prt("spent", f"{REPO}#2", "a1", "--run", "prt-x")
        text = "".join(f.read_text() for f in (self.T / "items").glob("*.md"))
        self.assertIn("cost tokens=1000000 usd=2.0 by=prt run=prt-x model=claude-sonnet effort=high", text)
        self.prt("spent", f"{REPO}#4", "a1", "--run", "prt-x", code=1)
        rows = (self.T / "home" / ".claude" / "state" / "global" / "metrics" / "critical-review"
                / SID[:2] / f"{SID}.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1, "a second spent for one agent replaces its row")
        row = json.loads(rows[0])
        self.assertEqual({k: row[k] for k in ("session_id", "review_id", "pr", "pr_guessed", "by", "run",
                                               "model", "effort", "input_tokens", "usd", "turns")},
                         {"session_id": SID, "review_id": "agent-a1", "pr": f"{REPO}#2", "pr_guessed": False,
                          "by": "prt", "run": "prt-x", "model": "claude-sonnet", "effort": "high",
                          "input_tokens": 1000000, "usd": 2.0, "turns": 1})
        self.assertEqual([row[k] for k in ("fixed", "look_at", "pencil", "decide")], [1, 0, 2, 0])
        # The estimate still reads the cost line with model= and effort= on it.
        spec = importlib.util.spec_from_loader("prt", importlib.machinery.SourceFileLoader("prt", str(PRT)))
        prt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prt)
        old = os.environ.get("WORK_ITEM_DIR")
        os.environ["WORK_ITEM_DIR"] = self.env["WORK_ITEM_DIR"]
        try:
            self.assertEqual(prt.measured_mean(), (2.0, 2))
        finally:
            if old is None:
                os.environ.pop("WORK_ITEM_DIR")
            else:
                os.environ["WORK_ITEM_DIR"] = old

    def test_10_clean_removes_only_unclaimed_prt_worktrees(self):
        clone, wt = self.T / "home" / "c", self.T / "wt"

        def git(*a):
            return subprocess.run(["git", "-C", str(clone), "-c", "user.name=t",
                                   "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *a],
                                  env=self.env, check=True, capture_output=True, text=True).stdout
        clone.mkdir()
        git("init", "-q", "-b", "main")
        git("remote", "add", "origin", "git@github.com:o/c.git")
        git("commit", "-q", "--allow-empty", "-m", "x")
        git("update-ref", "refs/remotes/origin/main", "HEAD")
        for name in ("prt-c-1", "prt-c-5", "prt-c-7", "prt-c-8", "other-1"):
            git("worktree", "add", "-q", "--detach", str(wt / name))
        git("-C", str(wt / "prt-c-7"), "commit", "-q", "--allow-empty", "-m", "unpushed")
        (wt / "prt-c-8" / "untracked").write_text("x")
        names = lambda: sorted(Path(l[9:]).name for l in git("worktree", "list", "--porcelain").splitlines()
                               if l.startswith("worktree ") and Path(l[9:]) != clone)
        self.assertIn(f"would remove {wt / 'prt-c-1'}", self.prt("clean", "--repo", "o/c", "--dry-run"))
        self.assertEqual(names(), ["other-1", "prt-c-1", "prt-c-5", "prt-c-7", "prt-c-8"])
        out = self.prt("clean", "--repo", "o/c")
        self.assertIn(f"kept {wt / 'prt-c-7'}: commits no remote branch has", out)
        self.assertIn(f"kept {wt / 'prt-c-8'}: uncommitted files", out)
        self.assertEqual(names(), ["other-1", "prt-c-5", "prt-c-7", "prt-c-8"])

    def test_11_score_bands(self):
        """Conflict and red CI make a PR fix-first, not higher scored; paths weigh by kind."""
        loader = importlib.machinery.SourceFileLoader("prt_mod", str(PRT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("prt_mod", loader))
        loader.exec_module(mod)
        mod.claims = lambda url: []

        def of(repo, **kw):
            pr = node(1, repo=repo, **kw)
            pr.update(commits=pr["commits"], mergeable=kw.get("mergeable", "MERGEABLE"))
            pr["files"]["nodes"] = [{"path": p} for p in kw.get("paths", ("bin/x",))]
            return mod.facts(repo, pr)

        plain = of("o/r")
        self.assertEqual((plain["score"], plain["fix_first"]), (0, False))
        red = of("o/r", ci="FAILURE", mergeable="CONFLICTING")
        self.assertEqual((red["score"], red["fix_first"]), (0, True))
        hard = of("o/r", labels=("fixup-hard",))
        self.assertEqual(hard["score"], 0)
        guards = ("languette/guards/x.py",)
        self.assertEqual(of("o/languette", paths=guards)["score"], 2)
        self.assertEqual(of("o/r", paths=guards)["score"], 0)
        self.assertEqual(of("o/languette", paths=("languette/scan.py",))["score"], 2)
        self.assertEqual(of("o/languette", paths=("tools/scan.py", "run.py"))["score"], 0)
        self.assertEqual(of("o/r", paths=("hooks/a.sh",))["score"], 2)
        self.assertEqual(of("o/r", paths=("docs/adr.md",))["score"], 3)
        self.assertEqual(of("o/r", paths=("docs/agent_decisions.md",))["score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)
