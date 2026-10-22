#!/usr/bin/env python3
# Tests for lib/jsonl.py. Run: python3 lib/jsonl.test.py
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jsonl  # noqa: E402


class Rows(unittest.TestCase):
    def test_skips_what_is_not_json(self):
        got = list(jsonl.rows(['{"a":1}\n', "\n", "not json\n", "[1, 2]", '"s"', "", "{bad"]))
        self.assertEqual(got, [{"a": 1}, [1, 2], "s"])

    def test_read_and_append(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "rows.jsonl")
            jsonl.append(p, {"ts": "x", "text": "caf\u00e9"})
            jsonl.append(p, {"n": 2})
            with open(p, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), '{"ts":"x","text":"caf\u00e9"}\n{"n":2}\n')
            self.assertEqual(list(jsonl.read(p)), [{"ts": "x", "text": "caf\u00e9"}, {"n": 2}])

    def test_read_missing_raises(self):
        with self.assertRaises(OSError):
            list(jsonl.read("/nonexistent/x.jsonl"))

    def test_read_replaces_bad_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            with open(p, "wb") as fh:
                fh.write(b'{"a":"\xff"}\n{"b":1}\n')
            self.assertEqual(list(jsonl.read(p)), [{"a": "\ufffd"}, {"b": 1}])


if __name__ == "__main__":
    unittest.main()
