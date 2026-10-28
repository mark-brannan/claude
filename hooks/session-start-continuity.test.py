#!/usr/bin/env python3
"""Tests for session-start-continuity.py. Run: python3 hooks/session-start-continuity.test.py

What matters: the board comes from `worklist --brief` and nowhere else; a
hung worklist costs at most 6 s and never loses the rest of the brief; a
missing worklist is named, not papered over; the state-repo-missing message
is unchanged; the decision-load and sitting-rung lines read both flat and
sharded per-session files. HOME and the state repo are fakes under a scratch
dir; `git` is a no-op shim so the courtesy pull never reaches the network.

Ported from session-start-continuity.test.sh, which was first run against
the .py (46 of 47 cases; the 47th, "no jq", has no meaning once jq is not
needed). Cost per push: about 7 s, one of them the 6 s hung-worklist case.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "session-start-continuity.py"

CHECKPOINT = ("- session abc — worked on the thing\n- next: more thing\n\n"
              "## Uncommitted at Stop\n M foo.sh\n\n## Other\n")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jl(*rows):
    return "".join(json.dumps(r) + "\n" for r in rows)


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home = t / "home"
        (self.home / ".claude/bin").mkdir(parents=True)
        (t / "bin").mkdir()
        shim = t / "bin/git"
        shim.write_text("#!/bin/sh\nexit 0\n")
        shim.chmod(0o755)
        self.state = t / "state"
        self.sd = self.state / "state/global"
        self.env = {"PATH": f"{t / 'bin'}:{os.environ['PATH']}", "HOME": str(self.home),
                    "CLAUDE_STATE_REPO": str(self.state), "TMPDIR": str(t)}
        self.reset_state()

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text):
        p = self.sd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def reset_state(self):
        subprocess.run(["rm", "-rf", str(self.state)], check=True)
        (self.state / ".git").mkdir(parents=True)
        self.put("log/auto/2026-01-01-1200-abc.md", CHECKPOINT)
        self.put("metrics/decisions/x.jsonl", jl({"ts": now(), "type": "gate"}, {"ts": now(), "type": "scoping"}))

    def worklist(self, body):
        p = self.home / ".claude/bin/worklist"
        p.write_text(f"#!/bin/sh\n{body}\n")
        p.chmod(0o755)

    def run_hook(self, env=None):
        t0 = time.time()
        r = subprocess.run([sys.executable, str(HOOK)], input='{"session_id":"t","hook_event_name":"SessionStart"}',
                           capture_output=True, text=True, env={**self.env, **(env or {})})
        self.elapsed = time.time() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        out = json.loads(r.stdout)
        self.assertEqual(list(out), ["hookSpecificOutput"])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.ctx = out["hookSpecificOutput"]["additionalContext"]
        return self.ctx

    # --- worklist present and fast ---

    def test_worklist_output_is_the_board(self):
        self.put("kanban.md", "# Board\n\n## Claude's\n\n- [x] TICKED-CARD-TEXT\n\n## Yours\n\n- [ ] LEGACY-SECTION-CARD\n")
        self.worklist('echo "as of 12:00Z (cached 3 min)"; echo "## Board"; echo "- WORKLIST-BOARD-LINE https://example.invalid/9"')
        c = self.run_hook()
        for want in ("as of 12:00Z (cached 3 min)", "WORKLIST-BOARD-LINE", "Where recent sessions left off",
                     "session abc", "Decision load, last 7 days", f"State repo: `{self.state}`"):
            self.assertIn(want, c)
        for gone in ("TICKED-CARD-TEXT", "LEGACY-SECTION-CARD", "Open board items", "worklist not installed"):
            self.assertNotIn(gone, c)
        self.assertLessEqual(self.elapsed, 3)

    def test_brief_order_and_text(self):
        self.worklist('echo BOARD')
        c = self.run_hook()
        self.assertEqual(c, (
            f"## Continuity brief\n\nState repo: `{self.state}` (board, checkpoints and metrics live here; the Stop\n"
            "hook commits and pushes to it automatically -- no need to be asked).\n\nBOARD\n"
            "\n### Where recent sessions left off\n\n**2026-01-01-1200-abc**\n"
            "- session abc — worked on the thing\n- next: more thing\n\n     M foo.sh\n\n"
            "\n### Decision load, last 7 days\n\n1 gate, 1 scoping\n"
            "\n`scoping` is cheap (asked before work exists),\n"
            "`gate` is expensive (open-ended, mid-flight, needs the user to reload\n"
            "context). Prefer front-loading questions; board the rest.\n"))

    # --- worklist missing, hung, failing, oversize ---

    def test_missing_worklist_is_named(self):
        c = self.run_hook()
        self.assertIn("worklist not installed -- live board view unavailable; this is not a clean state "
                      "(run dotsync / cloud-session-setup.sh)", c)
        self.assertIn("Decision load, last 7 days", c)

    def test_non_executable_worklist_is_missing(self):
        self.worklist("echo hi")
        (self.home / ".claude/bin/worklist").chmod(0o644)
        self.assertIn("worklist not installed", self.run_hook())

    def test_hung_worklist_is_cut_at_six_seconds(self):
        self.worklist('echo "as of 12:00Z"; sleep 30; echo "NEVER-PRINTED"')
        c = self.run_hook()
        self.assertLessEqual(self.elapsed, 8)
        self.assertIn("did not return in 6 s", c)
        self.assertIn("as of 12:00Z", c)
        self.assertNotIn("NEVER-PRINTED", c)
        self.assertIn("Where recent sessions left off", c)
        self.assertIn("Decision load, last 7 days", c)

    def test_failing_worklist_exit_is_named(self):
        self.worklist('echo "no gh"; exit 2')
        c = self.run_hook()
        self.assertIn("worklist --brief exited 2", c)
        self.assertIn("no gh", c)

    def test_broken_store_is_named_as_one(self):
        self.worklist('echo "Board: BROKEN STORE -- python3 not found"; echo "Pickup: open item"; exit 3')
        c = self.run_hook()
        self.assertIn("exited 3 -- the work-item store cannot be read", c)
        self.assertIn("Board: BROKEN STORE -- python3 not found", c)
        self.assertIn("Pickup: open item", c)

    def test_oversize_worklist_is_clipped(self):
        self.worklist('echo "as of 12:00Z"; yes xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx | head -400')
        c = self.run_hook()
        self.assertLess(len(c.encode()), 6000)
        self.assertIn("as of 12:00Z", c)

    # --- state repo missing, config line ---

    def test_state_repo_missing(self):
        subprocess.run(["rm", "-rf", str(self.state)], check=True)
        self.worklist('echo "as of 12:00Z"')
        c = self.run_hook({"CLAUDE_STATE_REPO": ""})
        self.assertTrue(c.startswith("## Continuity: state repo NOT available\n"))
        self.assertIn("mcp__Claude_Code_Remote__add_repo", c)
        self.assertNotIn("as of 12:00Z", c)

    def sync_file(self, text):
        (self.home / ".claude/.sync-status.json").write_text(text)

    def test_config_line_only_in_the_cloud(self):
        self.sync_file('{"complete":false}')
        self.assertTrue(self.run_hook().startswith("## Continuity brief"))

    def test_config_line_ok_degraded_and_absent(self):
        env = {"CLAUDE_CODE_REMOTE": "true"}
        self.assertTrue(self.run_hook(env).startswith(
            "config: DEGRADED — no .sync-status.json (installer never ran, or predates P1)\n\n## Continuity brief"))
        self.sync_file('{"complete":true,"sha":"0123456789abcdef","channel":"main","installed_at":"2026-01-01T00:00:00Z"}')
        self.assertTrue(self.run_hook(env).startswith(
            "config: main@0123456 (installed 2026-01-01T00:00:00Z)\n\n## Continuity brief"))
        self.sync_file('{"complete":false,"sha":"0123456789abcdef","channel":"main","installed_at":"t"}')
        self.assertTrue(self.run_hook(env).startswith("config: DEGRADED — incomplete install (main@0123456, t)\n\n"))
        self.sync_file('{"complete":true}')
        self.assertTrue(self.run_hook(env).startswith("config: null@null (installed null)\n\n"))
        self.sync_file("not json")
        self.assertTrue(self.run_hook(env).startswith("config: DEGRADED — incomplete install (@, )\n\n"))

    def test_config_line_leads_the_missing_state_message(self):
        subprocess.run(["rm", "-rf", str(self.state)], check=True)
        self.sync_file('{"complete":true,"sha":"abc","channel":"main","installed_at":"t"}')
        c = self.run_hook({"CLAUDE_CODE_REMOTE": "true", "CLAUDE_STATE_REPO": ""})
        self.assertTrue(c.startswith("config: main@abc (installed t)\n\n## Continuity: state repo NOT available"))

    # --- decisions per session-hour ---

    def test_week_ratio_and_last_session(self):
        self.worklist("echo 'as of 12:00Z'")
        self.put("metrics/sessions/a.json", jl({"ts": now(), "decisions": {"total": 3}, "friction": {"total": 2},
                                                  "prompt_span_seconds": 4200}))
        self.put("metrics/sessions/old.json", jl({"ts": "2000-01-01T00:00:00Z", "decisions": {"total": 99},
                                                    "friction": {"total": 0}, "prompt_span_seconds": 3600}))
        c = self.run_hook()
        self.assertIn("1 gate, 1 scoping · 2.6 decisions per session-hour", c)
        self.assertIn("last session: 3 decisions in 1h10 (2.6/h) · friction 2", c)
        subprocess.run(["rm", "-rf", str(self.sd / "metrics/sessions")], check=True)
        c = self.run_hook()
        self.assertNotIn("per session-hour", c)
        self.assertIn("Decision load, last 7 days", c)

    def test_unparseable_session_file_costs_only_the_ratio(self):
        self.put("metrics/sessions/a.json", "{not json")
        c = self.run_hook()
        self.assertNotIn("per session-hour", c)
        self.assertIn("1 gate, 1 scoping\n", c)

    def test_flat_and_sharded_files_are_read_together(self):
        self.put("metrics/decisions/ab/ab12.jsonl", jl({"ts": now(), "type": "gate"}))
        self.put("metrics/sessions/ab/ab12.json", jl({"ts": now(), "decisions": {"total": 4}, "friction": {"total": 0},
                                                       "prompt_span_seconds": 3600}))
        self.put("log/auto/ab/2026-01-02-repo-ab12.md", "- session ab12 — a sharded checkpoint\n\n")
        c = self.run_hook()
        self.assertIn("2 gate, 1 scoping", c)
        self.assertIn("last session: 4 decisions in 1h00", c)
        self.assertIn("2026-01-02-repo-ab12", c)
        self.assertIn("2026-01-01-1200-abc", c)

    def test_only_the_three_newest_checkpoints(self):
        for i in range(5):
            p = self.sd / f"log/auto/cp{i}.md"
            self.put(f"log/auto/cp{i}.md", f"- session s{i}\n\n")
            os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
        os.utime(self.sd / "log/auto/2026-01-01-1200-abc.md", (1_600_000_000, 1_600_000_000))
        c = self.run_hook()
        self.assertEqual([x for x in c.split("\n") if x.startswith("**")], ["**cp4**", "**cp3**", "**cp2**"])

    def test_old_decisions_do_not_count(self):
        self.put("metrics/decisions/x.jsonl", jl({"ts": "2000-01-01T00:00:00Z", "type": "gate"}))
        self.assertNotIn("Decision load", self.run_hook())

    # --- sitting rungs ---

    def test_rungs_median_and_stays_old_stamps_dropped(self):
        n = now()
        self.put("metrics/crossings/a.jsonl", jl(
            *[{"ts": n, "kind": "time_after", "at": 60, "min": m, "stay": m == 2} for m in (2, 5, 30)]))
        self.put("metrics/crossings/b.jsonl", jl(
            {"ts": n, "kind": "time_after", "at": 120, "min": 10, "stay": True},
            {"ts": n, "kind": "time_after", "at": 120, "min": 20, "stay": True},
            {"ts": "2020-01-01T00:00:00Z", "kind": "time_after", "at": 120, "min": 999, "stay": False},
            {"ts": n, "kind": "time", "at": 60}))
        self.assertIn("Sitting rungs, last 28 days: 60m: median 5m to next prompt, 1/3 stay · "
                      "120m: median 15m to next prompt, 2/2 stay", self.run_hook())

    def test_sitting_ends_latest_reading_stay_and_overrun(self):
        n = now()

        def last(c, m, o):
            return {"session_id": "s", "ts": n, "kind": "time_last", "at": 60, "crossing_ts": c, "min_to_last": m, "overrun": o}

        def after(c, m):
            return {"session_id": "s", "ts": n, "kind": "time_after", "at": 60, "crossing_ts": c, "stay_min": m}
        self.put("metrics/crossings/c.jsonl", jl(after("c1", 30), after("c4", 20), last("c1", 3, False), last("c1", 45, True),
                                                   last("c2", 8, None), last("c3", 60, None), last("c4", 25, False)))
        c = self.run_hook()
        self.assertIn("Sitting ends, last 28 days: 60m: median 35m to sitting end, 1/4 ended it, "
                      "stay median 25m, 1/2 overrun", c)

    def test_a_zero_minute_stay_counts(self):
        n = now()
        self.put("metrics/crossings/c.jsonl", jl(
            {"session_id": "s", "ts": n, "kind": "time_after", "at": 60, "crossing_ts": "c1", "stay_min": 0},
            {"session_id": "s", "ts": n, "kind": "time_last", "at": 60, "crossing_ts": "c1", "min_to_last": 5,
             "overrun": True}))
        self.assertIn("60m: median 5m to sitting end, 1/1 ended it, stay median 0m, 1/1 overrun", self.run_hook())

    def test_no_stamps_no_lines(self):
        c = self.run_hook()
        self.assertNotIn("Sitting rungs", c)
        self.assertNotIn("Sitting ends", c)

    def test_unparseable_crossings_print_nothing(self):
        self.put("metrics/crossings/a.jsonl", "{broken\n")
        c = self.run_hook()
        self.assertNotIn("Sitting", c)
        self.assertIn("Decision load", c)

    # --- held back from the state commit ---

    def test_the_brief_names_each_held_back_file_and_asks_for_a_resolution(self):
        # 12.7: whatever session wrote it, the next one is asked to offer the user a way out.
        (self.state / "drafts").mkdir()
        (self.state / "drafts/leak.md").write_text("x\n")
        (self.state / ".git/claude-held-back.json").write_text(json.dumps(
            [{"path": "drafts/leak.md", "reason": "secret scan: fake rule"},
             {"path": "drafts/gone.bin", "reason": "over 5 MB"}]))
        self.worklist("echo BOARD")
        c = self.run_hook()
        self.assertIn("drafts/leak.md", c)
        self.assertIn("secret scan: fake rule", c)
        self.assertNotIn("drafts/gone.bin", c, "a file resolved since is not raised")
        line = next(x for x in c.split("\n") if "offer the user" in x)
        for way in ("commit", "scrub", "move", "gitignore"):
            self.assertIn(way, line)
        self.assertLess(c.index("drafts/leak.md"), c.index("Where recent sessions left off"))

    def test_nothing_held_back_says_nothing(self):
        self.worklist("echo BOARD")
        self.assertNotIn("Held back", self.run_hook())


if __name__ == "__main__":
    unittest.main()
