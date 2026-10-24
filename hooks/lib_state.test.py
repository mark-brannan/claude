#!/usr/bin/env python3
# Tests for hooks/lib_state.py, the shim over lib/state.py.
# Run: python3 hooks/lib_state.test.py
#
# What matters: the hooks' import still works and gets lib/state.py's
# functions, not a copy; and with lib/ missing (a seed whose INSTALL lacks
# it) the shim fails open -- a hook that imports it still exits 0.
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
sys.path.insert(0, str(HOOKS))
import lib_state  # noqa: E402
import state  # noqa: E402  (on sys.path now, put there by the shim)


class ShimTest(unittest.TestCase):
    def test_reexports_lib_state_dir(self):
        self.assertIs(lib_state.state_dir, state.state_dir)
        self.assertIs(lib_state.state_repo, state.state_repo)
        self.assertEqual(Path(state.__file__).resolve(), HOOKS.parent / "lib" / "state.py")

    def test_missing_lib_fails_open(self):
        with tempfile.TemporaryDirectory() as t:
            hooks = Path(t) / "hooks"
            hooks.mkdir()
            for f in ("lib_state.py", "curia-roll.py", "curia_words.py"):
                shutil.copy(HOOKS / f, hooks / f)
            env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "HOME": t, "CLAUDE_STATE_REPO": ""}
            p = subprocess.run([sys.executable, "-c",
                                "import lib_state; print(lib_state.state_dir(), lib_state.state_repo())"],
                               cwd=hooks, env=env, capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "None None"))
            self.assertIn("lib/state.py not importable", p.stderr, "says why, on stderr")
            ev = json.dumps({"session_id": "s", "prompt": "/curia x"})
            p = subprocess.run([sys.executable, str(hooks / "curia-roll.py")], input=ev,
                               env=env, capture_output=True, text=True)
            self.assertEqual((p.returncode, p.stdout), (0, ""), "a hook on the shim still exits 0")


class TraceFailureTest(unittest.TestCase):
    def test_stage_and_session_reach_the_row(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / ".git").mkdir()
            old = os.environ.get("CLAUDE_STATE_REPO")
            os.environ["CLAUDE_STATE_REPO"] = t
            lib_state.LAST["session_id"] = "ab6"
            try:
                lib_state.trace_failure("some-hook", "Stop", ValueError("x"), "read")
                lib_state.trace_failure("some-hook", "Stop", ValueError("y"))
            finally:
                lib_state.LAST.clear()
                if old is None:
                    os.environ.pop("CLAUDE_STATE_REPO")
                else:
                    os.environ["CLAUDE_STATE_REPO"] = old
            rows = [json.loads(ln) for ln in
                    (Path(t) / "state/global/metrics/hook-errors/ab/ab6.jsonl").read_text().splitlines()]
            self.assertEqual([(r["hook"], r["event"], r["stage"], r["error"]) for r in rows],
                             [("some-hook", "Stop", "read", "ValueError: x"), ("some-hook", "Stop", "main", "ValueError: y")])


if __name__ == "__main__":
    unittest.main()
