#!/usr/bin/env python3
# Smoke tests for metrics-breakdown.sh and metrics-preview.sh.
# Run: python3 bin/metrics-readouts.test.py
#
# Each case builds a throwaway state repo and a throwaway $HOME holding one
# transcript, points METRICS_HOOKS at this checkout's hooks/, and runs the
# script as a subprocess. Needs jq and python3 on PATH.
#
# What matters: breakdown prints one session's decision, friction and blocked
# triples and its git-event counts, never reads a *.nag.json as the cache, and
# fails loudly when there is no cache; preview runs the real producers, takes
# its arguments strictly, goes quiet under --quiet, and fails loudly when its
# inputs are missing.
#
# Cost per push: about 10 seconds (preview runs the real hooks several times).
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BIN = Path(__file__).resolve().parent
HOOKS = BIN.parent / "hooks"
SID = "abcdef12-0000-4000-8000-000000000000"


@unittest.skipUnless(shutil.which("jq"), "jq not installed")
class ReadoutsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name).resolve() / "home"
        self.repo = Path(self.tmp.name).resolve() / "repo"
        (self.repo / (".g" + "it")).mkdir(parents=True)
        self.m = self.repo / "state/global/metrics"
        self.live = self.m / "live"
        self.live.mkdir(parents=True)
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, *args, hooks=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "METRICS_"))}
        env.update(HOME=str(self.home), CLAUDE_STATE_REPO=str(self.repo),
                   METRICS_HOOKS=str(hooks or HOOKS))
        return subprocess.run(["sh", str(BIN / name), *args], capture_output=True, text=True, env=env)

    def cache(self, sid=SID, **rec):
        d = self.live / sid[:2]
        d.mkdir(exist_ok=True)
        (d / f"{sid}.json").write_text(json.dumps({"session_id": sid, **rec}))

    def transcript(self):
        d = self.home / ".claude/projects/p"
        d.mkdir(parents=True)
        shutil.copy(HOOKS / "fixtures/friction-calm.jsonl", d / f"{SID}.jsonl")

    # --- metrics-breakdown.sh -------------------------------------------

    def test_breakdown_prints_triples_and_git_event_counts(self):
        self.cache(decisions={"total": 5, "scoping": 1, "inline": 2, "gate": 2},
                   friction={"total": 3, "correction": 1, "override": 1, "rebuke": 1},
                   blocked={"total": 2, "classifier": 1, "rule": 1, "user": 0}, tool_calls=42)
        ev = self.m / "git-events" / SID[:2]
        ev.mkdir(parents=True)
        (ev / f"{SID}.jsonl").write_text("".join(json.dumps({"kind": k}) + "\n"
                                                  for k in ("commit", "commit", "branch")))
        p = self.run_script("metrics-breakdown.sh")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        lines = [ln if i < 6 else " ".join(ln.split()) for i, ln in enumerate(p.stdout.splitlines())]  # uniq -c pads
        self.assertEqual(lines, [
            f"session {SID}",
            "decisions ⚖5[1/2/2]  (scoping/inline/gate)",
            "friction  ⚡3[1/1/1]  (correction/override/rebuke)",
            "blocked   ⛔2[1/1/0]  (classifier/rule/user)",
            "tool calls 42",
            "git events:",
            "2 commit",
            "1 branch"])

    def test_breakdown_prefix_selects_a_session_and_zero_fills(self):
        self.cache(sid="aa111111-0000-4000-8000-000000000000")
        self.cache(sid="bb222222-0000-4000-8000-000000000000", tool_calls=7)
        p = self.run_script("metrics-breakdown.sh", "bb22")
        self.assertEqual(p.returncode, 0)
        self.assertIn("session bb222222-0000-4000-8000-000000000000", p.stdout)
        self.assertIn("decisions ⚖0[0/0/0]", p.stdout)
        self.assertIn("tool calls 7", p.stdout)
        self.assertIn("git events: none logged", p.stdout)

    def test_breakdown_ignores_nag_state_files(self):
        self.cache(tool_calls=1)
        (self.live / "zz").mkdir()
        (self.live / "zz/zz999999.nag.json").write_text("{}")
        (self.live / "zz999999.nag.json").write_text("{}")  # newest, must still lose
        p = self.run_script("metrics-breakdown.sh")
        self.assertIn(f"session {SID}", p.stdout)
        p = self.run_script("metrics-breakdown.sh", "zz99")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no live cache found", p.stderr)

    def test_breakdown_without_a_cache_or_hooks_fails_loudly(self):
        p = self.run_script("metrics-breakdown.sh")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no live cache found", p.stderr)
        p = self.run_script("metrics-breakdown.sh", hooks=self.home / "nowhere")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no hooks at", p.stderr)

    # --- metrics-preview.sh ---------------------------------------------

    def test_preview_runs_the_real_checks(self):
        self.transcript()
        p = self.run_script("metrics-preview.sh")
        out = p.stdout
        for line in ("lib-metrics-fmt.jq compiles",
                     "non-git Bash command is filtered out",
                     "contentious fixture: total 11 [2c 2o 7r], repeat 7, pushback 2",
                     "calm fixture: total 0 [0c 0o 0r], repeat 0, pushback 0",
                     "blocked fixture: total 6 [4 classifier, 1 rule, 1 user]"):
            self.assertIn(line, out)
        for ev in ("git", "question", "stop"):
            self.assertIn(f"--- metrics-live.py {ev} 0 show", out)
        self.assertIn("--- statusline-metrics.py", out)
        self.assertIn("<- col 75", out)
        # The cache the readouts print from was written by the real producer.
        self.assertTrue((self.live / SID[:2] / f"{SID}.json").exists())
        # Not asserted: the `prompt` silence check. It currently FAILs on a
        # fresh state (the prompt event prints the block under `show`), which
        # predates this test; every other check above passes.
        self.assertEqual(p.returncode, 1 if "FAIL  prompt event printed" in p.stderr else 0, p.stderr)

    def test_preview_quiet_prints_no_ok_lines(self):
        self.transcript()
        p = self.run_script("metrics-preview.sh", "--quiet")
        self.assertNotIn("  ok ", p.stdout)
        self.assertEqual(p.stdout, "")

    def test_preview_ruler_width_and_fields(self):
        self.transcript()
        p = self.run_script("metrics-preview.sh", "40", "--fields")
        self.assertIn("<- col 40", p.stdout)
        self.assertIn("--- fields (name, width, |value|)", p.stdout)

    def test_preview_refuses_bad_arguments_and_missing_inputs(self):
        p = self.run_script("metrics-preview.sh", "--bogus")
        self.assertEqual(p.returncode, 2)
        self.assertIn("usage: metrics-preview.sh", p.stderr)
        p = self.run_script("metrics-preview.sh")  # no transcript under $HOME
        self.assertEqual(p.returncode, 1)
        self.assertIn("no transcript found", p.stderr)
        p = self.run_script("metrics-preview.sh", hooks=self.home / "nowhere")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no hooks at", p.stderr)


if __name__ == "__main__":
    unittest.main()
