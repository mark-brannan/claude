#!/usr/bin/env python3
# Tests for prose-budget-edit.py. Run: python3 hooks/prose-budget-edit.test.py
#
# Cost per push: a second or two, a step in CI's Python test suites; each case
# runs the real bin/prose-budget engine on a throwaway repo.
# PROSE_BUDGET_EDIT_HOOK names another script to drive through the same
# command line (the parity run against the old shell hook used it; a .sh runs
# under bash).
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HOOK = Path(os.environ.get("PROSE_BUDGET_EDIT_HOOK") or HERE / "prose-budget-edit.py").resolve()
ENGINE = HERE.parent / "bin" / "prose-budget"


class ProseBudgetEditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "repo"
        cls.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.repo)], check=True)
        r = cls.repo
        (r / ".prose-budgets.json").write_text(
            '{"lines": {"README.md": 2, "docs/near.md": 9, "docs/far.md": 9}, "voice": {"scope": "tree"}}\n')
        (r / "README.md").write_text("a\nb\nc\n")
        (r / "CLAUDE.md").write_text("a\n")
        (r / "docs").mkdir()
        (r / "docs/x.md").write_text("a seamless flow\n")
        (r / "docs/near.md").write_text("a\n" * 7)
        (r / "docs/far.md").write_text("a\n" * 6)
        (r / "x.py").write_text("print(1)\n")
        (r / "data.json").write_text('{"note": "a robust note"}\n')
        cls.noconf = Path(cls.tmp.name) / "noconf"
        cls.noconf.mkdir()
        (cls.noconf / "README.md").write_text("a robust line\n")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_hook(self, file, tool_input=None, engine=ENGINE, tool="Edit"):
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        payload = {"tool_name": tool, "tool_input": tool_input if tool_input is not None else {"file_path": str(file)}}
        env = {**os.environ, "PROSE_BUDGET": str(engine)}
        p = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def context(self, file, **kw):
        out = self.run_hook(file, **kw)
        self.assertNotEqual(out, "", f"expected context for {file}")
        h = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PostToolUse")
        self.assertNotIn("\n\n", h["additionalContext"])
        return h["additionalContext"]

    def silent(self, file, **kw):
        self.assertEqual(self.run_hook(file, **kw), "")

    def test_file_over_its_line_budget(self):
        ctx = self.context(self.repo / "README.md")
        self.assertIn("README.md:3: lines", ctx)
        self.assertIn("(3/2 lines)", ctx)
        self.assertIn("at least 10", ctx)
        self.assertTrue(ctx.startswith(f"prose-budget on {self.repo}/README.md (3/2 lines):\n"), ctx)
        self.assertTrue(ctx.endswith("Fix these before the push; CI fails on them.\n"), ctx)

    def test_voice_word_in_a_docs_file(self):
        self.context(self.repo / "docs/x.md")

    def test_clean_file_is_silent(self):
        self.silent(self.repo / "CLAUDE.md")

    def test_budgeted_file_past_two_thirds_speaks(self):
        self.assertEqual(self.context(self.repo / "docs/near.md"),
                         f"prose-budget: {self.repo}/docs/near.md 7/9 lines.\n")

    def test_budgeted_file_under_two_thirds_is_silent(self):
        self.silent(self.repo / "docs/far.md")

    def test_other_files_are_silent(self):
        self.silent(self.repo / "data.json")  # json outside any json_prose target
        self.silent(self.repo / "x.py")
        self.silent(self.noconf / "README.md")  # no config in the repo
        self.silent(self.repo / "missing.md")

    def test_odd_input_is_silent(self):
        self.silent(None, tool_input={})
        self.silent(None, tool_input={"file_path": 5})
        self.silent(None, tool_input={"file_path": str(self.repo)})  # a directory

    def test_missing_engine_is_silent(self):
        self.silent(self.repo / "README.md", engine=self.repo / "no-such-engine")


if __name__ == "__main__":
    unittest.main()
