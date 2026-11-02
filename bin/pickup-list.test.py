#!/usr/bin/env python3
"""Tests for `pickup-list handoff <id>`. Run: python3 bin/pickup-list.test.py

What matters: the body below the first `---` line is replaced by stdin and
the head is kept byte for byte; a body holding `---` lines is written whole;
every refusal (unknown id, a card id, empty stdin, no `---`) leaves the file
untouched and exits non-zero. A temp state repo and HOME; no network.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PL = Path(__file__).resolve().parent / "pickup-list"
ID = "2026-09-03T10-00-deadbeef"
HEAD = (
    "status: open\nupdated: 2026-09-03T10:00:00Z\nsession: x\nmodel: m\n"
    "branch: r b (1 ahead, clean)\npr: none\nwhere: w\nuntil: 2026-10-15\n"
    "prompt: café — tabs\there  \n---\n"
)


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "home").mkdir()
        self.pickup = root / "state" / "state" / "global" / "pickup"
        self.pickup.mkdir(parents=True)
        (root / "state" / ".git").mkdir()
        self.env = {
            **os.environ,
            "HOME": str(root / "home"),
            "CLAUDE_STATE_REPO": str(root / "state"),
            "TMPDIR": self.tmp.name,
        }
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)

    def write(self, name, data: bytes):
        p = self.pickup / f"{name}.md"
        p.write_bytes(data)
        return p

    def run_pl(self, *args, stdin=b""):
        return subprocess.run(
            ["sh", str(PL), *args], input=stdin, capture_output=True, env=self.env, timeout=60
        )

    def test_replaces_body_keeps_head_byte_for_byte(self):
        f = self.write(ID, (HEAD + "old body\nmore old\n").encode())
        r = self.run_pl("handoff", ID, stdin=b"new line 1\nnew line 2\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f.read_bytes(), (HEAD + "new line 1\nnew line 2\n").encode())
        self.assertEqual(r.stdout.decode().strip(), str(f))

    def test_body_with_rule_lines_and_missing_final_newline(self):
        f = self.write(ID, (HEAD + "old\n---\nolder\n").encode())
        body = b"intro\n---\nmiddle\n---\nend"
        r = self.run_pl("handoff", ID, stdin=body)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(f.read_bytes(), HEAD.encode() + body + b"\n")

    def test_only_first_rule_line_splits(self):
        # the old body has its own --- lines; all of them go, the head stays
        f = self.write(ID, (HEAD + "a\n---\nb\n---\nc\n").encode())
        self.assertEqual(self.run_pl("handoff", ID, stdin=b"x\n").returncode, 0)
        self.assertEqual(f.read_bytes(), (HEAD + "x\n").encode())

    def test_head_ending_at_rule_line_without_newline(self):
        f = self.write(ID, (HEAD.rstrip("\n")).encode())
        self.assertEqual(self.run_pl("handoff", ID, stdin=b"body\n").returncode, 0)
        self.assertEqual(f.read_bytes(), (HEAD + "body\n").encode())

    def test_show_reads_back_and_no_temp_left(self):
        self.write(ID, (HEAD + "old\n").encode())
        self.run_pl("handoff", ID, stdin=b"fresh\n")
        shown = self.run_pl("show", ID).stdout.decode()
        self.assertTrue(shown.endswith("---\nfresh\n"))
        self.assertEqual([p.name for p in self.pickup.iterdir()], [f"{ID}.md"])

    def refuses(self, args, stdin=b"body\n", name=ID, data=None):
        f = self.write(name, data) if data is not None else None
        before = f.read_bytes() if f else None
        r = self.run_pl("handoff", *args, stdin=stdin)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stderr, "a refusal says why")
        if f:
            self.assertEqual(f.read_bytes(), before)
        self.assertEqual(
            sorted(p.name for p in self.pickup.iterdir()), [f.name] if f else []
        )

    def test_unknown_id(self):
        self.refuses(["2026-09-09T09-09-00000000"])

    def test_missing_id(self):
        self.refuses([])

    def test_path_in_id(self):
        self.refuses(["../x"])

    def test_card_id(self):
        card = "1790836850aaaaaaaa"
        items = self.pickup.parent / "items"
        items.mkdir()
        (items / f"{card}.md").write_text("# T\n\n## Brief\nb\n\n## Log\n---\n")
        r = self.run_pl("handoff", card, stdin=b"body\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("card", r.stderr.decode())
        self.assertEqual((items / f"{card}.md").read_text(), "# T\n\n## Brief\nb\n\n## Log\n---\n")

    def test_card_id_naming_a_pickup_file_is_still_a_card(self):
        self.refuses(["1790836850aaaaaaaa"], name="1790836850aaaaaaaa", data=(HEAD + "o\n").encode())

    def test_empty_stdin(self):
        self.refuses([ID], stdin=b"", data=(HEAD + "keep me\n").encode())

    def test_whitespace_only_stdin(self):
        self.refuses([ID], stdin=b" \n\n", data=(HEAD + "keep me\n").encode())

    def test_no_rule_line(self):
        self.refuses([ID], data=b"status: open\nprompt: p\nno rule here\n--- not exact\n")


if __name__ == "__main__":
    unittest.main()
