#!/usr/bin/env python3
# Tests for lib/libpath.py. Run: python3 lib/libpath.test.py
#
# What matters: every Python tool that finds lib/ does it with the one
# BOOTSTRAP text, and that text finds lib/ beside the tool first, then
# ~/.claude/lib.
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent
ROOT = LIB.parent
sys.path.insert(0, str(LIB))
from libpath import BOOTSTRAP  # noqa: E402

# A line that searches for lib/ any other way: a "lib" path joined onto
# sys.path, or ~/.claude/lib named outside BOOTSTRAP.
OTHER = re.compile(r'sys\.path\.insert\([^\n]*"lib"|~/\.claude/lib"|for \w+ in \([^\n]*"lib"')
# Hooks that find lib/ beside them only, through HOOK_DIR; not yet moved
# onto BOOTSTRAP.
BESIDE_ONLY = {"hooks/lib_state.py", "hooks/stop-continuity.py"}


def tools():
    for d in ("bin", "hooks"):
        for p in sorted((ROOT / d).iterdir()):
            if p.is_file() and not p.name.endswith((".test.py", ".sh", ".jq", ".awk", ".md")):
                try:
                    text = p.read_text()
                except UnicodeDecodeError:
                    continue
                if p.suffix == ".py" or text.startswith("#!/usr/bin/env python3"):
                    yield f"{d}/{p.name}", text


class OneHomeTest(unittest.TestCase):
    def test_every_tool_uses_bootstrap(self):
        users, strays = [], []
        for name, text in tools():
            if BOOTSTRAP in text:
                users.append(name)
                text = text.replace(BOOTSTRAP, "")
            if OTHER.search(text) and name not in BESIDE_ONLY:
                strays.append(name)
        self.assertEqual(strays, [], "find lib/ with lib/libpath.py's BOOTSTRAP, verbatim")
        for t in ("bin/work-item", "bin/scoping-lock", "bin/github-limits", "bin/prose-budget",
                  "bin/agent-decision", "hooks/curia-roll.py", "bin/prune-worktrees",
                  "bin/metrics-db", "bin/metrics-dashboard"):
            self.assertIn(t, users)

    def test_beside_first_then_seeded(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            for d in ("tree/bin", "tree/lib", "home/.claude/lib"):
                (t / d).mkdir(parents=True)
            (t / "tree/lib/a.py").write_text("WHERE = 'beside'\n")
            (t / "home/.claude/lib/a.py").write_text("WHERE = 'seeded'\n")
            (t / "home/.claude/lib/b.py").write_text("WHERE = 'seeded'\n")
            (t / "tree/bin/tool").write_text(f"import os, sys\nsys.dont_write_bytecode = True\n{BOOTSTRAP}\n"
                                             "import a, b\nprint(a.WHERE, b.WHERE)\n")
            (t / "link").symlink_to(t / "tree/bin/tool")  # found through a symlink, as on PATH
            for tool in (t / "tree/bin/tool", t / "link"):
                r = subprocess.run([sys.executable, str(tool)], capture_output=True, text=True,
                                   env={**os.environ, "HOME": str(t / "home")})
                self.assertEqual((r.returncode, r.stdout), (0, "beside seeded\n"), r.stderr)
            shutil.rmtree(t / "home/.claude")
            r = subprocess.run([sys.executable, str(t / "tree/bin/tool")], capture_output=True, text=True,
                               env={**os.environ, "HOME": str(t / "home")})
            self.assertIn("No module named 'b'", r.stderr, "no lib/ anywhere is an ImportError")

    def test_broken_state_is_not_a_missing_one(self):
        # A tool that treats "no state.py" as "no state repo" must not treat a
        # state.py that fails its own import (gitrun absent from a partial
        # lib/) the same way: that surfaces, naming the missing module.
        runs = {"bin/scoping-lock": [], "bin/work-item": ["dir"],
                "bin/metrics-db": [], "bin/metrics-dashboard": []}
        for name, args in runs.items():
            with tempfile.TemporaryDirectory() as t, self.subTest(name):
                t = Path(t)
                (t / "bin").mkdir()
                (t / "home").mkdir()
                shutil.copy(ROOT / name, t / name)
                env = {k: v for k, v in os.environ.items() if k != "WORK_ITEM_DIR"}
                env.update(HOME=str(t / "home"), PYTHONDONTWRITEBYTECODE="1")
                cmd = [sys.executable, str(t / name), *args]
                r = subprocess.run(cmd, capture_output=True, text=True, env=env)
                self.assertNotIn("Traceback", r.stderr, "no state.py is handled, not a crash")
                (t / "lib").mkdir()
                shutil.copy(LIB / "state.py", t / "lib")  # without the gitrun.py it imports
                r = subprocess.run(cmd, capture_output=True, text=True, env=env)
                self.assertIn("No module named 'gitrun'", r.stderr)
                self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
