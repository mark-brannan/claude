#!/usr/bin/env python3
# Tests for languette-step-two-ready, against fixture metrics, fixture
# transcripts and a stand-in plugin whose guards deny any command containing
# DENYME. Run: python3 .local/bin/languette-step-two-ready.test.py
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "languette-step-two-ready"
SINCE = "2026-10-01T00:00:00Z"
ADD = "`git add -A` is blocked: stage by path."
FAKE_GUARD = """#!/bin/sh
p=$(cat)
case "$p" in
  *CRASH*) exit 1 ;;
  *DENYME*) printf '%s\\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"denied"}}' ;;
esac
"""


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.metrics = self.root / "metrics"
        self.projects = self.root / "projects"
        self.plugin = self.root / "plugin"
        for d in (self.metrics / "sessions", self.metrics / "blocked", self.projects / "-proj", self.plugin / "hooks"):
            d.mkdir(parents=True)
        hooks = []
        for g in ("no-git-footguns", "no-rm-tree", "no-delete-stacked-base"):
            (self.plugin / "hooks" / f"{g}.sh").write_text(FAKE_GUARD)
            # The real entries' shape: run the script, fail closed when it is missing or crashes.
            hooks.append({"type": "command", "command":
                          f'h="${{CLAUDE_PLUGIN_ROOT}}/hooks/{g}.sh"; {{ [ -f "$h" ] && sh "$h"; }} || printf \'%s\\n\' '
                          f'\'{{"hookSpecificOutput":{{"permissionDecision":"deny","permissionDecisionReason":'
                          f'"{g}.sh is missing from the plugin directory or crashed"}}}}\''})
        (self.plugin / "hooks/hooks.json").write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": hooks}]}}))

    def session(self, sid, started, bash):
        tools = {"Bash": bash} if bash else {"Read": 1}
        (self.metrics / "sessions" / f"{sid}.json").write_text(json.dumps(
            {"session_id": sid, "started_at": started, "tools": tools}))

    def deny(self, sid, reason, command=None, i=None):
        """Record a rule denial; with a command, write the transcript the record was read from."""
        rec = {"kind": "rule", "raw": "permission-rule", "tool": "Bash", "target": "x", "reason": reason}
        if command is not None:
            t = self.projects / "-proj" / f"{sid}.jsonl"
            lines = t.read_text().splitlines() if t.exists() else []
            tid = f"toolu_{sid}_{len(lines)}"
            lines.append(json.dumps({"type": "assistant", "cwd": str(self.root), "message": {"content": [
                {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}}))
            lines.append(json.dumps({"type": "user", "toolDenialKind": "permission-rule", "cwd": str(self.root),
                                     "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": True,
                                                              "content": [{"type": "text", "text": reason + " (and more)"}]}]}}))
            t.write_text("\n".join(lines) + "\n")
            rec["i"] = len(lines) - 1 if i is None else i
        with open(self.metrics / "blocked" / f"{sid}.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")

    def run(self, *flags, replay=True, home=None):
        args = [sys.executable, str(SCRIPT), "--metrics", str(self.metrics), "--transcripts", str(self.projects)]
        if replay:
            args += ["--plugin-root", str(self.plugin)]
        env = dict(os.environ, HOME=str(home)) if home else None
        r = subprocess.run(args + list(flags), capture_output=True, text=True, env=env)
        return r.returncode, r.stdout + r.stderr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Fixture(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, want_code, want_line, *flags, **kw):
        code, out = self.f.run(*flags, **kw)
        self.assertEqual(code, want_code, out)
        self.assertIn(want_line, out)


class CountingTest(Base):
    """The counts the shell version kept, unchanged."""

    def setUp(self):
        super().setUp()
        f = self.f
        f.session("old", "2026-09-01T00:00:00.000Z", 3)
        f.deny("old", ADD)                                   # before --since: ignored
        f.session("a", "2026-10-02T01:00:00.000Z", 4)
        f.deny("a", ADD)                                     # plugin
        f.deny("a", "[dotfiles copy] `git add -A` without a plain path is blocked")  # copy, plugin also denied
        f.session("b", "2026-10-02T02:00:00.000Z", 1)
        f.deny("b", "PreToolUse:Bash hook error: `rm -r build` is blocked: only the scratchpad")  # plugin, harness prefix
        f.session("c", "2026-10-02T03:00:00.000Z", 0)        # no Bash: not counted
        f.deny("c", ADD)
        f.session("d", "2026-10-02T04:00:00.000Z", 2)
        f.deny("d", "no-unsigned-push: 1 unsigned commit(s)")  # another guard: ignored

    def test_baseline(self):
        self.check(1, "sessions with a Bash call   3", "--since", SINCE)
        self.check(1, "plugin denials              2", "--since", SINCE)
        self.check(1, "copy denials, plugin silent 0", "--since", SINCE)
        self.check(0, "READY", "--since", SINCE, "--min-sessions", "3", "--min-plugin", "2")

    def test_copy_only_without_a_transcript(self):
        self.f.deny("d", "[dotfiles copy] `rm -r src` is blocked")
        self.f.session("e", "2026-10-02T05:00:00.000Z", 1)
        self.f.deny("e", "no-rm-tree.sh is missing from $HOME/.claude/hooks or crashed")  # copy wrapper
        self.f.session("f", "2026-10-02T06:00:00.000Z", 1)
        self.f.deny("f", "[dotfiles copy] `git add -u` with no path is blocked: stage by path.")  # real wording
        self.check(1, "copy denials, plugin silent 3", "--since", SINCE)
        self.check(1, "not replayed              3  (3 no transcript)", "--since", SINCE)
        self.check(1, "NOT READY", "--since", SINCE, "--min-sessions", "1")
        self.check(0, "READY", "--since", SINCE, "--min-sessions", "1", "--max-copy-only", "3")

    def test_plugin_wrapper_is_broken_not_plugin(self):
        self.f.session("g", "2026-10-02T07:00:00.000Z", 1)
        self.f.deny("g", "no-rm-tree.sh is missing from the plugin directory or crashed, so recursive rm could not be checked")
        self.f.deny("g", "[dotfiles copy] `rm -r lib` is blocked")
        self.check(1, "plugin denials              2", "--since", SINCE)
        self.check(1, "plugin fail-closed denials  1", "--since", SINCE)
        self.check(1, "copy denials, plugin silent 1", "--since", SINCE)
        self.check(1, "NOT READY", "--since", SINCE, "--min-sessions", "1", "--max-copy-only", "9")


class ReplayTest(Base):
    def setUp(self):
        super().setUp()
        self.f.session("r", "2026-10-02T01:00:00.000Z", 2)

    def test_plugin_denies_on_replay(self):
        self.f.deny("r", "PreToolUse:Bash hook error: [dotfiles copy] `rm -r out` is blocked", "rm -rf out # DENYME")
        self.check(0, "plugin denials              1  (want >= 1; 1 of them on replay)", "--since", SINCE, "--min-sessions", "1")
        self.check(0, "copy denials, plugin silent 0", "--since", SINCE, "--min-sessions", "1")

    def test_plugin_allows_on_replay(self):
        self.f.deny("r", "[dotfiles copy] `git reset --hard` is blocked at user scope", "git reset --hard")
        code, out = self.f.run("--since", SINCE, "--min-sessions", "1")
        self.assertEqual(code, 1, out)
        self.assertIn("copy denials, plugin silent 1", out)
        self.assertNotIn("not replayed", out)

    def test_moved_index_falls_back_to_the_reason(self):
        self.f.deny("r", "[dotfiles copy] `git reset --hard` is blocked at user scope", "git reset --hard # DENYME", i=0)
        self.check(0, "1 of them on replay", "--since", SINCE, "--min-sessions", "1")

    def test_ambiguous_fallback_is_not_replayed(self):
        # Two denials share the reason; the index matches neither, so the right command cannot be told apart.
        self.f.deny("r", "[dotfiles copy] `rm -r a` is blocked", "rm -rf a # DENYME", i=0)
        self.f.deny("r", "[dotfiles copy] `rm -r a` is blocked", "rm -rf a", i=0)
        self.check(1, "(2 call not found in transcript)", "--since", SINCE, "--min-sessions", "1")

    def test_crashed_replay_is_not_a_plugin_denial(self):
        self.f.deny("r", "[dotfiles copy] `rm -r x` is blocked", "rm -rf x # CRASH DENYME")
        self.check(1, "(1 plugin replay crashed)", "--since", SINCE, "--min-sessions", "1")

    def test_no_plugin_installed(self):
        self.f.deny("r", "[dotfiles copy] `rm -r x` is blocked", "rm -rf x # DENYME")
        self.check(1, "(1 no plugin installed)", "--since", SINCE, "--min-sessions", "1", replay=False, home=self.f.root)

    def test_no_replay_flag(self):
        self.f.deny("r", "[dotfiles copy] `rm -r x` is blocked", "rm -rf x # DENYME")
        self.check(1, "(1 replay off)", "--since", SINCE, "--min-sessions", "1", "--no-replay")


class UsageTest(Base):
    def test_missing_since(self):
        self.check(2, "required")

    def test_bad_count(self):
        self.check(2, "not a count", "--since", SINCE, "--min-plugin", "x")

    def test_missing_metrics(self):
        self.f.metrics = self.f.root / "nope"
        self.check(2, "no metrics", "--since", SINCE)

    def test_since_forms_normalise_to_utc(self):
        self.check(1, "since 2026-10-01T15:30:00Z", "--since", "2026-10-01T17:30:00+02:00")
        self.check(1, "since 2026-10-01T17:30:00Z", "--since", "2026-10-01 17:30")


if __name__ == "__main__":
    unittest.main()
