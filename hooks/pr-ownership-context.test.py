#!/usr/bin/env python3
"""Tests for pr-ownership-context.py. Run: python3 hooks/pr-ownership-context.test.py

What matters: it fires on PR-shaped calls and nothing else, exactly once per
session, emits valid JSON whatever the rules file contains, records the PR a
call touched (and whether it read or worked it) for the Stop gate, and says so
out loud when the rules file or the heading is missing instead of going quiet.

The hook reads commands through the languette plugin's scanner: the user-scope
install this machine's installed_plugins.json records (ci.yml clones languette
and records it). The scratch HOME's installed_plugins.json points there.

Cost per push: about 90 hook runs of ~100 ms each, a few seconds.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "pr-ownership-context.py"

REAL_PLUGINS = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "plugins" / "installed_plugins.json"


def real_languette():
    try:
        for key, installs in json.loads(REAL_PLUGINS.read_text())["plugins"].items():
            if key.startswith("languette@"):
                for i in installs:
                    if i.get("scope") == "user":
                        return i["installPath"]
    except (OSError, ValueError, KeyError):
        pass
    return ""


ROOT = real_languette()
RULES = (
    "# Code\n\n## Git\n\n- git stuff, not wanted\n\n"
    "## PR ownership: never red\n\n"
    '- **Green before it is handed over.** Quoted "text", a `backtick`, a\ttab and a \\backslash.\n'
    '- **"Resolve conversation" is mine to do.**\n\n'
    "### A board-only PR merges itself\n\nSub-heading stays inside the section.\n"
    "CRLF\r\n\fformfeed\n"  # real control bytes, before the next ## heading
    "\n## Provisional until decided\n\n- must not be injected\n"
)


def bash(sid, cmd, **extra):
    return {"session_id": sid, "tool_name": "Bash", "tool_input": {"command": cmd}, **extra}


def mcp(sid, tool, tool_input=None):
    return {"session_id": sid, "tool_name": tool, "tool_input": tool_input or {}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home, self.tmpdir = root / "home", root / "tmp"
        for d in (self.home / ".claude/rules", self.home / ".claude/plugins", self.tmpdir):
            d.mkdir(parents=True)
        self.rules = self.home / ".claude/rules/code.md"
        self.rules.write_bytes(RULES.encode())
        self.plugins = self.home / ".claude/plugins/installed_plugins.json"
        self.plugin_at(ROOT)
        self.env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        self.env.update(HOME=str(self.home), TMPDIR=str(self.tmpdir))

    def plugin_at(self, path):
        self.plugins.write_text(json.dumps(
            {"version": 2, "plugins": {"languette@languette": [{"scope": "user", "installPath": str(path)}]}}))

    def run_hook(self, payload):
        """The hook's stdout for a payload (a dict, or raw text); stderr must be empty."""
        data = payload if isinstance(payload, str) else json.dumps(payload)
        r = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=self.env)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        return r.stdout

    def context(self, payload):
        """The injected text, or None when the hook was silent."""
        out = self.run_hook(payload)
        if not out:
            return None
        return json.loads(out)["hookSpecificOutput"]["additionalContext"]

    def inject(self, payload, desc=""):
        text = self.context(payload)
        self.assertIsNotNone(text, f"want inject: {desc}")
        return text

    def silent(self, payload, desc=""):
        self.assertIsNone(self.context(payload), f"want silent: {desc}")

    def record(self, sid):
        p = self.tmpdir / f"claude-pr-threads.{sid}"
        return p.read_text().splitlines() if p.exists() else []

    def last(self, sid):
        rows = self.record(sid)
        return rows[-1] if rows else ""


def setUpModule():
    r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "languette", "__main__.py"), "scan"],
                       input="x", capture_output=True, text=True) if ROOT else None
    if not r or r.returncode:
        raise SystemExit(f"FAIL: no languette with `scan` at '{ROOT}' (install the languette plugin)")


class Fires(Base):
    def test_output_shape_and_section(self):
        out = json.loads(self.run_hook(bash("s1", "gh pr view 12 --comments")))
        h = out["hookSpecificOutput"]
        self.assertEqual((h["hookEventName"], h["permissionDecision"]), ("PreToolUse", "allow"))
        text = h["additionalContext"]
        self.assertIn("\n## PR ownership", "\n" + text)
        self.assertIn('Quoted "text", a `backtick`, a\ttab and a \\backslash', text)
        self.assertIn("\n### A board-only PR", text)  # a sub-heading stays in the section
        self.assertIn("\nCRLF\r\n", text)  # a CR survives, as JSON
        self.assertIn("formfeed", text)
        self.assertNotIn("must not be injected", text)  # the next ## section
        self.assertNotIn("git stuff", text)  # the earlier section
        self.assertIn("injected once per session by pr-ownership-context.py", text)

    def test_fires_on(self):
        cases = [
            ("gh api graphql", "gh api graphql -f query='{repository{pullRequest{reviewThreads}}}'"),
            ("gh api pulls", "gh api repos/o/r/pulls/4/comments"),
            ("gh pr after &&", "git push && gh pr checks --watch"),
            ("mergify stack push", "mergify stack push"),
            ("mergify stack checkout", "mergify stack checkout NAME"),
            ("mergify stack sync", "mergify stack sync"),
            ("mergify queue add", "mergify queue add"),
            ("mergify merge", "mergify merge 12"),
            ("git push", "git push origin HEAD"),
            ("git push -u after &&", "git fetch origin && git push -u origin HEAD"),
            ("yadm push", "yadm push"),
            ("mergify after &&", "git push && mergify stack push"),
            ("mergify after pipe", "echo x | mergify queue add"),
            ("gh pr inside sh -c", "sh -c 'gh pr view 5 -R o/r'"),
            ("real call beside prose", "cat <<EOF\ngh pr view 9 -R x/y\nEOF\ngh pr comment 7 -R o/r --body ok"),
        ]
        for i, (desc, cmd) in enumerate(cases):
            with self.subTest(desc):
                self.inject(bash(f"f{i}", cmd), desc)

    def test_fires_on_mcp(self):
        self.inject(mcp("m1", "mcp__plugin_github_github__pull_request_read"), "pull_request_read")
        self.inject(mcp("m2", "mcp__github__create_pending_pull_request_review"), "review tool")


class Silent(Base):
    def test_silent_on(self):
        cases = [
            ("gh issue", "gh issue view 3"),
            ("git status", "git status"),
            ("git commit msg names git push", 'git commit -m "fix: say why git push is blocked"'),
            ("heredoc names git push", "cat > note.md <<EOF\nrun git push origin HEAD\nEOF"),
            ("echo git push", "echo git push"),
            ("gh api unrelated", "gh api user"),
            ("word ending in gh", "high pr"),
            ("mergify config command", "mergify config validate"),
            ("mergify events command", "mergify events list"),
            ("word containing mergify", "echo unmergifyable"),
            ("mergify named, not run (echo)", "echo mergify merge"),
            ("mergify named, not run (comment)", "true # mergify merge"),
            ("gh pr in a heredoc body", "cat > card.md <<EOF\nrun gh pr view 5 -R o/r first\nEOF"),
            ("gh pr in a commit message", 'git commit -m "fix the gh pr view 5 -R o/r call"'),
            ("gh pr echoed", "echo gh pr view 5"),
        ]
        for i, (desc, cmd) in enumerate(cases):
            with self.subTest(desc):
                self.silent(bash(f"q{i}", cmd), desc)
        # Prose names a command without running it: no record either.
        self.assertEqual([self.record(f"q{i}") for i in (12, 13, 14)], [[], [], []])

    def test_silent_on_tools(self):
        self.silent(mcp("t1", "mcp__github__search_repositories"), "MCP non-PR github")
        self.silent(mcp("t2", "mcp__Trello__pull_request_read"), "MCP other server")
        self.silent({"session_id": "t3", "tool_name": "Read", "tool_input": {"file_path": "gh pr"}}, "other tool")
        self.silent("", "empty payload")
        self.silent("not json", "malformed payload")
        self.silent({"session_id": "t4"}, "no tool name")


class Records(Base):
    def test_mergify_records_cwd(self):
        self.inject(bash("s5f", "mergify stack push", cwd="/repo/checkout"))
        self.assertEqual(self.record("s5f"), ["cwd\t/repo/checkout"])

    def test_compound_call_does_not_fabricate_a_pair(self):
        # 2026-09-08: repo and number were each pulled from the whole command,
        # so one gh call's repo could pair with another's number.
        self.inject(bash("cx1", "gh api repos/o/r/issues/73 --jq '.state' 2>&1; echo ---; "
                                "gh api repos/o/r/pulls/80 --jq '.state' 2>&1"))
        self.assertEqual(self.last("cx1"), "repo\to/r\t80\tread")  # the PR clause, not the issue
        self.inject(bash("cx2", "gh pr view 73 -R mark-brannan/dotfiles --json state 2>&1; echo ---; "
                                "gh pr view 80 -R markbrannan/dotfiles --json state 2>&1"))
        self.assertEqual(self.last("cx2"), "repo\tmark-brannan/dotfiles\t73\tread")  # first clause intact

    def test_real_call_beside_prose_records_the_call(self):
        self.inject(bash("p3", "cat <<EOF\ngh pr view 9 -R x/y\nEOF\ngh pr comment 7 -R o/r --body ok"))
        self.assertEqual(self.last("p3"), "repo\to/r\t7\twork")

    def test_read_vs_work(self):
        # dotfiles#224: a bare view/checks/diff/list, or a non-mutating gh api
        # call, is a read; anything else naming `gh pr`, a mutating api call
        # or gh-resolve-thread is work.
        cases = [
            ("gh pr view", "gh pr view 25 -R o/r --comments", "repo\to/r\t25\tread"),
            ("gh pr checks", "gh pr checks 25 -R o/r", "repo\to/r\t25\tread"),
            ("gh pr comment", "gh pr comment 25 -R o/r --body hi", "repo\to/r\t25\twork"),
            ("gh pr merge", "gh pr merge 25 -R o/r --squash", "repo\to/r\t25\twork"),
            ("gh pr close: unrecognized subcommand fails closed", "gh pr close 25 -R o/r", "repo\to/r\t25\twork"),
            ("gh api GET on pulls", "gh api repos/o/r/pulls/25/comments", "repo\to/r\t25\tread"),
            ("gh api -X PATCH on pulls", "gh api repos/o/r/pulls/25 -X PATCH -f state=closed", "repo\to/r\t25\twork"),
            ("read then work on one PR upgrades to work",
             'gh pr diff 42 -R o/r --patch; gh pr comment 42 -R o/r --body "fixed in latest push"',
             "repo\to/r\t42\twork"),
            ("work then read on one PR stays work",
             "gh pr comment 42 -R o/r --body hi; gh pr diff 42 -R o/r --patch", "repo\to/r\t42\twork"),
            ("work on a different PR never contributes",
             "gh pr view 42 -R o/r; gh pr comment 99 -R o/r --body hi", "repo\to/r\t42\tread"),
            ("repo from a URL in a gh api call", "gh api https://github.com/o/r/pulls/8", "repo\to/r\t8\tread"),
            ("graphql mutation", "gh api graphql -f query='mutation (x) {y}' -R o/r", "cwd\t/w"),
        ]
        for i, (desc, cmd, want) in enumerate(cases):
            with self.subTest(desc):
                self.inject(bash(f"rw{i}", cmd, cwd="/w"))
                self.assertEqual(self.last(f"rw{i}"), want)

    def test_gh_resolve_thread_records_cwd(self):
        self.inject(bash("rw8", "gh-resolve-thread PRRT_abc", cwd="/repo/checkout"))
        self.assertEqual(self.last("rw8"), "cwd\t/repo/checkout")

    def test_no_pr_and_no_cwd_records_nothing(self):
        self.inject(bash("nc1", "gh pr list"))
        self.assertEqual(self.record("nc1"), [])

    def test_mcp_records(self):
        self.inject(mcp("rw9", "mcp__github__pull_request_read", {"owner": "o", "repo": "r", "pullNumber": 9}))
        self.assertEqual(self.last("rw9"), "repo\to/r\t9\tread")
        self.inject(mcp("rw10", "mcp__github__merge_pull_request", {"owner": "o", "repo": "r", "pullNumber": 10}))
        self.assertEqual(self.last("rw10"), "repo\to/r\t10\twork")
        self.inject(mcp("rw11", "mcp__github__get_review", {"owner": "o", "repo": "r", "pull_number": 11}))
        self.assertEqual(self.last("rw11"), "repo\to/r\t11\tread")
        self.inject(mcp("rw12", "mcp__github__create_pull_request_review", {"owner": "o"}))
        self.assertEqual(self.record("rw12"), [])  # no repo or number: nothing to record

    def test_session_id_becomes_a_safe_file_name(self):
        self.inject(bash("a/b c", "gh pr comment 7 -R o/r --body ok"))
        self.assertEqual(self.last("a_b_c"), "repo\to/r\t7\twork")


class NoScanner(Base):
    """No scanner: the raw command, over-matched, never silence."""

    def check(self, sid, cmd):
        self.inject(bash(sid, cmd), cmd)

    def test_no_plugin_file(self):
        self.plugins.unlink()
        self.check("nf1", "echo gh pr view 5")  # over-matches
        self.check("nf2", "gh pr comment 7 -R o/r --body ok")
        self.assertEqual(self.last("nf2"), "repo\to/r\t7\twork")  # the record still names the PR

    def test_gone_install_path(self):
        self.plugin_at(Path(self.tmp.name) / "nowhere")
        self.check("nf3", "echo gh pr view 5")

    def test_plugin_without_scan(self):
        old = Path(self.tmp.name) / "old"
        (old / "languette").mkdir(parents=True)
        (old / "languette/__main__.py").write_text("import sys\nsys.exit(2)\n")
        self.plugin_at(old)
        self.check("nf4", "echo gh pr view 5")

    def test_only_project_scope_install(self):
        self.plugins.write_text(json.dumps({"version": 2, "plugins": {
            "languette@languette": [{"scope": "project", "installPath": str(ROOT)}]}}))
        self.check("nf5", "echo gh pr view 5")

    def test_config_dir_is_honoured(self):
        cfg = Path(self.tmp.name) / "cfg"
        (cfg / "plugins").mkdir(parents=True)
        self.plugins.rename(cfg / "plugins/installed_plugins.json")
        self.env["CLAUDE_CONFIG_DIR"] = str(cfg)
        self.silent(bash("nf6", "echo gh pr view 5"), "scanner found through CLAUDE_CONFIG_DIR")


class OncePerSession(Base):
    def test_once_per_session(self):
        self.inject(bash("s8", "gh pr view"))
        self.silent(bash("s8", "gh pr checks"))
        self.inject(bash("s9", "gh pr view"))

    def test_the_record_keeps_growing_after_the_text_stops(self):
        self.inject(bash("s12", "gh pr view 1 -R o/r"))
        self.silent(bash("s12", "gh pr comment 2 -R o/r --body x"))
        self.assertEqual(self.record("s12"), ["repo\to/r\t1\tread", "repo\to/r\t2\twork"])

    def test_no_session_id_always_fires(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr list"}}
        self.inject(payload)
        self.inject(payload)
        self.assertEqual(list(self.tmpdir.iterdir()), [])  # no record, no marker


class FailureIsLoud(Base):
    def test_heading_missing(self):
        self.rules.write_text(RULES.replace("## PR ownership", "## Something else"))
        self.assertIn("no '## PR ownership' heading", self.inject(bash("s10", "gh pr view")))

    def test_file_missing(self):
        self.rules.unlink()
        self.assertIn("code.md is missing", self.inject(bash("s11", "gh pr view")))

    def test_section_at_end_of_file(self):
        self.rules.write_text("## PR ownership\n- last\n\n\n")
        self.assertTrue(self.inject(bash("s13", "gh pr view")).endswith("\n\n## PR ownership\n- last"))

    def test_unwritable_tmp_still_injects(self):
        self.env["TMPDIR"] = str(self.tmpdir / "gone")
        self.assertIn("## PR ownership", self.inject(bash("s14", "gh pr view 1 -R o/r")))

    def test_invalid_utf8_in_rules_is_still_valid_json(self):
        self.rules.write_bytes(b"## PR ownership\n- bad \xff byte\n")
        self.assertIn("bad \ufffd byte", self.inject(bash("s15", "gh pr view")))


if __name__ == "__main__":
    unittest.main()
