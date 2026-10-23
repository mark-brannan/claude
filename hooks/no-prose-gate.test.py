#!/usr/bin/env python3
# Tests for no-prose-gate.py. Run: python3 hooks/no-prose-gate.test.py
#
# Cost per push: about a second, a step in CI's tool-tests job.
# What matters: it blocks a closing permission question once, never a real
# choice or a statement, never a turn that used AskUserQuestion, and never
# twice in a turn. Its reason routes to a ruling card, not an issue.
# NO_PROSE_GATE_HOOK names another script to drive (a .sh runs under sh).
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(os.environ.get("NO_PROSE_GATE_HOOK") or Path(__file__).resolve().parent / "no-prose-gate.py").resolve()


def human(t): return {"type": "user", "message": {"role": "user", "content": t}}
def said(t): return {"type": "assistant", "message": {"content": [{"type": "text", "text": t}]}}
def asked(): return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {}}]}}
def result(): return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


class NoProseGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_")}
        self.env["HOME"] = str(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, payload):
        cmd = ["sh" if HOOK.suffix == ".sh" else sys.executable, str(HOOK)]
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        p = subprocess.run(cmd, input=raw, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def go(self, rows, active=False, msg="", raw_lines=None):
        tp = self.dir / "t.jsonl"
        lines = raw_lines if raw_lines is not None else [json.dumps(r) for r in rows]
        tp.write_text("\n".join(lines) + "\n")
        ev = {"transcript_path": str(tp), "stop_hook_active": active}
        if msg:
            ev["last_assistant_message"] = msg
        return self.run_hook(ev)

    def ends(self, text, **kw):
        return self.go([human("fix the hook"), result(), said(text)], **kw)

    def assertBlocks(self, out):
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_blocks_permission_shapes(self):
        for t in ["Tests pass. Want me to push and open the PR?", "Shall I write that card?",
                  "Diff above. Proceed?", "That is the plan. Go?", "Green and resolved. Merge it?",
                  "Want it added now?", "Done.\n\n**Want me to rebase #196 now?**\n"]:
            with self.subTest(t=t):
                self.assertBlocks(self.ends(t))

    def test_reason_routes_to_ruling_card_and_quotes_line(self):
        d = json.loads(self.ends("Want me to push?"))
        self.assertEqual(sorted(d), ["decision", "reason"])
        self.assertIn("ruling card", d["reason"])
        self.assertIn('"Want me to push?"', d["reason"])
        self.assertNotIn("issue", d["reason"].lower())

    def test_silent_non_permission(self):
        for t in ["Which do you want: A, or B?", "Where should the card go?", "Pushed; PR is up.",
                  "Want me to push? Done anyway, it is pushed."]:
            with self.subTest(t=t):
                self.assertEqual(self.ends(t), "")

    def test_ask_user_question_this_turn_only(self):
        self.assertEqual(self.go([human("go"), asked(), result(), said("Want me to push?")]), "")
        self.assertBlocks(self.go([human("a"), asked(), result(), said("ok"), human("b"), said("Want me to push?")]))

    def test_once_per_turn_and_payload_message_wins(self):
        self.assertEqual(self.go([human("go"), said("Want me to push?")], active=True), "")
        self.assertBlocks(self.go([human("go"), said("Pushed.")], msg="Proceed?"))

    def test_meta_user_row_is_not_the_human(self):
        meta = dict(human("ctx"), isMeta=True)
        self.assertEqual(self.go([human("a"), asked(), meta, said("Want me to push?")]), "")

    def test_reads_only_the_tail(self):
        # A turn past the 400-line tail starts at a cut-off row; it is skipped.
        filler = [json.dumps(result())] * 450
        rows = [json.dumps(human("a")), json.dumps(asked())] + filler + [json.dumps(said("Want me to push?"))]
        self.assertBlocks(self.go(None, raw_lines=rows))
        cut = ['"message": {"content": "half a row"}}'] + [json.dumps(r) for r in (human("b"), said("Merge it?"))]
        self.assertBlocks(self.go(None, raw_lines=cut))

    def test_missing_input_is_silent(self):
        self.assertEqual(self.run_hook({"transcript_path": str(self.dir / "none.jsonl")}), "")
        self.assertEqual(self.run_hook(""), "")
        self.assertEqual(self.run_hook("not json"), "")


if __name__ == "__main__":
    unittest.main()
