#!/usr/bin/env python3
"""Tests for prune-scratch. Run: python3 bin/prune-scratch.test.py

A scratch HOME holds a fake scratch root with backdated session dirs (one
per keep rule), real git checkouts (unpushed, dirty, no remote, clean and
pushed to a local bare repo), and a fake process-cwd provider. Cost per
push: about a second, no network."""
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.dont_write_bytecode = True
TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prune-scratch")
_loader = importlib.machinery.SourceFileLoader("prune_scratch", TOOL)
_spec = importlib.util.spec_from_loader("prune_scratch", _loader)
ps = importlib.util.module_from_spec(_spec)
_loader.exec_module(ps)

GITENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(repo, *a):
    subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", *a], check=True,
                   capture_output=True, env=dict(os.environ, **GITENV))


def backdate(top, days):
    t = time.time() - days * 86400
    for d, dirs, files in os.walk(top, topdown=False):
        for n in files + dirs:
            os.utime(os.path.join(d, n), (t, t), follow_symlinks=False)
    os.utime(top, (t, t))


class PruneScratch(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        self.root = os.path.join(self.home, ".local", "state", "claude-tmpdir")
        self.base = os.path.join(self.root, f"claude-{os.getuid()}")
        self.old_env = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self.old_env)))
        os.environ.pop("CLAUDE_CODE_TMPDIR", None)
        os.environ.update(GITENV, HOME=self.home)
        self.remote = os.path.join(self.home, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.remote], check=True)

    def session(self, name, slug="-home-p", files=("out.txt",)):
        path = os.path.join(self.base, slug, name)
        os.makedirs(path)
        for f in files:
            with open(os.path.join(path, f), "w") as fh:
                fh.write("x" * 5000)
        return path

    def checkout(self, parent, pushed=True, remote=True):
        co = os.path.join(parent, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", co], check=True)
        with open(os.path.join(co, ".gitignore"), "w") as f:
            f.write("build/\n")
        git(co, "add", ".gitignore")
        git(co, "commit", "-q", "-m", "base")
        if remote:
            git(co, "remote", "add", "origin", self.remote)
            git(co, "push", "-q", "origin", f"HEAD:refs/heads/{os.path.basename(parent)}")
            git(co, "fetch", "-q", "origin")
        if not pushed:
            git(co, "commit", "-q", "--allow-empty", "-m", "local only")
        os.makedirs(os.path.join(co, "build"))
        open(os.path.join(co, "build", "a.o"), "w").close()
        return co

    def run_tool(self, *argv, cwds=frozenset(), sessions=frozenset()):
        out, err = io.StringIO(), io.StringIO()
        provider = (lambda: None) if cwds is None else (lambda: set(cwds))
        with redirect_stdout(out), redirect_stderr(err):
            rc = ps.main(list(argv), cwds_provider=provider, sessions_provider=lambda: set(sessions))
        return rc, out.getvalue() + err.getvalue()

    def held(self):
        with open(os.path.join(self.home, ".local", "state", "prune-scratch", "held.json")) as f:
            return json.load(f)

    def tree(self):
        s = {}
        s["old"] = self.session("old")
        s["recent"] = self.session("recent")
        s["live"] = self.session("live")
        s["pushed"] = self.session("pushed"); self.checkout(s["pushed"])
        s["unpushed"] = self.session("unpushed"); self.checkout(s["unpushed"], pushed=False)
        s["dirty"] = self.session("dirty")
        open(os.path.join(self.checkout(s["dirty"]), "new.txt"), "w").close()
        s["noremote"] = self.session("noremote"); self.checkout(s["noremote"], remote=False)
        s["young-unpushed"] = self.session("young-unpushed")
        self.checkout(s["young-unpushed"], pushed=False)
        s["touched"] = self.session("touched", slug="-home-q")
        for k, p in s.items():
            backdate(p, {"recent": 2, "young-unpushed": 1}.get(k, 20))
        # one fresh file deep inside an otherwise old dir keeps it
        with open(os.path.join(s["touched"], "deep.txt"), "w") as f:
            f.write("now")
        return s

    def test_dry_run_names_candidates_and_removes_nothing(self):
        s = self.tree()
        rc, out = self.run_tool(cwds={s["live"] + "/sub"})
        self.assertEqual(rc, 0, out)
        for k in ("old", "pushed"):
            self.assertIn(f"would remove {s[k]} (", out)
        for k in ("recent", "live", "unpushed", "dirty", "noremote", "young-unpushed", "touched"):
            self.assertNotIn(f"would remove {s[k]} ", out)
        self.assertIn("would remove 2 session dir(s)", out)
        self.assertTrue(all(os.path.isdir(p) for p in s.values()))

    def test_delete_removes_only_safe_dirs_and_writes_held(self):
        s = self.tree()
        rc, out = self.run_tool("--delete", cwds={s["live"]})
        self.assertEqual(rc, 0, out)
        gone = {k for k, p in s.items() if not os.path.exists(p)}
        self.assertEqual(gone, {"old", "pushed"}, out)
        held = {h["path"]: h for h in self.held()}
        self.assertEqual(set(held), {s["unpushed"], s["dirty"], s["noremote"]})
        self.assertIn("commit(s) on no remote", held[s["unpushed"]]["reason"])
        self.assertIn("uncommitted", held[s["dirty"]]["reason"])
        self.assertIn("no remote", held[s["noremote"]]["reason"])
        self.assertGreater(held[s["unpushed"]]["age_days"], 19)

    def test_held_is_rewritten_empty_when_nothing_holds(self):
        s = self.tree()
        self.run_tool()
        self.assertTrue(self.held())
        for k in ("unpushed", "dirty", "noremote", "young-unpushed"):
            subprocess.run(["rm", "-rf", s[k]], check=True)
        self.run_tool()
        self.assertEqual(self.held(), [])

    def test_empty_project_dir_removed(self):
        p = self.session("only", slug="-home-solo")
        backdate(p, 30)
        self.run_tool("--delete")
        self.assertFalse(os.path.exists(os.path.dirname(p)))

    def test_unreadable_cwds_removes_nothing(self):
        s = self.tree()
        rc, out = self.run_tool("--delete", cwds=None)
        self.assertIn("removing nothing", out)
        self.assertTrue(all(os.path.isdir(p) for p in s.values()))
        self.assertEqual(len(self.held()), 3)

    def test_real_process_cwd_keeps_dir(self):
        p = self.session("busy")
        backdate(p, 30)
        proc = subprocess.Popen(["sleep", "30"], cwd=p)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            ps.main(["--delete"])
        self.assertTrue(os.path.isdir(p), out.getvalue())

    def test_days_option(self):
        p = self.session("mid")
        backdate(p, 6)
        self.run_tool("--delete")
        self.assertTrue(os.path.isdir(p))
        self.run_tool("--delete", "--days", "5")
        self.assertFalse(os.path.exists(p))

    def test_refuses_root_outside_home_or_home_itself(self):
        for root in ("/tmp", self.home):
            os.environ["CLAUDE_CODE_TMPDIR"] = root
            rc, out = self.run_tool("--delete")
            self.assertEqual(rc, 2, out)
            self.assertIn("refusing", out)

    def test_tree_past_walk_cap_is_held_not_removed(self):
        p = self.session("huge", files=[f"f{i}" for i in range(10)])
        backdate(p, 30)
        cap = ps.WALK_CAP
        ps.WALK_CAP = 5
        self.addCleanup(setattr, ps, "WALK_CAP", cap)
        self.run_tool("--delete")
        self.assertTrue(os.path.isdir(p))
        self.assertEqual([h["path"] for h in self.held()], [p])

    def test_empty_dot_git_dir_is_scratch(self):
        p = self.session("leftover")
        os.makedirs(os.path.join(p, "x", ".git"))
        backdate(p, 30)
        self.run_tool("--delete")
        self.assertFalse(os.path.exists(p))

    def test_cwd_seen_through_a_symlinked_root_keeps_dir(self):
        real = os.path.join(self.home, "elsewhere")
        os.makedirs(real)
        link = os.path.join(self.home, "linked-tmp")
        os.symlink(real, link)
        os.environ["CLAUDE_CODE_TMPDIR"] = link
        p = os.path.join(link, f"claude-{os.getuid()}", "-home-p", "s1")
        os.makedirs(p)
        backdate(p, 30)
        self.run_tool("--delete", cwds={os.path.realpath(p)})
        self.assertTrue(os.path.isdir(p))

    def test_registered_live_session_keeps_its_dir(self):
        p = self.session("1234-live-session")
        backdate(p, 30)
        reg = os.path.join(self.home, "sessions")
        os.makedirs(reg)
        with open(os.path.join(reg, f"{os.getpid()}.json"), "w") as f:
            json.dump({"pid": os.getpid(), "sessionId": "1234-live-session", "status": "idle",
                       "procStart": ps.state._proc_start(os.getpid(), "/proc")}, f)
        os.environ["CLAUDE_SESSIONS_DIR"] = reg
        self.assertEqual(ps.registered_live(), {"1234-live-session"})
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            ps.main(["--delete"], cwds_provider=set)
        self.assertTrue(os.path.isdir(p))

    def test_stash_and_unborn_branch_commits_hold(self):
        st = self.session("stash")
        co = self.checkout(st)
        with open(os.path.join(co, ".gitignore"), "a") as f:
            f.write("x\n")
        git(co, "stash", "-q")
        orphan = self.session("orphan")
        co = self.checkout(orphan)
        git(co, "branch", "side")
        git(co, "checkout", "-q", "side")
        git(co, "commit", "-q", "--allow-empty", "-m", "local only")
        git(co, "checkout", "-q", "--orphan", "fresh")
        git(co, "rm", "-rfq", "--cached", ".")
        os.remove(os.path.join(co, ".gitignore"))
        subprocess.run(["rm", "-rf", os.path.join(co, "build")], check=True)
        for p in (st, orphan):
            backdate(p, 30)
        self.run_tool("--delete")
        self.assertTrue(os.path.isdir(st))
        self.assertTrue(os.path.isdir(orphan))
        self.assertEqual({h["path"] for h in self.held()}, {st, orphan})

    def test_dangling_worktree_git_file_is_scratch(self):
        p = self.session("dangling")
        os.makedirs(os.path.join(p, "wt"))
        with open(os.path.join(p, "wt", ".git"), "w") as f:
            f.write("gitdir: /nowhere/.git/worktrees/wt\n")
        backdate(p, 30)
        self.run_tool("--delete")
        self.assertFalse(os.path.exists(p))

    def test_symlinked_session_dir_is_not_followed(self):
        outside = os.path.join(self.home, "precious")
        os.makedirs(outside)
        open(os.path.join(outside, "keep"), "w").close()
        backdate(outside, 30)
        os.makedirs(os.path.join(self.base, "-home-p"))
        os.symlink(outside, os.path.join(self.base, "-home-p", "link"))
        self.run_tool("--delete")
        self.assertTrue(os.path.exists(os.path.join(outside, "keep")))


if __name__ == "__main__":
    unittest.main()
