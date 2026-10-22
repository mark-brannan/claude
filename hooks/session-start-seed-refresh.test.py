#!/usr/bin/env python3
# Tests for session-start-seed-refresh.py. Run: python3 hooks/session-start-seed-refresh.test.py
#
# Cost per push: well under a second. Each case runs the hook as Claude Code
# does, a subprocess with HOME in a throwaway dir and CLAUDE_SEED pointing at
# a fake seed whose installer is a tiny sh script. SEED_REFRESH_HOOK names
# another script to drive through the same command line (the parity run
# against the old shell hook used it); a .sh runs under bash.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("SEED_REFRESH_HOOK") or Path(__file__).resolve().parent / "session-start-seed-refresh.py").resolve()


class SeedRefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve()
        self.orders = self.home / ".claude/CLAUDE.md"
        self.orders.parent.mkdir(parents=True)
        self.orders.write_text("old orders\n")
        self.seed = self.home / "seed"
        (self.seed / "bin").mkdir(parents=True)
        self.setup = self.seed / "bin/cloud-session-setup.sh"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        self.env.update(HOME=str(self.home), CLAUDE_CODE_REMOTE="true", CLAUDE_SEED=str(self.seed))

    def tearDown(self):
        self.tmp.cleanup()

    def installer(self, body):
        self.setup.write_text(body)

    def run_hook(self, **env):
        e = dict(self.env, **env)
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else ["python3", str(HOOK)]
        return subprocess.run(cmd, input="{}", capture_output=True, text=True, env=e)

    def test_not_remote_does_not_run_installer(self):
        self.installer(f'echo ran > "{self.home}/ran"\n')
        del self.env["CLAUDE_CODE_REMOTE"]
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        self.assertFalse((self.home / "ran").exists())

    def test_remote_must_be_exactly_true(self):
        self.installer(f'echo ran > "{self.home}/ran"\n')
        self.run_hook(CLAUDE_CODE_REMOTE="1")
        self.assertFalse((self.home / "ran").exists())

    def test_no_installer_is_silent(self):
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_unchanged_orders_are_silent_and_installer_runs_quietly(self):
        self.installer(f'echo "progress"; echo "$CLOUD_SESSION" > "{self.home}/ran"\n')
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        self.assertEqual((self.home / "ran").read_text(), "1\n")

    def test_changed_orders_are_emitted(self):
        self.installer(f'printf "new orders\\nline 2\\n" > "{self.orders}"\n')
        p = self.run_hook()
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        c = out["additionalContext"]
        self.assertTrue(c.startswith("## Standing orders were refreshed after this session started\n\n"))
        self.assertIn("it supersedes it.\n\nnew orders\nline 2\n", c)

    def test_orders_created_by_refresh_are_emitted(self):
        self.orders.unlink()
        self.installer(f'echo fresh > "{self.orders}"\n')
        c = json.loads(self.run_hook().stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertTrue(c.endswith("fresh\n"))

    def test_orders_removed_are_silent(self):
        self.installer(f'rm "{self.orders}"\n')
        self.assertEqual(self.run_hook().stdout, "")

    def test_failing_installer_with_no_change_is_silent(self):
        self.installer("exit 3\n")
        p = self.run_hook()
        self.assertEqual((p.returncode, p.stdout), (0, ""))


if __name__ == "__main__":
    unittest.main()
