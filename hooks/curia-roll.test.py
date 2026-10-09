#!/usr/bin/env python3
# Tests for curia-roll.py. Run: python3 hooks/curia-roll.test.py
#
# Cost per push: well under a second, a step in CI's existing tool-tests job,
# so no new job and nothing drawn from the account's concurrent-job cap.
# Each case runs the hook as Claude Code does, a subprocess fed event JSON on
# stdin, against a throwaway state repo named by CLAUDE_STATE_REPO.
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "curia-roll.py"
SID = "3554281d-fda5-4810-9e67-8117eb8e7006"
OTHER = "29ff522d-c4ec-4b34-bf83-e7a010fb6c1e"
ENTRY = re.compile(r"\n### (\d{8}t\d{6}z)\n(`{3,})\n(.*?)\n\2\n", re.S)
T1 = datetime.datetime(2026, 10, 2, 7, 3, 33, 100000, tzinfo=datetime.timezone.utc)
T1_LATER = T1 + datetime.timedelta(milliseconds=1)
T2 = T1 + datetime.timedelta(seconds=1)


def stamp(now):
    return now.strftime("%Y%m%dt%H%M%Sz")


def load_hook():
    spec = importlib.util.spec_from_file_location("curia_roll", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CuriaRollTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".git").mkdir()
        self.curia = self.repo / "state" / "global" / "curia"

    def tearDown(self):
        self.tmp.cleanup()

    def sitting(self, cid, live, moved=True):
        d = self.curia / cid
        d.mkdir(parents=True, exist_ok=True)
        (d / "LIVE").write_text(live)
        if moved:
            (d / "digest.md").write_text("# digest\n")
        return d

    def run_hook(self, payload):
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        env = dict(os.environ, CLAUDE_STATE_REPO=str(self.repo))
        return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env)

    def prompt(self, text, sid=SID, field="prompt"):
        r = self.run_hook({"session_id": sid, field: text, "hook_event_name": "UserPromptSubmit"})
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def entries(self, cid):
        return ENTRY.findall((self.curia / cid / "roll.md").read_text())

    def test_appends_one_stamped_entry_for_the_live_session(self):
        self.sitting("one-entry-point", f"{SID} 2026-10-02T05:00:00Z\n")
        self.prompt("yes, make it so")
        [(stamp, _, body)] = self.entries("one-entry-point")
        self.assertEqual(body, "yes, make it so")
        self.assertRegex(stamp, r"\A\d{8}t\d{6}z\Z")

    def test_live_with_a_session_prefix_still_matches(self):
        self.sitting("hook-guards", f"session {SID} 2026-10-02T03:17:35Z\n")
        self.prompt("hi")
        self.assertEqual(len(self.entries("hook-guards")), 1)

    def test_headings_and_backticks_survive_byte_for_byte(self):
        self.sitting("c", f"{SID} t\n")
        text = '### not a stamp\n```sh\nrun ````x````\n```\n<pasted_content id="353c">\n## h\n</pasted_content>\n\n'
        self.prompt(text)
        [(_, fence, body)] = self.entries("c")
        self.assertEqual((fence, body), ("`````", text))

    def test_never_touches_what_is_there(self):
        d = self.sitting("c", f"{SID} t\n")
        before = "# roll\n\n### 20261001t000000z\n```\nold words\n```\n"
        (d / "roll.md").write_text(before)
        self.prompt("first")
        self.prompt("second")
        after = (d / "roll.md").read_text()
        self.assertTrue(after.startswith(before))
        # Two prompts in one second fold into one entry: the words survive either way.
        bodies = [e[2] for e in self.entries("c")]
        self.assertEqual((bodies[0], "\n\n".join(bodies[1:])), ("old words", "first\n\nsecond"))

    def test_other_session_and_no_live_are_silent(self):
        self.sitting("c", f"{OTHER} t\n")
        self.sitting("d", "", moved=True)
        (self.curia / "e").mkdir()
        self.prompt("hi")
        self.assertFalse(any(self.curia.glob("*/roll.md")))

    def test_unmoved_curia_keeps_its_curated_roll(self):
        d = self.sitting("c", f"{SID} t\n", moved=False)
        (d / "roll.md").write_text("# curated\n")
        self.prompt("hi")
        self.assertEqual((d / "roll.md").read_text(), "# curated\n")

    def test_the_opening_curia_prompt_is_recorded_before_live_exists(self):
        self.sitting("c", "")
        self.sitting("unmoved", "", moved=False)
        self.prompt("/curia c and my opening words")
        self.prompt("/curia unmoved")
        self.prompt("/curia no-such-curia")
        self.assertEqual([e[2] for e in self.entries("c")], ["/curia c and my opening words"])
        self.assertEqual([p.parent.name for p in self.curia.glob("*/roll.md")], ["c"])

    def test_a_resumed_sitting_records_its_opening_prompt_once(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt("/curia c")
        self.assertEqual(len(self.entries("c")), 1)

    def test_user_input_field_is_read_too(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt("from the docs' field name", field="user_input")
        self.assertEqual(self.entries("c")[0][2], "from the docs' field name")

    def test_two_sessions_both_named_in_live_interleave_whole_entries(self):
        self.sitting("c", f"{SID} t\n{OTHER} t\n")
        self.prompt("from one")
        self.prompt("from two", sid=OTHER)
        self.assertEqual("\n\n".join(e[2] for e in self.entries("c")), "from one\n\nfrom two")

    def test_bad_input_and_unwritable_roll_exit_zero_silently(self):
        for payload in ("", "not json", "[]", {"session_id": SID}, {"prompt": "x"}):
            r = self.run_hook(payload)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        d = self.sitting("c", f"{SID} t\n")
        (d / "roll.md").mkdir()
        self.prompt("x")

    def test_agent_text_through_the_prompt_hook_stays_out(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt("<task-notification>\n<task-id>a1</task-id>\n</task-notification>")
        self.prompt("<agent-message from=\"a2\">\nreport\n</agent-message>")
        self.prompt("Another Claude session sent a message:\n<agent-message from=\"a3\">x</agent-message>")
        self.prompt("my words about a <task-notification>")
        self.assertEqual([e[2] for e in self.entries("c")], ["my words about a <task-notification>"])

    WORKTREE = ("<system-reminder>\nYou are operating in a git worktree.\nWorktree path: /w/x\n"
                "Worktree name: x\n</system-reminder>\n\n\n")
    FORK = "<system-reminder>\nThis conversation was forked from another.\n</system-reminder>\n"

    def test_leading_harness_reminders_are_stripped_like_build_roll(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt(self.WORKTREE + self.FORK + "my words\n\nsecond paragraph")
        self.assertEqual([e[2] for e in self.entries("c")], ["my words\n\nsecond paragraph"])

    def test_other_reminders_and_later_reminders_are_the_users_bytes(self):
        self.sitting("c", f"{SID} t\n")
        other = "<system-reminder>\nSomething else.\n</system-reminder>\nwords"
        later = "words, then\n" + self.WORKTREE + "more"
        self.prompt(other)
        self.prompt(later)
        self.assertEqual("\n\n".join(e[2] for e in self.entries("c")), other + "\n\n" + later)

    def test_a_prompt_that_is_only_a_harness_reminder_writes_nothing(self):
        self.sitting("c", f"{SID} t\n")
        self.prompt(self.WORKTREE)
        self.prompt("  \n")
        self.assertFalse((self.curia / "c" / "roll.md").exists())

    def test_the_opening_curia_prompt_and_agent_text_are_judged_after_the_strip(self):
        self.sitting("c", "")
        self.prompt(self.WORKTREE + "/curia c opening")
        self.prompt(self.WORKTREE + "<task-notification>\n<task-id>a1</task-id>\n</task-notification>")
        self.assertEqual([e[2] for e in self.entries("c")], ["/curia c opening"])

    def test_a_dialogs_answers_are_not_stripped(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": self.WORKTREE + "teal"})
        self.assertEqual([e[2] for e in self.entries("c")], [self.WORKTREE + "teal"])

    def dialog(self, answers, annotations=None, sid=SID, where="tool_response", tool="AskUserQuestion"):
        questions = [
            {"question": "Which colour?", "header": "Colour", "multiSelect": False,
             "options": [{"label": "Red", "description": "r"}, {"label": "Blue", "description": "b"}]},
            {"question": "Which sizes?", "header": "Sizes", "multiSelect": True,
             "options": [{"label": "Small", "description": "s"}, {"label": "Large", "description": "l"}]},
            {"question": "Anything else?", "header": "Else", "multiSelect": False,
             "options": [{"label": "No", "description": "n"}, {"label": "Yes", "description": "y"}]},
        ]
        result = {"questions": questions, "answers": answers}
        if annotations:
            result["annotations"] = annotations
        ev = {"session_id": sid, "hook_event_name": "PostToolUse", "tool_name": tool,
              "tool_input": {"questions": questions}, where: result}
        if where == "tool_input":
            ev["tool_response"] = "Your questions have been answered."
        r = self.run_hook(ev)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_dialogs_free_text_answers_are_one_entry_in_question_order(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Anything else?": "words, typed\n```\nfree", "Which colour?": "Green, not either",
                     "Which sizes?": "Small, Large"})
        [(_, fence, body)] = self.entries("c")
        self.assertEqual((fence, body), ("````", "Green, not either\n\nwords, typed\n```\nfree"))

    def test_a_dialog_with_only_picked_labels_writes_nothing(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "Red", "Which sizes?": "Large", "Anything else?": "No"})
        self.assertFalse((self.curia / "c" / "roll.md").exists())

    DISMISSED = "[User dismissed — do not proceed, wait for next instruction]"

    def test_a_dismissed_dialog_writes_nothing(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": self.DISMISSED, "Which sizes?": self.DISMISSED,
                     "Anything else?": self.DISMISSED})
        self.assertFalse((self.curia / "c" / "roll.md").exists())

    def test_a_dismissal_beside_real_answers_is_dropped_and_they_are_kept(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "teal", "Which sizes?": self.DISMISSED,
                     "Anything else?": "words, typed"})
        self.assertEqual([e[2] for e in self.entries("c")], ["teal\n\nwords, typed"])

    def test_a_note_typed_beside_a_picked_option_is_kept(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "Red", "Which sizes?": "Small", "Anything else?": "No"},
                    {"Which sizes?": {"notes": "small for now", "preview": "agent text"}})
        self.assertEqual([e[2] for e in self.entries("c")], ["small for now"])

    def test_a_multi_select_keeps_its_typed_part_and_drops_picked_labels(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "Red", "Which sizes?": "Small, huge, please", "Anything else?": "No"})
        self.assertEqual([e[2] for e in self.entries("c")], ["huge, please"])

    def test_a_malformed_annotation_keeps_the_other_answers(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "teal"}, {"Which colour?": "not a dict"})
        self.assertEqual([e[2] for e in self.entries("c")], ["teal"])

    def test_answers_carried_on_the_tool_input_are_read_too(self):
        self.sitting("c", f"{SID} t\n")
        self.dialog({"Which colour?": "teal"}, where="tool_input")
        self.assertEqual([e[2] for e in self.entries("c")], ["teal"])

    def test_dialogs_need_live_and_other_tools_are_ignored(self):
        self.sitting("c", f"{OTHER} t\n")
        self.dialog({"Which colour?": "teal"})
        self.sitting("d", f"{SID} t\n")
        self.dialog({"Which colour?": "teal"}, tool="Bash")
        self.assertFalse(any(self.curia.glob("*/roll.md")))

    def test_dialog_words_matches_what_the_hook_writes(self):
        mod = load_hook()
        qs = [{"question": "Q1", "options": [{"label": "A"}]}, {"question": "Q2", "options": []}]
        self.assertEqual(mod.dialog_words(qs, {"Q2": "two", "Q1": "one"}), "one\n\ntwo")
        self.assertEqual(mod.dialog_words(qs, {"Q1": "A", "Q2": "  "}), "")

    def test_no_state_repo_is_silent(self):
        env = dict(os.environ, CLAUDE_STATE_REPO="", HOME=self.tmp.name)
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"session_id": SID, "prompt": "x"}),
                           capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_a_lib_without_lock_py_writes_nothing_and_exits_zero(self):
        # A seed whose lib/ has state.py but not lock.py: a state dir is found,
        # so the missing lock must be what stops the write, not a swallowed error.
        import shutil
        tree = Path(self.tmp.name) / "seed"
        (tree / "hooks").mkdir(parents=True)
        (tree / "lib").mkdir()
        shutil.copy(HOOK, tree / "hooks")
        shutil.copy(HOOK.parent / "lib_state.py", tree / "hooks")
        shutil.copy(HOOK.parent.parent / "lib" / "state.py", tree / "lib")
        shutil.copy(HOOK.parent.parent / "lib" / "gitrun.py", tree / "lib")  # state.py imports it
        self.sitting("one-entry-point", f"{SID} 2026-10-02T05:00:00Z\n")
        # HOME away from ~/.claude/lib, the search's fallback, which has lock.py.
        env = dict(os.environ, CLAUDE_STATE_REPO=str(self.repo), HOME=self.tmp.name)
        r = subprocess.run([sys.executable, str(tree / "hooks" / "curia-roll.py")],
                           input=json.dumps({"session_id": SID, "prompt": "x"}),
                           capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("lib/lock.py not found", r.stderr, "says why, on stderr")
        self.assertFalse((self.curia / "one-entry-point" / "roll.md").exists())


class FoldTest(unittest.TestCase):
    """Words sharing a per-second stamp are one entry, joined by a blank line,
    as build-roll.py merges them. Fixed clocks, so no second boundary races."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.roll = Path(self.tmp.name) / "roll.md"
        self.hook = load_hook()

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_queued_pair_one_ms_apart_is_one_entry(self):
        self.hook.append(str(self.roll), "first", T1)
        self.hook.append(str(self.roll), "second", T1_LATER)
        self.assertEqual(self.roll.read_text(), self.hook.entry("first\n\nsecond", T1))
        # Same fence, so the rewrite opens with the earlier entry's bytes up to
        # its words: a kill mid-write cannot lose them.
        self.assertTrue(self.roll.read_text().startswith(self.hook.entry("first", T1)[: -len("\n```\n")]))

    def test_three_in_one_second_fold_in_time_order_after_older_entries(self):
        before = "# roll\n" + self.hook.entry("old", T1 - datetime.timedelta(seconds=5))
        self.roll.write_text(before)
        for w in ("a", "b", "c"):
            self.hook.append(str(self.roll), w, T1)
        self.assertEqual(self.roll.read_text(), before + self.hook.entry("a\n\nb\n\nc", T1))

    def test_a_fold_rerenders_the_fence_for_the_joined_words(self):
        self.hook.append(str(self.roll), "plain", T1)
        self.hook.append(str(self.roll), "has ```` four", T1)
        [(_, fence, body)] = ENTRY.findall(self.roll.read_text())
        self.assertEqual((fence, body), ("`````", "plain\n\nhas ```` four"))

    def test_a_new_second_appends_bytes_as_before(self):
        self.hook.append(str(self.roll), "one", T1)
        self.hook.append(str(self.roll), "two", T2)
        self.assertEqual(self.roll.read_text(), self.hook.entry("one", T1) + self.hook.entry("two", T2))

    def test_a_stamp_quoted_inside_the_last_entry_is_not_its_heading(self):
        quoted = "see\n### " + stamp(T1) + "\n```\nx\n```\nabove"
        self.hook.append(str(self.roll), quoted, T2)
        self.hook.append(str(self.roll), "later", T1)  # the last entry is T2's: no fold
        self.hook.append(str(self.roll), "more", T1)
        self.hook.append(str(self.roll), "and", T2)
        self.assertEqual([(s, b) for s, _, b in ENTRY.findall(self.roll.read_text())],
                         [(stamp(T2), quoted), (stamp(T1), "later\n\nmore"),
                          (stamp(T2), "and")])

    def test_a_curated_tail_is_appended_to(self):
        self.roll.write_text("# curated\n")
        self.hook.append(str(self.roll), "a", T1)
        self.assertEqual(self.roll.read_text(), "# curated\n" + self.hook.entry("a", T1))

    def test_an_undecodable_last_entry_is_kept_and_appended_after(self):
        bad = self.hook.entry("x", T1).encode().replace(b"x", b"\xff")
        self.roll.write_bytes(bad)
        self.hook.append(str(self.roll), "b", T1)
        self.assertEqual(self.roll.read_bytes(), bad + self.hook.entry("b", T1).encode())


if __name__ == "__main__":
    unittest.main(verbosity=1)
