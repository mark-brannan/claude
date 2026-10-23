#!/usr/bin/env python3
# Tests for critical_review.py. Run: python3 lib/critical_review.test.py
#
# What matters: a review runs from the /critical-review command to the next
# human prompt, and only that window is priced; sub-agents it started count,
# others do not; the four summary headings are counted, and a heading the
# summary lacks is null, never zero; a bare PR number is resolved from the
# checkout and marked a guess; quoting the command is not running it; a Stop
# that fires again rewrites the session's rows instead of adding, and keeps
# prt's.
#
# Cost per push: well under a second, a step in CI's existing tool-tests job,
# so no new job and nothing drawn from the account's concurrent-job cap.
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import critical_review as cr  # noqa: E402

SID = "c0ffee00-1111-2222-3333-444455556666"
CLOUD = ("/home/user/claude_prompts_scratch", "/workspace/claude_prompts_scratch")
SUMMARY = ("Fixes a typo; ready to merge.\n\n**Fixed** (commit `abc`)\n- the typo `abc`\n- a test\n\n"
           "**Look at**\n- None.\n\n**Pencil**\n- **risk** · kept it\n\n**Decide**\n\n"
           "https://github.com/o/r/pull/7\n")


def command(uuid, args, ts, cwd="/w"):
    return {"type": "user", "uuid": uuid, "timestamp": ts, "cwd": cwd, "origin": {"kind": "human"},
            "message": {"role": "user", "content": "<command-message>critical-review</command-message>\n"
                        f"<command-name>/critical-review</command-name>\n<command-args>{args}</command-args>"}}


def prompt(text, ts):
    return {"type": "user", "timestamp": ts, "origin": {"kind": "human"},
            "message": {"role": "user", "content": text}}


def assistant(mid, ts, out=0, read=0, text="", tools=(), model="claude-opus-5-5", effort="high"):
    content = ([{"type": "text", "text": text}] if text else []) + \
        [{"type": "tool_use", "id": t, "name": "Agent", "input": {}} for t in tools]
    e = {"type": "assistant", "timestamp": ts, "message": {
        "id": mid, "model": model, "content": content,
        "usage": {"input_tokens": 0, "output_tokens": out, "cache_read_input_tokens": read,
                  "cache_creation_input_tokens": 0}}}
    if effort:
        e["effort"] = effort
    return e


def tool_result(ts, content="ok"):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": content}]}}


def write_jsonl(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


class CriticalReviewTest(unittest.TestCase):
    def setUp(self):
        if any(os.path.isdir(d + "/.git") for d in CLOUD):
            self.skipTest("a cloud path holds a state repo here; rows would land in it")
        self.tmp = tempfile.TemporaryDirectory()
        self.T = Path(self.tmp.name)
        self.saved = {k: os.environ.get(k) for k in ("HOME", "CLAUDE_STATE_REPO")}
        os.environ["HOME"], os.environ["CLAUDE_STATE_REPO"] = str(self.T / "home"), ""
        self.tp = self.T / "proj" / f"{SID}.jsonl"
        self.pr_text, self.text = cr.pr_text, ""  # no network: the PR's text is whatever a test sets
        cr.pr_text = lambda pr: self.text

    def tearDown(self):
        cr.pr_text = self.pr_text
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def subagent(self, name, tool_use_id, lines, under=""):
        d = self.T / "proj" / SID / "subagents" / under
        write_jsonl(d / f"agent-{name}.jsonl", lines)
        (d / f"agent-{name}.meta.json").write_text(json.dumps({"toolUseId": tool_use_id}))

    def rows_file(self):
        return self.T / "home" / ".claude" / "state" / "global" / "metrics" / "critical-review" \
            / SID[:2] / f"{SID}.jsonl"

    def rows(self):
        return [json.loads(x) for x in self.rows_file().read_text().splitlines()]

    def session(self):
        write_jsonl(self.tp, [
            prompt("hello", "2026-10-09T07:00:00Z"),
            assistant("m0", "2026-10-09T07:00:05Z", out=999, tools=("t-before",)),
            command("cmd-1", "https://github.com/o/r/pull/7", "2026-10-09T07:10:00Z"),
            assistant("m1", "2026-10-09T07:10:10Z", out=100, read=1000, tools=("t-in",)),
            assistant("m1", "2026-10-09T07:10:10Z", out=100, read=1000),  # a second block, same message
            tool_result("2026-10-09T07:11:00Z"),
            {"type": "user", "isMeta": True, "timestamp": "2026-10-09T07:11:30Z",
             "message": {"role": "user", "content": "Stop hook feedback: write the hand-off"}},
            assistant("m2", "2026-10-09T07:12:00Z", out=50, text=SUMMARY),
            prompt("thanks; now something else", "2026-10-09T07:20:00Z"),
            assistant("m3", "2026-10-09T07:20:05Z", out=5000, text="**Fixed**\n- other"),
        ])
        self.subagent("in", "t-in", [assistant("s1", "2026-10-09T07:10:20Z", out=10, model="claude-haiku-5",
                                               tools=("t-nested",))])
        self.subagent("nested", "t-nested", [assistant("s2", "2026-10-09T07:10:30Z", out=1)], under="deep")
        self.subagent("before", "t-before", [assistant("s0", "2026-10-09T07:00:10Z", out=7777)])

    def test_one_row_priced_over_its_window_only(self):
        self.session()
        cr.record_session(SID, str(self.tp), "/w")
        [row] = self.rows()
        self.assertEqual({k: row[k] for k in ("ts", "session_id", "review_id", "pr", "pr_guessed", "by")},
                         {"ts": "2026-10-09T07:10:00Z", "session_id": SID, "review_id": "cmd-1",
                          "pr": "o/r#7", "pr_guessed": False, "by": "user"})
        self.assertEqual(row["output_tokens"], 100 + 50 + 10 + 1, "m1 once, m2, and both sub-agents")
        self.assertEqual(row["cache_read_input_tokens"], 1000)
        self.assertEqual((row["turns"], row["tool_calls"], row["subagents"]), (4, 2, 2))
        self.assertEqual(row["wall_s"], 120, "the command to the review's last event")
        self.assertEqual((row["model"], row["effort"]), ("claude-opus-5-5", "high"))
        # Opus $5/$25: 150 out + 1000 read; Haiku $1/$5: 11 out.
        self.assertAlmostEqual(row["usd"], round((150 * 25 + 1000 * 0.5 + 11 * 5) / 1e6, 4))
        self.assertEqual([row[k] for k in ("fixed", "look_at", "pencil", "decide")], [2, 0, 1, 0])

    def reviewer(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cr.main(["reviewer", "o/r#1", *argv])
        return out.getvalue().strip()

    def test_the_reviewer_is_no_family_that_coded_the_pr(self):
        trailer = "Co-Authored-By: Claude {} <noreply@anthropic.com>"
        for coders, line in ((("Sonnet 5.5",), "coder=sonnet reviewer=opus"),
                             (("Opus 5.5",), "coder=opus reviewer=fable"),
                             # mixed: a fixer's commits outnumber the coder's; both are excluded
                             (("Opus 5.5", "Fable 1", "Fable 1"), "coder=fable,opus reviewer=sonnet")):
            self.text = "body\n" + "\n".join(trailer.format(m) for m in coders)
            self.assertEqual(self.reviewer(), line)
        self.text = "\n".join(trailer.format(m) for m in ("Opus", "Opus", "Fable", "Sonnet", "Haiku"))
        self.assertEqual(self.reviewer(), "coder=fable,haiku,opus,sonnet reviewer=fable "
                         "(every family coded this PR; fable is the least present)")
        self.text = "Co-Authored-By: Pat <pat@example.com>"
        self.assertIn("coder=unknown reviewer=opus (no trailer names", self.reviewer())

    def test_the_drivers_coder_adds_to_trailers_and_gh_failure_exits(self):
        self.text = "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
        self.assertEqual(self.reviewer("--coder", "claude-opus-5-5"), "coder=opus,sonnet reviewer=fable")
        # an Opus fix, then a re-review with --coder sonnet: Opus must not review its own fix
        self.text = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        self.assertEqual(self.reviewer("--coder", "sonnet"), "coder=opus,sonnet reviewer=fable")
        self.assertRaises(SystemExit, self.reviewer, "--coder", "gpt")
        self.text = None
        self.assertRaises(SystemExit, self.reviewer)

    def test_the_row_records_the_models_the_review_chose(self):
        self.session()
        evs = cr.events(str(self.tp))
        evs.insert(4, tool_result("2026-10-09T07:10:05Z", "coder=sonnet reviewer=opus"))
        write_jsonl(self.tp, evs)
        self.text = None  # a later Stop with gh down changes nothing: the row never asks gh
        [row] = cr.session_rows(SID, str(self.tp), "/w")
        self.assertEqual((row["coder_model"], row["reviewer_model"]), ("sonnet", "opus"))

    def test_a_heading_the_summary_lacks_is_null_and_no_effort_is_null(self):
        write_jsonl(self.tp, [command("c", "o/r#3", "2026-10-09T07:00:00Z"),
                              assistant("m", "2026-10-09T07:00:01Z", effort=None,
                                        text="**Fixed**\n- a\n\n**Decide**\n- **risk** · q?")])
        [row] = cr.session_rows(SID, str(self.tp), "/w")
        self.assertEqual([row[k] for k in ("fixed", "look_at", "pencil", "decide")], [1, None, None, 1])
        self.assertIsNone(row["effort"])
        write_jsonl(self.tp, [command("c", "o/r#3", "2026-10-09T07:00:00Z"),
                              assistant("m", "2026-10-09T07:00:01Z", text="Still working.")])
        [row] = cr.session_rows(SID, str(self.tp), "/w")
        self.assertEqual([row[k] for k in ("fixed", "look_at", "pencil", "decide")], [None] * 4)

    def test_a_bare_number_is_resolved_from_the_checkout_and_marked_a_guess(self):
        repo = self.T / "checkout"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@github.com:mark-brannan/claude.git"], check=True)
        self.assertEqual(cr.pr_of("125", str(repo)), ("mark-brannan/claude#125", True))
        self.assertEqual(cr.pr_of("#125", str(repo)), ("mark-brannan/claude#125", True))
        self.assertEqual(cr.pr_of("125", str(self.T)), (None, True), "no origin: no PR, still a guess")
        self.assertEqual(cr.pr_of("a/b#4 please", ""), ("a/b#4", False))
        self.assertEqual(cr.pr_of("", ""), (None, False))

    def test_quoting_the_command_is_not_running_it(self):
        quoted = prompt("The transcript carries a `<command-name>/critical-review</command-name>` "
                        "message.", "2026-10-09T07:00:00Z")
        write_jsonl(self.tp, [quoted, assistant("m", "2026-10-09T07:00:01Z", text=SUMMARY)])
        cr.record_session(SID, str(self.tp), "/w")
        self.assertFalse(self.rows_file().exists(), "no review, no file")

    def test_a_second_stop_rewrites_its_rows_and_keeps_prts(self):
        self.session()
        cr.record_session(SID, str(self.tp), "/w")
        agent = self.T / "proj" / SID / "subagents" / "agent-in.jsonl"
        cr.save_agent(cr.agent_row(str(agent), "o/r#9", "prt-1"))
        cr.save_agent(cr.agent_row(str(agent), "o/r#9", "prt-1"))
        cr.record_session(SID, str(self.tp), "/w")
        rows = self.rows()
        self.assertEqual(sorted((r["by"], r["review_id"]) for r in rows),
                         [("prt", "agent-in"), ("user", "cmd-1")])
        prt = next(r for r in rows if r["by"] == "prt")
        self.assertEqual((prt["session_id"], prt["pr"], prt["run"], prt["subagents"], prt["output_tokens"]),
                         (SID, "o/r#9", "prt-1", 1, 11), "the agent and the one it started")


if __name__ == "__main__":
    unittest.main()
