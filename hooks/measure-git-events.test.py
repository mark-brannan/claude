#!/usr/bin/env python3
# Tests for measure-git-events.py. Run: python3 hooks/measure-git-events.test.py
#
# Cost per push: about a second, a step in CI's existing tool-tests job. Each
# case runs the hook as Claude Code does, a subprocess fed PostToolUse JSON on
# stdin, with CLAUDE_STATE_REPO and HOME pointed at a throwaway dir and the
# event's cwd set to a throwaway git repo.
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "measure-git-events.py"
CREATE_PR = "mcp__github__create_pull_request"


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false",
                        "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


class MeasureGitEventsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        state = self.home / "state"
        (state / ".git").mkdir(parents=True)
        self.events = state / "state/global/metrics/git-events"
        self.log = self.events / "ab/abc123.jsonl"
        self.env = {**os.environ, "HOME": str(self.home), "CLAUDE_STATE_REPO": str(state),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        self.repo = self.home / "myrepo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a").write_text("a\n")
        git(self.repo, "add", "a")
        git(self.repo, "commit", "-q", "-m", "first")

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, ev):
        r = subprocess.run([sys.executable, str(HOOK)], input=ev if isinstance(ev, str) else json.dumps(ev),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        return r

    def rows(self, path=None):
        path = path or self.log
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def run_hook(self, cmd, cwd=None, sid="abc123", tool="Bash"):
        ev = {"tool_name": tool, "cwd": str(cwd or self.repo), "tool_input": {"command": cmd}}
        if sid is not None:
            ev["session_id"] = sid
        self.send(ev)
        return self.rows()

    def one(self, cmd, **kw):
        rows = self.run_hook(cmd, **kw)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_mcp_create_pull_request(self):
        self.send({"tool_name": CREATE_PR, "session_id": "abc123", "cwd": str(self.home),
                   "tool_input": {"repo": "o/r", "head": "feat", "base": "main",
                                  "title": "T", "draft": True}})
        (r,) = self.rows()
        self.assertRegex(r.pop("ts"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(r, {"session_id": "abc123", "kind": "pr", "repo": "o/r", "branch": "feat",
                             "title": "T", "base": "main", "draft": True})

    def test_mcp_create_pull_request_with_no_optional_fields(self):
        self.send({"tool_name": CREATE_PR, "session_id": "abc123", "tool_input": {}})
        (r,) = self.rows()
        self.assertEqual((r["repo"], r["branch"], r["title"], r["base"], r["draft"]), ("", "", "", "", False))

    def test_keys_are_in_a_stable_order(self):
        self.send({"tool_name": CREATE_PR, "session_id": "abc123", "tool_input": {"title": "T"}})
        line = self.log.read_text().rstrip("\n")
        self.assertEqual(list(json.loads(line)),
                         ["ts", "session_id", "kind", "repo", "branch", "title", "base", "draft"])
        self.assertNotIn(": ", line)

    def test_other_tools_log_nothing(self):
        for tool in ("Edit", "mcp__github__merge_pull_request", ""):
            self.assertEqual(self.run_hook("git checkout -b x", tool=tool), [])

    def test_commands_that_are_not_git_events_log_nothing(self):
        for cmd in ("ls -la", "echo hello", "git status", "git log --oneline", "gh pr view 3",
                    "git branch -d old", "git branch -D old", "git branch -m new", "git branch --list",
                    "git branch -a", "git branch", "git checkout main", "git switch main"):
            self.assertEqual(self.run_hook(cmd), [], cmd)

    def test_branch_created_by_each_form(self):
        for cmd, name in (("git checkout -b feat/one", "feat/one"),
                          ("git switch -c feat/two", "feat/two"),
                          ("git worktree add -b feat/three ../wt", "feat/three"),
                          ("git branch feat/four", "feat/four"),
                          ("cd x && git checkout -b feat/five && git push", "feat/five"),
                          ("git branch feat/six origin/main", "feat/six")):
            self.log.unlink(missing_ok=True)
            r = self.one(cmd)
            self.assertEqual((r["kind"], r["created_branch"], r["repo"], r["branch"]),
                             ("branch", name, "myrepo", "main"), cmd)

    def test_branch_name_ends_at_a_shell_operator(self):
        for cmd in ("git checkout -b feat;ls", "git checkout -b feat&&ls", "git checkout -b feat|cat"):
            self.log.unlink(missing_ok=True)
            self.assertEqual(self.one(cmd)["created_branch"], "feat", cmd)

    def test_branch_recorded_is_the_one_checked_out_now(self):
        git(self.repo, "checkout", "-q", "-b", "feat/now")
        r = self.one("git checkout -b feat/now")
        self.assertEqual((r["created_branch"], r["branch"]), ("feat/now", "feat/now"))

    def test_gh_pr_create(self):
        r = self.one("gh pr create --title t --body b")
        self.assertEqual((r["kind"], r["title"], r["base"], r["draft"], r["repo"], r["branch"]),
                         ("pr", "", "", False, "myrepo", "main"))

    def test_gh_pr_create_draft(self):
        for cmd in ("gh pr create --draft", "gh pr create --title t --draft --body b",
                    "gh pr create --body b --draft"):
            self.log.unlink(missing_ok=True)
            self.assertTrue(self.one(cmd)["draft"], cmd)

    def test_draft_flag_must_be_a_whole_word(self):
        self.assertFalse(self.one("gh pr create --draft-ish")["draft"])

    def test_pr_and_branch_in_one_command(self):
        rows = self.run_hook("git checkout -b feat/x && gh pr create --draft")
        self.assertEqual([(r["kind"], r.get("created_branch"), r.get("draft")) for r in rows],
                         [("pr", None, True), ("branch", "feat/x", None)])

    def test_outside_a_git_repo_logs_nothing(self):
        plain = self.home / "plain"
        plain.mkdir()
        self.assertEqual(self.run_hook("git checkout -b x", cwd=plain), [])

    def test_missing_or_empty_cwd_logs_nothing(self):
        self.assertEqual(self.run_hook("git checkout -b x", cwd=self.home / "gone"), [])
        self.send({"tool_name": "Bash", "session_id": "abc123", "cwd": "",
                   "tool_input": {"command": "git checkout -b x"}})
        self.send({"tool_name": "Bash", "session_id": "abc123",
                   "tool_input": {"command": "git checkout -b x"}})
        self.assertEqual(self.rows(), [])

    def test_repo_is_the_toplevel_name_from_a_subdirectory(self):
        sub = self.repo / "deep/er"
        sub.mkdir(parents=True)
        self.assertEqual(self.one("git checkout -b x", cwd=sub)["repo"], "myrepo")

    def test_cherry_pick_is_logged_from_the_commit_trailer(self):
        git(self.repo, "checkout", "-q", "-b", "other")
        (self.repo / "b").write_text("b\n")
        git(self.repo, "add", "b")
        git(self.repo, "commit", "-q", "-m", "second")
        original = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "main")
        git(self.repo, "cherry-pick", "-x", original)
        picked = git(self.repo, "rev-parse", "HEAD")
        r = self.one(f"git cherry-pick -x {original}")
        self.assertEqual((r["kind"], r["commit"], r["original_commit"], r["branch"]),
                         ("cherry_pick", picked, original, "main"))
        self.assertNotEqual(picked, original)

    def test_commit_finishing_a_pick_counts_but_a_plain_commit_does_not(self):
        (self.repo / "c").write_text("c\n")
        git(self.repo, "add", "c")
        git(self.repo, "commit", "-q", "-m", "plain")
        self.assertEqual(self.run_hook("git commit -m plain"), [])
        git(self.repo, "commit", "-q", "--allow-empty", "-m",
            "picked\n\n(cherry picked from commit abc123def)")
        r = self.one("git commit -m picked")
        self.assertEqual((r["kind"], r["original_commit"]), ("cherry_pick", "abc123def"))

    def test_same_cherry_pick_is_not_counted_twice(self):
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "p\n\n(cherry picked from commit abc123def)")
        self.run_hook("git commit -m p")
        self.run_hook("git checkout main")
        rows = self.rows()
        self.assertEqual([r["kind"] for r in rows], ["cherry_pick"])
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "q\n\n(cherry picked from commit 0123abc)")
        self.run_hook("git commit -m q")
        self.assertEqual([r["original_commit"] for r in self.rows()], ["abc123def", "0123abc"])

    def test_a_branch_row_between_picks_does_not_hide_the_dedupe(self):
        git(self.repo, "commit", "-q", "--allow-empty", "-m", "p\n\n(cherry picked from commit abc123def)")
        self.run_hook("git commit -m p")
        self.run_hook("git branch foo")
        self.assertEqual([r["kind"] for r in self.rows()], ["cherry_pick", "branch"])

    def test_session_id_defaults_to_unknown(self):
        self.run_hook("git checkout -b x", sid=None)
        (r,) = self.rows(self.events / "un/unknown.jsonl")
        self.assertEqual(r["session_id"], "unknown")

    def test_a_flat_file_written_before_the_shard_split_is_appended_to(self):
        self.events.mkdir(parents=True)
        flat = self.events / "abc123.jsonl"
        flat.write_text('{"kind":"old"}\n')
        self.run_hook("git checkout -b x")
        self.assertEqual([r["kind"] for r in self.rows(flat)], ["old", "branch"])
        self.assertFalse(self.log.exists())

    def test_unparsable_input_logs_nothing_and_exits_zero(self):
        for text in ("", "not json", "[]", "null"):
            self.send(text)
        self.assertEqual(self.rows(), [])

    def test_a_swallowed_error_is_traced_to_hook_errors(self):
        self.events.parent.mkdir(parents=True)
        self.events.write_text("a file where the events directory should be\n")
        r = self.send({"tool_name": CREATE_PR, "session_id": "abc123", "tool_input": {}})
        self.assertEqual(r.stderr, "")
        row = json.loads((self.events.parent / "hook-errors/ab/abc123.jsonl").read_text())
        self.assertEqual((row["hook"], row["stage"], row["session_id"]), ("measure-git-events", "main", "abc123"))

    def test_a_failed_write_reaches_stderr_and_does_not_block(self):
        (self.home / "state/state").write_text("a file where the state dir should be\n")
        r = self.send({"tool_name": CREATE_PR, "session_id": "abc123", "tool_input": {}})
        self.assertRegex(r.stderr, r"measure-git-events")


if __name__ == "__main__":
    unittest.main()
