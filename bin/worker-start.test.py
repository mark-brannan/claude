#!/usr/bin/env python3
# Tests for worker-start. Run: python3 bin/worker-start.test.py
#
# What matters: --new cuts claude/<slug> from origin/main (or --base), in the
# repo or in a new worktree; --head and --pr check out the remote head, a
# worktree one detached; the issue or PR is read last; a failing step stops
# the run with its code; --item logs `dispatched` last and never fails it;
# --issue alone only prints the issue; with --worktree a repo in the SETUP
# table (keyed by its origin's owner/name) gets links, excludes or npm ci,
# unless --no-setup. A real git repo with a local "origin"; gh and npm are stubs.
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "worker-start"

GH = '''#!/bin/sh
echo "gh $*" >> "$GH_LOG"
pwd -P >> "$GH_LOG.pwd"
case "$1 $2" in "pr view") case "$*" in *headRefName*) [ -f "$GH_LOG.fork" ] && echo "true feature" || echo "false feature" ;; esac ;; esac
exit 0
'''


# npm ci stub: logs its argv and cwd, and leaves a real node_modules behind.
NPM = '''#!/bin/sh
echo "npm $* (in $(pwd -P))" >> "$GH_LOG.npm"
mkdir -p node_modules
exit 0
'''


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True).stdout


class WorkerStart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        origin, self.repo = self.tmp / "origin", self.tmp / "repo"
        sh("git", "init", "-q", "-b", "main", str(origin))
        sh("git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
           "commit", "-q", "--allow-empty", "-m", "root")
        sh("git", "-C", str(origin), "branch", "feature")
        sh("git", "clone", "-q", str(origin), str(self.repo))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(GH)
        (bindir / "gh").chmod(0o755)
        (bindir / "npm").write_text(NPM)
        (bindir / "npm").chmod(0o755)
        self.log = self.tmp / "gh.log"
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), GH_LOG=str(self.log))

    def run_tool(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), *args],
                              env=self.env, text=True, capture_output=True, cwd=cwd)

    def branch(self, where=None):
        return sh("git", "-C", str(where or self.repo), "rev-parse", "--abbrev-ref", "HEAD").strip()

    def gh_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_new_cuts_claude_branch_and_reads_issue(self):
        r = self.run_tool("--new", "fix-x", "--issue", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(), "claude/fix-x")
        self.assertEqual(self.gh_calls(), ["gh issue view 7 --comments"])
        self.assertIn("$ git -C", r.stdout)

    def test_new_in_worktree(self):
        wt = self.tmp / "wt"
        r = self.run_tool("--new", "fix-y", "--worktree", str(wt))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(wt), "claude/fix-y")
        self.assertEqual(self.branch(), "main")

    def test_head_checks_out_remote_branch(self):
        r = self.run_tool("--head", "feature")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(), "feature")
        self.assertEqual(sh("git", "-C", str(self.repo), "rev-parse", "HEAD"),
                         sh("git", "-C", str(self.repo), "rev-parse", "origin/feature"))

    def test_pr_in_worktree_is_detached_and_prints_pr(self):
        wt = self.tmp / "wt"
        r = self.run_tool("--pr", "5", "--worktree", str(wt))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.branch(wt), "HEAD")
        self.assertEqual(self.gh_calls()[-1], "gh pr view 5 --comments")

    def test_relative_worktree_is_the_callers_not_the_repos(self):
        r = self.run_tool("--new", "fix-r", "--worktree", "wt", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "wt").is_dir())
        self.assertFalse((self.repo / "wt").exists())

    def test_gh_runs_in_the_repo_whatever_the_callers_cwd(self):
        r = self.run_tool("--new", "fix-c", "--issue", "7", cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(str(self.log) + ".pwd").read_text().split(), [str(self.repo.resolve())])

    def test_new_branch_has_no_upstream(self):
        for wt in (None, self.tmp / "wt"):
            r = self.run_tool("--new", "fix-u%s" % bool(wt), *(["--worktree", str(wt)] if wt else []))
            self.assertEqual(r.returncode, 0, r.stderr)
            u = subprocess.run(["git", "-C", str(wt or self.repo), "rev-parse", "--abbrev-ref", "@{upstream}"],
                               capture_output=True)
            self.assertNotEqual(u.returncode, 0)

    def test_bad_arguments_exit_2_before_any_fetch(self):
        for args in (["--new", ""], ["--head", ""], ["--pr", "0"], ["--new", "x", "--issue", "0"], ["--new", "a..b"], ["--new", "x", "--item", "-x"]):
            r = self.run_tool(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("fetch", r.stdout, args)

    def test_failing_step_stops_the_run(self):
        r = self.run_tool("--new", "fix-z", "--base", "origin/nope", "--issue", "7")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("worker-start: failed", r.stderr)
        self.assertEqual(self.gh_calls(), [])

    def test_existing_local_branch_is_not_reset(self):
        sh("git", "-C", str(self.repo), "branch", "feature", "origin/main")
        self.assertNotEqual(self.run_tool("--head", "feature").returncode, 0)

    def with_work_item(self, body):
        """The tool copied beside a fake work-item, which is where it looks."""
        beside = self.tmp / "beside"
        beside.mkdir(exist_ok=True)
        shutil.copy(TOOL, beside / "worker-start")
        (beside / "work-item").write_text("#!/bin/sh\n" + body)
        (beside / "work-item").chmod(0o755)
        return subprocess.run([sys.executable, str(beside / "worker-start"), "-C", str(self.repo),
                               "--new", "fix-i", "--item", "abc123"],
                              env=self.env, text=True, capture_output=True)

    def test_item_logs_dispatched_last(self):
        r = self.with_work_item('echo "$*" >> "$GH_LOG.item"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(str(self.log) + ".item").read_text(), "log abc123 dispatched\n")
        self.assertEqual(self.branch(), "claude/fix-i")

    def test_item_that_fails_to_log_still_starts(self):
        r = self.with_work_item("echo boom >&2; exit 1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("work item abc123 not logged: boom", r.stderr)
        self.assertEqual(self.branch(), "claude/fix-i")

    def test_item_with_no_work_item_beside_still_starts(self):
        beside = self.tmp / "alone"
        beside.mkdir()
        shutil.copy(TOOL, beside / "worker-start")
        r = subprocess.run([sys.executable, str(beside / "worker-start"), "-C", str(self.repo),
                            "--new", "fix-j", "--item", "abc123"],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not logged", r.stderr)

    def test_fork_pr_is_refused(self):
        Path(str(self.log) + ".fork").write_text("")
        self.assertEqual(self.run_tool("--pr", "5").returncode, 2)

    def test_dash_argument_is_refused(self):
        self.assertEqual(self.run_tool("--new=--exec=x").returncode, 2)

    def test_base_without_new_is_refused(self):
        self.assertEqual(self.run_tool("--head", "feature", "--base", "origin/x").returncode, 2)


class Setup(unittest.TestCase):
    """The per-repo opening chores; portolani is the one entry."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin, self.repo = self.tmp / "origin", self.tmp / "repo"
        sh("git", "init", "-q", "-b", "main", str(self.origin))
        (self.origin / "package-lock.json").write_text("lock v1\n")
        sh("git", "-C", str(self.origin), "add", ".")
        sh("git", "-C", str(self.origin), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
           "commit", "-q", "-m", "root")
        sh("git", "clone", "-q", str(self.origin), str(self.repo))
        # The main checkout: installs and downloads that a worktree should reach.
        (self.repo / "node_modules").mkdir()
        (self.repo / "downloads").mkdir()
        (self.repo / "downloads" / "a.pdf").write_text("pdf")
        bindir = self.tmp / "bin"
        bindir.mkdir()
        for name, body in (("gh", GH), ("npm", NPM)):
            (bindir / name).write_text(body)
            (bindir / name).chmod(0o755)
        self.log = self.tmp / "gh.log"
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), GH_LOG=str(self.log))
        self.exclude = self.repo / ".git" / "info" / "exclude"

    def fake_origin(self, url):
        """Make origin's URL <url> while fetches still reach the local origin."""
        sh("git", "-C", str(self.repo), "config", "url.%s.insteadOf" % self.origin, url)
        sh("git", "-C", str(self.repo), "config", "remote.origin.url", url)

    def start(self, slug, *args):
        return subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), "--new", slug,
                               "--worktree", str(self.tmp / slug), *args],
                              env=self.env, text=True, capture_output=True)

    def npm_calls(self):
        f = Path(str(self.log) + ".npm")
        return f.read_text().splitlines() if f.exists() else []

    def test_portolani_links_installs_and_excludes_them(self):
        self.fake_origin("git@github.com:mark-brannan/portolani.git")
        r = self.start("w1")
        self.assertEqual(r.returncode, 0, r.stderr)
        wt = self.tmp / "w1"
        self.assertEqual(os.readlink(wt / "node_modules"), str(self.repo / "node_modules"))
        self.assertEqual(os.readlink(wt / "downloads"), str(self.repo / "downloads"))
        self.assertEqual(self.npm_calls(), [])
        self.assertIn("$ ln -s %s %s" % (self.repo / "node_modules", wt / "node_modules"), r.stdout)
        # The point: the links are not untracked, so nothing has to be rm'd before a commit.
        self.assertEqual(sh("git", "-C", str(wt), "status", "--porcelain"), "")

    def test_exclude_is_written_once(self):
        self.fake_origin("https://github.com/Mark-Brannan/portolani")
        for slug in ("w1", "w2"):
            self.assertEqual(self.start(slug).returncode, 0)
        self.assertEqual(self.exclude.read_text().splitlines().count("/node_modules"), 1)
        self.assertEqual(self.exclude.read_text().splitlines().count("/downloads"), 1)
        self.assertNotIn("echo", self.start("w3").stdout)

    def test_changed_lockfile_means_npm_ci_not_a_link(self):
        self.fake_origin("https://github.com/mark-brannan/portolani.git")
        (self.repo / "package-lock.json").write_text("lock v0\n")
        r = self.start("w1")
        self.assertEqual(r.returncode, 0, r.stderr)
        wt = self.tmp / "w1"
        self.assertFalse((wt / "node_modules").is_symlink())
        self.assertTrue((wt / "node_modules").is_dir())
        self.assertEqual(self.npm_calls(), ["npm --prefix %s ci --no-audit --no-fund (in %s)" % (wt, wt.resolve())])
        self.assertTrue((wt / "downloads").is_symlink())

    def test_no_main_node_modules_means_npm_ci(self):
        self.fake_origin("https://github.com/mark-brannan/portolani.git")
        (self.repo / "node_modules").rmdir()
        self.assertEqual(self.start("w1").returncode, 0)
        self.assertEqual(len(self.npm_calls()), 1)
        self.assertFalse((self.tmp / "w1" / "node_modules").is_symlink())

    def test_no_setup_skips_it(self):
        self.fake_origin("https://github.com/mark-brannan/portolani.git")
        r = self.start("w1", "--no-setup")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.tmp / "w1" / "node_modules"))
        self.assertFalse(os.path.lexists(self.tmp / "w1" / "downloads"))
        self.assertFalse(self.exclude.exists() and "node_modules" in self.exclude.read_text())

    def test_setup_needs_a_worktree(self):
        self.fake_origin("https://github.com/mark-brannan/portolani.git")
        r = subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), "--new", "w1"],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.repo / "node_modules").is_symlink())
        self.assertEqual(self.npm_calls(), [])

    def test_unknown_repo_gets_nothing_and_says_nothing(self):
        self.fake_origin("https://github.com/someone/else.git")
        r = self.start("w1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.tmp / "w1" / "node_modules"))
        self.assertEqual(self.npm_calls(), [])
        self.assertEqual([l for l in r.stdout.splitlines() if "ln" in l.split()[:2] or "npm" in l or "echo" in l], [])
        self.assertFalse(self.exclude.exists() and "node_modules" in self.exclude.read_text())

    def test_setup_leaves_what_is_there_alone(self):
        loader = importlib.machinery.SourceFileLoader("worker_start", str(TOOL))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("worker_start", loader))
        loader.exec_module(mod)
        self.fake_origin("https://github.com/mark-brannan/portolani.git")
        wt = self.tmp / "w1"
        sh("git", "-C", str(self.repo), "worktree", "add", "-q", "--detach", str(wt), "HEAD")
        (wt / "node_modules").mkdir()
        (wt / "node_modules" / "keep").write_text("x")
        (wt / "downloads").mkdir()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            mod.setup_portolani(str(self.repo), str(wt))
            mod.setup_portolani(str(self.repo), str(wt))
        self.assertEqual(out.getvalue().count("echo"), 2)  # the excludes, once
        self.assertNotIn("ln -s", out.getvalue())
        self.assertFalse((wt / "node_modules").is_symlink())
        self.assertFalse((wt / "downloads").is_symlink())
        self.assertTrue((wt / "node_modules" / "keep").exists())
        self.assertEqual(self.npm_calls(), [])

    def test_issue_alone_prints_the_issue_and_checks_out_nothing(self):
        r = subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), "--issue", "7"],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["$ gh issue view 7 --comments"])
        self.assertEqual(self.log.read_text().splitlines(), ["gh issue view 7 --comments"])
        self.assertEqual(sh("git", "-C", str(self.repo), "branch", "--list").split(), ["*", "main"])
        self.assertEqual(Path(str(self.log) + ".pwd").read_text().split(), [str(self.repo.resolve())])

    def test_nothing_to_do_is_a_usage_error(self):
        for args in ([], ["--worktree", "x"], ["--worktree", "x", "--issue", "7"]):
            r = subprocess.run([sys.executable, str(TOOL), "-C", str(self.repo), *args],
                               env=self.env, text=True, capture_output=True)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
