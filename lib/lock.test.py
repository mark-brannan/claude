#!/usr/bin/env python3
# Tests for lib/lock.py. Run: python3 lib/lock.test.py
#
# What matters: a second holder waits or gives up in the time asked, and
# the lock is gone once the holder's descriptor closes.
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import lock  # noqa: E402

HOLD = """import sys, time; sys.path.insert(0, sys.argv[1]); import lock
with lock.locked(sys.argv[2]):
    print("held", flush=True); time.sleep(float(sys.argv[3]))"""


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "f.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def holder(self, secs):
        """Another process holding the lock for secs, once it says so."""
        p = subprocess.Popen([sys.executable, "-c", HOLD, str(Path(lock.__file__).parent), self.path, str(secs)],
                             stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "held")
        self.addCleanup(p.wait)
        return p

    def test_free_lock_is_taken_at_once(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            self.assertTrue(lock.acquire(fd, wait=0))
        finally:
            os.close(fd)

    def test_held_lock_gives_up_after_wait(self):
        self.holder(2)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            t = time.monotonic()
            self.assertFalse(lock.acquire(fd, wait=1))
            self.assertGreaterEqual(time.monotonic() - t, 0.9, "waited the second asked")
        finally:
            os.close(fd)

    def test_blocking_lock_waits_for_the_holder(self):
        self.holder(1)
        t = time.monotonic()
        with lock.locked(self.path) as fd:
            os.write(fd, b"x")
        self.assertGreaterEqual(time.monotonic() - t, 0.5, "blocked until the holder let go")
        self.assertEqual(Path(self.path).read_bytes(), b"x")

    def test_close_releases(self):
        with lock.locked(self.path):
            pass
        fd = os.open(self.path, os.O_RDWR)
        try:
            self.assertTrue(lock.acquire(fd, wait=0), "free once the first holder closed")
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
