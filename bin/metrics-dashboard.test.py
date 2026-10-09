#!/usr/bin/env python3
# Tests for metrics-dashboard. Run: python3 bin/metrics-dashboard.test.py
#
# A smoke test over a synthetic database: metrics-db builds it from a
# throwaway state repo, the dashboard renders it, and the page must carry the
# four sections, the tiles with the right counts, and nothing that needs a
# network or a script. Dates are relative to today because the tiles are
# windows over the last 14 days. Nothing here is real data.
import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BIN = Path(__file__).resolve().parent
DASH = BIN / "metrics-dashboard"
DB = BIN / "metrics-db"
spec = importlib.util.spec_from_loader("metrics_dashboard", importlib.machinery.SourceFileLoader("metrics_dashboard", str(DASH)))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

TODAY = dt.date.today()


def day(n):
    """ISO timestamp n days ago, at noon UTC."""
    return (TODAY - dt.timedelta(days=n)).isoformat() + "T12:00:00Z"


def session(sid, ago, **kw):
    return {"session_id": sid, "started_at": day(ago), "ended_at": day(ago), "repo": "acme/widgets",
            "branch": "claude/fixture", "human_seconds": 1800, "agent_seconds": 7200, "tool_calls": 10,
            "commits": 1, "user_turns": 3, "friction": {"total": 2, "correction": 2},
            "decisions": {"total": 1, "gate": 1}, **kw}


class DashboardFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        repo = root / "state-repo"
        (repo / ".git").mkdir(parents=True)
        sd = repo / "state" / "global"
        (sd / "metrics" / "sessions").mkdir(parents=True)
        # Three sessions inside the last 7 days (one headless), one in the 7 before.
        for sid, ago, kw in (("typed-a", 1, {}), ("typed-b", 3, {}), ("headless-c", 2, {"user_turns": 0}),
                             ("typed-prior", 9, {}),
                             # outside both windows; no prompt count anywhere, so its typed count is NULL
                             ("unknown-d", 20, {"user_turns": None})):
            (sd / "metrics" / "sessions" / f"{sid}.json").write_text(json.dumps(session(sid, ago, **kw)))
        (sd / "commits.jsonl").write_text("".join(json.dumps(c) + "\n" for c in (
            {"ts": day(1), "session_id": "typed-a", "repo": "acme/widgets", "branch": "claude/fixture",
             "commit": "deadbeef"},
            {"ts": day(20), "session_id": "unknown-d", "repo": "acme/widgets", "branch": "claude/nulls",
             "commit": "cafef00d"})))
        (sd / "items").mkdir()
        (sd / "items" / "card-one.md").write_text(
            f"# Fixture card\n\n## Log\n{day(5)} abcd1234 status=open owner=human-ruling\n")
        projects = root / "projects" / "-fixture"
        projects.mkdir(parents=True)
        # typed-a was resumed: a second transcript carries the same session id.
        for name, sid, ago, text in (("typed-a", "typed-a", 1, "one two three"), ("typed-b", "typed-b", 3, "four five"),
                                     ("typed-a-resumed", "typed-a", 1, "six seven")):
            rec = {"type": "user", "isSidechain": False, "sessionId": sid, "cwd": "/fixture", "timestamp": day(ago),
                   "message": {"role": "user", "content": text}}
            (projects / f"{name}.jsonl").write_text(json.dumps(rec, separators=(",", ":")) + "\n")
        cls.env = {**os.environ, "CLAUDE_STATE_REPO": str(repo), "HOME": str(root)}
        cls.db = root / "out" / "metrics.db"
        cls.out = root / "out" / "index.html"
        r = subprocess.run([sys.executable, str(DB), "--db", str(cls.db), "--projects", str(root / "projects"),
                            "--quiet"], env=cls.env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # GitHub rows go in directly: the repo's topic carries markup, to prove it is escaped.
        cx = sqlite3.connect(cls.db)
        cx.execute("insert into gh_repos values ('acme/widgets', 'project-<b>alpha', 0, 0)")
        cx.execute("insert into gh_repos values ('acme/other', '', 0, 0)")
        # Same branch name in another repo: the session committed in acme/widgets, not here.
        cx.execute("insert into gh_items values ('acme/other', 3, 'pr', ?, ?, ?, 'MERGED', 0, 'claude/fixture', 'someone', 'x')",
                   (day(4), day(2), day(2)))
        cx.execute("insert into gh_items values ('acme/widgets', 4, 'pr', ?, ?, ?, 'MERGED', 0, 'claude/nulls', 'someone', 'x')",
                   (day(4), day(2), day(2)))
        cx.executemany("insert into gh_items values ('acme/widgets', ?, ?, ?, ?, ?, ?, 0, ?, 'someone', 'x')", [
            (1, "issue", day(10), None, None, "OPEN", None),
            (2, "pr", day(4), day(2), day(2), "MERGED", "claude/fixture")])
        cx.execute("insert or replace into meta values ('gh_refreshed_at', '2026-01-01T00:00:00Z')")
        cx.commit()
        cx.close()
        cls.run_result = subprocess.run([sys.executable, str(DASH), "--db", str(cls.db), "--out", str(cls.out)],
                                        env=cls.env, capture_output=True, text=True)
        cls.page = cls.out.read_text() if cls.out.exists() else ""

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tile(self, label):
        m = re.search(r'<div class="tile"><b>([^<]*)</b><span>' + re.escape(label) + r"</span>", self.page)
        self.assertIsNotNone(m, f"no tile {label!r}")
        return m.group(1)


class RenderTest(DashboardFixture):
    def test_exits_zero_and_prints_the_page_path(self):
        self.assertEqual(self.run_result.returncode, 0, self.run_result.stderr)
        self.assertEqual(self.run_result.stdout.strip(), str(self.out))

    def test_page_has_the_four_sections_and_their_charts(self):
        self.assertTrue(self.page.startswith("<!doctype html>"))
        self.assertIn("<title>Metrics</title>", self.page)
        for section in ("open", "sessions", "typing", "agent"):
            self.assertIn(f'<h2 id="{section}">', self.page)
        self.assertGreaterEqual(self.page.count("<svg "), 15)
        self.assertIn("Sessions per day: headless vs interactive", self.page)
        self.assertIn("Merged PRs per week, by prompts typed on the branch", self.page)

    def test_tiles_count_the_last_seven_days_and_headless_sessions_count(self):
        self.assertEqual(self.tile("sessions, 7d"), "3")
        self.assertEqual(self.tile("of them headless, 7d"), "1")
        self.assertEqual(self.tile("prompts typed, 7d"), "3")
        self.assertEqual(self.tile("words typed, 7d"), "7")
        self.assertEqual(self.tile("friction events, 7d"), "6")
        self.assertEqual(self.tile("open issues"), "1")

    def test_a_session_with_two_transcripts_is_counted_once(self):
        # typed-a has two transcript files; the sessions tile (3) is unchanged.
        self.assertEqual(self.tile("sessions, 7d"), "3")

    def test_pr_touch_buckets_match_on_repo_and_keep_unknown_counts_out_of_no_session(self):
        # PR 2 (acme/widgets): typed-a, 2 prompts over two transcripts -> 2-5.
        # PR 3 (acme/other, same branch name): no session committed there.
        # PR 4: a session whose prompt count is unknown -> 0-1, not "no session".
        self.assertRegex(self.page, r"0–1 prompts: 1\n2–5 prompts: 1\n6\+ prompts: 0\nno session: 1\ntotal: 3")

    def test_days_under_the_tile_windows_do_not_crash(self):
        r = subprocess.run([sys.executable, str(DASH), "--db", str(self.db),
                            "--out", str(self.out.with_name("short.html")), "--days", "3"],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('id="open"', self.out.with_name("short.html").read_text())

    def test_tile_deltas_compare_with_the_prior_seven_days(self):
        # 3 sessions now against 1 in the week before: +200%, and up is the good direction.
        self.assertIn('<small class="good">+200% vs prior</small>', self.page)

    def test_header_shows_both_refresh_times(self):
        self.assertRegex(self.page, r"built \d{4}-\d{2}-\d{2}T[\d:]+Z · GitHub refreshed 2026-01-01T00:00:00Z")

    def test_self_contained_no_scripts_no_network(self):
        self.assertNotIn("<script", self.page)
        self.assertNotRegex(self.page, r"(src|href)=\"https?:")
        self.assertNotIn("@import", self.page)

    def test_both_themes_are_a_stylesheet_not_a_second_render(self):
        self.assertIn("prefers-color-scheme: dark", self.page)
        self.assertIn('[data-theme="dark"]', self.page)

    def test_series_names_from_repo_topics_are_escaped(self):
        self.assertNotIn("<b>alpha", self.page)
        self.assertIn("&lt;b&gt;alpha", self.page)


class CliTest(unittest.TestCase):
    def run_dash(self, *args, env=None):
        return subprocess.run([sys.executable, str(DASH), *args], env=env or os.environ,
                              capture_output=True, text=True)

    def test_missing_db_is_exit_1_and_says_to_run_metrics_db(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.run_dash("--db", os.path.join(d, "none.db"), "--out", os.path.join(d, "o.html"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("run metrics-db first", r.stderr)

    def test_no_state_repo_and_no_paths_is_exit_3(self):
        absolute = ["/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch"]
        if any(os.path.isdir(os.path.join(p, ".git")) for p in absolute):
            self.skipTest("a fallback state repo exists on this machine")
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CLAUDE_STATE_REPO": os.path.join(home, "nope")}
            r = self.run_dash(env=env)
        self.assertEqual(r.returncode, 3)

    def test_an_empty_database_still_renders(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "e.db")
            cx = sqlite3.connect(db)
            cx.executescript(subprocess.run(
                [sys.executable, "-c", "import importlib.machinery as m,importlib.util as u;"
                 f"l=m.SourceFileLoader('x','{DB}');s=u.spec_from_loader('x',l);o=u.module_from_spec(s);"
                 "l.exec_module(o);print(o.SCHEMA)"], capture_output=True, text=True).stdout)
            cx.close()
            out = os.path.join(d, "o.html")
            r = self.run_dash("--db", db, "--out", out, "--days", "14")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('<h2 id="open">', Path(out).read_text())


class HelpersTest(unittest.TestCase):
    def test_fmt(self):
        self.assertEqual(md.fmt(None), "–")
        self.assertEqual(md.fmt(1234), "1,234")
        self.assertEqual(md.fmt(12345), "12.3k")
        self.assertEqual(md.fmt(2.5), "2.5")
        self.assertEqual(md.fmt(3.0), "3")

    def test_ticks_cover_the_max_with_round_steps(self):
        self.assertEqual(md.ticks(0), [0, 1])
        self.assertEqual(md.ticks(7), [0, 2, 4, 6, 8])
        self.assertEqual(md.ticks(45), [0, 10, 20, 30, 40, 50])

    def test_days_and_mondays(self):
        end = dt.date(2026, 10, 8)
        self.assertEqual(md.days(3, end), ["2026-10-06", "2026-10-07", "2026-10-08"])
        self.assertEqual(md.mondays(dt.date(2026, 10, 1), end), ["2026-09-28", "2026-10-05"])

    def test_tile_delta_direction_and_markup_escape(self):
        self.assertIn('class="good"', md.tile("x", 12, 10, good="up"))
        self.assertIn('class="bad"', md.tile("x", 12, 10, good="down"))
        self.assertIn('class="flat"', md.tile("x", 100, 100, good="up"))
        self.assertIn("prior: 0", md.tile("x", 4, 0))
        self.assertNotIn("<i>", md.tile("<i>label</i>", 1))


if __name__ == "__main__":
    unittest.main()
