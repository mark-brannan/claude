#!/usr/bin/env python3
# Tests for stop-sequence.py. Run: python3 .claude/hooks/stop-sequence.test.py
#
# Cost per push: about three seconds (one deliberate 2s timeout), a step in
# CI's existing tool-tests job, so no new job and nothing drawn from the
# account's concurrent-job cap. stop-continuity.test.sh runs the sequence
# against the real hooks; these cases stub both hooks to pin the sequencing
# itself: order, the STOP_VERDICT_SINCE handoff, whose stdout passes, and
# fail-open on a hung first hook.
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "stop-sequence.py"


class StopSequenceTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copy(HOOK, self.dir / "stop-sequence.py")
        self.log = self.dir / "log"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def stub(self, name, body):
        (self.dir / name).write_text("#!/bin/bash\n" + body + "\n")

    def run_seq(self, **env):
        e = dict(os.environ, LOG=str(self.log), **env)
        return subprocess.run(
            [sys.executable, str(self.dir / "stop-sequence.py")],
            input=b'{"session_id":"s"}', capture_output=True, env=e, timeout=30,
        )

    def test_order_payload_and_stdout(self):
        self.stub("stop-continuity.sh",
                  'echo "continuity $(cat)" >> "$LOG"; echo noise')
        self.stub("metrics-live.sh",
                  'echo "readout $* since=$STOP_VERDICT_SINCE $(cat)" >> "$LOG"; '
                  'echo \'{"systemMessage":"📦"}\'')
        before = int(time.time())
        r = self.run_seq()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode().strip(), '{"systemMessage":"📦"}')
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[0], 'continuity {"session_id":"s"}')
        self.assertTrue(lines[1].startswith("readout stop 0 show since="))
        since = int(lines[1].split("since=")[1].split()[0])
        self.assertGreaterEqual(since, before)
        self.assertTrue(lines[1].endswith('{"session_id":"s"}'))

    def test_hung_continuity_is_killed_whole_and_readout_still_runs(self):
        pidfile = self.dir / "child.pid"
        self.stub("stop-continuity.sh",
                  f'sleep 60 & echo $! > "{pidfile}"; wait')
        self.stub("metrics-live.sh", 'echo readout >> "$LOG"; echo out')
        t0 = time.time()
        r = self.run_seq(STOP_CONTINUITY_SECS="2")
        self.assertLess(time.time() - t0, 15)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.decode().strip(), "out")
        self.assertEqual(self.log.read_text().strip(), "readout")
        child = int(pidfile.read_text())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_missing_hooks_fail_open(self):
        r = self.run_seq()
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, b"")


if __name__ == "__main__":
    unittest.main()
