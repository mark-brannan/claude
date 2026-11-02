#!/usr/bin/env python3
# Tests for apply-edits. Run: python3 bin/apply-edits.test.py
#
# What matters: an edit applies only when old matches exactly once, edits to
# one file apply in order, and one failing edit -- no match, two, a missing
# file, a refused path -- writes nothing anywhere and names every failure; a
# written file keeps its mode. The path guard: only the cwd's work tree, the
# state repo and the scratchpads, never the live ~/.claude, a .git, a .claude
# dir outside .claude/worktrees/<name>/, or a symlink out of the roots. The
# tool runs in a subprocess with its home and /tmp pointed into a temp dir.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "apply-edits"

# Loads the tool, points its home and /tmp at argv[1] and argv[2], runs main.
RUN = """
import importlib.machinery, sys
m = importlib.machinery.SourceFileLoader("apply_edits", sys.argv[3]).load_module()
m.home = lambda: sys.argv[1]
m.TMP = sys.argv[2]
sys.exit(m.main())
"""


class ApplyEdits(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.systmp = self.tmp / "systmp"
        self.repo = self.home / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.systmp.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def run_tool(self, edits, cwd=None):
        stdin = edits if isinstance(edits, str) else json.dumps(edits)
        return subprocess.run([sys.executable, "-c", RUN, str(self.home), str(self.systmp), str(TOOL)],
                              input=stdin, cwd=cwd or self.repo, text=True, capture_output=True)

    def file(self, rel, text, base=None):
        p = (base or self.repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def assertRefused(self, r, *needles):
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("nothing written", r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)

    def test_single_edit(self):
        p = self.file("a.txt", "alpha beta\n")
        r = self.run_tool({"path": "a.txt", "old": "beta", "new": "gamma"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_text(), "alpha gamma\n")
        self.assertEqual(r.stdout, "edited a.txt\n")

    def test_same_file_edits_apply_in_order(self):
        p = self.file("a.txt", "one\n")
        r = self.run_tool([{"path": "a.txt", "old": "one", "new": "two"},
                           {"path": str(p), "old": "two", "new": "three"}])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_text(), "three\n")
        self.assertEqual(r.stdout, "edited a.txt\n")

    def test_zero_and_two_matches_write_nothing(self):
        a, b = self.file("a.txt", "x x\n"), self.file("b.txt", "y\n")
        r = self.run_tool([{"path": "b.txt", "old": "y", "new": "z"},
                           {"path": "a.txt", "old": "x", "new": "w"},
                           {"path": "a.txt", "old": "nope", "new": "w"}])
        self.assertRefused(r, "edit 1 (a.txt): old matches 2 times", "edit 2 (a.txt): old matches 0 times")
        self.assertNotIn("edit 0", r.stderr)
        self.assertEqual((a.read_text(), b.read_text()), ("x x\n", "y\n"))
        self.assertEqual(sorted(os.listdir(self.repo)), [".git", "a.txt", "b.txt"])

    def test_mixed_batch_one_missing_file_writes_nothing(self):
        a = self.file("a.txt", "keep\n")
        r = self.run_tool([{"path": "a.txt", "old": "keep", "new": "lose"},
                           {"path": "gone.txt", "old": "x", "new": "y"}])
        self.assertRefused(r, "edit 1 (gone.txt): no such file")
        self.assertEqual(a.read_text(), "keep\n")
        self.assertFalse((self.repo / "gone.txt").exists())

    def test_empty_old_refused(self):
        self.file("e.txt", "")
        r = self.run_tool({"path": "e.txt", "old": "", "new": "x"})
        self.assertRefused(r, "old is empty")
        self.assertEqual((self.repo / "e.txt").read_text(), "")

    def test_bad_input_exits_2(self):
        for stdin in ("not json", "[]", '[{"path": "a", "old": "b"}]', '{"path": "a", "old": "b", "new": 1}'):
            r = self.run_tool(stdin)
            self.assertEqual(r.returncode, 2, stdin)

    def test_mode_kept_and_crlf_kept(self):
        p = self.repo / "run.sh"
        p.write_bytes(b"echo a\r\n")
        p.chmod(0o751)
        r = self.run_tool({"path": "run.sh", "old": "a", "new": "b"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(p.read_bytes(), b"echo b\r\n")
        self.assertEqual(p.stat().st_mode & 0o7777, 0o751)
        self.assertEqual(sorted(os.listdir(self.repo)), [".git", "run.sh"])

    def test_symlink_inside_root_writes_its_target(self):
        t = self.file("real.txt", "a\n")
        (self.repo / "link.txt").symlink_to(t)
        r = self.run_tool({"path": "link.txt", "old": "a", "new": "b"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(t.read_text(), "b\n")
        self.assertTrue((self.repo / "link.txt").is_symlink())

    def test_symlink_escape_refused(self):
        t = self.file("secret.txt", "a\n", base=self.outside)
        (self.repo / "link.txt").symlink_to(t)
        (self.repo / "dir").symlink_to(self.outside)
        r = self.run_tool([{"path": "link.txt", "old": "a", "new": "b"},
                           {"path": "dir/secret.txt", "old": "a", "new": "b"},
                           {"path": str(t), "old": "a", "new": "b"}])
        self.assertRefused(r, "edit 0 (link.txt): is outside", "edit 1", "edit 2")
        self.assertEqual(t.read_text(), "a\n")

    def test_git_dir_refused(self):
        c = self.file(".git/config", "[core]\n")
        r = self.run_tool({"path": ".git/config", "old": "[core]", "new": "[x]"})
        self.assertRefused(r, "is in a .git")
        self.assertEqual(c.read_text(), "[core]\n")

    def test_claude_dir_refused_but_worktrees_open(self):
        s = self.file(".claude/settings.json", "{}\n")
        h = self.file(".claude/hooks/h.py", "a\n")
        w = self.file(".claude/worktrees/wt/f.txt", "a\n")
        ws = self.file(".claude/worktrees/wt/.claude/settings.local.json", "{}\n")
        m = self.file(".mcp.json", "{}\n")
        r = self.run_tool([{"path": str(p.relative_to(self.repo)), "old": o, "new": "z"}
                           for p, o in ((s, "{}"), (h, "a"), (ws, "{}"), (m, "{}"))])
        self.assertRefused(r, "edit 0", "edit 1", "edit 2", "edit 3 (.mcp.json): is a .mcp.json")
        r = self.run_tool({"path": ".claude/worktrees/wt/f.txt", "old": "a", "new": "b"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.read_text(), "b\n")

    def test_live_claude_refused_even_as_cwd_work_tree(self):
        live = self.home / ".claude"
        (live / ".git").mkdir(parents=True)
        f = self.file("CLAUDE.md", "a\n", base=live)
        r = self.run_tool({"path": "CLAUDE.md", "old": "a", "new": "b"}, cwd=live)
        self.assertRefused(r, "is in the live ~/.claude")
        self.assertEqual(f.read_text(), "a\n")

    def test_work_tree_must_be_strictly_inside_home(self):
        (self.home / ".git").mkdir()
        f = self.file("notes.txt", "a\n", base=self.home)
        r = self.run_tool({"path": "notes.txt", "old": "a", "new": "b"}, cwd=self.home)
        self.assertRefused(r, "is outside")
        (self.outside / ".git").mkdir()
        g = self.file("g.txt", "a\n", base=self.outside)
        r = self.run_tool({"path": "g.txt", "old": "a", "new": "b"}, cwd=self.outside)
        self.assertRefused(r, "is outside")
        self.assertEqual((f.read_text(), g.read_text()), ("a\n", "a\n"))

    def test_other_repo_refused_from_this_cwd(self):
        other = self.home / "other"
        (other / ".git").mkdir(parents=True)
        f = self.file("x.txt", "a\n", base=other)
        r = self.run_tool({"path": str(f), "old": "a", "new": "b"})
        self.assertRefused(r, "is outside")

    def test_state_repo_and_scratchpads_open(self):
        uid = "claude-%d" % os.getuid()
        s = self.file("state/x.md", "a\n", base=self.home / "claude_prompts_scratch")
        p = self.file("sess/scratchpad/y.mjs", "a\n", base=self.home / ".local/state/claude-tmpdir" / uid)
        q = self.file("sess/z.txt", "a\n", base=self.systmp / uid)
        r = self.run_tool([{"path": "~/claude_prompts_scratch/state/x.md", "old": "a", "new": "b"},
                           {"path": str(p), "old": "a", "new": "b"},
                           {"path": str(q), "old": "a", "new": "b"}], cwd=self.outside)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([x.read_text() for x in (s, p, q)], ["b\n"] * 3)
        self.assertEqual(len(r.stdout.splitlines()), 3)

    def test_symlinked_tmp_root_not_trusted(self):
        uid = "claude-%d" % os.getuid()
        (self.systmp / uid).symlink_to(self.outside)
        f = self.file("z.txt", "a\n", base=self.outside)
        r = self.run_tool({"path": str(self.systmp / uid / "z.txt"), "old": "a", "new": "b"})
        self.assertRefused(r, "is outside")
        self.assertEqual(f.read_text(), "a\n")


if __name__ == "__main__":
    unittest.main(verbosity=1)
