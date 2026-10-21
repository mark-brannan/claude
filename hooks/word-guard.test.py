#!/usr/bin/env python3
# Tests for word-guard.py. Run: python3 hooks/word-guard.test.py
#
# Cost per push: about a second, a few throwaway git repos; a step in the existing tool-tests job.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "word-guard.py"

CONFIG = {"entries": [
    {"pattern": r"\bZed\b", "action": "deny", "repos": ["acme/*"],
     "exclude_repos": ["acme/notes"], "exclude_paths": ["word-guard.json"], "outward": True,
     "message": "No name."},
    {"pattern": r"\brul(e|ed|ing)\b", "action": "warn", "repos": ["acme/*"],
     "paths": ["*.md"], "outward": True, "message": "Say decided."},
]}


def run(payload, config):
    env = dict(os.environ, WORD_GUARD_CONFIG=config)
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=env, timeout=30)
    return json.loads(r.stdout) if r.stdout.strip() else None


class WordGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.config = str(base / "config.json")
        Path(cls.config).write_text(json.dumps(CONFIG))
        cls.repos = {}
        for slug in ("acme/app", "acme/notes", "other/app"):
            d = base / slug.replace("/", "_")
            d.mkdir()
            subprocess.run(["git", "init", "-q", str(d)], check=True)
            subprocess.run(["git", "-C", str(d), "remote", "add", "origin",
                            f"git@github.com:{slug}.git"], check=True)
            (d / ".gitignore").write_text("ignored/\n")
            cls.repos[slug] = d

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def edit(self, slug, rel, new, old="", event="PreToolUse", tool="Edit"):
        path = str(self.repos[slug] / rel)
        ti = {"file_path": path, "old_string": old, "new_string": new} if tool == "Edit" \
            else {"file_path": path, "content": new}
        return run({"hook_event_name": event, "tool_name": tool, "tool_input": ti,
                    "cwd": str(self.repos[slug])}, self.config)

    def bash(self, slug, cmd, event="PreToolUse"):
        return run({"hook_event_name": event, "tool_name": "Bash", "tool_input": {"command": cmd},
                    "cwd": str(self.repos[slug])}, self.config)

    def decision(self, out):
        return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")

    # --- deny entries, PreToolUse ---------------------------------------
    def test_name_added_in_code_is_denied(self):
        out = self.edit("acme/app", "src/a.js", "// decided by Zed")
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("No name.", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_write_is_denied(self):
        self.assertEqual(self.decision(self.edit("acme/app", "new/b.md", "Zed said", tool="Write")), "deny")

    def test_kept_hit_is_not_new(self):
        self.assertIsNone(self.edit("acme/app", "a.md", "Zed said yes.", old="Zed said no."))

    def test_case_insensitive_by_default(self):
        self.assertEqual(self.decision(self.edit("acme/app", "a.md", "zed")), "deny")

    def test_word_boundary(self):
        self.assertIsNone(self.edit("acme/app", "a.md", "Zedonk"))

    def test_excluded_repo(self):
        self.assertIsNone(self.edit("acme/notes", "a.md", "Zed"))

    def test_other_owner(self):
        self.assertIsNone(self.edit("other/app", "a.md", "Zed"))

    def test_excluded_path(self):
        self.assertIsNone(self.edit("acme/app", "word-guard.json", "Zed"))

    def test_ignored_file(self):
        self.assertIsNone(self.edit("acme/app", "ignored/x.md", "Zed"))

    def test_outside_any_repo(self):
        out = run({"hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": "/nonexistent-dir/x.md", "content": "Zed"}}, self.config)
        self.assertIsNone(out)

    def test_commit_message_denied(self):
        self.assertEqual(self.decision(self.bash("acme/app", 'git commit -m "per Zed"')), "deny")

    def test_pr_body_denied(self):
        out = self.bash("acme/app", "cd x && gh pr create --body 'Zed wants it'")
        self.assertEqual(self.decision(out), "deny")

    def test_other_bash_ignored(self):
        self.assertIsNone(self.bash("acme/app", "grep -rn Zed ."))

    def test_mcp_write_denied(self):
        out = run({"hook_event_name": "PreToolUse", "tool_name": "mcp__github-pat__create_pull_request",
                   "tool_input": {"owner": "acme", "repo": "app", "title": "t", "body": "for Zed"}},
                  self.config)
        self.assertEqual(self.decision(out), "deny")

    def test_mcp_read_ignored(self):
        out = run({"hook_event_name": "PreToolUse", "tool_name": "mcp__github-pat__search_code",
                   "tool_input": {"owner": "acme", "repo": "app", "query": "Zed"}}, self.config)
        self.assertIsNone(out)

    # --- warn entries, PostToolUse --------------------------------------
    def test_warn_in_markdown(self):
        out = self.edit("acme/app", "docs/d.md", "Ruled on Tuesday.", event="PostToolUse")
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Ruled", ctx)
        self.assertIn("Say decided.", ctx)
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])

    def test_warn_skips_code(self):
        self.assertIsNone(self.edit("acme/app", "s.css", "a css rule", event="PostToolUse"))

    def test_warn_not_raised_pre(self):
        self.assertIsNone(self.edit("acme/app", "docs/d.md", "ruled"))

    def test_deny_not_raised_post(self):
        self.assertIsNone(self.edit("acme/app", "a.md", "Zed", event="PostToolUse"))

    def test_repo_config_adds_entries(self):
        d = self.repos["other/app"]
        (d / ".claude").mkdir(exist_ok=True)
        (d / ".claude" / "word-guard.json").write_text(json.dumps(
            {"entries": [{"pattern": "banana", "action": "deny"}]}))
        try:
            self.assertEqual(self.decision(self.edit("other/app", "x.py", "banana")), "deny")
        finally:
            (d / ".claude" / "word-guard.json").unlink()

    def test_garbage_input_is_silent(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
