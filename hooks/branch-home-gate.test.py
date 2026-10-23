#!/usr/bin/env python3
# Tests for branch-home-gate.py. Run: python3 hooks/branch-home-gate.test.py
#
# What matters: the quiet path really is quiet (default branch, detached
# HEAD, nothing ahead, no origin, not a repo); a PR, a work item or an open
# issue each count as a home, and a false substring match doesn't; nothing at
# all blocks once and only once per session; "cannot look" blocks rather than
# passing, and so does a crash. --check and --card answer one line each.
#
# Cost: about five seconds, local git repos and a fake gh; no network.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOKS = Path(__file__).resolve().parent
GATE = HOOKS / "branch-home-gate.py"
FAKE_GH = """#!/bin/sh
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: could not authenticate" >&2; exit 1; }
case "$1 ${2:-}" in
  "pr list")
    case " $* " in
      *" --head "*) printf '%s\\n' "${GH_PRS:-[]}" ;;
      *)            printf '%s\\n' "${GH_PRS_ALL:-[]}" ;;
    esac ;;
  "issue list") printf '%s\\n' "${GH_ISSUES:-[]}" ;;
  *) exit 1 ;;
esac
"""


def gitq(d, *args):
    subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *args],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        T = cls.T = Path(cls.tmp.name)
        cls.saved = dict(os.environ)
        (T / "home").mkdir()
        (T / "tmp").mkdir()
        sr = T / "claude_prompts_scratch"
        (sr / "state" / "global").mkdir(parents=True)
        gitq(sr, "init", "-q")
        cls.SR = sr
        cls.ITEMS = sr / "state" / "global" / "items"
        b = T / "bin"
        b.mkdir()
        (b / "gh").write_text(FAKE_GH)
        (b / "gh").chmod(0o755)
        # A PATH with git and sh but no gh, for "cannot look".
        nogh = T / "nogh"
        nogh.mkdir()
        for tool in ("git", "sh"):
            (nogh / tool).symlink_to(shutil.which(tool))
        cls.NOGH = str(nogh)
        os.environ.update(HOME=str(T / "home"), TMPDIR=str(T / "tmp"), GIT_CONFIG_GLOBAL="/dev/null",
                          GIT_CONFIG_NOSYSTEM="1", CLAUDE_STATE_REPO=str(sr),
                          WORK_ITEM_BIN=str(HOOKS.parent / "bin" / "work-item"),
                          PATH=f"{b}:{os.environ['PATH']}")
        for k in ("WORK_ITEM_DIR", "GH_PRS", "GH_PRS_ALL", "GH_ISSUES", "GH_FAIL"):
            os.environ.pop(k, None)
        cls.ORIGIN = T / "origin.git"
        cls.WORK = T / "work"

    @classmethod
    def tearDownClass(cls):
        os.environ.clear()
        os.environ.update(cls.saved)
        cls.tmp.cleanup()

    def setUp(self):
        shutil.rmtree(self.ITEMS, ignore_errors=True)
        self.item("1790000000aaaaaaaa", "Something else.")

    def item(self, id_, brief):
        self.ITEMS.mkdir(exist_ok=True)
        (self.ITEMS / f"{id_}.md").write_text(
            f"# Design\n\n## Brief\n{brief}\n\n## Log\n"
            "2026-10-03T05:00:00Z 1d68120b status=open owner=agent repo=- parent=- model=- effort=-\n"
            "2026-10-03T05:00:00Z 1d68120b status=ready\n")

    def repo(self, branch="", ahead=1):
        shutil.rmtree(self.ORIGIN, ignore_errors=True)
        shutil.rmtree(self.WORK, ignore_errors=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.ORIGIN)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.WORK)], check=True)
        gitq(self.WORK, "remote", "add", "origin", str(self.ORIGIN))
        (self.WORK / "f").write_text("one\n")
        gitq(self.WORK, "add", "--", "f")
        gitq(self.WORK, "commit", "-m", "one")
        gitq(self.WORK, "push", "-u", "origin", "main")
        if branch:
            gitq(self.WORK, "checkout", "-b", branch)
            if ahead:
                (self.WORK / "g").write_text("two\n")
                gitq(self.WORK, "add", "--", "g")
                gitq(self.WORK, "commit", "-m", "two")
            gitq(self.WORK, "push", "-u", "origin", branch)

    def stop(self, sid, cwd=None, active=False, path=None, **env):
        payload = json.dumps({"session_id": sid, "cwd": str(cwd or self.WORK), "stop_hook_active": active})
        e = dict(os.environ, **env)
        if path:
            e["PATH"] = path
        p = subprocess.run([sys.executable, str(GATE)], input=payload.encode(), env=e, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = p.stdout.decode()
        if not out:
            return "silent", ""
        d = json.loads(out)
        return ("block" if d.get("decision") == "block" else "other"), d.get("reason", "")

    def card(self, cwd=None, mode="--card", **env):
        p = subprocess.run([sys.executable, str(GATE), mode, str(cwd or self.WORK)],
                           env=dict(os.environ, **env), capture_output=True)
        return p.stdout.decode().rstrip("\n")

    def rec(self, sid):
        return self.T / "tmp" / f"claude-branch-home.{sid}"

    # --- the quiet path -----------------------------------------------------
    def test_quiet_path(self):
        self.repo()
        self.assertEqual(self.stop("q1")[0], "silent", "on the default branch")
        self.assertEqual(self.stop("q2", cwd=self.T)[0], "silent", "cwd is not a git repo")
        self.assertEqual(self.stop("q3", cwd=self.T / "nope")[0], "silent", "cwd does not exist")
        self.repo("claude/level", 0)
        self.assertEqual(self.stop("q4")[0], "silent", "branch level with origin/main")
        self.repo("claude/ahead")
        gitq(self.WORK, "checkout", "--detach")
        self.assertEqual(self.stop("q5")[0], "silent", "detached HEAD")
        gitq(self.WORK, "checkout", "claude/ahead")
        gitq(self.WORK, "remote", "remove", "origin")
        self.assertEqual(self.stop("q6")[0], "silent", "no origin remote")
        self.assertEqual(self.stop("", )[0], "silent", "no session id")

    # --- a home -------------------------------------------------------------
    def test_homes(self):
        self.repo("claude/homed")
        self.assertEqual(self.stop("h1", GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]')[0], "silent")
        # The store is local files, read before gh: a home even when gh fails.
        self.item("1790000002aaaaaaaa", "It lives on `claude/homed`.")
        self.assertEqual(self.stop("h2", GH_FAIL="1")[0], "silent", "a work item names the branch")
        self.item("1790000002aaaaaaaa", "Something else.")
        # kanban.md is not read: a card there, with the store empty, is no home.
        shutil.rmtree(self.ITEMS)
        kb = self.SR / "state" / "global" / "kanban.md"
        kb.write_text("# Board\n\n## Claude's\n- [ ] **Design lives on `claude/homed`** ([log](log/d.md))\n")
        self.assertEqual(self.stop("h2b", GH_FAIL="1")[0], "block", "a kanban.md card is not a home")
        kb.unlink()
        self.assertEqual(self.stop("h3", GH_ISSUES='[{"number":4,"title":"t","body":"the work is on claude/homed"}]')[0],
                         "silent", "an open issue names the branch")
        stack = ('[{"url":"https://github.com/o/r/pull/9",'
                 '"headRefName":"stack/mark-brannan/claude/homed/record-rulings--ad4fbbdd"}]')
        self.assertEqual(self.stop("h3b", GH_PRS_ALL=stack)[0], "silent", "a mergify stack PR has this head")

    def test_longer_branch_is_not_a_home(self):
        self.repo("claude/homed")
        self.item("1790000004aaaaaaaa", "Design lives on `claude/homed-extra`.")
        self.assertEqual(self.stop("h4", GH_FAIL="1")[0], "block")
        self.item("1790000004aaaaaaaa", "Something else.")
        self.assertEqual(self.stop("h5", GH_ISSUES='[{"number":5,"title":"t","body":"on claude/homed-extra"}]')[0],
                         "block")

    # --- no home ------------------------------------------------------------
    def test_no_home_blocks_once(self):
        self.repo("claude/orphan")
        got, reason = self.stop("b1")
        self.assertEqual(got, "block")
        for want in ("claude/orphan", "1 commit(s) ahead of origin/main", "open the PR", "/card-write",
                     "once per session", "in origin"):
            self.assertIn(want, reason)
        self.assertTrue(self.rec("b1").read_text().startswith("blocked"))
        self.assertEqual(self.stop("b1")[0], "silent", "a second Stop in the same session")
        self.assertEqual(self.stop("b2")[0], "block", "a different session blocks again")
        self.assertEqual(self.stop("b3", active=True)[0], "silent", "the retry within a turn is quiet")
        self.assertFalse(self.rec("b3").exists())
        gitq(self.WORK, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        got, reason = self.stop("b4")
        self.assertEqual(got, "block")
        self.assertIn("ahead of origin/main", reason)

    def test_odd_session_id_names_a_safe_marker(self):
        self.repo("claude/orphan")
        self.assertEqual(self.stop("a/b c")[0], "block")
        self.assertTrue(self.rec("a_b_c").exists())

    # --- cannot look is not a pass ------------------------------------------
    def test_cannot_look_blocks(self):
        self.repo("claude/orphan")
        got, reason = self.stop("u1", GH_FAIL="1")
        self.assertEqual(got, "block")
        self.assertIn("could not be verified", reason)
        self.assertIn("/card-write", reason)
        got, reason = self.stop("u2", path=self.NOGH)
        self.assertEqual(got, "block")
        self.assertIn("not installed", reason)
        self.assertEqual(self.stop("u3", active=True, path=self.NOGH)[0], "silent")

    def test_odd_gh_answers_are_no_home(self):
        self.repo("claude/orphan")
        self.assertEqual(self.stop("c1", GH_PRS='{"not":"a list"}')[0], "block")
        self.assertEqual(self.stop("c2", GH_PRS="[")[0], "block")

    def crashed(self, *args, payload=""):
        """Run the gate with where() raising; (stdout, stderr)."""
        code = ("import importlib.util, sys\n"
                f"sys.path.insert(0, {str(HOOKS)!r})\n"
                f"s = importlib.util.spec_from_file_location('g', {str(GATE)!r})\n"
                "g = importlib.util.module_from_spec(s); s.loader.exec_module(g)\n"
                "def boom(cwd): raise RuntimeError('boom')\n"
                "g.where = boom\n"
                f"g.main(['g', *{list(args)!r}])\n")
        p = subprocess.run([sys.executable, "-c", code], input=payload.encode(), capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.decode(), p.stderr.decode()

    def test_crash_fails_closed_and_traces(self):
        self.repo("claude/orphan")
        out, _ = self.crashed(payload=json.dumps({"session_id": "c3", "cwd": str(self.WORK)}))
        d = json.loads(out)
        self.assertEqual(d["decision"], "block")
        self.assertIn("RuntimeError: boom", d["reason"])
        rows = [json.loads(ln) for f in (self.SR / "state").rglob("*.jsonl") if "hook-errors" in f.parts
                for ln in f.read_text().splitlines()]
        self.assertTrue(any(r["hook"] == "branch-home-gate" and r["session_id"] == "c3" for r in rows), rows)
        out, _ = self.crashed(payload=json.dumps({"session_id": "c4", "cwd": str(self.WORK),
                                                  "stop_hook_active": True}))
        self.assertEqual(out, "", "the retry after a crash block is quiet")
        # A crash that repeats on the next turn's Stop, same session, no
        # stop_hook_active: still once per session.
        out, _ = self.crashed(payload=json.dumps({"session_id": "c3", "cwd": str(self.WORK), "turn": 2}))
        self.assertEqual(out, "", "a repeated crash blocks once per session")
        out, _ = self.crashed("--card", str(self.WORK))
        self.assertEqual(out, "unverified: branch-home-gate crashed (RuntimeError)\n")

    # --- --check and --card -------------------------------------------------
    def test_card(self):
        self.repo("claude/carded")
        self.assertEqual(self.card(GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]'),
                         "pr https://github.com/o/r/pull/7")
        self.assertEqual(self.card(GH_ISSUES='[{"number":4,"title":"t","body":"work on claude/carded",'
                                             '"url":"https://github.com/o/r/issues/4"}]'),
                         "issue https://github.com/o/r/issues/4")
        self.assertEqual(self.card(), "none")
        self.assertEqual(self.card(GH_FAIL="1"), "unverified: gh pr list failed (not authenticated here?)")
        # A local work item is a home but not a card.
        self.item("1790000005aaaaaaaa", "Design lives on `claude/carded`.")
        self.assertEqual(self.card(), "none")
        self.assertTrue(self.card(mode="--check").startswith("home: a work item in "))
        self.repo()
        self.assertEqual(self.card(), "none")
        self.assertEqual(self.card(self.T), "none")

    def test_check(self):
        before = set((self.T / "tmp").glob("claude-branch-home.*"))
        self.repo()
        self.assertEqual(self.card(mode="--check"), "home: on `main`")
        self.assertEqual(self.card(self.T, mode="--check"), "home: not a git repo")
        self.repo("claude/checked")
        self.assertEqual(self.card(mode="--check"), "none")
        self.assertEqual(self.card(mode="--check", GH_PRS='[{"url":"https://github.com/o/r/pull/7"}]'),
                         "home: https://github.com/o/r/pull/7 has this head")
        self.assertEqual(self.card(mode="--check", GH_FAIL="1"),
                         "unverified: gh pr list failed (not authenticated here?)")
        # --check never touches the once-per-session marker.
        self.assertEqual(set((self.T / "tmp").glob("claude-branch-home.*")), before)


if __name__ == "__main__":
    unittest.main()
