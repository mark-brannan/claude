#!/usr/bin/env python3
# Tests for mixed-loops-screen. Run: python3 bin/mixed-loops-screen.test.py
#
# Synthetic unified diffs, one per screen rule, a true mix that must still
# fail, and a design file whose hunks are part rename sync, part new sentence.
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "mixed-loops-screen.py"
spec = importlib.util.spec_from_loader("mixed_loops_screen", importlib.machinery.SourceFileLoader("mixed_loops_screen", str(TOOL)))
mls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mls)


def modified(path, old_lines, new_lines, start=10):
    body = "".join(f"-{l}\n" for l in old_lines) + "".join(f"+{l}\n" for l in new_lines)
    return (f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{start},{len(old_lines)} +{start},{len(new_lines)} @@ context\n{body}")


def added(path, lines):
    body = "".join(f"+{l}\n" for l in lines)
    return (f"diff --git a/{path} b/{path}\nnew file mode 100755\nindex 0000000..3333333\n--- /dev/null\n+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n{body}")


def deleted(path, lines):
    body = "".join(f"-{l}\n" for l in lines)
    return (f"diff --git a/{path} b/{path}\ndeleted file mode 100644\nindex 3333333..0000000\n--- a/{path}\n+++ /dev/null\n"
            f"@@ -1,{len(lines)} +0,0 @@\n{body}")


def binary(path):
    return f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\nBinary files a/{path} and b/{path} differ\n"


IMPL = modified("hooks/widget.py", ['CACHE = "state/widget.json"'], ['CACHE = "state/widget-cache.json"'])


def run(diff):
    files = mls.parse_diff(diff)
    return mls.evaluate(files, mls.diff_shebang(files))


class Rules(unittest.TestCase):
    def test_an_image_under_docs_is_neutral(self):
        design, impl, neutral = run(binary("docs/flow.png") + IMPL)
        self.assertEqual(design, [])
        self.assertEqual(neutral, [("docs/flow.png", "image")])

    def test_a_format_only_change_is_neutral(self):
        diff = modified("docs/guide.md",
                        ["* the widget  reads state", "| a | b |"],
                        ["- **the widget** reads `state`", "|a|b|"]) + IMPL
        self.assertEqual(run(diff)[2], [("docs/guide.md", "format")])

    def test_a_reflowed_paragraph_is_format_only(self):
        diff = modified("rules/code.md",
                        ["the widget reads state and", "writes nothing"],
                        ["the widget reads state", "and writes nothing"]) + IMPL
        self.assertEqual(run(diff)[2], [("rules/code.md", "format")])

    def test_up_to_three_small_typos_are_neutral(self):
        diff = modified("CLAUDE.md",
                        ["the widgit reads teh state and wirtes nothing"],
                        ["the widget reads the state and writes nothing"]) + IMPL
        self.assertEqual(run(diff)[2], [("CLAUDE.md", "typo")])

    def test_four_typos_are_not_typo_neutral(self):
        diff = modified("CLAUDE.md",
                        ["teh widgit reeds teh state"],
                        ["the widget reads the state"]) + IMPL
        self.assertEqual(run(diff)[0], ["CLAUDE.md"])

    def test_a_word_swap_past_distance_two_is_not_a_typo(self):
        diff = modified("CLAUDE.md", ["the widget never writes"], ["the widget always writes"]) + IMPL
        self.assertEqual(run(diff)[0], ["CLAUDE.md"])

    def test_a_path_renamed_in_step_with_the_code_is_rename_sync(self):
        diff = modified("hooks/widget-requirements.md",
                        ["The widget caches to `state/widget.json`, read on start."],
                        ["The widget caches to `state/widget-cache.json`, read on start."]) + IMPL
        self.assertEqual(run(diff)[2], [("hooks/widget-requirements.md", "rename sync")])

    def test_a_script_renamed_from_sh_to_py_matches_by_its_path(self):
        diff = (modified("docs/hooks.md",
                         ["- `hooks/old-gate.sh` stops the push; see bin/old-gate-helper"],
                         ["- `hooks/new-gate.py` stops the push; see bin/new-gate-helper"])
                + deleted("hooks/old-gate.sh", ["#!/bin/sh", "exit 0"])
                + added("hooks/new-gate.py", ["#!/usr/bin/env python3", "HELPER = 'bin/new-gate-helper'"])
                + "diff --git a/bin/old-gate-helper b/bin/old-gate-helper\ndeleted file mode 100755\n"
                  "--- a/bin/old-gate-helper\n+++ /dev/null\n@@ -1 +0,0 @@\n-#!/bin/sh\n")
        design, impl, neutral = run(diff)
        self.assertEqual(neutral, [("docs/hooks.md", "rename sync")])
        self.assertEqual(sorted(impl), ["bin/old-gate-helper", "hooks/new-gate.py", "hooks/old-gate.sh"])


class StillMixed(unittest.TestCase):
    def test_a_new_rule_beside_its_code_still_fails(self):
        diff = modified("hooks/widget-requirements.md",
                        ["The widget caches its state."],
                        ["The widget caches its state, and expires the cache after a day."]) + IMPL
        design, impl, _ = run(diff)
        self.assertEqual(design, ["hooks/widget-requirements.md"])
        self.assertEqual(impl, ["hooks/widget.py"])

    def test_one_substantive_hunk_spoils_a_rename_sync_file(self):
        rename = modified("docs/widget.md",
                          ["Cache: `state/widget.json`."], ["Cache: `state/widget-cache.json`."], start=5)
        diff = rename + "@@ -40,0 +40,1 @@\n+A stale cache is a bug, never a fallback.\n" + IMPL
        files = mls.parse_diff(diff)
        self.assertEqual(len(files[0].hunks), 2)
        self.assertEqual(run(diff)[0], ["docs/widget.md"])

    def test_a_deleted_design_file_is_never_neutral(self):
        diff = deleted("docs/old-layer.md", ["state/widget.json"]) + IMPL
        self.assertEqual(run(diff)[0], ["docs/old-layer.md"])

    def test_an_added_design_file_is_never_neutral(self):
        diff = added("docs/new.md", ["state/widget-cache.json"]) + IMPL
        self.assertEqual(run(diff)[0], ["docs/new.md"])


class Classification(unittest.TestCase):
    def test_paths_classify_as_the_guard_always_has(self):
        never = lambda p: False  # noqa: E731
        cases = {
            "CLAUDE.md": "design", "skills/x/CLAUDE.md": "design", "rules/code.md": "design",
            "docs/a/b.md": "design", "hooks/metrics-live-requirements.md": "design",
            "notes/x.adr.md": "design", "skills/curia/SKILL.md": "design", "skills/agora/brief.md": "design",
            "hooks/x.test.py": None, "tests/conftest.py": None, "lib/test_state.py": None, "x.examples.sh": None,
            "hooks/x.sh": "impl", "lib/state.py": "impl", "bin/q.jq": "impl", "settings.json": "impl",
            ".github/workflows/ci.yml": "impl", "README.md": None, "RUNBOOK.md": None, "skills/prt/SKILL.md": None,
        }
        for path, kind in cases.items():
            with self.subTest(path=path):
                self.assertEqual(mls.classify(path, never), kind)

    def test_a_shebang_seen_in_the_diff_makes_a_bin_file_implementation(self):
        diff = modified("docs/a.md", ["one thing"], ["another thing entirely here"]) + added("bin/tool", ["#!/bin/sh", "echo"])
        design, impl, _ = run(diff)
        self.assertEqual((design, impl), (["docs/a.md"], ["bin/tool"]))

    def test_a_renamed_file_classifies_by_its_new_path(self):
        diff = ("diff --git a/docs/old.md b/notes/old.md\nsimilarity index 100%\n"
                "rename from docs/old.md\nrename to notes/old.md\n")
        f = mls.parse_diff(diff)[0]
        self.assertEqual((f.status, f.path), ("renamed", "notes/old.md"))


class Cli(unittest.TestCase):
    def tool(self, *args, stdin=None, cwd=None):
        return subprocess.run([sys.executable, str(TOOL), *args], input=stdin, capture_output=True, text=True, cwd=cwd)

    def test_stdin_mix_exits_1_and_names_both_sets(self):
        diff = modified("docs/a.md", ["the cache lasts an hour"], ["the cache lasts a day, then expires"]) + IMPL
        r = self.tool("--diff", "-", stdin=diff)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("  docs/a.md", r.stdout)
        self.assertIn("  hooks/widget.py", r.stdout)

    def test_stdin_screened_out_exits_0_and_says_which_rule(self):
        diff = modified("docs/a.md", ["the widgit"], ["the widget"]) + IMPL
        r = self.tool("--diff", "-", stdin=diff)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "neutral: docs/a.md (typo)"))

    def test_bad_usage_exits_2(self):
        self.assertEqual(self.tool().returncode, 2)
        self.assertEqual(self.tool("--diff", "x").returncode, 2)

    def test_base_ref_mode_reads_the_branch_and_its_shebangs(self):
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
            git = lambda *a: subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", *a],  # noqa: E731
                                            check=True, capture_output=True, env=env)
            git("init", "-q", "-b", "main")
            Path(d, "docs").mkdir()
            Path(d, "docs/a.md").write_text("intro\nthe widgit reads state\noutro\n")
            Path(d, "tool").write_text("#!/bin/sh\necho one\n")
            git("add", ".")
            git("commit", "-qm", "base")
            git("checkout", "-qb", "work")
            Path(d, "docs/a.md").write_text("intro\nthe widget reads state\noutro\n")
            Path(d, "tool").write_text("#!/bin/sh\necho two\n")
            git("commit", "-qam", "typo and code")
            r = self.tool("main", cwd=d)
            self.assertEqual((r.returncode, r.stdout.strip()), (0, "neutral: docs/a.md (typo)"), r.stderr)
            Path(d, "docs/a.md").write_text("intro\nthe widget reads state and writes a log\noutro\n")
            git("commit", "-qam", "a new rule")
            r = self.tool("main", cwd=d)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("  tool", r.stdout)


if __name__ == "__main__":
    unittest.main()
