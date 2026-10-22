#!/usr/bin/env python3
# Tests for scratch-mirror.py. Run: python3 hooks/scratch-mirror.test.py
#
# Cost per push: about a second, a step in CI's existing tool-tests job.
# Each case runs the hook as Claude Code does, a subprocess fed PostToolUse
# JSON on stdin, with CLAUDE_STATE_REPO pointed at a throwaway repo.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "scratch-mirror.py"
NAME = "2026-10-20-foo-bar.md"


def init(p):
    p.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(p)], check=True)
    return p


class ScratchMirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.state = init(t / "state")
        (self.state / "global/foo/bar").mkdir(parents=True)
        self.doc = self.state / "global/foo/bar" / NAME
        self.doc.write_text("# v1\n")
        self.work = init(t / "work")
        self.t = t

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, path, cwd):
        payload = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}, "cwd": str(cwd)})
        env = {**os.environ, "CLAUDE_STATE_REPO": str(self.state)}
        return subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True,
                              text=True, env=env).stdout

    def test_copies_flat_and_names_the_link(self):
        out = self.run_hook(self.doc, self.work)
        self.assertEqual((self.work / ".scratch" / NAME).read_text(), "# v1\n")
        self.assertIn(f"[{NAME}](<.scratch/{NAME}>)", out)

    def test_copy_is_ignored_and_exclude_written_once(self):
        self.run_hook(self.doc, self.work)
        self.run_hook(self.doc, self.work)
        status = subprocess.run(["git", "-C", str(self.work), "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        self.assertEqual(status, "")
        self.assertEqual((self.work / ".git/info/exclude").read_text().splitlines().count(".scratch/"), 1)

    def test_edit_refreshes_copy(self):
        self.run_hook(self.doc, self.work)
        self.doc.write_text("# v2\n")
        self.run_hook(self.doc, self.work)
        self.assertEqual((self.work / ".scratch" / NAME).read_text(), "# v2\n")

    def test_link_is_relative_to_session_dir(self):
        (self.work / "sub").mkdir()
        self.assertIn(f"(<../.scratch/{NAME}>)", self.run_hook(self.doc, self.work / "sub"))

    def test_link_survives_spaces_and_parentheses(self):
        odd = self.state / "global" / "my notes (v2).md"
        odd.write_text("x\n")
        self.assertIn("[my notes (v2).md](<.scratch/my notes (v2).md>)", self.run_hook(odd, self.work))

    def test_quiet_cases(self):
        notes = self.state / "global/notes.txt"
        notes.write_text("x\n")
        local = self.work / "local.md"
        local.write_text("a\n")
        for path, cwd in ((notes, self.work), (local, self.work), (self.doc, self.state), (self.doc, self.t)):
            with self.subTest(path=path.name, cwd=cwd.name):
                self.assertEqual(self.run_hook(path, cwd), "")
        self.assertFalse((self.state / ".scratch").exists())

    def test_symlinked_scratch_is_not_written_through(self):
        linked, outside = init(self.t / "linked"), self.t / "outside"
        outside.mkdir()
        (linked / ".scratch").symlink_to(outside)
        self.assertEqual(self.run_hook(self.doc, linked), "")
        self.assertEqual(list(outside.iterdir()), [])

    def test_tracked_scratch_gets_no_copy(self):
        tracked = init(self.t / "tracked")
        (tracked / ".scratch").mkdir()
        (tracked / ".scratch/keep").write_text("k\n")
        subprocess.run(["git", "-C", str(tracked), "add", ".scratch/keep"], check=True)
        self.assertEqual(self.run_hook(self.doc, tracked), "")
        self.assertFalse((tracked / ".scratch" / NAME).exists())

# Runs the hook named by argv[1] as Claude Code would, after the patch in
# argv[2], so a test can make it crash where no input could.
# The patch can name boom, which raises RuntimeError("boom").
WRAP = """import os, runpy, sys
def boom(*a, **k):
    raise RuntimeError("boom")
hook, patch = sys.argv.pop(1), sys.argv.pop(1)
sys.path.insert(0, os.path.dirname(hook))
exec(patch)
runpy.run_path(hook, run_name="__main__")
"""


class CrashIsTraced(unittest.TestCase):
    setUp, tearDown = ScratchMirrorTest.setUp, ScratchMirrorTest.tearDown

    def test_a_failed_copy_is_traced_not_sent_to_stderr(self):
        payload = json.dumps({"session_id": "ab5", "tool_name": "Write",
                              "tool_input": {"file_path": str(self.doc)}, "cwd": str(self.work)})
        env = {**os.environ, "CLAUDE_STATE_REPO": str(self.state)}
        r = subprocess.run([sys.executable, "-c", WRAP, str(HOOK), "import shutil; shutil.copyfile = boom"],
                           input=payload, capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        row = json.loads((self.state / "state/global/metrics/hook-errors/ab/ab5.jsonl").read_text())
        self.assertEqual((row["hook"], row["event"], row["stage"], row["session_id"], row["error"]),
                         ("scratch-mirror", "PostToolUse", "main", "ab5", "RuntimeError: boom"))


if __name__ == "__main__":
    unittest.main()
