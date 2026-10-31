#!/usr/bin/env python3
# Tests for metrics-rollup.py. Run: python3 hooks/metrics-rollup.test.py
#
# Each case builds a throwaway state repo, runs the hook as Stop does (a
# subprocess, CLAUDE_STATE_REPO pointing at it) and reads metrics.json back.
# METRICS_ROLLUP_HOOK names another script to drive through the same command
# line (the parity run against the old shell hook used it); a .sh runs under
# bash.
#
# Cost per push: well under a second.
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("METRICS_ROLLUP_HOOK") or Path(__file__).resolve().parent / "metrics-rollup.py").resolve()


class MetricsRollupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name).resolve() / "repo"
        (self.repo / (".g" + "it")).mkdir(parents=True)
        self.m = self.repo / "state/global/metrics"
        (self.m / "sessions").mkdir(parents=True)
        self.out = self.m / "metrics.json"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, rec, age_days=None):
        p = self.m / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rec if isinstance(rec, str) else json.dumps(rec))
        if age_days is not None:
            t = time.time() - age_days * 86400
            os.utime(p, (t, t))
        return p

    def run_hook(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        env["CLAUDE_STATE_REPO"] = str(self.repo)
        cmd = ["bash", str(HOOK)] if HOOK.suffix == ".sh" else [sys.executable, str(HOOK)]
        p = subprocess.run(cmd, capture_output=True, text=True, env=env)
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        return json.loads(self.out.read_text()) if self.out.exists() else None

    def test_junk_count_and_rate_per_day(self):
        self.put("sessions/a.json", {"session_id": "a", "started_at": "2026-09-21T10:00:00Z", "decisions": {"total": 4, "gate": 1, "junk": 1}})
        self.put("sessions/b.json", {"session_id": "b", "started_at": "2026-09-21T15:00:00Z", "decisions": {"total": 6, "gate": 0, "junk": 2}})
        self.put("sessions/c.json", {"session_id": "c", "started_at": "2026-09-22T09:00:00Z", "decisions": {"total": 2, "gate": 0, "junk": 0}})
        t = self.run_hook()["totals"]
        self.assertEqual(t["junk"], 3)
        self.assertEqual(t["junk_rate"], 25)
        self.assertEqual(t["junk_by_day"], [
            {"day": "2026-09-21", "decisions": 10, "junk": 3, "junk_rate": 30},
            {"day": "2026-09-22", "decisions": 2, "junk": 0, "junk_rate": 0}])

    def test_totals_and_order(self):
        self.put("sessions/a.json", {"session_id": "a", "started_at": "2026-09-22T00:00:00Z", "output_tokens": 10,
                                     "tool_calls": 2, "cache_churn_pct": 10, "decisions": {"total": 1, "gate": 1, "junk": 0}})
        self.put("sessions/x/b.json", {"session_id": "b", "started_at": "2026-09-21T00:00:00Z", "output_tokens": 5,
                                       "cache_churn_pct": 21, "updated_at": "2026-09-23T00:00:00Z"})
        r = self.run_hook()
        self.assertEqual([s["session_id"] for s in r["sessions"]], ["b", "a"])  # by started_at
        self.assertEqual(r["generated_at"], "2026-09-23T00:00:00Z")
        t = r["totals"]
        self.assertEqual((t["sessions"], t["output_tokens"], t["tool_calls"], t["decisions"], t["gates"]), (2, 15, 2, 1, 1))
        self.assertEqual(t["cache_churn_pct_avg"], 16)  # 15.5 rounds half up

    def test_finished_session_wins_over_its_live_snapshot(self):
        self.put("sessions/s.json", {"session_id": "s", "ended_at": "e", "output_tokens": 9, "updated_at": "1"})
        self.put("live/s.json", {"session_id": "s", "last_event": "x", "output_tokens": 3, "updated_at": "2"})
        self.put("live/t.json", {"session_id": "t", "output_tokens": 4, "updated_at": "1"})
        self.put("live/t2.json", {"session_id": "t", "output_tokens": 6, "ts": "2"})
        r = self.run_hook()
        by = {s["session_id"]: s["output_tokens"] for s in r["sessions"]}
        self.assertEqual(by, {"s": 9, "t": 6})  # no ended record: the latest snapshot

    def test_records_without_session_id_are_dropped_and_empty_totals_are_null(self):
        self.put("sessions/z.json", {"note": "no id"})
        r = self.run_hook()
        self.assertEqual(r["sessions"], [])
        self.assertEqual(r["generated_at"], "")
        self.assertEqual(r["totals"]["sessions"], 0)
        self.assertIsNone(r["totals"]["junk_rate"])
        self.assertIsNone(r["totals"]["output_tokens"])

    def test_old_live_files_are_pruned_and_not_counted(self):
        self.put("live/old.json", {"session_id": "old"}, age_days=20)
        self.put("live/tmp.json.123", "{", age_days=3)
        self.put("live/fresh.json.123", "{", age_days=0)
        self.put("sessions/a.json", {"session_id": "a"})
        r = self.run_hook()
        self.assertEqual([s["session_id"] for s in r["sessions"]], ["a"])
        self.assertFalse((self.m / "live/old.json").exists())
        self.assertFalse((self.m / "live/tmp.json.123").exists())
        self.assertTrue((self.m / "live/fresh.json.123").exists())

    CONFLICTED = ('{\n  "session_id": "n",\n<<<<<<< HEAD:a.nag.json\n  "x": 1\n=======\n'
                  '  "x": 2\n>>>>>>> abc (State: s):b.nag.json\n}\n')

    def traced(self):
        return [json.loads(ln) for f in (self.repo / "state/global/metrics/hook-errors").rglob("*.jsonl")
                for ln in f.read_text().splitlines()]

    def test_failed_rollup_leaves_previous_rollup_and_no_temp_file(self):
        self.out.write_text('{"keep": true}')
        self.put("sessions/a.json", {"session_id": "a"})
        self.put("sessions/list.json", "[1]")  # valid JSON, not a record: the rollup itself fails
        self.run_hook()
        self.assertEqual(json.loads(self.out.read_text()), {"keep": True})
        self.assertEqual([p.name for p in self.m.iterdir() if "metrics.json." in p.name], [])
        self.assertEqual([(r["hook"], r["stage"]) for r in self.traced()], [("metrics-rollup", "rollup")])

    def test_undecodable_file_is_skipped_and_traced_not_fatal(self):
        self.put("sessions/a.json", {"session_id": "a", "output_tokens": 7})
        self.put("sessions/bad.json", "{ not json")
        r = self.run_hook()
        self.assertEqual([s["session_id"] for s in r["sessions"]], ["a"])
        rows = self.traced()
        self.assertEqual([(r["hook"], r["stage"].split()[0]) for r in rows], [("metrics-rollup", "skip-file")])
        self.assertIn("bad.json", rows[0]["stage"])
        self.assertIn("JSONDecodeError", rows[0]["error"])

    def test_nag_state_files_are_skipped_silently(self):
        self.put("sessions/a.json", {"session_id": "a"})
        self.put("live/48/x.nag.json", self.CONFLICTED)
        self.put("live/y.nag.json", {"session_id": "nag"})
        r = self.run_hook()
        self.assertEqual([s["session_id"] for s in r["sessions"]], ["a"])
        self.assertEqual(self.traced(), [])

    def test_conflict_marked_session_file_is_skipped(self):
        self.put("sessions/a.json", {"session_id": "a"})
        self.put("live/48/c.json", self.CONFLICTED)
        r = self.run_hook()
        self.assertEqual([s["session_id"] for s in r["sessions"]], ["a"])
        self.assertEqual(len(self.traced()), 1)

    def test_no_inputs_or_no_metrics_dir_writes_nothing(self):
        self.assertIsNone(self.run_hook())
        (self.m / "sessions").rmdir()
        self.m.rmdir()
        self.assertIsNone(self.run_hook())


if __name__ == "__main__":
    unittest.main()
