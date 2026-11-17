#!/usr/bin/env python3
"""Tests for session-start-github-limits.py. Run: python3 hooks/session-start-github-limits.test.py

Silent below warn and when no snapshot exists; one line for the worst
warn/over row of the latest snapshot; API quota rows speak like any other; garbage
never crashes. A scratch HOME, no network.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "session-start-github-limits.py"


def row(metric, value, limit, status, unit=""):
    return {"metric": metric, "value": value, "limit": limit, "unit": unit,
            "used": value / limit, "status": status, "note": ""}


class Line(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.snaps = self.home / ".local/state/github-limits/snapshots.jsonl"
        self.snaps.parent.mkdir(parents=True)

    def snap(self, *rows, at="2026-11-17T05:17:00Z"):
        with self.snaps.open("a") as f:
            f.write(json.dumps({"at": at, "rows": list(rows)}) + "\n")

    def run_hook(self):
        p = subprocess.run([sys.executable, str(HOOK)], input="{}", capture_output=True, text=True,
                           env={**os.environ, "HOME": str(self.home)}, timeout=10)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        return json.loads(p.stdout)["systemMessage"] if p.stdout.strip() else None

    def test_no_snapshot_is_silent(self):
        self.assertIsNone(self.run_hook())

    def test_ok_rows_are_silent(self):
        self.snap(row("deepest path", 5, 50, "ok"))
        self.assertIsNone(self.run_hook())

    def test_api_quota_rows_speak_like_any_other(self):
        self.snap(row("API core used this window", 4500, 5000, "warn"))
        self.assertEqual(self.run_hook(),
                         "github-limits: API core used this window 4,500 of 5,000 (90%), warn; "
                         "snapshot 2026-11-17T05:17Z; run `github-limits` for the table")

    def test_worst_row_with_count_of_the_rest(self):
        self.snap(row("remote branches", 3000, 5000, "warn"),
                  row("widest directory", 3100, 3000, "over", "entries"),
                  row("deepest path", 30, 50, "warn", "levels"))
        self.assertEqual(self.run_hook(),
                         "github-limits: widest directory 3,100 entries of 3,000 (103%), over; +2 more; "
                         "snapshot 2026-11-17T05:17Z; run `github-limits` for the table")

    def test_only_the_latest_snapshot_counts(self):
        self.snap(row("deepest path", 30, 50, "warn"))
        self.snap(row("deepest path", 5, 50, "ok"))
        self.assertIsNone(self.run_hook())

    def test_garbage_is_survived(self):
        self.snaps.write_text("not json\n[1]\n{\"rows\": 3}\n")
        self.assertIsNone(self.run_hook())


if __name__ == "__main__":
    unittest.main()
