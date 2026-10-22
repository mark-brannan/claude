#!/usr/bin/env python3
# Tests for lib/ids.py. Run: python3 lib/ids.test.py
#
# What matters: a work item's id is epoch seconds then the session's eight
# hex, and one session never gets the same id twice, in one process or in
# many at once; the shape never changes to achieve that. Without a usable
# counter dir the id is still made, stepped past the store only, and says so.
import datetime
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ids  # noqa: E402

LIB = str(Path(__file__).resolve().parent)
HEX = "077c62eb"
NOW = 1790836842
# One id from a child process, at the fixed second: what two sessions'
# processes racing through card-id new would each run.
CHILD = ("import sys; sys.path.insert(0, sys.argv[1]); import ids\n"
         "i, note = ids.new_item_id(sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5])\n"
         "print(i); print(note, file=sys.stderr)")


class IdsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.items = os.path.join(self.tmp.name, "items")
        self.state = os.path.join(self.tmp.name, "state")
        os.makedirs(self.items)

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, now=NOW, hex8=HEX):
        return ids.new_item_id(hex8, now, self.items, self.state)

    def test_roll_stamp(self):
        t = datetime.datetime.fromtimestamp(1790920867, datetime.timezone.utc)
        self.assertEqual(ids.get_roll_stamp(t), "20261002t060107z")

    def test_session_hex(self):
        self.assertEqual(ids.session_hex("077c62eb-2979-4277-b798-0d0fd9e9bb8d"), HEX, "dashes dropped, cut to eight")
        self.assertEqual(ids.session_hex("077C62EB"), HEX, "lowercased")
        self.assertEqual(ids.session_hex("d654192b-0000"), "d654192b")
        for bad in ("", None, "077c62e", "zzzzzzzz", "077c62eg"):
            self.assertEqual(ids.session_hex(bad), "", f"{bad!r} is not a session")

    def test_shape_is_the_clock_then_the_hex(self):
        i, note = self.new()
        self.assertEqual(i, f"{NOW}{HEX}")
        self.assertEqual(note, "", "the counter was used")
        self.assertEqual(len(i), 18)

    def test_a_burst_in_one_second_takes_consecutive_seconds(self):
        got = [self.new()[0] for _ in range(7)]
        self.assertEqual(len(set(got)), 7, "seven calls, seven ids")
        self.assertEqual(got, [f"{NOW + k}{HEX}" for k in range(7)], "each the next second, same hex")

    def test_the_clock_wins_once_it_moves_on(self):
        self.new(NOW)
        self.new(NOW)  # hands out NOW + 1
        i, _ = self.new(NOW + 60)
        self.assertEqual(i, f"{NOW + 60}{HEX}", "a later second is the id's second, not last + 1")
        i, _ = self.new(NOW + 30)
        self.assertEqual(i, f"{NOW + 61}{HEX}", "a clock that went back never repeats or reuses")

    def test_steps_past_ids_filed_in_the_store(self):
        for k in (0, 1):
            Path(self.items, f"{NOW + k}{HEX}.md").touch()
        self.assertEqual(self.new()[0], f"{NOW + 2}{HEX}")
        Path(self.items, f"{NOW + 3}{HEX}.md").touch()
        self.assertEqual(self.new()[0], f"{NOW + 4}{HEX}", "the counter and the store both step")

    def test_sessions_do_not_share_a_counter(self):
        self.new(NOW, HEX)
        self.new(NOW, HEX)
        self.assertEqual(self.new(NOW, "d654192b")[0], f"{NOW}d654192b", "another session's first id is the clock")
        self.assertEqual(sorted(os.listdir(self.state)), ["last.077c62eb", "last.d654192b"], "one counter file per session")

    def test_processes_racing_in_one_second_all_differ(self):
        procs = [subprocess.Popen([sys.executable, "-c", CHILD, LIB, HEX, str(NOW), self.items, self.state],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(7)]
        outs = [p.communicate(timeout=30) for p in procs]
        got = sorted(o.strip() for o, _ in outs)
        self.assertEqual([e.strip() for _, e in outs], [""] * 7, "every process used the counter")
        self.assertEqual(got, [f"{NOW + k}{HEX}" for k in range(7)], "seven processes, seven consecutive seconds")

    def test_no_usable_counter_dir_still_makes_an_id_and_says_so(self):
        blocked = os.path.join(self.tmp.name, "a-file")
        Path(blocked).write_text("")
        i, note = ids.new_item_id(HEX, NOW, self.items, os.path.join(blocked, "state"))
        self.assertEqual(i, f"{NOW}{HEX}", "the id is the clock and the hex")
        self.assertIn("stepped past the store only", note)
        Path(self.items, f"{NOW}{HEX}.md").touch()
        i, note = ids.new_item_id(HEX, NOW, self.items, os.path.join(blocked, "state"))
        self.assertEqual(i, f"{NOW + 1}{HEX}", "and it still steps past the store")
        self.assertNotEqual(note, "")

    @unittest.skipIf(os.geteuid() == 0, "root writes anywhere")
    def test_an_unwritable_counter_dir_is_the_same_fallback(self):
        os.makedirs(self.state, mode=0o500)
        try:
            i, note = self.new()
            self.assertEqual(i, f"{NOW}{HEX}")
            self.assertIn("stepped past the store only", note)
            self.assertEqual(os.listdir(self.state), [], "nothing was written")
        finally:
            os.chmod(self.state, 0o700)

    def test_default_state_dir(self):
        self.assertEqual(ids.card_id_state_dir({"CARD_ID_STATE": "/x/y"}), "/x/y")
        self.assertEqual(ids.card_id_state_dir({"XDG_STATE_HOME": "/s", "HOME": "/h"}), "/s/card-id")
        self.assertEqual(ids.card_id_state_dir({"HOME": "/h"}), "/h/.local/state/card-id")
        self.new()
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o700, "the counter dir is the user's alone")


if __name__ == "__main__":
    unittest.main()
