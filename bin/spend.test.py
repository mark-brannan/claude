#!/usr/bin/env python3
# Tests for spend. Run: python3 bin/spend.test.py
#
# Offline and synthetic: a throwaway state dir with sessions in both layouts
# (flat and sharded), a commits.jsonl and a metrics.db holding a made-up PR
# table. No network, no real repo names.
#
# What matters: a session's cost lands on the PR its branch became; a session
# on two PRs splits its cost; a reused branch name picks the PR that existed
# when the session ended; the window and the timezone decide the day and hour;
# the roll-ups all add up to the same total.
import importlib.machinery
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "spend"
spec = importlib.util.spec_from_loader("spend", importlib.machinery.SourceFileLoader("spend", str(ENGINE)))
spend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spend)


def session(sid, ended, cost, branch, cwd="/home/u/widgets/.claude/worktrees/w", commits=1, out=1000, cache=2000):
    return {"session_id": sid, "ts": ended, "ended_at": ended, "repo": "w", "branch": branch, "cwd": cwd,
            "cost_usd": cost, "output_tokens": out, "cache_read_tokens": cache, "cache_creation_tokens": 0,
            "commits": commits}


class SpendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sd = self.tmp.name
        sess = Path(self.sd, "metrics", "sessions")
        (sess / "ab").mkdir(parents=True)
        rows = [
            # lands in widgets#7 (merged)
            ("flat", session("s1", "2026-10-15T01:30:00Z", 4.0, "claude/feat-a")),
            # two branches, two PRs: cost splits 50/50
            ("shard", session("s2", "2026-10-15T08:10:00Z", 6.0, "claude/feat-b")),
            # branch name reused: the PR opened after the session ended is not its PR
            ("flat", session("s3", "2026-10-10T08:10:00Z", 2.0, "claude/reused")),
            # no commits, on main: no PR
            ("flat", session("s4", "2026-10-16T20:00:00Z", 1.0, "main", cwd="/home/u/widgets", commits=0)),
            # outside the window
            ("flat", session("s5", "2026-10-01T00:00:00Z", 99.0, "claude/feat-a")),
        ]
        for kind, s in rows:
            d = sess if kind == "flat" else sess / "ab"
            (d / f"{s['session_id']}.json").write_text(json.dumps(s))
        Path(self.sd, "commits.jsonl").write_text("".join(json.dumps(c) + "\n" for c in [
            {"session_id": "s2", "branch": "claude/feat-b", "commit": "1"},
            {"session_id": "s2", "branch": "claude/feat-c", "commit": "2"},
            {"session_id": "s2", "branch": "HEAD", "commit": "3"},
        ]))
        self.db = os.path.join(self.sd, "m.db")
        cx = sqlite3.connect(self.db)
        cx.executescript("""
          create table gh_items(repo text, number int, kind text, created_at text, closed_at text,
            merged_at text, state text, draft int, head_ref text, author text, title text,
            primary key(repo, number, kind));
          create table gh_repos(repo text primary key, topics text, archived int, private int);""")
        cx.execute("insert into gh_repos values ('acme/widgets','',0,0)")
        for row in [
            ("acme/widgets", 7, "pr", "2026-10-15T01:00:00Z", None, "2026-10-15T02:00:00Z", "MERGED", "claude/feat-a"),
            ("acme/widgets", 8, "pr", "2026-10-15T08:00:00Z", None, "2026-10-15T09:00:00Z", "MERGED", "claude/feat-b"),
            ("acme/gears", 3, "pr", "2026-10-15T08:05:00Z", None, None, "OPEN", "claude/feat-c"),
            ("acme/widgets", 9, "pr", "2026-10-12T00:00:00Z", None, None, "CLOSED", "claude/reused"),
            ("acme/widgets", 10, "pr", "2026-10-09T00:00:00Z", None, None, "CLOSED", "claude/reused"),
            ("acme/widgets", 11, "issue", "2026-10-09T00:00:00Z", None, None, "OPEN", "claude/feat-a"),
        ]:
            cx.execute("insert into gh_items values (?,?,?,?,?,?,?,0,?,'a','t')", row[:7] + row[7:])
        cx.commit()
        cx.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_json(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = spend.main(["--state", self.sd, "--db", self.db, "--tz", "UTC", "--json",
                             "--since", "2026-10-02", *args])
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_cost_lands_on_the_pr_its_branch_became(self):
        pr = self.run_json()["pr"]
        self.assertAlmostEqual(pr["acme/widgets#7"]["cost"], 4.0)

    def test_two_prs_split_a_session_and_head_is_ignored(self):
        pr = self.run_json()["pr"]
        self.assertAlmostEqual(pr["acme/widgets#8"]["cost"], 3.0)
        self.assertAlmostEqual(pr["acme/gears#3"]["cost"], 3.0)
        self.assertEqual(pr["acme/gears#3"]["state"], "OPEN")

    def test_a_reused_branch_name_picks_the_pr_that_existed_then(self):
        pr = self.run_json()["pr"]
        self.assertAlmostEqual(pr["acme/widgets#10"]["cost"], 2.0)
        self.assertNotIn("acme/widgets#9", pr)

    def test_no_pr_is_split_by_whether_there_were_commits(self):
        pr = self.run_json()["pr"]
        self.assertAlmostEqual(pr["(no PR) - no commits"]["cost"], 1.0)

    def test_repo_falls_back_to_the_checkout_in_cwd(self):
        repo = self.run_json()["repo"]
        self.assertAlmostEqual(repo["acme/widgets"]["cost"], 4.0 + 3.0 + 2.0 + 1.0)

    def test_every_rollup_totals_the_same(self):
        out = self.run_json()
        for k in ("pr", "repo", "day", "hour"):
            self.assertAlmostEqual(sum(v["cost"] for v in out[k].values()), 13.0, msg=k)

    def test_window_and_timezone_set_day_and_hour(self):
        out = self.run_json("--until", "2026-10-17")
        self.assertIn("2026-10-15 01:00", out["hour"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            spend.main(["--state", self.sd, "--db", self.db, "--tz", "America/Los_Angeles", "--json",
                        "--since", "2026-10-02", "--by", "day"])
        # 01:30Z on the 15th is the evening of the 14th in Pacific time
        self.assertIn("2026-10-14", json.loads(buf.getvalue())["day"])
        # --since cuts s5 (99.0) in every case
        self.assertNotIn("99", buf.getvalue())

    def test_no_pr_table_is_said_not_guessed(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            spend.main(["--state", self.sd, "--db", os.path.join(self.sd, "none.db"), "--since", "2026-10-02",
                        "--by", "pr"])
        self.assertIn("no PR table", buf.getvalue())

    def test_text_table_prints(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            spend.main(["--state", self.sd, "--db", self.db, "--tz", "UTC", "--since", "2026-10-02"])
        text = buf.getvalue()
        for title in ("spend by PR", "spend by repo", "spend by day", "spend by hour"):
            self.assertIn(title, text)
        self.assertIn("2 merged PRs", text)

    def test_bad_by_is_usage(self):
        with self.assertRaises(SystemExit) as cm:
            spend.main(["--by", "nope"]) if False else sys.exit(spend.main(["--by", "nope"]))
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
