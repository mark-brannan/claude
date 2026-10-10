#!/usr/bin/env python3
# Tests for log-gh-writes.py. Run: python3 hooks/log-gh-writes.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PostToolUse
# JSON on stdin, with CLAUDE_STATE_REPO and HOME pointed at a throwaway dir.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "log-gh-writes.py"


class LogGhWritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        repo = self.home / "state"
        (repo / ".git").mkdir(parents=True)
        self.log = repo / "state/global/metrics/gh-writes/ab/abc123.jsonl"
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_STATE_REPO": str(repo)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, cmd, tool="Bash", stdout="", sid="abc123"):
        ev = {"tool_name": tool, "session_id": sid, "cwd": str(self.home),
              "tool_input": {"command": cmd}, "tool_response": {"stdout": stdout}}
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        if not self.log.exists():
            return []
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def one(self, cmd, **kw):
        rows = self.run_hook(cmd, **kw)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_pr_merge(self):
        r = self.one("gh pr merge 42 --squash -R o/r")
        self.assertEqual((r["verb"], r["target"], r["repo"], r["session_id"]),
                         ("pr merge", "42", "o/r", "abc123"))
        self.assertRegex(r["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_value_flag_not_target(self):
        r = self.one("gh pr comment -R o/r --body 'hi there' 7")
        self.assertEqual((r["verb"], r["target"]), ("pr comment", "7"))

    def test_create_target_from_printed_url(self):
        r = self.one("gh pr create --title t --body b", stdout="https://github.com/o/r/pull/9\n")
        self.assertEqual((r["verb"], r["target"], r["repo"]),
                         ("pr create", "https://github.com/o/r/pull/9", "o/r"))

    def test_issue_and_label(self):
        self.assertEqual(self.one("gh issue close 3 -R o/r")["verb"], "issue close")

    def test_api_methods(self):
        r = self.one("gh api -X DELETE repos/o/r/git/refs/heads/x")
        self.assertEqual((r["verb"], r["target"], r["repo"]),
                         ("api DELETE", "repos/o/r/git/refs/heads/x", "o/r"))

    def test_api_fields_imply_post(self):
        self.assertEqual(self.one("gh api repos/o/r/issues -f title=x")["verb"], "api POST")

    def test_api_get_not_logged(self):
        self.assertEqual(self.run_hook("gh api repos/o/r/pulls/1"), [])
        self.assertEqual(self.run_hook("gh api -X GET repos/o/r/pulls"), [])

    def test_git_push(self):
        r = self.one("git push -u origin claude/x")
        self.assertEqual((r["verb"], r["target"]), ("git push", "origin claude/x"))

    def test_chain_logs_each_write(self):
        rows = self.run_hook("git push origin b && gh pr create -R o/r; gh pr merge 5 -R o/r")
        self.assertEqual([r["verb"] for r in rows], ["git push", "pr create", "pr merge"])

    def test_reads_and_other_commands_not_logged(self):
        for cmd in ("gh pr view 4", "gh pr list", "gh issue view 1", "git status",
                    "git commit -m 'gh pr merge 1'", "echo gh pr merge 1", "gh pr diff 3"):
            self.assertEqual(self.run_hook(cmd), [], cmd)

    def test_other_tool_ignored(self):
        self.assertEqual(self.run_hook("gh pr merge 1", tool="Read"), [])

    def test_malformed_input_fails_open(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json",
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0)

    def test_quoted_separators_and_newlines_are_one_write(self):
        r = self.one("gh pr comment 1 -b 'done; merged | ok && x'")
        self.assertEqual((r["verb"], r["target"]), ("pr comment", "1"))
        r = self.one("gh pr comment 2 --body $'a\\nb'")
        self.assertEqual(r["target"], "2")

    def test_multiline_body_one_row(self):
        self.assertEqual(len(self.run_hook('gh pr create --title t --body "line1\nline2"')), 1)

    def test_heredoc_body_not_a_command(self):
        rows = self.run_hook("cat <<'EOF'\ngh pr merge 1\nEOF\ngh pr merge 2")
        self.assertEqual([r["target"] for r in rows], ["2"])

    def test_git_push_force_keeps_remote(self):
        self.assertEqual(self.one("git push -f origin b")["target"], "origin b")

    def test_gh_short_d_flag_is_boolean(self):
        self.assertEqual(self.one("gh pr merge -d 42")["target"], "42")

    def test_credential_stripped_from_target(self):
        r = self.one("git push https://user:TOKEN@github.com/o/r.git b")
        self.assertNotIn("TOKEN", r["target"])

    def test_api_attached_method(self):
        self.assertEqual(self.one("gh api -XPOST repos/o/r/issues")["verb"], "api POST")

    def test_graphql_read_not_logged_mutation_is(self):
        self.assertEqual(self.run_hook("gh api graphql -f query='query{viewer{login}}'"), [])
        self.assertEqual(self.one("gh api graphql -f query='mutation{x}'")["verb"], "api POST")

    def test_unbalanced_quote_fails_open(self):
        self.assertEqual(self.run_hook("gh pr comment 1 --body 'oops"), [])


if __name__ == "__main__":
    unittest.main()
