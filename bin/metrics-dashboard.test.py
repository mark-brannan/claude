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
import zoneinfo
from pathlib import Path

sys.dont_write_bytecode = True
BIN = Path(__file__).resolve().parent
DASH = BIN / "metrics-dashboard"
DB = BIN / "metrics-db"
spec = importlib.util.spec_from_loader("metrics_dashboard", importlib.machinery.SourceFileLoader("metrics_dashboard", str(DASH)))
md = importlib.util.module_from_spec(spec)
spec.loader.exec_module(md)

TODAY = dt.datetime.now(dt.timezone.utc).date()


def day(n):
    """ISO timestamp n days ago, at noon UTC."""
    return (TODAY - dt.timedelta(days=n)).isoformat() + "T12:00:00Z"


def session(sid, ago, **kw):
    return {"session_id": sid, "started_at": day(ago), "ended_at": day(ago), "repo": "acme/widgets",
            "branch": "claude/fixture", "human_seconds": 1800, "agent_seconds": 7200, "tool_calls": 10,
            "commits": 1, "user_turns": 3, "friction": {"total": 2, "correction": 2},
            "decisions": {"total": 1, "gate": 1}, "assistant_turns": 10, "elapsed_seconds": 600,
            "cache_read_tokens": 90000, "cache_creation_tokens": 10000, "input_tokens": 0, "output_tokens": 500,
            "cost_usd": 2.0, "cost_usd_by_model": {"claude-opus-5-5": 1.5, "claude-sonnet-5-5": 0.5}, **kw}


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
        # CI check rows as metrics-db --github writes them: one file per run, sharded; run 7 is a fork's.
        (sd / "metrics" / "headless-runs" / "41").mkdir(parents=True)
        (sd / "metrics" / "headless-runs" / "41" / "ci-41.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            {"ts": day(2), "what": "claude-review", "repo": "acme/widgets", "run": 41, "trusted": True, "model": "claude-opus-5-5", "total_cost_usd": 1.0},
            {"ts": day(2), "what": "claude-maxims", "repo": "acme/widgets", "run": 41, "trusted": True, "model": "claude-sonnet-5-5", "total_cost_usd": 0.5},
            {"ts": day(2), "repo": "acme/widgets", "run": 41, "trusted": True, "model": "claude-opus-5-5", "total_cost_usd": 1.0})))  # no `what`, same run: a second review
        (sd / "metrics" / "headless-runs" / "41" / "ci-77.jsonl").write_text(json.dumps(
            {"ts": day(2), "what": "claude-arete", "repo": "acme/widgets", "run": 77, "trusted": False, "total_cost_usd": 99}) + "\n")
        (sd / "items").mkdir()
        (sd / "items" / "card-one.md").write_text(
            f"# Fixture card\n\n## Log\n{day(5)} abcd1234 status=open owner=human-ruling\n")
        # Re-owned: the agent's until day 3, then the user's, with a status-only line in between.
        (sd / "items" / "card-two.md").write_text(
            f"# Re-owned card\n\n## Log\n{day(5)} abcd1234 status=open owner=agent\n"
            f"{day(4)} abcd1234 status=claimed\n{day(3)} abcd1234 status=open owner=human-ruling\n")
        projects = root / "projects" / "-fixture"
        projects.mkdir(parents=True)
        # typed-a was resumed: a second transcript carries the same session id.
        # headless-c has a transcript with nothing typed in it: known to be headless.
        for name, sid, ago, text in (("typed-a", "typed-a", 1, "one two three"), ("typed-b", "typed-b", 3, "four five"),
                                     ("typed-a-resumed", "typed-a", 1, "six seven"),
                                     ("headless-c", "headless-c", 2, "<system-reminder>injected</system-reminder>")):
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
        for section in ("open", "sessions", "typing", "agent", "cost"):
            self.assertIn(f'<h2 id="{section}">', self.page)
        self.assertGreaterEqual(self.page.count("<svg "), 15)
        self.assertIn("Sessions per day: headless vs interactive", self.page)
        self.assertIn("Merged PRs per week, by prompts typed on the branch", self.page)
        self.assertIn("API-equivalent $ per week, by model", self.page)
        self.assertIn('<span><i class="s1"></i>opus</span><span><i class="s2"></i>sonnet</span>', self.page)

    def test_ci_checks_section_totals_runs_and_means_per_check(self):
        self.assertIn('<h2 id="ci">', self.page)
        # The two reviews on one run dedupe to one; the fork's $99 is left out.
        self.assertIn("<tr><td>claude-review</td><td class=num>$1.00</td><td class=num>1</td><td class=num>$1.00</td></tr>", self.page)
        self.assertIn("<tr><td>claude-maxims</td><td class=num>$0.500</td><td class=num>1</td><td class=num>$0.500</td></tr>", self.page)
        self.assertNotIn("claude-arete", self.page)
        self.assertIn("CI check $ per week, by check", self.page)

    def test_cost_tiles_price_the_window_and_read_the_session_shape(self):
        self.assertEqual(self.tile("API-equivalent $, 7d"), "6")       # three sessions at $2
        self.assertEqual(self.tile("cold context share, 7d"), "10%")   # 10k written of 100k context
        self.assertEqual(self.tile("context per turn, 7d"), "10k")     # 100k context over 10 turns

    def test_a_sessions_dollars_split_across_the_branches_it_committed_on(self):
        # typed-a committed on one branch only, so acme/widgets#2 carries its whole $2.
        self.assertIn("API-equivalent $ per merged PR, weekly mean", self.page)
        self.assertRegex(self.page, r"\n\$ per merged PR: 2(\.0)?</title>")

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

    def test_a_card_is_counted_under_its_owner_of_the_day_not_its_first_owner(self):
        d = lambda n: (TODAY - dt.timedelta(days=n)).isoformat()
        # Today both cards are the user's; the re-owned one has left the agent's queue.
        self.assertEqual(self.tile("rulings waiting"), "2")
        self.assertIn(f"{d(0)}\nhuman-ruling: 2\nhuman-click: 0", self.page)
        self.assertIn(f"{d(0)}\nagent queue: 0", self.page)
        # While it was the agent's (a claimed line between keeps the owner), it was not the user's.
        self.assertIn(f"{d(4)}\nhuman-ruling: 1\nhuman-click: 0", self.page)
        self.assertIn(f"{d(4)}\nagent queue: 1", self.page)

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


def week_of(ago):
    d = TODAY - dt.timedelta(days=ago)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


class TypedPromptTest(unittest.TestCase):
    """Typed counts come only from the transcripts' typed prompts; a transcript's
    prompts sit in the week of its first prompt, however early the session began."""
    # session id -> days ago it started
    STARTED = {"late": 20, "orphan": 2, "quiet": 3}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        repo = root / "state-repo"
        (repo / ".git").mkdir(parents=True)
        sd = repo / "state" / "global"
        (sd / "metrics" / "sessions").mkdir(parents=True)
        cls.sess = {
            # begun 20 days ago, first prompt 1 day ago (two prompts); user_turns says 0
            "late": session("late", 20, user_turns=0, tool_calls=6, commits=2, friction={"total": 4}),
            # no transcript at all; user_turns says 0, which is no evidence of headless
            "orphan": session("orphan", 2, user_turns=0, tool_calls=10, commits=1, friction={"total": 3}),
            # a transcript with nothing typed in it
            "quiet": session("quiet", 3, user_turns=5, tool_calls=4, commits=0, friction={"total": 1}),
        }
        for sid, rec in cls.sess.items():
            (sd / "metrics" / "sessions" / f"{sid}.json").write_text(json.dumps(rec))
        projects = root / "projects" / "-fixture"
        projects.mkdir(parents=True)

        def user(sid, ago, text):
            return json.dumps({"type": "user", "isSidechain": False, "sessionId": sid, "cwd": "/fixture", "timestamp": day(ago),
                               "message": {"role": "user", "content": text}}, separators=(",", ":")) + "\n"
        (projects / "late.jsonl").write_text(user("late", 1, "first words") + user("late", 1, "second"))
        (projects / "quiet.jsonl").write_text(user("quiet", 3, "<system-reminder>injected</system-reminder>"))
        env = {**os.environ, "CLAUDE_STATE_REPO": str(repo), "HOME": str(root)}
        db, cls.out = root / "out" / "metrics.db", root / "out" / "index.html"
        for cmd in ([DB, "--db", db, "--projects", root / "projects", "--quiet"], [DASH, "--db", db, "--out", cls.out]):
            r = subprocess.run([sys.executable, *map(str, cmd)], env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        cls.page = cls.out.read_text()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tips(self, caption):
        """{x key: {series: value text}} for one chart, from its hover titles."""
        fig = re.search(r"<figure><figcaption>" + re.escape(caption) + r"</figcaption>.*?</figure>", self.page, re.S)
        self.assertIsNotNone(fig, f"no chart {caption!r}")
        out = {}
        for t in re.findall(r"<title>([^<]*)</title>", fig.group(0)):
            key, *rows = t.split("\n")
            out[key] = dict(r.split(": ", 1) for r in rows if ": " in r)
        return out

    def tile(self, label):
        return re.search(r'<div class="tile"><b>([^<]*)</b><span>' + re.escape(label) + r"</span>", self.page).group(1)

    def started_in(self, week, num):
        return sum(num(self.sess[sid]) for sid, ago in self.STARTED.items() if week_of(ago) == week)

    def test_a_session_with_no_transcript_is_unknown_not_headless(self):
        # orphan and quiet are in the window; only quiet is known to be headless.
        self.assertEqual(self.tile("sessions, 7d"), "2")
        self.assertEqual(self.tile("of them headless, 7d"), "1")

    def test_a_session_with_no_transcript_is_in_no_prompt_bucket(self):
        buckets = self.tips("Sessions per week, by prompts typed")
        total = lambda name: sum(int(v[name]) for v in buckets.values())
        self.assertEqual(total("0 (headless)"), 1)  # quiet
        self.assertEqual(total("2–5"), 1)           # late, two prompts
        self.assertEqual(total("1") + total("6+"), 0)

    def test_the_daily_mix_leaves_an_unknown_session_out_of_both_sides(self):
        day_of_orphan = (TODAY - dt.timedelta(days=2)).isoformat()
        mix = self.tips("Sessions per day: headless vs interactive")[day_of_orphan]
        self.assertEqual((mix["headless (nothing typed)"], mix["interactive"]), ("0", "0"))

    def test_weekly_per_prompt_charts_use_the_week_of_the_first_prompt(self):
        # late began in an earlier week than its two prompts: that week has no prompts, so no point;
        # the prompts' week divides the events of the sessions started in it by 2.
        w_start, w_typed = week_of(20), week_of(1)
        self.assertNotEqual(w_start, w_typed)
        cases = (("Friction per 100 prompts, weekly", "friction/100", lambda r: 100.0 * r["friction"]["total"]),
                 ("Tool calls per prompt, weekly", "tool calls/prompt", lambda r: r["tool_calls"]),
                 ("Commits per prompt, weekly", "commits/prompt", lambda r: r["commits"]))
        for caption, name, num in cases:
            tip = self.tips(caption)
            self.assertEqual(tip[w_start][name], "–", caption)
            digits = 2 if name.startswith("commits") else 1
            self.assertEqual(tip[w_typed][name], md.fmt(round(self.started_in(w_typed, num) / 2, digits)), caption)


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


class WindowsAndBucketsTest(unittest.TestCase):
    """The spec's windows (daily: UTC, weekly: the whole record) and the session length buckets."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        l = importlib.machinery.SourceFileLoader("metrics_db_schema", str(DB))
        schema = importlib.util.module_from_spec(importlib.util.spec_from_loader("metrics_db_schema", l))
        l.exec_module(schema)
        cls.schema = schema.SCHEMA

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def render(self, name, setup, env=None):
        db = os.path.join(self.tmp.name, name + ".db")
        cx = sqlite3.connect(db)
        cx.executescript(self.schema)
        setup(cx)
        cx.commit()
        cx.close()
        out = os.path.join(self.tmp.name, name + ".html")
        r = subprocess.run([sys.executable, str(DASH), "--db", db, "--out", out],
                           env=env or os.environ, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return Path(out).read_text()

    @staticmethod
    def monday(n):
        d = TODAY - dt.timedelta(days=n)
        return (d - dt.timedelta(days=d.weekday())).isoformat()

    def test_daily_window_ends_on_the_utc_date_whatever_the_host_zone(self):
        # UTC+14 and UTC-11: at every hour of the day one of them is on another date than UTC.
        for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
            try:
                zoneinfo.ZoneInfo(tz)
            except zoneinfo.ZoneInfoNotFoundError:
                self.skipTest(f"no tzdata for {tz}")  # an unknown TZ is read as UTC, which would prove nothing
            before = dt.datetime.now(dt.timezone.utc).date().isoformat()
            page = self.render("tz", lambda cx: None, {**os.environ, "TZ": tz})
            after = dt.datetime.now(dt.timezone.utc).date().isoformat()
            last = re.findall(r"<title>(\d{4}-\d{2}-\d{2})\nopen PRs: ", page)[-1]
            self.assertIn(last, {before, after}, tz)

    def test_weekly_charts_reach_back_to_the_earliest_typing_or_merged_pr(self):
        def setup(cx):
            cx.execute("insert into sessions(session_id, started_at, elapsed_seconds) values ('s', ?, 600)", (day(1),))
            cx.execute("insert into typing(path, session_id, first_ts, prompts, chars, words) values ('p', 'old', ?, 2, 20, 4)", (day(120),))
            cx.execute("insert into gh_items values ('acme/w', 1, 'pr', ?, ?, ?, 'MERGED', 0, 'claude/x', 'u', 't')", (day(101), day(100), day(100)))
        page = self.render("weekly", setup)
        self.assertIn(f"<title>{self.monday(120)}\nwords/prompt: 2", page)
        self.assertRegex(page, rf"<title>{self.monday(100)}\nclaude/\* branch: 1\n")

    def test_session_length_buckets_leave_no_gap(self):
        def setup(cx):
            for i, secs in enumerate((299.9, 300, 3599.5, 3600, 3600.5)):
                cx.execute("insert into sessions(session_id, started_at, elapsed_seconds) values (?, ?, ?)", (f"s{i}", day(1), secs))
        page = self.render("buckets", setup)
        self.assertRegex(page, r"under 5 min: 1\n5 min to 1 h: 3\nover 1 h: 1\ntotal: 5")


class InputHelpersTest(unittest.TestCase):
    def test_parallel_sessions_share_minutes_per_host(self):
        rows = [{"host": "boxa", "started_at": "2026-10-20T18:43:10Z", "ended_at": "2026-10-20T18:45:00Z"},
                {"host": "boxa", "started_at": "2026-10-20T18:44:00Z", "ended_at": "2026-10-20T18:44:30Z"},
                {"host": "boxb", "started_at": "2026-10-20T18:43:00Z", "ended_at": None}]
        m = md.session_minutes(rows)
        self.assertEqual(sorted(m["boxa"]), [29875363, 29875364, 29875365])
        self.assertNotIn("boxb", m)


if __name__ == "__main__":
    unittest.main()
