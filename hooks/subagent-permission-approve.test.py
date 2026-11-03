#!/usr/bin/env python3
# Tests for subagent-permission-approve.py. Run: python3 hooks/subagent-permission-approve.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PermissionRequest
# JSON on stdin, with XDG_STATE_HOME pointed at a throwaway languette record.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "subagent-permission-approve.py"
ALLOW = {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
SUGGEST = [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "touch:*"}],
            "behavior": "allow", "destination": "localSettings"}]


STUB = "def mask(text, extra=()):\n    return text, 0\n"


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


class SubagentPermissionApproveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name) / "state"
        self.records = self.state / "languette" / "other.jsonl"  # the name world.RECORDS gives
        self.records.parent.mkdir(parents=True)
        repo = Path(self.tmp.name) / "staterepo"
        (repo / ".git").mkdir(parents=True)
        self.log = repo / "state/global/metrics/permission-approvals/ab/abc123.jsonl"
        lang = Path(self.tmp.name) / "languette-stub" / "languette"
        lang.mkdir(parents=True)
        (lang / "__init__.py").write_text("")
        (lang / "record.py").write_text(STUB)
        (lang / "world.py").write_text('RECORDS = "other.jsonl"\n')
        plugins = Path(self.tmp.name) / ".claude" / "plugins"
        plugins.mkdir(parents=True)
        (plugins / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {
            "languette@languette": [{"scope": "user", "installPath": str(lang.parent)}]}}))
        self.env = {**os.environ, "HOME": self.tmp.name, "XDG_STATE_HOME": str(self.state),
                    "CLAUDE_STATE_REPO": str(repo), "PYTHONDONTWRITEBYTECODE": "1"}
        self.env.pop("CLAUDE_CONFIG_DIR", None)

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, verdict, session="abc123", t=None, path=None, tool="Bash", command=None):
        rec = {"v": 1, "t": stamp(time.time() if t is None else t), "session": session,
               "event": "PreToolUse", "tool": tool, "verdict": verdict}
        if command:
            rec["command"] = {"text": command}
        with open(path or self.records, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def verdicts(self):
        if not self.log.exists():
            return []
        return [json.loads(x)["verdict"] for x in self.log.read_text().splitlines()]

    def run_hook(self, agent=True, suggestions=SUGGEST, stdin=None, agent_type=None, mode="default"):
        ev = {"hook_event_name": "PermissionRequest", "session_id": "abc123", "cwd": "/w/repo",
              "permission_mode": mode, "tool_name": "Bash", "tool_input": {"command": "touch x"}}
        if agent:
            ev.update(agent_id="a4aadbe92e02e5780", agent_type="general-purpose")
        if agent_type:
            ev["agent_type"] = agent_type
        if suggestions is not None:
            ev["permission_suggestions"] = suggestions
        r = subprocess.run([sys.executable, str(HOOK)], input=stdin if stdin is not None else json.dumps(ev),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout) if r.stdout.strip() else None

    def test_subagent_rule_request_is_approved(self):
        self.record("silent")
        self.assertEqual(self.run_hook(), ALLOW)
        self.assertEqual(self.verdicts(), ["allow"])

    def test_approved_with_no_languette_record_at_all(self):
        self.records.unlink(missing_ok=True)
        self.assertEqual(self.run_hook(), ALLOW)

    def test_plan_and_accept_edits_modes_are_left_to_the_dialog(self):
        self.assertIsNone(self.run_hook(mode="plan"))
        self.assertIsNone(self.run_hook(mode="acceptEdits"))
        self.assertEqual(self.verdicts(), [])

    def test_another_tools_recent_ask_does_not_hold_it_back(self):
        self.record("ask", tool="Write")
        self.assertEqual(self.run_hook(), ALLOW)

    def test_old_ask_for_the_same_command_holds_it_back(self):
        # a queued dialog can show well after the ask; the command text places it
        self.record("ask", t=time.time() - 60, command="touch x")
        self.assertIsNone(self.run_hook())

    def test_main_session_request_is_left_to_the_dialog(self):
        self.assertIsNone(self.run_hook(agent=False))
        self.assertEqual(self.verdicts(), [])

    def test_main_session_under_agent_flag_is_left_to_the_dialog(self):
        # --agent sets agent_type on the main session but no agent_id (measured, CC 2.1.300)
        self.assertIsNone(self.run_hook(agent=False, agent_type="prober"))

    def test_request_without_suggestions_is_left_alone_as_a_hook_ask(self):
        self.assertIsNone(self.run_hook(suggestions=None))
        self.assertIsNone(self.run_hook(suggestions=[]))
        self.assertEqual(self.verdicts(), ["no-suggestions", "no-suggestions"])

    def test_recent_languette_ask_in_this_session_holds_it_back(self):
        self.record("ask")
        self.assertIsNone(self.run_hook())
        self.assertEqual(self.verdicts(), ["languette-ask"])

    def test_languette_ask_in_the_rotated_file_holds_it_back(self):
        self.record("ask", path=str(self.records) + ".1")
        self.assertIsNone(self.run_hook())

    def test_old_ask_or_another_sessions_ask_does_not(self):
        self.record("ask", t=time.time() - 60)
        self.record("ask", session="other")
        self.assertEqual(self.run_hook(), ALLOW)

    def test_ask_with_an_unreadable_time_holds_it_back(self):
        with open(self.records, "a") as f:
            f.write(json.dumps({"session": "abc123", "tool": "Bash", "verdict": "ask", "t": "soon"}) + "\n")
        self.assertIsNone(self.run_hook())

    def test_garbled_record_lines_are_skipped(self):
        with open(self.records, "a") as f:
            f.write("{not json\n")
        self.assertEqual(self.run_hook(), ALLOW)

    def test_unreadable_record_fails_closed(self):
        self.records.mkdir()  # a directory where the record should be: open() raises
        self.assertIsNone(self.run_hook())

    def test_unwritable_log_still_approves(self):
        self.log.parent.parent.mkdir(parents=True)
        self.log.parent.write_text("")  # a file where the shard directory should be
        self.assertEqual(self.run_hook(), ALLOW)

    def test_malformed_stdin_decides_nothing(self):
        self.assertIsNone(self.run_hook(stdin="not json"))


if __name__ == "__main__":
    unittest.main()
