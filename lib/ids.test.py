#!/usr/bin/env python3
# Tests for lib/ids.py. Run: python3 lib/ids.test.py
#
# What matters: a work item's id is epoch seconds then eight random hex, so
# any number of calls in one second give distinct ids with nothing consulted;
# the shape never changes.
import datetime
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ids  # noqa: E402

NOW = 1790836842
SHAPE = re.compile(r"^[0-9]{10}[0-9a-f]{8}$")


class IdsTest(unittest.TestCase):
    def test_shape_is_seconds_then_eight_hex(self):
        i = ids.new_item_id(NOW)
        self.assertRegex(i, SHAPE)
        self.assertEqual(i[:10], str(NOW))

    def test_the_seconds_are_the_clock_as_given(self):
        self.assertTrue(ids.new_item_id(NOW + 0.9).startswith(str(NOW)))

    def test_a_burst_in_one_second_does_not_repeat(self):
        # Seven is the scar (2026-10-08: seven cards, one id). The odds of a
        # repeat among a hundred 32-bit draws are about one in a million.
        burst = {ids.new_item_id(NOW) for _ in range(100)}
        self.assertEqual(len(burst), 100)
        self.assertTrue(all(SHAPE.match(i) for i in burst))

    def test_roll_stamp(self):
        at = datetime.datetime(2026, 10, 2, 5, 41, 7, tzinfo=datetime.timezone.utc)
        self.assertEqual(ids.get_roll_stamp(at), "20261002t054107z")


if __name__ == "__main__":
    unittest.main()
