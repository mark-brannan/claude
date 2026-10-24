#!/usr/bin/env python3
# Tests for metrics-db. Run: python3 bin/metrics-db.test.py
#
# Offline and synthetic: a throwaway state repo, a throwaway transcript
# directory and a fake `gh` on PATH. Nothing here is a real prompt, session or
# repo; the repo is public and the real data is not.
#
# What matters: every source lands in its table; a typed prompt is what the
# user typed (a slash command counts, a harness-injected, relayed or headless
# machine prompt does not, a pasted block is counted apart); the transcript
# scan is incremental; a rebuild replaces rather than duplicates.
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "metrics-db"
spec = importlib.util.spec_from_loader("metrics_db", importlib.machinery.SourceFileLoader("metrics_db", str(ENGINE)))
mdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mdb)

FAKE_GH = """#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
if a[:2] == ["repo", "list"]:
    print(json.dumps([
        {"nameWithOwner": "acme/widgets", "isArchived": False, "isPrivate": False,
         "repositoryTopics": [{"name": "project-alpha"}, {"name": "python"}]},
        {"nameWithOwner": "acme/old", "isArchived": True, "isPrivate": True, "repositoryTopics": None}]))
elif a[:2] == ["api", "graphql"]:
    repo = next(x for x in a if x.startswith("name=")).split("=", 1)[1]
    page = {"hasNextPage": False, "endCursor": None}
    issues = {"pageInfo": page, "nodes": [
        {"number": 1, "title": "an issue", "createdAt": "2026-09-01T10:00:00Z", "closedAt": None,
         "state": "OPEN", "author": {"login": "someone"}}]}
    prs = {"pageInfo": page, "nodes": [
        {"number": 2, "title": "a pr", "createdAt": "2026-09-02T10:00:00Z", "closedAt": "2026-09-03T10:00:00Z",
         "mergedAt": "2026-09-03T10:00:00Z", "state": "MERGED", "isDraft": False,
         "headRefName": "claude/fixture", "author": None}]}
    print(json.dumps({"data": {"repository": {"issues": issues, "pullRequests": prs}}}))
else:
    sys.exit(1)
"""


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


def transcript_line(content, ts, session="sess-typed-1", sidechain=False, cwd="/fixture/cwd"):
    """One transcript record. Compact separators on purpose: the scanner's
    cheap pre-filter matches the exact bytes the harness writes."""
    rec = {"type": "user", "isSidechain": sidechain, "sessionId": session, "cwd": cwd, "timestamp": ts,
           "message": {"role": "user", "content": content}}
    return json.dumps(rec, separators=(",", ":"))


class Fixture:
    """A state repo, a projects dir and a bin dir holding a fake gh."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo = root / "state-repo"
        (self.repo / ".git").mkdir(parents=True)
        self.sd = self.repo / "state" / "global"
        self.projects = root / "projects"
        (self.projects / "-fixture-cwd").mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.db = root / "out" / "metrics.db"
        self.home = root / "home"
        self.home.mkdir()
        self.populate()

    def close(self):
        self.tmp.cleanup()

    def populate(self):
        m = self.sd / "metrics"
        (m / "sessions").mkdir(parents=True)
        (m / "sessions" / "sess-typed-1.json").write_text(json.dumps({
            "session_id": "sess-typed-1", "ts": "2026-10-01T12:00:00Z", "started_at": "2026-10-01T10:00:00Z",
            "ended_at": "2026-10-01T12:00:00Z", "repo": "acme/widgets", "branch": "claude/fixture",
            "model": "model-x", "version": "9.9.9", "elapsed_seconds": 7200, "active_seconds": 3600,
            "human_seconds": 600, "agent_seconds": 3000, "idle_seconds": 3600, "user_turns": 4,
            "assistant_turns": 20, "tool_calls": 50, "output_tokens": 1000, "input_tokens": 200,
            "cache_creation_tokens": 30, "cache_read_tokens": 4000, "cost_usd": 1.5, "context_peak": 90000,
            "cost_usd_by_model": {"model-x": 1.2, "model-y": 0.3, "model-z": "n/a"},
            "files_written": 3, "commits": 2, "work_started": True,
            "decisions": {"total": 3, "scoping": 1, "inline": 1, "gate": 1},
            "blocked": {"total": 2, "classifier": 1, "rule": 1, "user": 0},
            "friction": {"total": 5, "correction": 2, "override": 1, "rebuke": 1, "repeat": 0, "pushback": 1},
            "verdict": "ok", "tools": {"Bash": 30, "Edit": 20}}))
        # Sessions may also sit one directory down.
        (m / "sessions" / "2026-10").mkdir()
        (m / "sessions" / "2026-10" / "sess-headless-2.json").write_text(json.dumps(
            {"session_id": "sess-headless-2", "started_at": "2026-10-02T03:00:00Z", "user_turns": 0, "commits": 1}))
        # Unusable files are skipped, not fatal.
        (m / "sessions" / "broken.json").write_text("{not json")
        (m / "sessions" / "no-id.json").write_text(json.dumps({"repo": "acme/widgets"}))

        write_jsonl(m / "decisions" / "sess-typed-1.jsonl", [
            {"ts": "2026-10-01T10:05:00Z", "session_id": "sess-typed-1", "repo": "acme/widgets", "seq": 1,
             "turn_index": 3, "mechanism": "question", "questions": 2, "before_first_write": True,
             "type": "inline", "question": "which fixture?"}])
        write_jsonl(m / "friction" / "sess-typed-1.jsonl", [
            {"ts": "2026-10-01T10:06:00Z", "session_id": "sess-typed-1", "repo": "acme/widgets", "seq": 1,
             "turn_index": 4, "type": "correction", "tags": ["a", "b"], "retracted": False, "repeat": True}])
        write_jsonl(m / "blocked" / "sess-typed-1.jsonl", [
            {"i": 1, "kind": "rule", "raw": "denied", "tool": "Bash"}])
        write_jsonl(m / "git-events" / "sess-typed-1.jsonl", [
            {"ts": "2026-10-01T11:00:00Z", "kind": "pr-create", "repo": "acme/widgets",
             "branch": "claude/fixture", "created_branch": "claude/fixture", "draft": False}])
        write_jsonl(m / "headless-runs" / "agent-decision.jsonl", [
            {"ts": "2026-10-01T10:07:00Z", "what": "agent-decision judge", "repo": "acme/widgets", "pr": 7,
             "model": "claude-sonnet-5-5", "total_cost_usd": 0.0123, "outcome": "success",
             "usage": {"input_tokens": 5, "output_tokens": 6, "cache_creation_input_tokens": 7, "cache_read_input_tokens": 8},
             "num_turns": 3},
            {"ts": "2026-10-01T10:08:00Z", "what": "claude-review", "usage": "junk", "total_cost_usd": {"x": 1}},
            ["not", "an", "object"]])
        write_jsonl(m / "crossings" / "sess-typed-1.jsonl", [
            {"ts": "2026-10-01T11:30:00Z", "kind": "sitting", "at": 90, "min": 30, "stay": True, "overrun": 0},
            {"ts": "2026-10-01T11:40:00Z", "kind": "sitting", "at": 100, "min": 40, "stay": False, "overrun": 1},
            {"ts": "2026-10-01T11:50:00Z", "kind": "sitting", "at": 110, "min": 50, "overrun": 2}])
        write_jsonl(m / "permission-requests" / "se" / "sess-typed-1.jsonl", [  # sharded, as the hook writes it
            {"ts": "2026-10-01T11:45:00Z", "session_id": "sess-typed-1", "cwd": "/w", "permission_mode": "auto",
             "tool": "Bash", "input": {"command": "git push"}, "masked": 0},
            {"ts": "2026-10-01T11:46:00Z", "session_id": "sess-typed-1", "cwd": "/w", "permission_mode": "auto",
             "tool": "Write", "input": None, "masked": None}])
        write_jsonl(self.sd / "commits.jsonl", [
            {"ts": "2026-10-01T11:00:00Z", "session_id": "sess-typed-1", "repo": "acme/widgets",
             "branch": "claude/fixture", "commit": "deadbeef"},
            {"ts": "2026-10-01T11:10:00Z", "session_id": "sess-typed-1", "repo": "acme/widgets",
             "branch": "claude/fixture", "commit": "cafef00d"}])

        items = self.sd / "items"
        items.mkdir()
        (items / "item-one.md").write_text(
            "# Fixture card\n\nstatus=open in the prose is ignored\n\n## Log\n"
            "2026-10-01T09:00:00Z abcd1234 status=open owner=human-ruling repo=acme/widgets parent=item-zero model=m effort=low home=board\n"
            "2026-10-02T09:00:00Z abcd1234 status=`done`, owner=human-ruling\n"
            "2026-10-02T09:30:00Z abcd1234 cost=0.5\n"
            "\n## Notes\n2026-10-03T09:00:00Z abcd1234 status=open owner=agent\n")

        t = self.projects / "-fixture-cwd"
        lines = [
            transcript_line("first typed prompt here", "2026-10-01T10:00:00Z"),
            transcript_line("second typed prompt", "2026-10-01T10:30:00Z"),
            transcript_line("<command-name>/fixture-cmd</command-name><command-args>x</command-args>",
                            "2026-10-01T10:40:00Z"),
            transcript_line("<system-reminder>machine text</system-reminder>", "2026-10-01T10:41:00Z"),
            transcript_line("<task-notification>done</task-notification>", "2026-10-01T10:42:00Z"),
            transcript_line("  <local-command-caveat>x</local-command-caveat>", "2026-10-01T10:43:00Z"),
            transcript_line("Another Claude session sent a message: hello", "2026-10-01T10:44:00Z"),
            transcript_line("Stop hook feedback: do the thing", "2026-10-01T10:45:00Z"),
            transcript_line("Review this change for security vulnerabilities in the diff", "2026-10-01T10:46:00Z"),
            transcript_line("You previously flagged these candidate vulnerabilities: none", "2026-10-01T10:47:00Z"),
            transcript_line("sidechain prompt", "2026-10-01T10:48:00Z", sidechain=True),
            transcript_line([{"type": "tool_result", "content": "not a string"}], "2026-10-01T10:49:00Z"),
            transcript_line("pasted <pasted_content size=9>0123456789</pasted_content> tail words",
                            "2026-10-01T10:50:00Z"),
            "this line is not json but mentions \"role\":\"user\",\"content\":\" anyway",
        ]
        (t / "sess-typed-1.jsonl").write_text("\n".join(lines) + "\n")
        # A transcript with only machine-written prompts is a headless run.
        (t / "sess-headless-2.jsonl").write_text(
            transcript_line("Review this change for security vulnerabilities", "2026-10-02T03:00:00Z",
                            session="sess-headless-2") + "\n")

    def run(self, *args, github=False, extra_env=None):
        env = {**os.environ, "CLAUDE_STATE_REPO": str(self.repo), "HOME": str(self.home),
               "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        env.update(extra_env or {})
        cmd = [sys.executable, str(ENGINE), "--db", str(self.db), "--projects", str(self.projects), *args]
        if github:
            cmd.append("--github")
        return subprocess.run(cmd, env=env, capture_output=True, text=True)

    def q(self, sql, *params):
        cx = sqlite3.connect(self.db)
        try:
            return cx.execute(sql, params).fetchall()
        finally:
            cx.close()


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.fx = Fixture()
        self.addCleanup(self.fx.close)

    def build(self, *args, **kw):
        r = self.fx.run(*args, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r


class SourcesTest(FixtureTest):
    def test_sessions_map_nested_counters_and_skip_unusable_files(self):
        self.build("--quiet")
        self.assertEqual(self.fx.q("select count(*) from sessions"), [(2,)])
        row = self.fx.q("select repo, user_turns, dec_gate, blk_rule, fr_correction, fr_pushback, work_started, "
                        "cost_usd, tools_json from sessions where session_id='sess-typed-1'")[0]
        self.assertEqual(row[:7], ("acme/widgets", 4, 1, 1, 2, 1, 1))
        self.assertEqual(row[7], 1.5)
        self.assertEqual(json.loads(row[8]), {"Bash": 30, "Edit": 20})
        # one row per model with a numeric figure; a record without the field and with
        # no cost_usd has none
        self.assertEqual(self.fx.q("select model, cost_usd from session_cost order by model"),
                         [("model-x", 1.2), ("model-y", 0.3)])
        self.assertEqual(self.fx.q("select work_started, dec_total from sessions where session_id='sess-headless-2'"),
                         [(0, None)])

    def test_streams_land_one_table_each(self):
        self.build("--quiet")
        self.assertEqual(self.fx.q("select mechanism, questions, before_first_write, type from decisions"),
                         [("question", 2, 1, "inline")])
        self.assertEqual(self.fx.q("select type, tags, retracted, repeat from friction"),
                         [("correction", "a,b", 0, 1)])
        # blocked rows carry the file's session id, the record has none.
        self.assertEqual(self.fx.q("select session_id, kind, tool from blocked"),
                         [("sess-typed-1", "rule", "Bash")])
        self.assertEqual(self.fx.q("select kind, created_branch, draft from git_events"),
                         [("pr-create", "claude/fixture", 0)])
        self.assertEqual(self.fx.q("select what, repo, pr, cost_usd, input_tokens, cache_read_tokens, outcome,"
                                   " json_extract(raw, '$.num_turns') from headless_runs where ts is not null order by ts"),
                         [("agent-decision judge", "acme/widgets", 7, 0.0123, 5, 8, "success", 3),
                          ("claude-review", None, None, '{"x": 1}', None, None, None, None)])
        self.assertEqual(self.fx.q("select raw from headless_runs where ts is null"), [('["not", "an", "object"]',)])
        self.assertEqual(self.fx.q("select stay from crossings order by at"), [(1,), (0,), (None,)])
        self.assertEqual(self.fx.q("select count(*), count(distinct commit_sha) from commits"), [(2, 2)])
        self.assertEqual(self.fx.q("select tool, permission_mode, json_extract(input, '$.command') from"
                                   " permission_requests order by ts"),
                         [("Bash", "auto", "git push"), ("Write", "auto", None)])

    def test_item_events_come_only_from_the_log_section(self):
        self.build("--quiet")
        rows = self.fx.q("select item_id, ts, status, owner, repo, parent, title from item_events order by ts")
        self.assertEqual(rows, [
            ("item-one", "2026-10-01T09:00:00Z", "open", "human-ruling", "acme/widgets", "item-zero", "Fixture card"),
            ("item-one", "2026-10-02T09:00:00Z", "done", "human-ruling", None, None, "Fixture card")])

    def test_rebuild_replaces_instead_of_duplicating(self):
        self.build("--quiet")
        before = [self.fx.q(f"select count(*) from {t}") for t in
                  ("sessions", "decisions", "friction", "commits", "item_events", "typing")]
        self.build("--quiet")
        after = [self.fx.q(f"select count(*) from {t}") for t in
                 ("sessions", "decisions", "friction", "commits", "item_events", "typing")]
        self.assertEqual(before, after)

    def test_meta_records_the_build_time(self):
        self.build("--quiet")
        built = self.fx.q("select value from meta where key='built_at'")
        self.assertRegex(built[0][0], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_report_names_every_source_unless_quiet(self):
        r = self.build()
        for word in ("sessions", "decisions", "item_events", "typing"):
            self.assertIn(word, r.stdout)
        self.assertEqual(self.build("--quiet").stdout, "")


class InputTest(FixtureTest):
    def write_host(self, host, home, minutes):
        d = self.fx.sd / "metrics" / "input" / host
        d.mkdir(parents=True, exist_ok=True)
        (d / "host.json").write_text(json.dumps({"host": host, "home": home}))
        write_jsonl(d / "2026-10-20.jsonl", minutes)

    def test_minutes_and_categories_load_per_host(self):
        self.write_host("boxa", "/home/a", [
            {"minute": 100, "keys": 30, "clicks": 2, "scroll": 1, "move": 9, "afk": 0, "seen": 60,
             "win": {"claude": 40, "browser": 20}},
            {"minute": "bad"}])
        self.write_host("boxb", "/Users/b", [{"minute": 100, "keys": 5, "afk": 60, "seen": 60}])
        self.build("--quiet", "--no-typing")
        self.assertEqual(self.fx.q("select host, minute, keys, afk from input order by host"),
                         [("boxa", 100, 30, 0), ("boxb", 100, 5, 60)])
        self.assertEqual(self.fx.q("select category, seconds from input_win order by category"),
                         [("browser", 20), ("claude", 40)])

    def test_a_session_takes_the_host_whose_home_holds_its_cwd(self):
        self.write_host("boxa", "/fixture", [])
        self.write_host("boxb", "/fixture/cwd/deeper", [])
        self.build("--quiet", "--no-typing")
        self.assertEqual(mdb.host_for("/fixture/cwd", [("/fixture/cwd/deeper", "boxb"), ("/fixture", "boxa")]), "boxa")
        self.assertEqual(mdb.host_for("/fixturelike", [("/fixture", "boxa")]), None)
        self.assertEqual(mdb.host_for(None, [("/fixture", "boxa")]), None)
        self.assertEqual(mdb.host_for("c:\\Users\\x\\repo", [("C:\\Users\\x", "boxw")]), "boxw")

    def test_no_input_leaves_the_tables_as_they_were(self):
        self.write_host("boxa", "/home/a", [{"minute": 1, "keys": 1}])
        self.build("--quiet", "--no-typing")
        (self.fx.sd / "metrics" / "input" / "boxa" / "2026-10-20.jsonl").unlink()
        self.build("--quiet", "--no-typing", "--no-input")
        self.assertEqual(self.fx.q("select count(*) from input"), [(1,)])


class TypingTest(FixtureTest):
    def typing(self, sid):
        return self.fx.q("select prompts, chars, words, pasted_chars, cwd, first_ts, last_ts "
                         "from typing where session_id=?", sid)[0]

    def test_only_what_the_user_wrote_counts(self):
        self.build("--quiet")
        prompts, chars, words, pasted, cwd, first, last = self.typing("sess-typed-1")
        # two plain prompts, one slash command and the prompt with a paste in it
        self.assertEqual(prompts, 4)
        self.assertEqual(cwd, "/fixture/cwd")
        self.assertEqual(first, "2026-10-01T10:00:00Z")
        self.assertEqual(last, "2026-10-01T10:50:00Z")

    def test_a_typed_slash_command_counts_as_a_touch_of_its_name(self):
        self.build("--quiet")
        _, chars, words, _, _, _, _ = self.typing("sess-typed-1")
        plain = len("first typed prompt here") + len("second typed prompt") + len("/fixture-cmd")
        paste_rest = len("pasted  tail words")
        self.assertEqual(chars, plain + paste_rest)
        self.assertEqual(words, 4 + 3 + 1 + 3)

    def test_pasted_blocks_are_counted_apart_from_typing(self):
        self.build("--quiet")
        _, _, _, pasted, _, _, _ = self.typing("sess-typed-1")
        self.assertEqual(pasted, len("<pasted_content size=9>0123456789</pasted_content>"))

    def test_headless_machine_prompts_leave_zero_typed(self):
        self.build("--quiet")
        self.assertEqual(self.typing("sess-headless-2")[:4], (0, 0, 0, 0))

    def test_injected_prefixes_are_machine_text(self):
        for text in ("<system-reminder>x", "  <anything-else>x", "Another Claude session sent a message: x",
                     "Stop hook feedback: x", "Review this change for security vulnerabilities x",
                     "You previously flagged these candidate vulnerabilities x"):
            self.assertTrue(mdb.INJECTED.match(text), text)
        for text in ("fix the <b> tag", "please review this change", "Stop the hook feedback loop"):
            self.assertFalse(mdb.INJECTED.match(text), text)

    def test_scan_is_incremental_and_rescan_forces_every_transcript(self):
        r = self.build()
        self.assertIn("2 of 2 transcripts rescanned", r.stdout)
        self.assertIn("0 of 2 transcripts rescanned", self.build().stdout)
        path = self.fx.projects / "-fixture-cwd" / "sess-typed-1.jsonl"
        with open(path, "a") as f:
            f.write(transcript_line("a late prompt", "2026-10-01T11:00:00Z") + "\n")
        self.assertIn("1 of 2 transcripts rescanned", self.build().stdout)
        self.assertEqual(self.typing("sess-typed-1")[0], 5)
        self.assertIn("2 of 2 transcripts rescanned", self.build("--rescan-typing").stdout)

    def test_no_typing_skips_the_scan(self):
        r = self.build("--no-typing")
        self.assertNotIn("typing", r.stdout)
        self.assertEqual(self.fx.q("select count(*) from typing"), [(0,)])


class TypingCacheTest(FixtureTest):
    """The cache is keyed by transcript path: two files can carry one session id."""

    def test_two_transcripts_of_one_session_are_two_rows_and_both_stay_cached(self):
        t = self.fx.projects / "-fixture-cwd"
        (t / "resumed.jsonl").write_text(transcript_line("a resumed prompt", "2026-10-03T10:00:00Z") + "\n")
        self.assertIn("3 of 3", self.build().stdout)
        self.assertEqual(self.fx.q("select count(*), count(distinct session_id) from typing"), [(3, 2)])
        self.assertEqual(self.fx.q("select sum(prompts) from typing where session_id='sess-typed-1'"), [(5,)])
        self.assertIn("0 of 3", self.build().stdout)

    def test_a_deleted_transcript_takes_its_row_with_it(self):
        self.build("--quiet")
        (self.fx.projects / "-fixture-cwd" / "sess-headless-2.jsonl").unlink()
        self.build("--quiet")
        self.assertEqual(self.fx.q("select session_id from typing"), [("sess-typed-1",)])

    def test_a_cache_keyed_by_session_id_is_rebuilt(self):
        self.fx.db.parent.mkdir(parents=True)
        cx = sqlite3.connect(self.fx.db)
        cx.execute("create table typing(session_id text primary key, path text, mtime real, size int, cwd text, "
                   "first_ts text, last_ts text, prompts int, chars int, words int, pasted_chars int)")
        cx.execute("insert into typing values ('old','/gone',0,0,null,null,null,1,1,1,0)")
        cx.commit()
        cx.close()
        self.assertIn("2 of 2", self.build().stdout)
        self.assertEqual(self.fx.q("select count(*) from typing where session_id='old'"), [(0,)])
        self.assertEqual(self.fx.q("select name from pragma_table_info('typing') where pk=1"), [("path",)])


class PrivacyGuardTest(FixtureTest):
    """The database holds private titles; the Stop hook commits state/ wholesale."""

    def checkout(self, ignore=None, exclude=None):
        repo = Path(self.fx.tmp.name) / "tracked"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        if ignore:
            (repo / ".gitignore").write_text(ignore)
        if exclude:
            (repo / ".git" / "info").mkdir(exist_ok=True)
            (repo / ".git" / "info" / "exclude").write_text(exclude)
        self.fx.db = repo / "state" / "dashboard" / "metrics.db"

    def test_refuses_to_write_where_git_would_track_it(self):
        self.checkout()
        r = self.fx.run("--quiet")
        self.assertEqual(r.returncode, 4)
        self.assertIn("not gitignored", r.stderr)
        self.assertFalse(self.fx.db.exists())

    def test_writes_where_gitignore_covers_it(self):
        self.checkout(ignore="state/dashboard/\n")
        self.build("--quiet")
        self.assertTrue(self.fx.db.exists())

    def test_writes_where_the_local_exclude_covers_it(self):
        self.checkout(exclude="state/dashboard/\n")
        self.build("--quiet")
        self.assertTrue(self.fx.db.exists())

    def test_no_check_outside_a_checkout(self):
        self.assertTrue(mdb.ignored_by_git(str(self.fx.db)))


class SessionPrTest(FixtureTest):
    def test_pr_create_rows_load_and_cost_splits_over_merged_prs(self):
        d = self.fx.sd / "metrics" / "gh-writes"
        d.mkdir(parents=True)
        lines = [{"session_id": "sess-typed-1", "verb": "pr create", "target": "https://github.com/acme/widgets/pull/7"},
                 {"session_id": "sess-typed-1", "verb": "pr create", "target": "https://github.com/acme/widgets/pull/8"},
                 {"session_id": "sess-typed-1", "verb": "pr create", "target": "no url"},
                 {"session_id": "sess-typed-1", "verb": "pr merge", "target": "https://github.com/acme/widgets/pull/9"}]
        (d / "sess-typed-1.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        self.build("--quiet")
        self.assertEqual(self.fx.q("select session_id, repo, number from session_pr order by number"),
                         [("sess-typed-1", "acme/widgets", 7), ("sess-typed-1", "acme/widgets", 8)])
        cx = sqlite3.connect(self.fx.db)
        cx.execute("insert into gh_items(repo, number, kind, merged_at) values ('acme/widgets', 7, 'pr', '2026-10-02T00:00:00Z')")
        cx.execute("insert into gh_items(repo, number, kind) values ('acme/widgets', 8, 'pr')")
        cx.commit()
        cx.close()
        # session cost 1.5 over two PRs; only #7 is merged
        self.assertEqual(self.fx.q("select repo, number, cost_usd_guess, sessions from pr_cost_guess"),
                         [("acme/widgets", 7, 0.75, 1)])


class CardCostTest(FixtureTest):
    def test_session_cost_lands_once_on_its_first_claim_and_sums_up_the_tree(self):
        items = self.fx.sd / "items"
        items.mkdir(exist_ok=True)
        def card(name, *log):
            (items / (name + ".md")).write_text("# " + name + "\n\n## Log\n" + "\n".join(log) + "\n")
        # sess-typed-1 (cost 1.5) is the driver: claims the parent, then every child
        card("parent", "2026-10-01T09:00:00Z abcd1234 status=open owner=agent",
             "2026-10-01T09:01:00Z sess-typ status=claimed", "2026-10-01T09:02:00Z abcd1234 allocation=3usd",
             "2026-10-01T09:03:00Z abcd1234 allocation=2.5usd")
        card("kid", "2026-10-01T09:00:00Z abcd1234 status=open parent=parent",
             "2026-10-01T09:05:00Z sess-typ status=claimed",
             "2026-10-01T09:05:10Z abcd1234 actual=1.25usd", "2026-10-01T09:05:20Z abcd1234 actual=unknown (no meter)",
             "2026-10-01T09:05:30Z abcd1234 actual=0.5usd")
        card("grandkid", "2026-10-01T09:00:00Z abcd1234 status=open parent=kid",
             "2026-10-01T09:06:00Z sess-typ status=claimed", "2026-10-01T09:07:00Z abcd1234 actual=unmeasured")
        self.build("--quiet")
        self.assertEqual(self.fx.q("select session8, item_id from session_card"), [("sess-typ", "parent")])
        self.assertEqual(self.fx.q("select card, own_usd, subtree_usd from card_cost where card != 'item-one' order by card"),
                         [("grandkid", 0, 0), ("kid", 0, 0), ("parent", 1.5, 1.5)])
        # a worker session of its own, on the grandchild, rolls up through two levels
        cx = sqlite3.connect(self.fx.db)
        cx.execute("insert into sessions(session_id, cost_usd) values ('wrk12345-x', 0.25)")
        cx.execute("insert into item_events(item_id, ts, session8, status) values ('grandkid', '2026-10-01T10:00:00Z', 'wrk12345', 'claimed')")
        cx.commit()
        cx.close()
        self.assertEqual(self.fx.q("select card, own_usd, subtree_usd from card_cost where card != 'item-one' order by card"),
                         [("grandkid", 0.25, 0.25), ("kid", 0, 0.25), ("parent", 1.5, 1.75)])
        self.assertEqual(self.fx.q("select card, allocation_usd, subtree_usd from batch_cost order by card"),
                         [("kid", None, 0.25), ("parent", 2.5, 1.75)])
        # appended actuals sum; the non-numeric one is skipped
        self.assertEqual(self.fx.q("select card, actual_usd from batch_cost order by card"),
                         [("kid", 1.75), ("parent", None)])


class GithubTest(FixtureTest):
    def test_github_flag_loads_repos_issues_and_prs(self):
        r = self.build("--github")
        self.assertRegex(r.stdout, r"gh_items +4 from ")  # the item count, not another loader's
        self.assertEqual(self.fx.q("select repo, topics, archived, private from gh_repos order by repo"),
                         [("acme/old", "", 1, 1), ("acme/widgets", "project-alpha,python", 0, 0)])
        self.assertEqual(self.fx.q("select count(*) from gh_items"), [(4,)])
        self.assertEqual(self.fx.q("select kind, state, head_ref, author from gh_items "
                                   "where repo='acme/widgets' order by kind"),
                         [("issue", "OPEN", None, "someone"), ("pr", "MERGED", "claude/fixture", None)])
        self.assertEqual(len(self.fx.q("select value from meta where key='gh_refreshed_at'")), 1)

    def test_without_the_flag_gh_is_never_called_and_rows_survive(self):
        self.build("--github", "--quiet")
        # A gh that fails every call would break the build if it were invoked.
        (self.fx.bin / "gh").write_text("#!/bin/sh\nexit 9\n")
        self.build("--quiet")
        self.assertEqual(self.fx.q("select count(*) from gh_items"), [(4,)])

    def test_ci_check_artifacts_land_once_per_check_and_a_refetch_adds_none(self):
        rows = [{"ts": "2026-10-20T10:00:00Z", "what": "claude-review", "repo": "evil/x", "pr": 2, "num_turns": 7,
                 "model": "claude-sonnet-5-5", "total_cost_usd": 0.5, "outcome": "success", "usage": {"input_tokens": 3, "output_tokens": 4}},
                {"ts": "2026-10-20T10:05:00Z", "what": "claude-maxims", "pr": 2, "model": "claude-opus-5-5", "total_cost_usd": 1.5},
                {"ts": "2026-10-20T10:09:00Z", "pr": 2, "model": "claude-sonnet-5-5", "total_cost_usd": 0.25}]  # no `what`: a review
        # Run 42 is acme/widgets' own; run 43 is a fork's; run 44's file is junk; run 45 is expired.
        def art(aid, rid, own=True, expired=False):
            return {"id": aid, "expired": expired, "created_at": "2026-10-20T10:10:00Z",
                    "workflow_run": {"id": rid, "head_sha": "abc123", "repository_id": 1, "head_repository_id": 1 if own else 2}}
        listing = json.dumps({"artifacts": [art(142, 42), art(143, 43, own=False), art(144, 44), art(145, 45, expired=True)]})
        zipper = self.fx.bin / "mkzip.py"
        zipper.write_text("""import io, sys, zipfile
b = io.BytesIO()
with zipfile.ZipFile(b, "w") as z:
    z.writestr("headless-run.jsonl", sys.argv[1] if sys.argv[1:] else "")
sys.stdout.buffer.write(b.getvalue())
""")
        good = "\n".join(json.dumps(r) for r in rows) + "\n"
        (self.fx.bin / "good.jsonl").write_text(good)
        gh = self.fx.bin / "gh"
        gh.rename(self.fx.bin / "gh-real")
        # The fixture's PR is made recent so the item fetch is unchanged.
        gh.write_text(f"""#!/bin/sh
case "$1" in
  api) case "$2" in
         repos/acme/widgets/actions/artifacts/144/zip) python3 {zipper} '[1, "junk"';;
         repos/acme/widgets/actions/artifacts/*/zip) python3 {zipper} "$(cat {self.fx.bin}/good.jsonl)";;
         repos/acme/widgets/actions/artifacts\?*) echo '{listing}';;
         repos/*) echo '{{"artifacts": []}}';;
         *) gh-real "$@";;
       esac;;
  *) exec gh-real "$@";;
esac
""")
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        for _ in range(2):
            self.build("--github", "--quiet")
            self.assertEqual(self.fx.q("select what, repo, run, cost_usd, head_sha from ci_checks order by what"),
                             [("claude-maxims", "acme/widgets", 42, 1.5, "abc123"),
                              ("claude-review", "acme/widgets", 42, 0.5, "abc123")])  # dedupe by repo, run and check
        runs = list((self.fx.sd / "metrics" / "headless-runs").glob("*/ci-*.jsonl"))  # sharded by run id
        self.assertEqual(sorted(p.name for p in runs), ["ci-42.jsonl", "ci-43.jsonl", "ci-44.jsonl"])
        got = {p.name: [json.loads(l) for l in p.read_text().splitlines()] for p in runs}
        self.assertEqual([r["what"] for r in got["ci-42.jsonl"]], ["claude-review", "claude-maxims", "claude-review"])
        self.assertEqual({r["repo"] for r in got["ci-42.jsonl"]}, {"acme/widgets"})  # the artifact cannot name its repo
        self.assertEqual(got["ci-43.jsonl"][0]["trusted"], False)
        self.assertEqual((got["ci-44.jsonl"][0]["unparsed"], got["ci-44.jsonl"][0]["text"]), (True, '[1, "junk"'))

    def test_a_failing_gh_is_a_failed_build(self):
        (self.fx.bin / "gh").write_text("#!/bin/sh\necho nope >&2\nexit 9\n")
        r = self.fx.run("--quiet", github=True)
        self.assertNotEqual(r.returncode, 0)


class StateRepoTest(unittest.TestCase):
    def test_env_override_wins_when_it_is_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".git").mkdir()
            old = os.environ.get("CLAUDE_STATE_REPO")
            os.environ["CLAUDE_STATE_REPO"] = d
            try:
                self.assertEqual(mdb.state_dir(), os.path.join(d, "state", "global"))
            finally:
                if old is None:
                    del os.environ["CLAUDE_STATE_REPO"]
                else:
                    os.environ["CLAUDE_STATE_REPO"] = old

    def test_missing_state_repo_exits_3(self):
        absolute = ["/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch"]
        if any(os.path.isdir(os.path.join(p, ".git")) for p in absolute):
            self.skipTest("a fallback state repo exists on this machine")
        with tempfile.TemporaryDirectory() as home:
            env = {**os.environ, "HOME": home, "CLAUDE_STATE_REPO": os.path.join(home, "nope")}
            r = subprocess.run([sys.executable, str(ENGINE), "--db", os.path.join(home, "x.db")],
                               env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 3)
        self.assertIn("state repo not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
