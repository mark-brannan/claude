#!/usr/bin/env python3
# Tests for connector-budget.py. Run: python3 hooks/connector-budget.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess with HOME and cwd
# in a throwaway dir. CONNECTOR_BUDGET_HOOK names another script to drive
# through the same command line (the parity run against the old shell hook
# used it); a .sh runs under bash.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("CONNECTOR_BUDGET_HOOK") or Path(__file__).resolve().parent / "connector-budget.py").resolve()


class ConnectorBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.cwd = self.home / "proj"
        self.cwd.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        self.env["HOME"] = str(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def servers(self, n):
        return {f"s{i}": {} for i in range(n)}

    def write(self, path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))

    def run_hook(self, **env):
        e = dict(self.env, **env)
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else ["python3", str(HOOK)]
        return subprocess.run(cmd, input="{}", capture_output=True, text=True, cwd=self.cwd, env=e)

    def ctx(self, p):
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        return out["hookSpecificOutput"]["additionalContext"]

    def test_no_config_is_silent(self):
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_at_limit_is_silent(self):
        self.write(self.home / ".claude.json", {"mcpServers": self.servers(5)})
        self.assertEqual(self.run_hook().stdout, "")

    def test_over_limit_shouts(self):
        self.write(self.home / ".claude.json", {"mcpServers": self.servers(6)})
        c = self.ctx(self.run_hook())
        self.assertIn("CONNECTOR BUDGET EXCEEDED: 6 enabled, limit 5", c)
        self.assertIn("Enabled: s0, s1, s2, s3, s4, s5\n", c)
        self.assertIn("`deniedMcpServers`", c)

    def test_all_three_sources_count_and_dedupe(self):
        self.write(self.home / ".claude.json", {
            "mcpServers": {"a": {}, "b": {}},
            "projects": {str(self.cwd): {"mcpServers": {"c": {}, "a": {}}}, "/other": {"mcpServers": {"zz": {}}}}})
        self.write(self.cwd / ".mcp.json", {"mcpServers": {"d": {}, "e": {}}})
        c = self.ctx(self.run_hook(CLAUDE_CONNECTOR_MAX="4"))
        self.assertIn("5 enabled, limit 4", c)
        self.assertIn("Enabled: a, b, c, d, e\n", c)

    def test_denied_servers_do_not_count(self):
        self.write(self.home / ".claude.json", {"mcpServers": self.servers(7)})
        self.write(self.home / ".claude/settings.json", {"deniedMcpServers": [{"serverName": "s0"}, {"serverName": "s1"}]})
        self.assertEqual(self.run_hook().stdout, "")
        self.write(self.cwd / ".claude/settings.local.json", {"deniedMcpServers": [{"serverName": "s2"}]})
        self.write(self.home / ".claude.json", {"mcpServers": self.servers(9)})
        c = self.ctx(self.run_hook())
        self.assertIn("6 enabled", c)
        self.assertIn("Enabled: s3, s4, s5, s6, s7, s8\n", c)

    def test_config_dir_override_for_settings(self):
        self.write(self.home / ".claude.json", {"mcpServers": self.servers(6)})
        alt = self.home / "alt"
        self.write(alt / "settings.json", {"deniedMcpServers": [{"serverName": "s0"}]})
        self.assertEqual(self.run_hook(CLAUDE_CONFIG_DIR=str(alt)).stdout, "")

    def test_broken_json_is_silent(self):
        (self.home / ".claude.json").write_text("{nope")
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
