#!/usr/bin/env python3
# Tests for demo-line-gate.py. Run: python3 hooks/demo-line-gate.test.py
#
# Cost per push: about a second, a step in CI's tool-tests job.
# What matters: in a repo whose show-dont-tell.yml sets serve:, a turn that
# hands over any demo line but the exact Try it line blocks once, with the
# exact line in the reason; the exact line, prose, a repo that has not opted
# in and the retry all pass. LINE is the string show-dont-tell.test.mjs pins
# for tryItLine in mark-brannan/.github; the two copies move together.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "demo-line-gate.py"

LINE = ("git -C ~/searoom fetch origin +pull/221/head:refs/pr/221 && { [ -d ~/searoom/.claude/worktrees/pr-221 ] "
        "|| git -C ~/searoom worktree add --detach ~/searoom/.claude/worktrees/pr-221 refs/pr/221; } && "
        "git -C ~/searoom/.claude/worktrees/pr-221 checkout -q --detach refs/pr/221 && cd ~/searoom/.claude/worktrees/pr-221 "
        "&& npm ci && npm run dev -- --strictPort --port 10221")
CONFIG = ("paths:\n  - ui/**\ncheckout: ~/searoom   # the clone\ninstall: npm ci\n"
          "serve: npm run dev -- --strictPort --port {port}\n")


def fence(s): return f"Try it:\n\n```bash\n{s}\n```\n"


class DemoLineGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        self.env["HOME"] = str(self.dir)
        self.repo = self.dir / "searoom"
        (self.repo / ".github").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / ".github/show-dont-tell.yml").write_text(CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, msg, active=False, cwd=None):
        ev = {"hook_event_name": "Stop", "stop_hook_active": active,
              "cwd": str(cwd or self.repo), "last_assistant_message": msg}
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(ev),
                           capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if p.stdout.strip() else None

    def assert_blocks(self, msg):
        out = self.run_hook(msg)
        self.assertIsNotNone(out, msg)
        self.assertEqual(out.get("decision"), "block")
        self.assertIn(LINE, out.get("reason", ""))

    def test_exact_line_passes(self):
        self.assertIsNone(self.run_hook(fence(LINE)))
        self.assertIsNone(self.run_hook(f"Run `{LINE}` then open the page."))

    def test_hand_written_forms_block_with_the_exact_line(self):
        self.assert_blocks(fence("gh pr checkout 221 && npm ci && npm run dev -- --port 10231"))
        self.assert_blocks(fence("npm run try-it -- 221"))
        self.assert_blocks("Paste ` npm run try-it -- 221` in the repo.")
        self.assert_blocks(fence("try-pr searoom 221"))
        self.assert_blocks(fence(LINE.replace("10221", "10231")))

    def test_wrapped_line_blocks(self):
        self.assert_blocks(fence(LINE.replace(" && cd ", " \\\n  && cd ")))

    def test_prose_and_numberless_mentions_pass(self):
        self.assertIsNone(self.run_hook("No more `gh pr checkout N && npm …` lines; the check wants `pull/<N>/head`."))
        self.assertIsNone(self.run_hook("PR 221 is merged."))

    def test_backslash_tail_does_not_leak_into_the_next_fence(self):
        self.assertIsNone(self.run_hook("```bash\nnpm ci \\\n```\n" + fence(LINE)))

    def test_no_checkout_takes_the_origin_name_not_the_clone_dir(self):
        (self.repo / ".github/show-dont-tell.yml").write_text(CONFIG.replace("checkout: ~/searoom   # the clone\n", ""))
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin",
                        "git@github.com:mark-brannan/harbour.git"], check=True)
        want = LINE.replace("~/searoom", "~/harbour")
        self.assertIsNone(self.run_hook(fence(want)))
        out = self.run_hook(fence(LINE))
        self.assertEqual(out.get("decision"), "block")
        self.assertIn(want, out.get("reason", ""))

    def test_retry_passes(self):
        self.assertIsNone(self.run_hook(fence("npm run try-it -- 221"), active=True))

    def test_repo_without_serve_passes(self):
        (self.repo / ".github/show-dont-tell.yml").write_text("paths:\n  - ui/**\n")
        self.assertIsNone(self.run_hook(fence("gh pr checkout 221 && npm ci")))
        other = self.dir / "plain"
        other.mkdir()
        self.assertIsNone(self.run_hook(fence("gh pr checkout 221"), cwd=other))


if __name__ == "__main__":
    unittest.main()
