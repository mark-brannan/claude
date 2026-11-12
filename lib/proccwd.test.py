#!/usr/bin/env python3
# Tests for lib/proccwd.py. Run: python3 lib/proccwd.test.py
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proccwd  # noqa: E402


class InUse(unittest.TestCase):
    def test_path_or_below_matches_sibling_prefix_does_not(self):
        cwds = {"/a/b/c"}
        self.assertTrue(proccwd.in_use("/a/b", cwds))
        self.assertTrue(proccwd.in_use("/a/b/c", cwds))
        self.assertFalse(proccwd.in_use("/a/bc", cwds))
        self.assertFalse(proccwd.in_use("/a/b/c/d", cwds))


@unittest.skipUnless(os.path.islink("/proc/self/cwd"), "needs /proc")
class LiveCwds(unittest.TestCase):
    def test_sees_a_child_process_in_its_dir(self):
        with tempfile.TemporaryDirectory() as d:
            d = os.path.realpath(d)
            p = subprocess.Popen(["sleep", "30"], cwd=d)
            try:
                self.assertIn(d, proccwd.live_cwds())
            finally:
                p.kill()
                p.wait()

    def test_no_proc_and_not_macos_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            if sys.platform != "darwin":
                self.assertIsNone(proccwd.live_cwds(proc=d))


if __name__ == "__main__":
    unittest.main()
