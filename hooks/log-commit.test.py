#!/usr/bin/env python3
# Tests for log-commit.py. Run: python3 hooks/log-commit.test.py
#
# Cost per push: about a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PostToolUse
# JSON on stdin, with HOME pointed at a throwaway dir. LOG_COMMIT_HOOK names
# another script to drive through the same command line (the parity run
# against the old shell hook used it); a .sh runs under bash.
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("LOG_COMMIT_HOOK") or Path(__file__).resolve().parent / "log-commit.py").resolve()
KEYS = ["ts", "session_id", "remote_session_id", "repo", "branch", "commit", "claude_code_version"]


class LogCommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CLAUDE_", "GIT_"))}
        self.env.update(HOME=str(self.home), GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
        self.state = self.home / "claude_prompts_scratch"
        (self.state / ".git").mkdir(parents=True)
        self.log = self.state / "state/global/commits.jsonl"
        self.repo = self.home / "work" / "myrepo"
        self.repo.mkdir(parents=True)
        self.git("init", "-q", "-b", "feature")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, cwd=None):
        return subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True,
                              capture_output=True, text=True, env=self.env)

    def run_hook(self, cmd="git commit -m x", tool="Bash", cwd=None, sid="sess-1", extra_env=None, raw=None, event=None):
        ev = event if event is not None else {"tool_name": tool, "cwd": str(self.repo if cwd is None else cwd),
                                              "tool_input": {"command": cmd}}
        if sid is not None and event is None:
            ev["session_id"] = sid
        argv = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        r = subprocess.run(argv, input=raw if raw is not None else json.dumps(ev),
                           capture_output=True, text=True, env={**self.env, **(extra_env or {})})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", "the hook prints nothing to the model")
        return r

    def rows(self, log=None):
        log = log or self.log
        return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    def test_commit_is_logged(self):
        self.run_hook()
        (row,) = self.rows()
        self.assertEqual(list(row), KEYS)
        self.assertEqual((row["session_id"], row["repo"], row["branch"], row["commit"]),
                         ("sess-1", "myrepo", "feature", self.head))
        self.assertRegex(row["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((row["remote_session_id"], row["claude_code_version"]), ("", ""))

    def test_line_is_compact_json(self):
        self.run_hook()
        line = self.log.read_text()
        self.assertTrue(line.endswith("}\n") and line.count("\n") == 1)
        self.assertIsNone(re.search(r'[,:] ', line))

    def test_non_ascii_branch_survives_a_c_locale(self):
        self.git("checkout", "-q", "-b", "feat/caf\u00e9")
        self.run_hook(extra_env={"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"})
        (row,) = self.rows()
        self.assertEqual(row["branch"], "feat/caf\u00e9")

    def test_remote_session_and_version_come_from_env(self):
        self.run_hook(extra_env={"CLAUDE_CODE_REMOTE_SESSION_ID": "remote-9", "CLAUDE_CODE_VERSION": "9.9.9"})
        (row,) = self.rows()
        self.assertEqual((row["remote_session_id"], row["claude_code_version"]), ("remote-9", "9.9.9"))

    def test_session_id_falls_back_to_env(self):
        self.run_hook(sid=None, extra_env={"CLAUDE_CODE_SESSION_ID": "env-sess"})
        self.assertEqual(self.rows()[0]["session_id"], "env-sess")

    def test_payload_session_id_beats_env(self):
        self.run_hook(extra_env={"CLAUDE_CODE_SESSION_ID": "env-sess"})
        self.assertEqual(self.rows()[0]["session_id"], "sess-1")

    def test_commit_in_a_longer_command(self):
        for cmd in ("git add f && git commit -m x", "cd /tmp && git -C . commit --amend"):
            with self.subTest(cmd=cmd):
                self.log.unlink(missing_ok=True)
                self.run_hook(cmd)
                self.assertEqual(len(self.rows()), 1)

    def test_commands_that_did_not_commit(self):
        for cmd in ("git status", "git log --oneline", "echo commit", "gitcommit", "git add .", "ls",
                    "git\ncommit"):  # the match is per line, as grep's was
            with self.subTest(cmd=cmd):
                self.run_hook(cmd)
                self.assertEqual(self.rows(), [])

    def test_other_tools_are_ignored(self):
        self.run_hook(tool="Edit")
        self.run_hook(tool="mcp__github__push_files")
        self.assertEqual(self.rows(), [])

    def test_no_cwd_or_missing_cwd_or_not_a_repo(self):
        self.run_hook(event={"tool_name": "Bash", "tool_input": {"command": "git commit"}})
        self.run_hook(cwd=self.home / "nope")
        plain = self.home / "plain"
        plain.mkdir()
        self.run_hook(cwd=plain)
        self.assertEqual(self.rows(), [])

    def test_no_commit_yet_logs_nothing(self):
        fresh = self.home / "fresh"
        fresh.mkdir()
        self.git("init", "-q", cwd=fresh)
        self.run_hook(cwd=fresh)
        self.assertEqual(self.rows(), [])

    def test_subdirectory_names_the_toplevel(self):
        sub = self.repo / "a" / "b"
        sub.mkdir(parents=True)
        self.run_hook(cwd=sub)
        self.assertEqual(self.rows()[0]["repo"], "myrepo")

    def test_detached_head_branch_is_HEAD(self):
        self.git("checkout", "-q", "--detach")
        self.run_hook()
        self.assertEqual(self.rows()[0]["branch"], "HEAD")

    def test_appends_one_line_per_call(self):
        self.run_hook()
        self.run_hook()
        self.assertEqual(len(self.rows()), 2)

    def test_a_swallowed_error_is_traced_not_sent_to_stderr(self):
        self.log.mkdir(parents=True)  # the append fails: commits.jsonl is a directory
        r = self.run_hook()
        self.assertEqual(r.stderr, "")
        (path,) = self.log.parent.glob("metrics/hook-errors/*/sess-1.jsonl")
        row = json.loads(path.read_text())
        self.assertEqual((row["hook"], row["stage"], row["event"], row["session_id"]),
                         ("log-commit", "main", "PostToolUse", "sess-1"))
        self.assertIn("Directory", row["error"])

    def test_malformed_input_is_harmless(self):
        for raw in ("", "not json", "[]", "{}"):
            with self.subTest(raw=raw):
                self.run_hook(raw=raw)
        self.assertEqual(self.rows(), [])

    def test_without_state_repo_falls_back_under_dot_claude(self):
        (self.state / ".git").rmdir()
        self.run_hook()
        found = list((self.home / ".claude").rglob("commits.jsonl"))
        self.assertEqual(len(found), 1, found)
        self.assertEqual(len(self.rows(found[0])), 1)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main()
