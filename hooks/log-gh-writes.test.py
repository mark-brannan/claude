#!/usr/bin/env python3
# Tests for log-gh-writes.py. Run: python3 hooks/log-gh-writes.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PostToolUse
# JSON on stdin, with CLAUDE_STATE_REPO and HOME pointed at a throwaway dir.
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "log-gh-writes.py"
sys.path.insert(0, str(HOOK.parent))


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

    def git_repo(self, name, origin):
        d = self.home / name
        d.mkdir()
        for args in (["init", "-q", "-b", "main"], ["remote", "add", "origin", origin]):
            subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True)
        return d

    def run_hook(self, cmd, tool="Bash", stdout="", sid="abc123", cwd=None):
        ev = {"tool_name": tool, "session_id": sid, "cwd": str(cwd or self.home),
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

    def test_quoted_empty_or_operator_argument_does_not_split(self):
        for cmd in ('gh pr merge --body "" 5 -R o/r', "gh pr comment -b ';' 5 -R o/r",
                    'gh pr comment -b "&&" 5 -R o/r'):
            self.log.unlink(missing_ok=True)
            r = self.one(cmd)
            self.assertEqual((r["target"], r["repo"]), ("5", "o/r"), cmd)

    def test_dollar_quoted_body(self):
        self.assertEqual(self.one("gh pr comment 2 --body $'a\\nb'")["target"], "2")

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

    def test_graphql_mutation_in_every_field_spelling(self):
        for cmd in ("gh api graphql -fquery='mutation{x}'", "gh api graphql --raw-field=query='mutation{x}'",
                    "gh api graphql -F query=@m.graphql"):
            self.assertEqual(self.one(cmd)["verb"], "api POST", cmd)
            self.log.unlink()
        self.assertEqual(self.run_hook("gh api graphql -fquery='query{viewer{login}}'"), [])

    def test_hash_inside_a_word_is_not_a_comment(self):
        for cmd, verb in (("echo build#12 && gh pr merge 5", "pr merge"),
                          ("gh pr create --title fix#12; gh issue close 3", "pr create"),
                          ("gh issue comment https://github.com/o/r/issues/5#issuecomment-1 -b x", "issue comment")):
            self.assertIn(verb, [r["verb"] for r in self.run_hook(cmd)], cmd)
            self.log.unlink()
        self.assertEqual(self.one("echo a#b && gh pr merge 5")["target"], "5")

    def test_a_real_comment_hides_what_follows_it(self):
        self.assertEqual(self.run_hook("echo hi # gh pr merge 5"), [])
        self.assertEqual(self.one("gh pr merge 5 # gh pr close 6\n")["target"], "5")
        self.log.unlink()
        self.assertEqual(self.one("gh pr comment 7 --body '#8 is fixed' -R o/r")["repo"], "o/r")

    def test_unbalanced_quote_fails_open(self):
        self.assertEqual(self.run_hook("gh pr comment 1 --body 'oops"), [])

    def test_heredoc_opener_line_keeps_the_command(self):
        for cmd, verb, target in (
                ("cat <<'EOF' | gh pr comment 1 -F -\nbody\nEOF", "pr comment", "1"),
                ("cat <<'EOF' | gh issue comment 5 -F -\ngh pr merge 9\nEOF", "issue comment", "5"),
                ("cat <<EOF && gh pr merge 3\nbody\nEOF", "pr merge", "3"),
                ("gh issue create --body-file - <<'EOF'\nbody\nEOF", "issue create", "")):
            r = self.one(cmd)
            self.assertEqual((r["verb"], r["target"]), (verb, target), cmd)
            self.log.unlink()

    def test_short_flag_is_boolean_on_one_verb_and_a_value_on_another(self):
        self.assertEqual(self.one("gh pr merge -r 42")["target"], "42")
        self.log.unlink()
        self.assertEqual(self.one("gh pr review -r -b x 42")["target"], "42")
        self.log.unlink()
        self.assertEqual(self.one("gh pr review -a -c 42")["target"], "42")
        self.log.unlink()
        r = self.one("gh pr create -r alice -m v1 --title t", stdout="https://github.com/o/r/pull/9\n")
        self.assertEqual(r["target"], "https://github.com/o/r/pull/9")

    def test_repo_flag_before_the_verb(self):
        self.assertEqual(self.one("gh pr -R o/r merge 8")["repo"], "o/r")

    def test_push_that_writes_nothing_not_logged(self):
        for cmd in ("git push --dry-run origin b", "git push -n origin b", "git push -fn origin b",
                    "git push --help", "git -C . push --dry-run"):
            self.assertEqual(self.run_hook(cmd), [], cmd)
        self.assertEqual(self.one("git push -u -o ci.skip origin b")["target"], "origin b")

    def test_push_repo_comes_from_the_directory_it_runs_in(self):
        other = self.git_repo("other", "git@github.com:o/other.git")
        self.git_repo("here", "https://github.com/o/here.git")
        for cmd in (f"git -C {other} push origin b", f"cd {other} && git push origin b",
                    f"cd {other}; gh pr merge 1", f"(cd {other} && git push origin b)"):
            r = self.one(cmd, cwd=self.home / "here")
            self.assertEqual(r["repo"], "o/other", cmd)
            self.assertNotIn(")", r["target"], cmd)
            self.log.unlink()
        self.assertEqual(self.one("git push origin b", cwd=self.home / "here")["repo"], "o/here")

    def test_more_write_verbs(self):
        for cmd, verb in (("gh pr update-branch 3", "pr update-branch"), ("gh pr lock 3 -r spam", "pr lock"),
                          ("gh issue transfer 3 o/other", "issue transfer"), ("gh issue pin 3", "issue pin"),
                          ("gh release create v1 --notes x", "release create"),
                          ("gh release upload v1 a.zip", "release upload"),
                          ("gh workflow run ci.yml -f x=1", "workflow run"), ("gh run rerun 9", "run rerun"),
                          ("gh run cancel 9", "run cancel"), ("gh repo archive o/r --yes", "repo archive"),
                          ("gh repo edit o/r --visibility private", "repo edit"),
                          ("gh label clone o/r", "label clone")):
            self.assertEqual(self.one(cmd)["verb"], verb, cmd)
            self.log.unlink()
        for cmd in ("gh release list", "gh run view 9", "gh workflow list", "gh repo view o/r"):
            self.assertEqual(self.run_hook(cmd), [], cmd)

    def test_command_wrapped_in_shell_syntax(self):
        for cmd, target in (("if true; then gh pr merge 1; fi", "1"), ("! gh pr merge 2", "2"),
                            ("(gh pr merge 3)", "3"), ("sudo gh pr merge 4", "4"),
                            ("while true; do gh pr merge 5; done", "5"),
                            ("echo 6 | xargs -I{} gh pr merge {}", "{}"), ("{ gh pr merge 7; }", "7")):
            self.assertEqual(self.one(cmd)["target"], target, cmd)
            self.log.unlink()
        r = self.one("url=$(gh pr create --title t)", stdout="https://github.com/o/r/pull/9\n")
        self.assertEqual(r["target"], "https://github.com/o/r/pull/9")

    def test_no_state_dir_returns_without_raising(self):
        spec = importlib.util.spec_from_file_location("log_gh_writes", HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        import lib_state
        ev = {"tool_name": "Bash", "session_id": "abc123", "tool_input": {"command": "gh pr merge 1"}}
        with mock.patch.object(lib_state, "state_dir", return_value=None), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps(ev))):
            hook.main()  # main() itself, not the wrapper that would swallow a TypeError
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
