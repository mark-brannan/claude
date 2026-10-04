#!/usr/bin/env python3
# Tests for lib/state.py. Run: python3 lib/state.test.py
#
# What matters: the lookup is lib-state.sh's, not a second list -- an
# explicit CLAUDE_STATE_REPO wins, a machine with no repo gets the local
# fallback, and a missing lib-state.sh yields None rather than an exception.
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent / "state.py"
# lib-state.sh checks these before $HOME; a machine that has one cannot
# exercise the no-repo fallback.
CLOUD = ("/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch")


def load(path):
    spec = importlib.util.spec_from_file_location("state_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.T = Path(self.tmp.name)
        self.env = dict(os.environ)
        os.environ["HOME"] = str(self.T / "home")
        os.environ.pop("CLAUDE_STATE_REPO", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env)
        self.tmp.cleanup()

    def test_explicit_repo_wins(self):
        repo = self.T / "repo"
        (repo / ".git").mkdir(parents=True)
        os.environ["CLAUDE_STATE_REPO"] = str(repo)
        state = load(LIB)
        self.assertEqual(state.state_repo(), str(repo))
        self.assertEqual(state.state_dir(), f"{repo}/state/global")

    def test_home_path_lib_state_sh_knows(self):
        repo = self.T / "home" / "src" / "claude_prompts_scratch"
        (repo / ".git").mkdir(parents=True)
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        self.assertEqual(load(LIB).state_repo(), str(repo), "the search path is lib-state.sh's")

    def test_no_repo_falls_back_locally(self):
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here")
        state = load(LIB)
        self.assertIsNone(state.state_repo())
        self.assertEqual(state.state_dir(), f"{self.T}/home/.claude/state/global")

    def test_missing_lib_state_sh_is_none(self):
        (self.T / "lib").mkdir()
        shutil.copy(LIB, self.T / "lib" / "state.py")
        state = load(self.T / "lib" / "state.py")
        self.assertIsNone(state.state_repo())
        self.assertIsNone(state.state_dir())


if __name__ == "__main__":
    unittest.main()
