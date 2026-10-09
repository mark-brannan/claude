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
        write_jsonl(m / "crossings" / "sess-typed-1.jsonl", [
            {"ts": "2026-10-01T11:30:00Z", "kind": "sitting", "at": 90, "min": 30, "stay": True, "overrun": 0},
            {"ts": "2026-10-01T11:40:00Z", "kind": "sitting", "at": 100, "min": 40, "stay": False, "overrun": 1},
            {"ts": "2026-10-01T11:50:00Z", "kind": "sitting", "at": 110, "min": 50, "overrun": 2}])
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
        self.assertEqual(self.fx.q("select stay from crossings order by at"), [(1,), (0,), (None,)])
        self.assertEqual(self.fx.q("select count(*), count(distinct commit_sha) from commits"), [(2, 2)])

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


class GithubTest(FixtureTest):
    def test_github_flag_loads_repos_issues_and_prs(self):
        r = self.build("--github")
        self.assertIn("gh_items", r.stdout)
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
