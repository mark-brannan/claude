#!/usr/bin/env python3
# Tests for lib/cksum.py. Run: python3 lib/cksum.test.py
#
# What matters: the number is the one cksum(1) prints for the same bytes, so
# a key the shell computed is still found.
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cksum  # noqa: E402

SAMPLES = [b"", b"a", b"https://github.com/o/r/issues/12", b"log/2026-09-01-note.md",
           "café · x".encode(), bytes(range(256)) * 3]


class CksumTest(unittest.TestCase):
    def test_known_value(self):
        # POSIX's own check value: cksum of the empty input.
        self.assertEqual(cksum.cksum(b""), 4294967295)

    @unittest.skipUnless(shutil.which("cksum"), "no cksum(1) here")
    def test_matches_cksum_1(self):
        for s in SAMPLES:
            want = subprocess.run(["cksum"], input=s, capture_output=True, check=True).stdout.split()[0]
            self.assertEqual(cksum.cksum(s), int(want), s[:40])


if __name__ == "__main__":
    unittest.main()
