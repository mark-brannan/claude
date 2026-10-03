#!/usr/bin/env python3
# Tests for languette-step-two's edit, against a copy of this checkout's own
# files, so a change to main that the hourly job could no longer edit fails
# here first. Run: python3 bin/languette-step-two.test.py
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("step_two", str(REPO / "bin/languette-step-two"))
spec = importlib.util.spec_from_loader("step_two", loader)
st = importlib.util.module_from_spec(spec)
loader.exec_module(st)

FILES = [".claude/settings.json", ".local/bin/cloud-session-setup.sh", ".github/workflows/ci.yml"] + [
    f".claude/hooks/{g}{s}" for g in st.GUARDS for s in (".sh", ".test.sh")]


# The job runs this suite on its own edited tree, where the copies are gone.
@unittest.skipUnless(all((REPO / f).exists() for f in FILES), "step two has landed: no copies left to edit")
class EditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self.tmp.name)
        for f in FILES:
            (self.tree / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / f, self.tree / f)

    def tearDown(self):
        self.tmp.cleanup()

    def text(self, f):
        return (self.tree / f).read_text()

    def test_removes_every_copy_and_keeps_the_rest(self):
        st.edit(self.tree)
        for g in st.GUARDS:
            self.assertFalse((self.tree / f".claude/hooks/{g}.sh").exists())
            for f in FILES[:3]:
                self.assertNotIn(f"hooks/{g}.sh", self.text(f))
                self.assertNotIn(f"{g}.test.sh", self.text(f))
        self.assertIn(".claude/hooks/lib-shell-words.awk", self.text(".local/bin/cloud-session-setup.sh"))
        self.assertIn("no-checkout-home.sh", self.text(".claude/settings.json"))
        self.assertIn("for t in .claude/hooks/no-foreign-worktree.test.sh \\\n", self.text(".github/workflows/ci.yml"))

    def test_settings_stay_valid_json_and_only_three_entries_go(self):
        before = json.loads(self.text(".claude/settings.json"))
        st.edit(self.tree)
        after = json.loads(self.text(".claude/settings.json"))
        count = lambda d: sum(len(m["hooks"]) for m in d["hooks"]["PreToolUse"])  # noqa: E731
        self.assertEqual(count(before) - count(after), 3)

    def test_seeded_step_is_found_and_passes(self):
        st.edit(self.tree)
        shutil.copytree(REPO / ".claude/hooks", self.tree / ".claude/hooks", dirs_exist_ok=True,
                        ignore=lambda d, names: [n for n in names if any(n.startswith(g + ".") for g in st.GUARDS)])
        r = subprocess.run(["bash", "-euo", "pipefail", "-c", st.seeded_script(self.tree)], cwd=self.tree,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_settings_reformatted_refuses(self):
        sp = self.tree / ".claude/settings.json"
        sp.write_text(json.dumps(json.loads(sp.read_text()), indent=4) + "\n")
        with self.assertRaisesRegex(RuntimeError, "round-trips"):
            st.edit(self.tree)

    def test_a_shape_it_cannot_edit_refuses(self):
        ci = self.tree / ".github/workflows/ci.yml"
        ci.write_text(ci.read_text() + "      # see .claude/hooks/no-rm-tree.test.sh; done\n")
        with self.assertRaisesRegex(RuntimeError, "edit by hand"):
            st.edit(self.tree)


if __name__ == "__main__":
    unittest.main()
