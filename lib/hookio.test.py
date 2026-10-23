#!/usr/bin/env python3
# Tests for lib/hookio.py. Run: python3 lib/hookio.test.py
#
# What matters: read() never raises and hands back an object or {}; the
# builders give the shapes Claude Code reads, keys in the order the hooks
# have always written them; and emit() writes the same bytes each hook wrote
# by hand before it moved here.
import io
import json
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
LIB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LIB)
import hookio  # noqa: E402


def emitted(code):
    """stdout bytes of `import hookio; <code>` in a fresh python."""
    p = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {LIB!r}); import hookio; {code}"],
                       capture_output=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert p.returncode == 0, p.stderr
    return p.stdout


class Read(unittest.TestCase):
    def test_object(self):
        self.assertEqual(hookio.read(io.StringIO('{"session_id": "s", "cwd": "/x"}')),
                         {"session_id": "s", "cwd": "/x"})

    def test_absent_malformed_or_not_an_object_is_empty(self):
        for raw in ("", "{bad", "[1, 2]", '"s"', "null"):
            with self.subTest(raw=raw):
                self.assertEqual(hookio.read(io.StringIO(raw)), {})

    def test_unreadable_is_empty(self):
        s = io.StringIO("{}")
        s.close()
        self.assertEqual(hookio.read(s), {})

    def test_bad_utf8_on_stdin_does_not_raise(self):
        # Whether the byte survives as a surrogate or empties the read is
        # stdin's own errors handler; either way the hook gets a dict.
        p = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {LIB!r}); import hookio; "
                            "print(type(hookio.read()).__name__)"], input=b'{"a":"\xff"}', capture_output=True)
        self.assertEqual((p.returncode, p.stdout), (0, b"dict\n"))


class StopHookActive(unittest.TestCase):
    def test_only_json_true(self):
        self.assertTrue(hookio.stop_hook_active({"stop_hook_active": True}))
        for ev in ({}, {"stop_hook_active": False}, {"stop_hook_active": "true"},
                   {"stop_hook_active": 1}, None, []):
            with self.subTest(ev=ev):
                self.assertFalse(hookio.stop_hook_active(ev))


class Builders(unittest.TestCase):
    def test_block(self):
        self.assertEqual(json.dumps(hookio.block("r")), '{"decision": "block", "reason": "r"}')

    def test_context_without_and_with_system(self):
        self.assertEqual(json.dumps(hookio.context("SessionStart", "t")),
                         '{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "t"}}')
        self.assertEqual(json.dumps(hookio.context("UserPromptSubmit", "t", system="s")),
                         '{"systemMessage": "s", "hookSpecificOutput": '
                         '{"hookEventName": "UserPromptSubmit", "additionalContext": "t"}}')

    def test_allow_and_deny(self):
        self.assertEqual(json.dumps(hookio.allow("t")),
                         '{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
                         '"permissionDecision": "allow", "additionalContext": "t"}}')
        self.assertEqual(json.dumps(hookio.deny("r")),
                         '{"hookSpecificOutput": {"hookEventName": "PreToolUse", '
                         '"permissionDecision": "deny", "permissionDecisionReason": "r"}}')

    def test_merge_keeps_stop_order(self):
        out = {"systemMessage": "m"}
        out.update(hookio.block("r"))
        out.update(hookio.context("PostToolUse", "c"))
        self.assertEqual(list(out), ["systemMessage", "decision", "reason", "hookSpecificOutput"])


class Emit(unittest.TestCase):
    OUT = {"systemMessage": "café →", "n": [1, 2]}

    def test_default_is_print_json_dumps(self):
        self.assertEqual(emitted(f"hookio.emit({self.OUT!r})"),
                         (json.dumps(self.OUT) + "\n").encode())

    def test_ascii_false_is_utf8(self):
        self.assertEqual(emitted(f"hookio.emit({self.OUT!r}, ascii=False)"),
                         (json.dumps(self.OUT, ensure_ascii=False) + "\n").encode("utf-8"))

    def test_compact(self):
        self.assertEqual(emitted(f"hookio.emit({self.OUT!r}, ascii=False, compact=True)"),
                         '{"systemMessage":"café →","n":[1,2]}\n'.encode("utf-8"))

    def test_errors_replace_takes_a_lone_surrogate(self):
        self.assertEqual(emitted("hookio.emit({'t': '\\udcff'}, ascii=False, compact=True, errors='replace')"),
                         b'{"t":"?"}\n')

    def test_after_text_already_printed(self):
        self.assertEqual(emitted("print('a'); hookio.emit({})"), b"a\n{}\n")


if __name__ == "__main__":
    unittest.main()
