#!/usr/bin/env python3
# Tests for memfloor. Run: python3 lib/memfloor.test.py
#
# What matters: available RAM plus free swap under the floor refuses with the
# numbers; at or over it, nothing; an unreadable /proc/meminfo or no floor in
# config.json refuses nothing; self-check's row names free of total and the
# avg10 pressure, warn under the floor. $CLAUDE_PROC points at a faked /proc.
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config  # noqa: E402
import memfloor  # noqa: E402

GIB = 1024 * 1024  # kB


def fake_proc(root, avail_gb, swapfree_gb, ram_gb=14, swap_gb=4, avg10="12.00"):
    """A /proc with meminfo and pressure/memory, as the kernel writes them; returns its path."""
    root = Path(root)
    (root / "pressure").mkdir(parents=True, exist_ok=True)
    (root / "meminfo").write_text(
        "MemTotal:       %8d kB\nMemFree:          512000 kB\nMemAvailable:   %8d kB\n"
        "Buffers:           20480 kB\nSwapTotal:      %8d kB\nSwapFree:       %8d kB\n"
        % (ram_gb * GIB, round(avail_gb * GIB), swap_gb * GIB, round(swapfree_gb * GIB)))
    if avg10 is not None:
        (root / "pressure" / "memory").write_text(
            "some avg10=%s avg60=8.10 avg300=3.02 total=91234567\n"
            "full avg10=6.50 avg60=4.00 avg300=1.10 total=41234567\n" % avg10)
    return str(root)


class MemFloorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def proc(self, *a, **k):
        p = fake_proc(self.tmp.name, *a, **k)
        patch = mock.patch.dict(os.environ, {"CLAUDE_PROC": p})
        patch.start()
        self.addCleanup(patch.stop)
        return p

    def floor(self, v):
        patch = mock.patch.object(memfloor, "floor_gb", return_value=v)
        patch.start()
        self.addCleanup(patch.stop)

    def test_under_the_floor_refuses_with_the_numbers(self):
        self.proc(1.4, 0.2)
        self.floor(3.0)
        self.assertEqual(memfloor.refusal(),
                         "1.4 GB available + 0.2 GB swap, under the 3.0 GB floor; not starting")

    def test_at_or_over_the_floor_refuses_nothing(self):
        self.floor(3.0)
        for avail, swap in ((2.0, 1.0), (8.0, 4.0)):
            self.proc(avail, swap)
            self.assertIsNone(memfloor.refusal())

    def test_swap_counts_toward_the_floor(self):
        self.proc(1.5, 2.0)
        self.floor(3.0)
        self.assertIsNone(memfloor.refusal())

    def test_unreadable_meminfo_refuses_nothing(self):
        patch = mock.patch.dict(os.environ, {"CLAUDE_PROC": os.path.join(self.tmp.name, "nowhere")})
        patch.start()
        self.addCleanup(patch.stop)
        self.floor(3.0)
        self.assertIsNone(memfloor.refusal())
        self.assertEqual(memfloor.row()[0], "warn")

    def test_no_floor_in_config_refuses_nothing(self):
        self.proc(0.1, 0.0)
        with mock.patch.object(config, "get", side_effect=config.ConfigError("no memory.floor_gb")):
            self.assertIsNone(memfloor.floor_gb())
            self.assertIsNone(memfloor.refusal())

    def test_the_floor_is_in_config_json(self):
        self.assertEqual(memfloor.floor_gb(), 3.0)

    def test_row_under_the_floor_warns(self):
        p = self.proc(1.4, 0.2)
        self.assertEqual(memfloor.row(p, 3.0),
                         ("warn", "1.6 GB free of 18 GB (RAM+swap) · pressure 12% avg10"))

    def test_row_with_room_is_ok(self):
        p = self.proc(9.0, 4.0, avg10="0.00")
        self.assertEqual(memfloor.row(p, 3.0),
                         ("ok", "13.0 GB free of 18 GB (RAM+swap) · pressure 0% avg10"))

    def test_row_without_pressure_says_unread(self):
        p = self.proc(9.0, 4.0, avg10=None)
        self.assertIn("· pressure unread", memfloor.row(p, 3.0)[1])


if __name__ == "__main__":
    unittest.main()
