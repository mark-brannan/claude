#!/usr/bin/env python3
# Tests for lib/when.py. Run: python3 lib/when.test.py
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import when  # noqa: E402


class Stamp(unittest.TestCase):
    def test_round_trip(self):
        self.assertEqual(when.stamp(1_700_000_000), "2023-11-14T22:13:20Z")
        self.assertEqual(when.unstamp("2023-11-14T22:13:20Z"), 1_700_000_000)

    def test_now_is_whole_seconds_utc(self):
        s = when.stamp()
        self.assertRegex(s, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertLessEqual(abs(when.unstamp(s) - datetime.datetime.now(datetime.timezone.utc).timestamp()), 2)

    def test_unstamp_is_strict(self):
        for bad in ("2023-11-14T22:13:20", "2023-11-14T22:13:20.5Z", "2023-11-14T22:13:20+00:00", "", "x"):
            with self.assertRaises(ValueError, msg=bad):
                when.unstamp(bad)


class Parse(unittest.TestCase):
    def test_z_and_offset_and_fraction(self):
        utc = datetime.timezone.utc
        self.assertEqual(when.parse("2023-11-14T22:13:20Z"), datetime.datetime(2023, 11, 14, 22, 13, 20, tzinfo=utc))
        self.assertEqual(when.epoch("2023-11-14T22:13:20.500Z"), 1_700_000_000.5)
        self.assertEqual(when.epoch("2023-11-14T23:13:20+01:00"), 1_700_000_000)

    def test_naive_stays_naive(self):
        self.assertIsNone(when.parse("2023-11-14T22:13:20").tzinfo)

    def test_errors(self):
        with self.assertRaises(ValueError):
            when.parse("yesterday")
        with self.assertRaises(AttributeError):
            when.parse(None)


if __name__ == "__main__":
    unittest.main()
