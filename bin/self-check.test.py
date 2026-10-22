#!/usr/bin/env python3
# Tests for self-check. Run: python3 bin/self-check.test.py
# Offline only: the live clone is a throwaway clone of a throwaway origin.
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
ENGINE = Path(__file__).resolve().parent / "self-check"
spec = importlib.util.spec_from_loader("self_check", importlib.machinery.SourceFileLoader("self_check", str(ENGINE)))
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)


def sh(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="t",
                            GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


class LiveCloneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        origin, live = os.path.join(self.tmp.name, "origin"), os.path.join(self.tmp.name, "live")
        sh(self.tmp.name, "git", "init", "-q", "-b", "main", origin)
        sh(origin, "git", "commit", "-q", "--allow-empty", "-m", "one")
        sh(self.tmp.name, "git", "clone", "-q", origin, live)
        self.origin, sc.LIVE = origin, live

    def tearDown(self):
        self.tmp.cleanup()

    def test_on_main_and_current_is_ok(self):
        status, value = sc.live_row(fetch=True)
        self.assertEqual(status, "ok", value)
        self.assertIn("0 behind", value)

    def test_stranded_on_a_deleted_branch_is_bad(self):
        # The 2026-10-21 shape: a branch in the live clone, merged and deleted upstream, main moved on.
        sh(self.origin, "git", "checkout", "-q", "-b", "orders/x")
        sh(sc.LIVE, "git", "fetch", "-q")
        sh(sc.LIVE, "git", "checkout", "-q", "-t", "origin/orders/x")
        sh(self.origin, "git", "checkout", "-q", "main")
        sh(self.origin, "git", "branch", "-q", "-D", "orders/x")
        sh(self.origin, "git", "commit", "-q", "--allow-empty", "-m", "two")
        sh(sc.LIVE, "git", "fetch", "-q", "--prune")
        status, value = sc.live_row(fetch=False)
        self.assertEqual(status, "bad")
        self.assertIn("orders/x", value)
        self.assertIn("1 behind", value)
        self.assertIn("upstream deleted", value)

    def test_unfetched_or_failed_fetch_is_never_ok(self):
        self.assertEqual(sc.live_row(fetch=False)[0], "warn")
        sh(sc.LIVE, "git", "remote", "set-url", "origin", "/nonexistent")
        status, value = sc.live_row(fetch=True)
        self.assertEqual(status, "warn")
        self.assertIn("fetch failed", value)

    def test_dirty_paths_keep_their_first_letter(self):
        Path(sc.LIVE, "settings.json").write_text("{}")
        self.assertEqual(sc.dirty_row(), ("warn", "1: settings.json"))


NOW = sc.when("2026-10-21T22:00:00Z")


class HookRecordsTest(unittest.TestCase):
    def test_counts_by_event_and_names_the_last(self):
        lines = [{"type": "user"},
                 {"type": "attachment", "timestamp": "2026-10-21T21:59:00Z",
                  "attachment": {"type": "hook_success", "hookEvent": "SessionStart", "hookName": "SessionStart:startup", "exitCode": 0}},
                 {"type": "attachment", "timestamp": "t2", "attachment": {"type": "date"}},
                 {"type": "attachment", "timestamp": "2026-10-21T21:59:30.500Z",
                  "attachment": {"type": "hook_success", "hookEvent": "PostToolUse", "hookName": "PostToolUse:Bash", "exitCode": 1}}]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
        try:
            counts, last = sc.hook_rows(sc.hook_records(fh.name), NOW)
        finally:
            os.unlink(fh.name)
        self.assertEqual(counts, ("warn", "PostToolUse 1, SessionStart 1; 1 non-zero exits"))
        self.assertEqual(last[0], "ok")
        self.assertIn("PostToolUse:Bash", last[1])

    def test_an_old_last_record_is_not_bad(self):
        # Away from the keyboard for two hours: the record is old and nothing is wrong.
        rec = {"ts": "2026-10-21T20:00:00Z", "event": "PostToolUse", "name": "PostToolUse:Bash", "type": "hook_success", "exit": 0}
        self.assertEqual(sc.hook_rows([rec], NOW)[1][0], "ok")

    def test_no_records_is_bad(self):
        self.assertEqual(sc.hook_rows([], NOW)[0][0], "bad")


class CacheTest(unittest.TestCase):
    def cache(self, updated_at):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "metrics", "live", "ab"))
        with open(os.path.join(d, "metrics", "live", "ab", "abcd.json"), "w") as fh:
            json.dump({"last_event": "posttooluse", "updated_at": updated_at}, fh)
        return d

    def test_cache_written_with_the_last_hook_is_ok(self):
        d = self.cache("2026-10-21T21:59:30Z")
        self.assertEqual(sc.cache_row(d, "abcd", "2026-10-21T21:59:30.500Z", "2026-10-21T21:59:31Z", NOW)[0], "ok")

    def test_cache_left_behind_by_the_hooks_is_bad(self):
        # Hooks still fire, the cache stopped moving: the "notices stopped" shape.
        d = self.cache("2026-10-21T19:00:00Z")
        self.assertEqual(sc.cache_row(d, "abcd", "2026-10-21T21:59:30Z", None, NOW)[0], "bad")

    def test_a_tool_result_after_the_cache_is_bad(self):
        # The hook stopped: tool calls go on landing with no write behind them.
        d = self.cache("2026-10-21T21:50:00Z")
        status, value = sc.cache_row(d, "abcd", "2026-10-21T21:50:00Z", "2026-10-21T21:59:00Z", NOW)
        self.assertEqual(status, "bad")
        self.assertIn("540s behind", value)

    def test_a_long_break_after_the_last_event_is_ok(self):
        d = self.cache("2026-10-21T18:00:00Z")
        self.assertEqual(sc.cache_row(d, "abcd", "2026-10-21T18:00:00Z", "2026-10-21T18:00:00.400Z", NOW)[0], "ok")


class LastEventTest(unittest.TestCase):
    def test_counts_results_and_typed_prompts_not_denials_errors_or_notifications(self):
        def result(ts, **kw):
            return dict({"type": "user", "timestamp": ts,
                         "message": {"content": [dict({"type": "tool_result"}, **kw.pop("c", {}))]}}, **kw)
        lines = [{"type": "user", "timestamp": "t-prompt", "origin": {"kind": "human"}, "message": {"content": "hi"}},
                 result("t-result"),
                 result("t-denied", toolDenialKind="hook"),
                 result("t-error", c={"is_error": True}),
                 {"type": "user", "timestamp": "t-note", "origin": {"kind": "task-notification"}, "message": {"content": "x"}},
                 {"type": "assistant", "timestamp": "t-asst", "message": {"content": []}}]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write("\n".join(json.dumps(x) for x in lines) + "\n")
        try:
            self.assertEqual(sc.last_event(fh.name), "t-result")
        finally:
            os.unlink(fh.name)


class FindTranscriptTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "projects", "p"))
        for name, mtime, body in (("aaaa1111-old", 1, '{"hookEvent":"x"}'), ("bbbb2222-new", 2, '{"hookEvent":"x"}'),
                                  ("cccc3333-headless", 3, "{}")):
            path = os.path.join(self.d, "projects", "p", name + ".jsonl")
            Path(path).write_text(body)
            os.utime(path, (mtime, mtime))
        self.live, sc.LIVE = sc.LIVE, self.d
        self.env = os.environ.pop("CLAUDE_CODE_SESSION_ID", None)

    def tearDown(self):
        sc.LIVE = self.live
        if self.env is not None:
            os.environ["CLAUDE_CODE_SESSION_ID"] = self.env

    def test_outside_a_session_guesses_nothing(self):
        self.assertEqual(sc.find_transcript(None), (None, ""))

    def test_a_prefix_finds_the_session(self):
        self.assertEqual(sc.find_transcript("bbbb2222")[1], "bbbb2222-new")

    def test_the_list_is_newest_first_and_skips_sessions_without_hooks(self):
        listed = sc.recent_sessions(NOW)
        self.assertEqual([s.split()[0] for s in listed], ["bbbb2222", "aaaa1111"])


if __name__ == "__main__":
    unittest.main()
