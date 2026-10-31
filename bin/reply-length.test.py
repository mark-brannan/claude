#!/usr/bin/env python3
# Smoke tests for reply-length. Run: python3 bin/reply-length.test.py
#
# A throwaway CLAUDE_PROJECTS root holds one synthetic transcript; the tool
# runs as a subprocess and its three printed reports and --dump rows are read
# back. No real transcript text.
#
# What matters: a reply is paired with the user's next real prompt; prose,
# table and code words are counted apart; a clarifying prompt is flagged; a
# sidechain or a non-human session is ignored; an empty root reports nothing
# without failing.
#
# Cost per push: well under a second.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "reply-length"


def user(text, t, **kw):
    return {"type": "user", "entrypoint": "cli", "timestamp": t, "message": {"content": text}, **kw}


def reply(text, t, **kw):
    return {"type": "assistant", "timestamp": t, "message": {"content": [{"type": "text", "text": text}]}, **kw}


WORDS_10 = "one two three four five six seven eight nine ten"
MIXED = "alpha beta gamma\n| a | b |\n| c | d |\n```\ncode line here\n```\ndelta"


class ReplyLengthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "projects"
        (self.root / "p").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def transcript(self, rows, name="s1"):
        (self.root / "p" / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def run_tool(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("DAYS", "FRICTION_DIR")}
        env["CLAUDE_PROJECTS"] = str(self.root)
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, env=env)

    def basic(self):
        return [
            user("start", "2026-10-29T10:00:00Z"),
            reply(WORDS_10, "2026-10-29T10:00:10Z"),
            user("ok thanks", "2026-10-29T10:00:40Z"),
            reply(MIXED, "2026-10-29T10:01:00Z"),
            user("please explain that", "2026-10-29T10:01:30Z"),
            reply("final words", "2026-10-29T10:02:00Z"),
        ]

    def test_reports_print_and_pairs_are_counted(self):
        self.transcript(self.basic())
        p = self.run_tool("--days", "28")
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertIn("files=1 pairs=2 days=28", p.stdout)
        self.assertIn("## buckets", p.stdout)
        self.assertIn("## slope", p.stdout)

    def test_dump_has_one_row_per_pair_with_counts_and_clarification(self):
        self.transcript(self.basic())
        dump = Path(self.tmp.name) / "dump.jsonl"
        p = self.run_tool("--dump", str(dump))
        self.assertEqual(p.returncode, 0)
        rows = [json.loads(ln) for ln in dump.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        first, second = rows
        self.assertEqual((first["prose"], first["table"], first["code"]), (10, 0, 0))
        self.assertEqual(first["gap"], 30)
        self.assertFalse(first["clar"])
        self.assertEqual((second["prose"], second["table"], second["code"]), (4, 4, 3))
        self.assertTrue(second["clar"])  # "explain": a single word, since CLAR's multi-word alternatives do not match
        self.assertEqual(oct(dump.stat().st_mode & 0o777), "0o600")

    def test_sidechain_and_non_human_sessions_are_ignored(self):
        rows = self.basic()
        for r in rows:
            r["isSidechain"] = True
        self.transcript(rows, "side")
        self.transcript([dict(r, entrypoint="sdk-cli") for r in self.basic()], "bot")
        p = self.run_tool()
        self.assertIn("pairs=0", p.stdout)
        self.assertIn("no pairs: nothing to report", p.stdout)

    def test_empty_root_reports_nothing_and_succeeds(self):
        p = self.run_tool()
        self.assertEqual(p.returncode, 0)
        self.assertIn("files=0 pairs=0", p.stdout)
        self.assertIn("no pairs: nothing to report", p.stdout)

    def test_unknown_key_is_refused(self):
        p = self.run_tool("--key", "bogus")
        self.assertEqual(p.returncode, 2)
        self.assertIn("invalid choice", p.stderr)


if __name__ == "__main__":
    unittest.main()
