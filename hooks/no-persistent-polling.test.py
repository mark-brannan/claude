#!/usr/bin/env python3
# Tests for no-persistent-polling.py. Run: python3 hooks/no-persistent-polling.test.py
#
# Cost per push: well under a second, a step in CI's Python test suites.
# NO_PERSISTENT_POLLING_HOOK names another script to drive through the same
# command line (the parity run against the old shell hook used it; a .sh runs
# under bash).
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("NO_PERSISTENT_POLLING_HOOK")
            or Path(__file__).resolve().parent / "no-persistent-polling.py").resolve()


def run(payload, hook=HOOK, env=None):
    cmd = ["bash", str(hook)] if hook.suffix == ".sh" else [sys.executable, str(hook)]
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    p = subprocess.run(cmd, input=raw, capture_output=True, text=True, timeout=30, env=env)
    return p.returncode, p.stdout


def decision(out):
    """deny, or allow when the hook said nothing."""
    if not out.strip():
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def call(tool, **tool_input):
    return {"tool_name": tool, "tool_input": tool_input}


class NoPersistentPollingTest(unittest.TestCase):
    def check(self, want, payload):
        rc, out = run(payload)
        self.assertEqual(rc, 0)
        self.assertEqual(decision(out), want, out)
        return out

    def test_send_later_is_always_blocked(self):
        for tool in ("mcp__symphony__send_later", "mcp__other-server__send_later"):
            with self.subTest(tool=tool):
                self.check("deny", call(tool))

    def test_deny_names_the_remedy(self):
        out = json.loads(self.check("deny", call("mcp__symphony__send_later")))
        h = out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PreToolUse")
        self.assertIn("subscribe_pr_activity", h["permissionDecisionReason"])

    def test_create_trigger_bound_to_a_session_is_blocked(self):
        t = "mcp__symphony__create_trigger"
        self.check("deny", call(t))
        self.check("deny", call(t, create_new_session_on_fire=False))
        self.check("deny", call(t, create_new_session_on_fire=None))
        self.check("deny", call(t, create_new_session_on_fire="true"))
        self.check("deny", call(t, create_new_session_on_fire=True, persistent_session_id="abc123"))
        for bound in (0, {}, [], "0", "x", True, 1.5):
            with self.subTest(persistent_session_id=bound):
                self.check("deny", call(t, create_new_session_on_fire=True, persistent_session_id=bound))
        self.check("deny", {"tool_name": t})
        self.check("deny", {"tool_name": t, "tool_input": None})

    def test_fresh_trigger_is_allowed(self):
        t = "mcp__symphony__create_trigger"
        self.check("allow", call(t, create_new_session_on_fire=True))
        self.check("allow", call(t, create_new_session_on_fire=True, persistent_session_id=""))
        self.check("allow", call(t, create_new_session_on_fire=True, persistent_session_id=None))
        self.check("allow", call(t, create_new_session_on_fire=True, persistent_session_id=False))

    def test_other_tools_are_not_gated(self):
        self.check("allow", call("mcp__symphony__subscribe_pr_activity"))
        self.check("allow", call("Bash", command="ls"))
        self.check("allow", call("mcp__symphony__get_status"))
        self.check("allow", call("mcp__symphony__send_later_not"))
        self.check("allow", {})
        self.check("allow", "not json")
        self.check("allow", "")

    @unittest.skipIf(HOOK.suffix == ".sh", "fail-closed on a broken seed is the Python hook's")
    def test_fails_closed_when_lib_is_missing(self):
        # A seed without lib/ must deny, not slip through settings.json's `|| true`.
        with tempfile.TemporaryDirectory() as tmp:
            hooks = Path(tmp) / "hooks"
            hooks.mkdir()
            shutil.copy(HOOK, hooks / HOOK.name)
            env = {**os.environ, "HOME": tmp}
            rc, out = run(call("mcp__symphony__send_later"), hook=hooks / HOOK.name, env=env)
            self.assertEqual(rc, 0)
            self.assertEqual(decision(out), "deny")
            # ... and a call that would have passed is denied too: it cannot be judged.
            rc, out = run(call("Bash", command="ls"), hook=hooks / HOOK.name, env=env)
            self.assertEqual(decision(out), "deny")


if __name__ == "__main__":
    unittest.main()
