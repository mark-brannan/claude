#!/usr/bin/env python3
# Tests for curia_words.py. Run: python3 hooks/curia_words.test.py
#
# Cost per push: well under a second, no I/O; a step in the existing tool-tests job.
import importlib.util
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("curia_words", Path(__file__).resolve().parent / "curia_words.py")
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

WORKTREE = "<system-reminder>\nYou are operating in a git worktree.\nstay here\n</system-reminder>\n"
FORK = "<system-reminder>\nThis conversation was forked from another.\n</system-reminder>\n\n"
OTHER = "<system-reminder>\nSomething else the user typed.\n</system-reminder>\n"


class HarnessTest(unittest.TestCase):
    def test_leading_notices_go_with_their_newlines(self):
        self.assertEqual(cw.strip_harness(WORKTREE + FORK + "hello"), "hello")

    def test_a_notice_that_is_not_the_apps_stays(self):
        self.assertEqual(cw.strip_harness(OTHER + "hi"), OTHER + "hi")

    def test_only_leading_notices_go(self):
        self.assertEqual(cw.strip_harness("hi\n" + WORKTREE), "hi\n" + WORKTREE)

    def test_nothing_but_notices_is_blank(self):
        self.assertEqual(cw.strip_harness(WORKTREE).strip(), "")


class AgentTextTest(unittest.TestCase):
    def test_each_prefix_is_agent_text(self):
        for p in cw.AGENT_TEXT:
            self.assertTrue(cw.is_agent_text("  \n" + p + " rest"), p)

    def test_the_users_words_are_not(self):
        self.assertFalse(cw.is_agent_text("please <task-notification> later"))


class EntryTest(unittest.TestCase):
    STAMP = "20261002t070333z"

    def test_format(self):
        self.assertEqual(cw.entry("words", self.STAMP), f"\n### {self.STAMP}\n```\nwords\n```\n")

    def test_the_fence_outgrows_the_longest_run_inside(self):
        self.assertTrue(cw.entry("a ``` b", self.STAMP).startswith(f"\n### {self.STAMP}\n````\n"))
        self.assertTrue(cw.entry("a ` b", self.STAMP).startswith(f"\n### {self.STAMP}\n```\n"))

    def test_parse_reads_back_what_entry_wrote(self):
        for words in ("plain", "two\n\nparas", "fenced ``` inside", "ticks ```` more", "trailing\n"):
            text = cw.entry(words, self.STAMP)
            self.assertEqual(cw.ENTRY.findall(text)[0][0::2], (self.STAMP, words))
            self.assertEqual(cw.last_entry(text.encode()), (0, self.STAMP, words.encode()))

    def test_last_entry_is_the_last_and_reports_its_offset(self):
        head = "# roll\n" + cw.entry("old", "20261002t070000z")
        roll = head + cw.entry("new", self.STAMP)
        self.assertEqual(cw.last_entry(roll.encode()), (len(head.encode()), self.STAMP, b"new"))

    def test_no_entry_at_the_end_is_none(self):
        self.assertIsNone(cw.last_entry(b"# curated\n"))
        self.assertIsNone(cw.last_entry((cw.entry("a", self.STAMP) + "tail\n").encode()))


class DismissedTest(unittest.TestCase):
    def test_the_sentence(self):
        self.assertEqual(cw.DISMISSED, "[User dismissed — do not proceed, wait for next instruction]")


if __name__ == "__main__":
    unittest.main()
