#!/usr/bin/env python3
# Tests for lib/atomic.py. Run: python3 lib/atomic.test.py
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atomic  # noqa: E402


class Write(unittest.TestCase):
    def test_replaces_and_leaves_no_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.json")
            atomic.write(p, "one\n")
            atomic.write(pathlib.Path(p), "caf\u00e9\n")
            with open(p, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "caf\u00e9\n")
            self.assertEqual(os.listdir(d), ["f.json"])

    def test_failure_raises_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(OSError):
                atomic.write(os.path.join(d, "missing", "f"), "x")
            self.assertEqual(os.listdir(d), [])


if __name__ == "__main__":
    unittest.main()
