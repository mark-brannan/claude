#!/usr/bin/env python3
# Tests for github-limits. Run: python3 bin/github-limits.test.py
# Offline only: the gh rows are thin wrappers over `gh api`.
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "github-limits"
spec = importlib.util.spec_from_loader("github_limits", importlib.machinery.SourceFileLoader("github_limits", str(ENGINE)))
gl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gl)


class PureTest(unittest.TestCase):
    def test_widest_dir_counts_files_and_subdirs(self):
        paths = ["a/1", "a/2", "a/b/3", "c"]
        self.assertEqual(gl.widest_dir(paths), (3, "a"))

    def test_widest_dir_root(self):
        self.assertEqual(gl.widest_dir(["x", "y", "z/1"]), (3, "."))

    def test_deepest(self):
        self.assertEqual(gl.deepest(["a", "a/b/c"]), 2)

    def test_peak_per_minute(self):
        ts = ["2026-10-03T08:55:30Z", "2026-10-03T08:55:59Z", "2026-10-03T08:56:00Z"]
        self.assertEqual(gl.peak_per_minute(ts), (2, "2026-10-03T08:55"))
        self.assertEqual(gl.peak_per_minute([]), (0, "-"))

    def test_status_bands(self):
        self.assertEqual(gl.status(2, 6), "ok")
        self.assertEqual(gl.status(3, 6), "warn")
        self.assertEqual(gl.status(6, 6), "over")
        self.assertEqual(gl.status(9, None), "info")


class RepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.remote = Path(self.tmp.name) / "remote.git"
        self.repo = Path(self.tmp.name) / "repo"
        run = lambda *a, cwd=None: subprocess.run(a, cwd=cwd, check=True, capture_output=True)
        run("git", "init", "-q", "--bare", str(self.remote))
        run("git", "init", "-q", "-b", "main", str(self.repo))
        for i in range(4):
            (self.repo / "wide").mkdir(exist_ok=True)
            (self.repo / "wide" / f"f{i}").write_text("x" * i)
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
        run(*g, "add", ".", cwd=self.repo)
        run(*g, "commit", "-qm", "one", cwd=self.repo)
        run("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        run("git", "push", "-q", "origin", "main", cwd=self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_offline_rows(self):
        rows = {r["metric"]: r for r in gl.local_rows(str(self.repo))}
        self.assertEqual(rows["widest directory"]["value"], 4)
        self.assertEqual(rows["widest directory"]["note"], "wide")
        self.assertEqual(rows["tracked files"]["value"], 4)
        self.assertEqual(rows["remote branches"]["value"], 1)
        self.assertEqual(rows["commits on HEAD"]["value"], 1)
        self.assertTrue(all(r["status"] in ("ok", "info") for r in rows.values()))

    def test_cli_exit_zero_when_nothing_over(self):
        p = subprocess.run([sys.executable, str(ENGINE), str(self.repo), "--offline"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("widest directory", p.stdout)

    def test_offline_needs_no_reachable_remote(self):
        subprocess.run(["git", "-C", str(self.repo), "remote", "set-url", "origin", "/nonexistent.git"], check=True)
        p = subprocess.run([sys.executable, str(ENGINE), str(self.repo), "--offline"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_non_github_origin_exits_3_not_1(self):
        p = subprocess.run([sys.executable, str(ENGINE), str(self.repo)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 3, p.stderr)

    def test_no_repo_given_is_usage_error(self):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_STATE_REPO"}
        p = subprocess.run([sys.executable, str(ENGINE), "--offline"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 2)

    def test_tool_failure_exits_3_not_1(self):
        p = subprocess.run([sys.executable, str(ENGINE), self.tmp.name, "--offline"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 3)
        self.assertNotIn("Traceback", p.stderr)


if __name__ == "__main__":
    unittest.main()
