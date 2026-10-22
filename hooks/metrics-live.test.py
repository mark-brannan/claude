#!/usr/bin/env python3
# Tests for metrics-live.py, the crossing engine and the event block.
# Run: python3 hooks/metrics-live.test.py
#
# Black-box: every case runs the hook as Claude Code does, a subprocess fed a
# payload on stdin, in a scratch HOME with a fake gh first on PATH. A straight
# translation of the bash suite it replaced (metrics-live.test.sh, 241 cases):
# every assertion is kept, under the same description, in the same order
# within each section.
#
# What matters is that the nag is edge-triggered: a line fires once when its
# counter first crosses, and then not again until the next line. The context
# rungs are counted, never spoken; a gap between prompts starts a new sitting;
# prompts own the sitting clock outright; a Stop on an archivable session past
# the line blocks once with one instruction; and a session with sub-agent
# transcripts beside its own still prints its block (#206).
#
# The transcripts are built here rather than committed: each one exists to
# hold a single usage number, and a fixture file would say less than the
# generator. Every section checks that the hook traced no error.
#
# Cost per push: about ten seconds, a step in CI's existing tool-tests job, so
# no new job and nothing drawn from the account's concurrent-job cap. The
# sections share nothing -- each builds its own scratch world -- so they run
# side by side, one thread each; a section stops at its first failed
# assertion and the others carry on.
import calendar
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOKS = Path(__file__).resolve().parent
HOOK = HOOKS / "metrics-live.py"
FIX = HOOKS / "fixtures" / "friction-contentious.jsonl"
HARNESS = HOOKS / "lib-metrics-test-harness.sh"
ORDERS = HOOKS.parent / "CLAUDE.md"
# 2026-10-01 20:58:09Z, the instant the bedtime case was last red in CI under
# the shell hook, two minutes short of the hour. BED_PIN probes another.
PIN = int(os.environ.get("BED_PIN", "1790888289"))
GH_ONE = "#!/bin/sh\necho 1\n"


def utc(ts, fmt):
    return time.strftime(fmt, time.gmtime(ts))


def tzfmt(ts, tz, fmt):
    import zoneinfo
    import datetime
    return datetime.datetime.fromtimestamp(ts, zoneinfo.ZoneInfo(tz)).strftime(fmt)


class World:
    """One section's scratch HOME, state dir and helpers, as the bash
    suite's preamble and lib-metrics-test-harness.sh built them."""

    def __init__(self, root):
        self.scratch = Path(root)
        self.home = self.scratch / "home"
        self.bin = self.scratch / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("METRICS_", "STOP_VERDICT", "CLAUDE_STATE", "GIT_"))}
        self.env = dict(env, HOME=str(self.home), CLAUDE_STATE_REPO="",
                        METRICS_CONTEXT_LINES="100000 150000 200000", METRICS_CONTEXT_STEP="50000",
                        # Daylight, whatever the wall clock says; the night cases set their own hours.
                        METRICS_STOP_HOUR="24", METRICS_NIGHT_END_HOUR="0",
                        # A grind worker runs this under claude -p; its inherited sdk-cli
                        # would skip every blocking-Stop case.
                        CLAUDE_CODE_ENTRYPOINT="cli",
                        GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                        PATH=f"{self.bin}:{os.environ.get('PATH', '')}")
        self.state = self.home / ".claude" / "state" / "global"
        self.sitf = self.state / "metrics" / "sitting.json"
        self.checks = 0

    # -- assertions, as the bash suite's t/has/hasnt -------------------------
    def t(self, desc, want, got):
        self.checks += 1
        if str(want) != str(got):
            raise AssertionError(f"{desc}\n  want [{want}]\n  got  [{got}]")

    def has(self, desc, pat, text):
        self.checks += 1
        if not any(re.search(pat, ln) for ln in text.split("\n")):
            raise AssertionError(f"(no /{pat}/) {desc}\n  in [{text}]")

    def hasnt(self, desc, pat, text):
        self.checks += 1
        if any(re.search(pat, ln) for ln in text.split("\n")):
            raise AssertionError(f"(has /{pat}/) {desc}\n  in [{text}]")

    # -- transcripts and payloads ------------------------------------------------
    def turn(self, path, n):
        """One human turn plus one assistant turn carrying the context number,
        from lib-metrics-test-harness.sh: the one home for the transcript shape."""
        subprocess.run(["bash", "-c", '. "$1"; turn "$2" "$3"', "_", str(HARNESS), str(path), str(n)],
                       check=True)
        return str(path)

    def askturn(self, path):
        """turn(), with the assistant text an ask: a decision pushed to the user."""
        self.asks = getattr(self, "asks", 0) + 1
        with open(path, "a") as fh:
            fh.write(json.dumps({"type": "assistant", "timestamp": "2026-09-09T10:00:00.000Z",
                                 "requestId": f"q-{time.time()}-{self.asks}",
                                 "message": {"model": "claude-opus-5", "role": "assistant",
                                             "content": [{"type": "text", "text": "Which way should this go?"}],
                                             "usage": {"input_tokens": 40000, "output_tokens": 10,
                                                       "cache_read_input_tokens": 0,
                                                       "cache_creation_input_tokens": 0}}}) + "\n")
            fh.write(json.dumps({"type": "queue-operation", "operation": "enqueue",
                                 "timestamp": "2026-09-09T10:00:00.000Z", "sessionId": "t",
                                 "content": "the first one"}) + "\n")

    @staticmethod
    def payload(tp, sid, cwd, hook="", prompt="", **extra):
        p = {"transcript_path": str(tp), "session_id": sid, "cwd": str(cwd)}
        if hook:
            p["hook_event_name"] = hook
        if prompt:
            p["prompt"] = prompt
        p.update(extra)
        return p

    def run(self, payload, event, show=False, env=None):
        """The hook's (stdout, returncode). stderr must stay empty: a failure
        is the trace file's to hold, never the terminal's."""
        args = [sys.executable, str(HOOK), event, "0"] + (["show"] if show else [])
        p = subprocess.run(args, input=json.dumps(payload), env=dict(self.env, **(env or {})),
                           capture_output=True, text=True, timeout=120)
        if p.stderr:
            raise AssertionError(f"the hook wrote to stderr: {p.stderr}")
        return p.stdout, p.returncode

    def hook(self, payload, event, show=False, env=None):
        return self.run(payload, event, show, env)[0]

    def start(self, payload, event, show=False, env=None):
        args = [sys.executable, str(HOOK), event, "0"] + (["show"] if show else [])
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(self.env, **(env or {})), text=True)
        p.stdin.write(json.dumps(payload))
        p.stdin.close()
        return p

    @staticmethod
    def field(out, *keys):
        try:
            v = json.loads(out) if out.strip() else {}
        except ValueError:
            return ""
        for k in keys:
            v = v.get(k) if isinstance(v, dict) else None
        return "" if v is None else v

    def msg(self, out):
        return self.field(out, "systemMessage")

    def ctx(self, out):
        return self.field(out, "hookSpecificOutput", "additionalContext")

    def decision(self, out):
        return self.field(out, "decision")

    def reason(self, out):
        return self.field(out, "reason")

    # -- state --------------------------------------------------------------------
    def shard(self, d, sid, suffix):
        return self.state / "metrics" / d / sid[:2] / f"{sid}{suffix}"

    def read(self, path):
        return json.loads(Path(path).read_text())

    def write(self, path, value):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) + "\n")

    def update(self, path, **fields):
        v = self.read(path)
        v.update(fields)
        self.write(path, v)

    def clock(self, since_start, since_prompt):
        """The machine-wide sitting clock, minutes since it started and since
        the last prompt."""
        now = int(time.time())
        self.write(self.sitf, {"sitting_start": now - since_start * 60, "last_prompt": now - since_prompt * 60})

    def clock_clear(self):
        if self.sitf.exists():
            self.sitf.unlink()

    def sitting(self, sid, since_start, since_prompt):
        """A session's own state, with the context line out of the way, on a
        shared clock that far in."""
        self.write(self.shard("live", sid, ".nag.json"),
                   {"context_line": 200000, "time_line": 0, "time_line_sitting": 0,
                    "friction_tripped": False, "since_nag": False, "resume_ts": 0, "nag_pending": False})
        self.clock(since_start, since_prompt)

    def sit_start(self):
        return self.read(self.sitf).get("sitting_start") or 0 if self.sitf.exists() else 0

    def nag_field(self, sid, key):
        return self.read(self.shard("live", sid, ".nag.json")).get(key)

    def rows(self, sid, kind=None):
        f = self.shard("crossings", sid, ".jsonl")
        if not f.exists():
            return []
        rows = [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
        return [r for r in rows if kind is None or r.get("kind") == kind]

    def plant(self, sid, verdict="archivable", at=None):
        """stop-continuity.py's verdict, flat as a record from before the shard split."""
        self.write(self.state / "metrics" / "sessions" / f"{sid}.json",
                   {"verdict": verdict, "verdict_at": int(time.time()) if at is None else at})

    def gh(self, script):
        g = self.bin / "gh"
        g.write_text(script)
        g.chmod(0o755)

    def git(self, cwd, *args):
        subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t",
                        "-c", "commit.gpgsign=false", *args],
                       env=self.env, check=True, capture_output=True)

    def repo(self, name, branch, origin=False):
        """A repo with one empty commit; pushed to a bare origin when asked."""
        r = self.scratch / name
        r.mkdir()
        self.git(r, "init", "-q", "-b", branch)
        self.git(r, "commit", "-q", "--allow-empty", "-m", "init")
        if origin:
            bare = self.scratch / f"{name}.git"
            self.git(self.scratch, "init", "-q", "--bare", str(bare))
            self.git(r, "remote", "add", "origin", str(bare))
            self.git(r, "push", "-q", "-u", "origin", branch)
        return r

    def errors(self):
        return [ln for f in glob.glob(f"{self.state}/metrics/hook-errors/*/*.jsonl")
                for ln in Path(f).read_text().splitlines()]


class MetricsLiveTest(unittest.TestCase):
    def world(self):
        tmp = tempfile.mkdtemp(prefix="metrics-live-test-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return World(tmp)

    def done(self, w):
        """A section ran clean: no error traced anywhere."""
        if w.errors():
            raise AssertionError(f"the hook traced errors: {w.errors()}")
        return w.checks

    # --- 1. context rungs are counted, never spoken ------------------------------
    # dotfiles#137: one notice per event, and that notice is the block. A
    # context crossing moves the block's ⛁ cluster and prints no line of its own.
    def section_context_rungs(self):
        w = self.world()
        S = w.scratch
        tp = w.turn(S / "ctx.jsonl", 103000)
        out1 = w.hook(w.payload(tp, "ctx1", S), "prompt")
        w.turn(tp, 152000)
        w.hook(w.payload(tp, "ctx1", S), "prompt")
        out2 = w.hook(w.payload(tp, "ctx1", S), "posttooluse", show=True)
        w.t("a crossing on a prompt says nothing at all", "", w.msg(out1))
        w.has("the block counts both rungs", "^⛁⛁ ", w.msg(out2))
        w.hasnt("and never names the rung it crossed", "/(100|150)k", w.msg(out2))
        w.hasnt("no threshold line rides in front of it", "still room", w.msg(out2))
        w.has("the stop rung still reaches the verdict", "— 💸$", w.msg(out2))
        w.hasnt("and the tail carries no words", "propose|stopping", w.msg(out2))

        # A tool hook inside a sub-agent carries agent_id but reads the PARENT's
        # transcript: it must say nothing, and must not consume the crossing.
        tpa = w.turn(S / "agent.jsonl", 152000)
        outa = w.hook(w.payload(tpa, "agent1", S, "PostToolUse", agent_id="a1b2c3", agent_type="Explore"),
                      "posttooluse", show=True)
        w.t("a tool hook inside a sub-agent is silent", "", outa)
        outp = w.hook(w.payload(tpa, "agent1", S, "PostToolUse"), "posttooluse", show=True)
        w.has("and the parent still gets its block afterwards", "^⛁⛁ ", w.msg(outp))

        # #206: once a sub-agent transcript sits beside the parent's, the
        # parent's block must keep coming, not go silent for the session.
        tps = w.turn(S / "withsubs.jsonl", 152000)
        (S / "withsubs" / "subagents").mkdir(parents=True)
        w.turn(S / "withsubs" / "subagents" / "agent-a1b2c3.jsonl", 5000)
        outs = w.hook(w.payload(tps, "subs1", S, "PostToolUse"), "posttooluse", show=True)
        w.has("a session with sub-agent transcripts still gets its block", "^⛁⛁ ", w.msg(outs))

        w.t("both crossings are recorded, in order", "100000\n150000",
            "\n".join(str(r["at"]) for r in w.rows("ctx1", "context")))
        return self.done(w)

    # --- 2. a 40-minute gap starts a new sitting ---------------------------------
    def section_gap(self):
        w = self.world()
        S = w.scratch
        tp2 = w.turn(S / "sit.jsonl", 1000)
        w.sitting("gap", 61, 40)
        out = w.hook(w.payload(tp2, "gap", S), "prompt")
        w.hasnt("a 40 min gap resets the clock: no 60 min line", "⏱", w.msg(out))
        w.sitting("nogap", 61, 10)
        out = w.hook(w.payload(tp2, "nogap", S), "prompt")
        w.has("a 10 min gap leaves the clock running", "⏱ 1h0[0-9]", w.msg(out))
        w.hasnt("the hour line gives no instruction", "stand up|stop here|/wrapup|offer", w.msg(out))
        out = w.hook(w.payload(tp2, "nogap", S), "prompt")
        w.t("the 60 min line does not repeat", "", w.msg(out))
        w.sitting("twohours", 121, 10)
        out = w.hook(w.payload(tp2, "twohours", S), "prompt")
        w.has("two hours names the elapsed time", "⏱ 2h01", w.msg(out))
        w.hasnt("and gives no instruction either", "stop here|/wrapup", w.msg(out))
        return self.done(w)

    # --- 2b. the clock belongs to the prompt -------------------------------------
    # No verdict is planted, so the Stop nag stays out of the way.
    def section_clock_is_the_prompts(self):
        w = self.world()
        S = w.scratch
        tps = w.turn(S / "stopfirst.jsonl", 1000)
        w.hook(w.payload(tps, "sfirst", S, "Stop"), "stop", show=True)
        w.t("a Stop before any prompt does not start the clock", 0, w.sit_start())
        w.hook(w.payload(tps, "sfirst", S, "SubagentStop"), "subagentstop", show=True)
        w.t("nor does a SubagentStop", 0, w.sit_start())
        out = w.hook(w.payload(tps, "sfirst", S), "prompt")
        w.hasnt("so the first prompt after them is minute zero", "⏱", w.msg(out))
        w.t("and it is the prompt that starts the clock", "yes", "yes" if w.sit_start() > 0 else "no")

        w.sitting("quiet", 61, 10)
        before = w.sit_start()
        out = w.hook(w.payload(tps, "quiet", S, "Stop"), "stop", show=True)
        w.hasnt("a Stop past the line says nothing about sitting", "⏱ sitting", w.msg(out))
        w.t("and leaves the clock exactly where it found it", before, w.sit_start())
        out = w.hook(w.payload(tps, "quiet", S), "prompt")
        w.has("the next prompt is what reports it", "⏱ 1h0[0-9]", w.msg(out))
        return self.done(w)

    # --- 2c. one clock for the machine, one report per session -------------------
    def section_one_clock(self):
        w = self.world()
        S = w.scratch
        tpm = w.turn(S / "multi.jsonl", 1000)

        def P(sid):
            return w.hook(w.payload(tpm, sid, S), "prompt")

        P("mA")
        started = w.sit_start()
        w.t("the first prompt anywhere starts the one clock", "yes", "yes" if started > 0 else "no")
        P("mB")
        w.t("a second session id does not start a second clock", started, w.sit_start())
        w.t("and no session keeps a clock of its own", "",
            "".join(str(w.nag_field(s, "sitting_start") or "") for s in ("mA", "mB")))

        w.clock(61, 10)
        outA = P("mA")
        w.has("a prompt in one session reports the shared hour", "⏱ 1h0[0-9]", w.msg(outA))
        kept = w.sit_start()
        outB = P("mB")
        w.has("and the other session reports the same hour, not zero", "⏱ 1h0[0-9]", w.msg(outB))
        w.t("neither prompt restarted the sitting", kept, w.sit_start())
        w.t("the second prompt advanced the shared last_prompt", "yes",
            "yes" if w.read(w.sitf)["last_prompt"] >= int(time.time()) - 5 else "no")
        w.t("the line does not repeat in the session that said it", "", w.msg(P("mA")))
        w.t("nor in the other one", "", w.msg(P("mB")))

        # A session opened partway into someone else's sitting inherits it.
        w.clock(50, 5)
        outF1 = P("mF")
        w.hasnt("a session opened 50 minutes in says nothing at 50", "⏱", w.msg(outF1))
        w.t("and does not restart the clock it walked in on", 0, w.nag_field("mF", "time_line"))
        w.clock(61, 5)
        outF2 = P("mF")
        w.has("and reports 1h00 at its next prompt", "⏱ 1h0[0-9]", w.msg(outF2))

        # A nag file from before the clock moved out of it: its time_line has
        # no sitting to belong to, so it is spent rather than trusted.
        w.clock(61, 10)
        ss = int(time.time()) - 900
        w.write(w.state / "metrics" / "live" / "mO" / "mOld.nag.json",
                {"context_line": 200000, "time_line": 60, "friction_tripped": False,
                 "sitting_start": ss, "last_prompt": ss, "since_nag": False,
                 "resume_ts": 0, "nag_pending": False})
        w.has("a pre-move nag file does not suppress the new hour", "⏱ 1h0[0-9]", w.msg(P("mOld")))

        # A live cache still at the flat path must not stop the nag file
        # landing in its own shard.
        w.write(w.state / "metrics" / "live" / "flatLive.json", {})
        P("flatLive")
        w.t("a flat live cache: the nag file is still written, in its shard", "yes",
            "yes" if (w.state / "metrics" / "live" / "fl" / "flatLive.nag.json").is_file() else "no")

        # A restarted clock frees every session to speak again, not only the
        # one whose prompt restarted it.
        w.clock(61, 10)
        P("mI")
        w.t("the hour is spent in that session", "", w.msg(P("mI")))
        before_break = w.read(w.sitf)["sitting_start"]
        w.clock(62, 10)
        w.t("which is a different sitting", "no",
            "yes" if before_break == w.read(w.sitf)["sitting_start"] else "no")
        w.has("a restarted clock frees the other session to speak again", "⏱ 1h0[0-9]", w.msg(P("mI")))
        return self.done(w)

    # --- 3. Stop, archivable, past the line --------------------------------------
    def section_stop(self):
        w = self.world()
        S = w.scratch
        repo = w.repo("repo", "feat/nags", origin=True)
        w.gh(GH_ONE)
        tp3 = w.turn(S / "stop.jsonl", 1000)

        # 3b. only the two-hour sitting crossing arms the Stop block.
        def arm(sid, minutes):
            w.clock(minutes, 10)
            w.hook(w.payload(tp3, sid, repo), "prompt")
            w.plant(sid)
            return w.hook(w.payload(tp3, sid, repo, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "24"})

        o = arm("arm1", 61)
        w.clock(61, 10)
        w.has("the one-hour crossing is still reported", "⏱ 1h0[0-9]",
              w.msg(w.hook(w.payload(tp3, "armX", repo), "prompt")))
        w.t("but it does not arm the Stop block", "", w.decision(o))
        o = arm("arm2", 121)
        w.t("the two-hour crossing does", "block", w.decision(o))

        def stop(sid, env=None):
            w.plant(sid)
            return w.hook(w.payload(tp3, sid, repo, "Stop"), "stop", show=True,
                          env={"METRICS_STOP_HOUR": "0", **(env or {})})

        o = stop("stop1h", {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})
        w.t("a headless Stop is not asked for a hand-off", "", w.decision(o))

        o1 = stop("stop1")
        w.t("the first Stop blocks", "block", w.decision(o1))
        w.has("saying what the body holds",
              "^Write the hand-off: replace the body .* next step, then link:, model: and effort: lines",
              w.reason(o1))
        w.hasnt("without leaning on a skill", "/wrapup", w.reason(o1))
        w.hasnt("and nothing about the session ending", "last of the session", w.reason(o1))

        pk = w.state / "pickup"
        pk.mkdir(parents=True)

        def handoff(sid):
            (pk / f"2026-09-09T10-00-{sid}.md").write_text(
                f"status: open\nupdated: x\nsession: {sid}\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: p\n"
                "---\nnext: x\nlink: https://github.com/o/r/pull/7\nmodel: sonnet\neffort: medium\n")

        # An unedited item (body still the prompt line) is no hand-off.
        (pk / "2026-09-09T09-00-stopn.md").write_text(
            "status: open\nupdated: x\nsession: stopn\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: p\n---\np\n")
        o = stop("stopn")
        w.t("an unedited pickup item still blocks", "block", w.decision(o))
        w.has("the notice names the item, without its directory, as unwritten",
              r"^📄 2026-09-09T09-00-stopn\.md \(p\)$", w.msg(o))
        w.has("the notice still carries the metrics block", "^» ", w.msg(o))
        w.has("the reason gives the model the full path",
              r"Item: `/.*/pickup/2026-09-09T09-00-stopn\.md`\. Then answer with the body you wrote", w.reason(o))
        w.hasnt("and no item lines in the reason", "📄", w.reason(o))
        w.has("and keeps the last word the user's", r"no summary, no question, nothing new\.$", w.reason(o))
        (pk / "2026-09-09T11-00-stopm.md").write_text("status: open\nprompt: p\n---\nnext: x\n")
        (pk / "2026-09-09T12-00-stopm.md").write_text("status: open\nprompt: p\n---\np\n")
        o = stop("stopm")
        w.t("two items for one session are each listed with their state",
            "📄 2026-09-09T11-00-stopm.md (saved HH:MM: ? · ? · ?)|📄 2026-09-09T12-00-stopm.md (p)",
            "|".join(re.sub(r"saved [0-9]{2}:[0-9]{2}", "saved HH:MM", ln)
                     for ln in w.msg(o).split("\n") if ln.startswith("📄")))
        w.has("an item-less Stop says there is none", "^📄 no pickup item for stop1$", w.msg(o1))
        w.has("and tells the model where a new one goes", r"none exists yet in /.*/pickup/\.", w.reason(o1))

        # A wrap-up that already wrote its hand-off is never blocked (dotfiles#391).
        handoff("stop0")
        o = stop("stop0")
        o1s = o
        w.t("an armed Stop with the block on disk does not block", "", w.decision(o))
        w.has("and lists the item with its saved time, link, model and effort",
              r"^📄 2026-09-09T10-00-stop0\.md \(saved [0-9]{2}:[0-9]{2}: o/r/pull/7 · sonnet · medium\)$", w.msg(o))
        w.hasnt("and no longer says the hand-off was found", "Hand-off already written|Next time", w.msg(o))
        o = stop("stop0")
        w.t("the next Stop does not block either", "", w.decision(o))
        w.hasnt("and carries no age line", "Hand-off .* old", w.msg(o))
        saved = re.compile(r"saved [0-9:]*")
        w.t("and the saved time does not move between Stops",
            saved.search(w.msg(o1s)).group(0), saved.search(w.msg(o)).group(0))
        # The saved time follows the body.
        nf0 = w.shard("live", "stop0", ".nag.json")
        w.update(nf0, resume_ts=1000000000)
        stop("stop0")
        w.t("an unchanged body keeps its saved time", "yes",
            "yes" if w.nag_field("stop0", "resume_ts") == 1000000000 else "no")
        with open(pk / "2026-09-09T10-00-stop0.md", "a") as fh:
            fh.write("later: edited\n")
        stop("stop0")
        w.t("an edited body restamps its saved time", "yes",
            "yes" if w.nag_field("stop0", "resume_ts") > 1000000000 else "no")

        # The model answers the block by editing its pickup item's body; the
        # hook must find it on disk, not assume it from having asked.
        handoff("stop1")
        o2 = stop("stop1")
        w.t("the second Stop does not block", "", w.decision(o2))
        w.has("and lists the item as saved", r"^📄 2026-09-09T10-00-stop1\.md \(saved [0-9]{2}:[0-9]{2}: ", w.msg(o2))
        o3 = stop("stop1")
        w.t("a later Stop does not block", "", w.decision(o3))
        w.hasnt("and carries no age line", "Hand-off .* old|Next time", w.msg(o3))

        # The block was ignored: say so, never claim one, never block again.
        o = stop("stop3")
        w.t("blocks once", "block", w.decision(o))
        o = stop("stop3")
        w.t("an unanswered block does not re-block", "", w.decision(o))
        w.has("and the item line says there is none", "^📄 no pickup item for stop3$", w.msg(o))
        w.hasnt("never claims it was saved", "saved ", w.msg(o))
        o = stop("stop3")
        w.t("and stays quiet after", "", w.decision(o))

        # A context crossing still arms the Stop, and says nothing on the way.
        tp4 = w.turn(S / "cross.jsonl", 103000)
        w.plant("stop4")
        o = w.hook(w.payload(tp4, "stop4", repo, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "24"})
        w.t("a context crossing at Stop blocks", "block", w.decision(o))
        w.hasnt("and the reason carries no threshold line", "⛁", w.reason(o))

        # A dirty tree is not archivable, so nothing blocks however late it is.
        (repo / "dirty").touch()
        w.plant("stop2", "not archivable: worktree dirty")
        o4 = w.hook(w.payload(tp3, "stop2", repo, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "0"})
        w.t("a dirty tree is never archivable", "", w.decision(o4))
        return self.done(w)

    # --- 3c. order: the block first, the archival verdict after it ---------------
    def section_order(self):
        w = self.world()
        S = w.scratch
        repoo = w.repo("repoo", "feat/order", origin=True)
        w.gh(GH_ONE)
        tpo = w.turn(S / "order.jsonl", 103000)
        w.plant("orderx")
        oO1 = w.hook(w.payload(tpo, "orderx", repoo, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "24"})
        w.t("order setup: the first Stop blocks", "block", w.decision(oO1))
        (w.state / "pickup").mkdir(parents=True)
        (w.state / "pickup" / "2026-09-09T10-00-orderx.md").write_text(
            "status: open\nupdated: x\nsession: orderx\nmodel: m\nbranch: b\npr: none\nwhere: w\nprompt: p\n"
            "---\nnext: x\nlink: https://github.com/o/r/pull/7\nmodel: sonnet\neffort: medium\n")
        # The second Stop also crosses 150k while confirming the hand-off.
        w.turn(tpo, 152000)
        w.plant("orderx")
        oO2 = w.hook(w.payload(tpo, "orderx", repoo, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "24"})
        w.t("order: the confirming Stop does not re-block", "", w.decision(oO2))
        lines = w.msg(oO2).split("\n")

        def first(mark):
            return next((i + 1 for i, ln in enumerate(lines) if mark in ln), 0)

        status_at, block_at, arch_at = first("— "), first("⇢ "), first("📦")
        w.t("both sections are present", "yes", "yes" if status_at and block_at and arch_at else "no")
        w.t("the block opens the message, no line in front of it", 1, status_at)
        w.t("the archival verdict renders after the block", "yes", "yes" if block_at < arch_at else "no")
        w.has("and reports the hand-off it found", r"^📄 .*\(saved ", w.msg(oO2))
        return self.done(w)

    # --- 4. the friction counter is the one line addressed to the model ----------
    # The committed contentious fixture, since the classifier that types a turn
    # as a correction or a rebuke is what is relied on here.
    def section_friction(self):
        if not FIX.is_file():
            self.skipTest(f"{FIX} is missing")
        w = self.world()
        S = w.scratch
        fric_env = {"METRICS_FRICTION_TURNS": "200", "METRICS_SIT_EVERY_MIN": "0"}
        ctx = w.ctx(w.hook(w.payload(FIX, "fric", S), "prompt", env=fric_env))
        w.has("the friction line reaches the model", "corrections or rebukes", ctx)
        w.has("and names the capacity rule", "capacity rule", ctx)
        ctx2 = w.ctx(w.hook(w.payload(FIX, "fric", S), "prompt", env=fric_env))
        w.t("and fires once, not every turn", "0", str(ctx2.count("corrections or rebukes")))
        scr = w.msg(w.hook(w.payload(FIX, "fric2", S), "posttooluse", show=True))
        w.has("friction past its nag threshold trips the reason cluster", "— [^ ]*⚡", scr)

        # --- 4b. with work in flight: land it, then the capacity rule (dotfiles#194).
        fwt = S / "fricflight"
        fwt.mkdir()
        w.git(fwt, "init", "-q")
        w.git(fwt, "checkout", "-q", "-b", "feature")
        (fwt / "dirty.txt").touch()
        fctx1 = w.ctx(w.hook(w.payload(FIX, "fricflight", fwt), "prompt", env=fric_env))
        w.has("with work in flight the friction line says land it, not apply the rule",
              "with work in flight.*Do not raise capacity or offer a stopping point yet", fctx1)
        w.hasnt("and does not carry the ordinary capacity-rule wording yet",
                "Apply the capacity rule from the standing orders, once", fctx1)
        fctx2 = w.ctx(w.hook(w.payload(FIX, "fricflight", fwt), "prompt", env=fric_env))
        w.has("and a second call still says it -- unspent, not fired-once", "with work in flight", fctx2)
        w.git(fwt, "commit", "-q", "--allow-empty", "-m", "init")
        (fwt / "dirty.txt").unlink()
        fctx3 = w.ctx(w.hook(w.payload(FIX, "fricflight", fwt), "prompt", env=fric_env))
        w.has("and once the work lands the ordinary capacity-rule line fires",
              "Apply the capacity rule from the standing orders, once", fctx3)
        w.hasnt("with the in-flight wording gone", "with work in flight", fctx3)
        return self.done(w)

    # --- 5. the ladder extends past the configured lines, forever ----------------
    def section_ladder(self):
        w = self.world()
        S = w.scratch
        tp5 = w.turn(S / "ladder.jsonl", 350000)
        w.hook(w.payload(tp5, "ladder", S), "prompt")
        out5 = w.hook(w.payload(tp5, "ladder", S), "posttooluse", show=True)
        w.has("the ladder reaches past the last configured line", "/350k", w.msg(out5))
        w.has("and the glyph count is capped, with the total after it", r"⛁⛁⛁⛁⛁\(x6\)", w.msg(out5))
        w.t("six rungs cross in one jump, in order", "100000\n150000\n200000\n250000\n300000\n350000",
            "\n".join(str(r["at"]) for r in w.rows("ladder", "context")))
        return self.done(w)

    # --- 6. model injection rides its own context ladder -------------------------
    def section_model_context(self):
        w = self.world()
        S = w.scratch
        quiet = {"METRICS_SIT_EVERY_MIN": "0"}
        tp6 = w.turn(S / "inject.jsonl", 103000)

        def C(tp, sid):
            return w.ctx(w.hook(w.payload(tp, sid, S), "prompt", env=quiet))

        w.t("below the first model rung, nothing reaches the model", "", C(tp6, "inject"))
        w.turn(tp6, 152000)
        w.has("the first crossing at/above the stop line offers to stop", "a stopping point", C(tp6, "inject"))
        w.turn(tp6, 260000)
        ctx6c = C(tp6, "inject")
        w.has("a later crossing names the rung last offered", "last offered at 125k", ctx6c)
        w.hasnt("and does not repeat the stopping-point offer", "a stopping point", ctx6c)
        w.turn(tp6, 261000)
        w.t("and the next prompt over the same rung says nothing", "", C(tp6, "inject"))
        # One call crossing several rungs at once still sends one line.
        tp6b = w.turn(S / "inject2.jsonl", 300000)
        ctx6d = C(tp6b, "inject2")
        w.t("one jump across three stop-eligible rungs still sends one line", 1,
            sum(1 for ln in ctx6d.split("\n") if re.search("stopping point|last offered", ln)))
        return self.done(w)

    # --- 6b. model injection: sitting clock, mirrors section 6 --------------------
    def section_model_sitting(self):
        w = self.world()
        S = w.scratch
        tp2 = w.turn(S / "sit.jsonl", 1000)
        sid = "sitmodel"

        def P():
            return w.ctx(w.hook(w.payload(tp2, sid, S), "prompt"))

        w.sitting(sid, 40, 10)
        w.t("below the first sitting rung, nothing reaches the model", "", P())
        w.clock(61, 10)
        out6f = P()
        w.has("the first sitting crossing is the time, the pickup and a pointer",
              r'^Sitting 1h01 at this machine, past 1h00\. Write the single next step .*pickup item.*without '
              r'showing it\. Standing orders: "At a sitting rung"\.$', out6f)
        w.has("and names the pickup item by this session's short id", rf"pickup/\*-{sid[:8]}\.md", out6f)
        # The pointer is only as good as its target.
        anchor = re.search(r'Standing orders: "([^"]*)"', out6f).group(1)
        w.t("and the standing orders still carry that bold lead", 1,
            sum(1 for ln in ORDERS.read_text().split("\n") if f"**{anchor}" in ln))
        w.hasnt("and never offers a break or asks", r"offer a break|Offer one|\?", out6f)
        w.clock(121, 10)
        out6g = P()
        w.has("a later sitting crossing shapes the stop again at the new rung",
              r"Sitting 2h01 at this machine, past 2h00\. Write the single next step", out6g)
        w.hasnt('with no "last offered" repeat line', "last offered", out6g)
        w.clock(125, 10)
        w.t("and the next prompt inside the same rung says nothing", "", P())
        w.clock(5, 2)
        w.t("a sitting-clock restart resets the model side too", "", P())
        w.clock(61, 10)
        w.has("so the next real crossing shapes a stop again", r"past 1h00\. Write the single", P())

        # --- 6b2. with work in flight: land it; the rung stays unspent.
        wt = S / "inflight"
        wt.mkdir()
        w.git(wt, "init", "-q")
        w.git(wt, "checkout", "-q", "-b", "feature")
        (wt / "dirty.txt").touch()

        def F():
            return w.ctx(w.hook(w.payload(tp2, "sitflight", wt), "prompt"))

        w.sitting("sitflight", 61, 10)
        out6j = F()
        w.has("with work in flight the rung is held until it lands",
              r"with work in flight .*land this first, without asking.*comes back once it lands\. Standing orders",
              out6j)
        w.hasnt("and does not point at the stop yet", r"past 1h00\. Write the single", out6j)
        w.clock(121, 10)
        out6k = F()
        w.has("two hours in flight still holds the rung", "comes back once it lands", out6k)
        w.hasnt("and still does not point at the stop", r"past 2h00\. Write the single", out6k)
        w.clock(125, 10)
        w.t("the in-flight line does not repeat inside its rung", "", F())
        w.git(wt, "commit", "-q", "--allow-empty", "-m", "init")
        (wt / "dirty.txt").unlink()
        w.has("and once the work lands the unspent shaping fires", r"past 2h00\. Write the single", F())
        return self.done(w)

    # --- 6b3. the sitting line's tail: clock first, list second ------------------
    # Every knob below forces one branch: a meal window spanning the whole day,
    # none at all, and the sunset hour gate at 0 (always) or 24 (never).
    def section_tail(self):
        w = self.world()
        S = w.scratch
        loc, outs = w.state / "location.json", w.state / "outside.txt"
        tpt = w.turn(S / "tail.jsonl", 1000)

        def tail_line(sid, **env):
            w.sitting(sid, 61, 10)
            return w.msg(w.hook(w.payload(tpt, sid, S), "prompt", env=env))

        def solar_lon(want):
            """The longitude whose local mean solar time is `want` hours now,
            on the equator, where the day is ~12h07 long all year."""
            utc_h = (int(time.time()) % 86400) / 3600
            lon = (want - utc_h) * 15
            while lon >= 180:
                lon -= 360
            while lon < -180:
                lon += 360
            return "%.3f" % lon

        nomeal = {"METRICS_MEAL_WINDOWS": "", "METRICS_SUN_AFTER_HOUR": "0"}
        w.has("a meal window asks what was eaten", r"^⏱ 1h01 · context [0-9]+k · what did you eat today\?$",
              tail_line("tail1", METRICS_MEAL_WINDOWS="0-24"))
        loc.write_text('{"lat": 0, "lon": %s}\n' % solar_lon(10))
        w.has("daylight left names the sunset in hours", r"^⏱ 1h01 · context [0-9]+k · sun sets in [0-9]+h [0-9]{2}$",
              tail_line("tail2", **nomeal))
        loc.write_text('{"lat": 0, "lon": %s}\n' % solar_lon(17.4))
        w.has("under an hour of daylight names it in minutes", r"^⏱ 1h01 · context [0-9]+k · sun sets in [0-9]+ min$",
              tail_line("tail3", **nomeal))
        w.has("the meal window outranks the sunset", "what did you eat today",
              tail_line("tail4", METRICS_MEAL_WINDOWS="0-24", METRICS_SUN_AFTER_HOUR="0"))
        w.has("before the sunset hour the sun is not mentioned", r"^⏱ 1h01 · context [0-9]+k$",
              tail_line("tail5", METRICS_MEAL_WINDOWS="", METRICS_SUN_AFTER_HOUR="24"))
        outs.write_text("look at the plum tree\n\n")
        loc.write_text('{"lat": 0, "lon": %s}\n' % solar_lon(22))
        w.has("after sunset the line comes from outside.txt", r"^⏱ 1h01 · context [0-9]+k · look at the plum tree$",
              tail_line("tail6", **nomeal))
        loc.write_text('{"lat": null, "lon": null}\n')
        w.has("a placeholder location skips the sunset", r"^⏱ 1h01 · context [0-9]+k · look at the plum tree$",
              tail_line("tail7", **nomeal))
        outs.unlink()
        loc.unlink()
        w.has("with no list and no clock tail the line is the time and context alone", r"^⏱ 1h01 · context [0-9]+k$",
              tail_line("tail8", **nomeal))
        return self.done(w)

    # --- 6b4. the stay valve ------------------------------------------------------
    def section_stay(self):
        w = self.world()
        S = w.scratch
        tps = w.turn(S / "stay.jsonl", 1000)

        def say(sid, prompt):
            return w.hook(w.payload(tps, sid, S, "UserPromptSubmit", prompt), "prompt")

        w.sitting("stay1", 89, 2)
        o = say("stay1", "stay 40")
        w.has("stay <n> answers on screen with the quiet window", "^⏱ 1h29 · staying 40, quiet until 2h09$", w.msg(o))
        w.t("and asks the model for a one-line acknowledgement",
            "The user said stay: acknowledge in one line, nothing else.", w.ctx(o))
        w.t("quiet_until lands in the machine-wide clock file", "yes",
            "yes" if abs(w.read(w.sitf)["quiet_until"] - int(time.time()) - 2400) <= 5 else "no")
        w.t("and the use is logged as a stay crossing", 40,
            "\n".join(str(r["at"]) for r in w.rows("stay1", "stay")))
        # Two hours passes inside the quiet window.
        w.update(w.sitf, sitting_start=int(time.time()) - 121 * 60)
        o = say("stay1", "go on")
        w.hasnt("a rung crossed while quiet prints no sitting line", "⏱", w.msg(o))
        w.t("and sends no sitting injection", "", w.ctx(o))
        # Once the quiet ends, the unspent rung is said on the next prompt.
        w.update(w.sitf, quiet_until=1)
        o = say("stay1", "go on")
        w.has("after the quiet the rung it covered is said", "^⏱ 2h01", w.msg(o))
        w.has("and the stop is shaped then", r"past 2h00\. Write the single", w.ctx(o))

        w.sitting("stay2", 10, 2)
        w.has("bare stay quiets for the default 30", "staying 30, quiet until 40m$", w.msg(say("stay2", "stay")))
        w.sitting("stay3", 61, 2)
        o = say("stay3", "stay a while longer")
        w.hasnt("anything but stay [minutes] is an ordinary prompt", "staying", w.msg(o))
        w.has("and the rung fires as usual", "^⏱ 1h01", w.msg(o))
        return self.done(w)

    # --- 6b5. bedtime --------------------------------------------------------------
    # One question per evening, machine-wide, on the first prompt after the
    # night hour; a bare clock time is the reply; a warning before it, the hour
    # itself once, then silence. The clock is pinned (METRICS_NOW) so the case
    # cannot move under the minute and hour boundaries it rounds to.
    def section_bedtime(self):
        w = self.world()
        S = w.scratch
        tpb = w.turn(S / "bed.jsonl", 1000)
        loc = w.state / "location.json"
        w.write(loc, {"tz": "UTC"})
        night = {"METRICS_STOP_HOUR": "0", "METRICS_NIGHT_END_HOUR": "0", "METRICS_NOW": str(PIN)}

        def BP(sid, prompt, **env):
            return w.hook(w.payload(tpb, sid, S, "UserPromptSubmit", prompt), "prompt", env={**night, **env})

        def BT(sid):
            return w.hook(w.payload(tpb, sid, S, "PostToolUse"), "posttooluse", show=True, env=night)

        def BD(sid, prompt):
            return w.hook(w.payload(tpb, sid, S, "UserPromptSubmit", prompt), "prompt", env={"METRICS_NOW": str(PIN)})

        def set_bed(b):
            w.update(w.sitf, bed_at=b)

        def kinds(sid):
            return "".join(f"{r['kind']} " for r in w.rows(sid) if r["kind"].startswith("bed_"))

        o = BD("bed1", "go on")
        w.t("by day nothing is asked", "", w.msg(o))
        o = BP("bed1", "go on")
        w.t("the first prompt after the night hour asks", "what time would you like to go to bed?", w.msg(o))
        w.t("and nothing goes to the model for it", "", w.ctx(o))
        w.t("the ask is stamped on the evening, machine-wide", utc(PIN, "%Y-%m-%d"), w.read(w.sitf)["bed_asked_eve"])
        w.t("the next prompt does not ask again", "", w.msg(BP("bed1", "go on")))
        w.t("nor does another session the same evening", "", w.msg(BP("bed2", "go on")))
        w.t("a sentence with a number in it is an ordinary prompt", "", w.msg(BP("bed1", "11 is bedtime")))
        w.t("an hour past 23 is not a time", "", w.msg(BP("bed1", "25")))
        want = utc(PIN + 420, "%H:%M")
        o = BP("bed1", want)
        w.t("a bare HH:MM is the reply", f"bed at {want} noted", w.msg(o))
        w.t("and the model is told to acknowledge in one line",
            f"The user named a bedtime, {want}: acknowledge in one line, nothing else.", w.ctx(o))
        w.t("bed_at lands in the machine-wide clock file", "yes",
            "yes" if abs(w.read(w.sitf)["bed_at"] - PIN - 420) <= 60 else "no")
        hb = (int(utc(PIN, "%H")) + 1) % 24
        # In an hour's last minutes the next hour is inside the warning window.
        o = BP("bed1", str(hb), METRICS_BED_WARN_MIN="0")
        w.has("a bare hour is the next time the clock reads it", "^bed at [0-9][0-9]:00 noted$", w.msg(o))
        d = w.read(w.sitf)["bed_at"] - PIN
        w.t("and that is within the hour", "yes", "yes" if 0 < d <= 3600 else "no")

        set_bed(PIN + 240)
        o = BP("bed1", "go on")
        w.has("inside the warning window the minutes left are on screen", "^4 min to [0-9][0-9]:[0-9][0-9]$", w.msg(o))
        w.has("and the model gets the sitting rung's shaping instruction",
              r"Bedtime [0-9:]+ is 4 minutes away\. Write the single next step.*Standing orders", w.ctx(o))
        w.hasnt("which never asks", r"\?", w.ctx(o))
        o = BP("bed1", "go on")
        w.t("the warning is said once", "", w.msg(o) + w.ctx(o))
        w.has("another open session says it once too, on a tool call", "^4 min to ", w.msg(BT("bed2")))

        set_bed(PIN - 60)
        o = BP("bed1", "go on")
        w.has("past the hour: the time now, and the time named", "^ok, it's [0-9:]+, you said [0-9:]+$", w.msg(o))
        w.has("the model says it once and shapes the stop",
              r"^It's [0-9:]+; the user said bed at [0-9:]+\. Say that once\. Write the single next step.*Standing orders",
              w.ctx(o))
        o = BP("bed1", "go on")
        w.t("then silence", "", w.msg(o) + w.ctx(o))
        w.t("on tool calls too", "", w.ctx(BT("bed1")))
        w.t("every step is a crossing the measurement can read", "bed_ask bed_set bed_set bed_warn bed_past ",
            kinds("bed1"))

        want2 = utc(PIN + 600, "%H:%M")
        w.t("a new time can be named after the hour", f"bed at {want2} noted", w.msg(BP("bed1", want2)))
        set_bed(PIN + 170)
        w.has("and it re-arms the warning", "^3 min to ", w.msg(BP("bed1", "go on")))

        set_bed(PIN - 60)
        o = BD("bed3", "go on")
        w.t("a bedtime left from last night is not read out by day", "", w.msg(o) + w.ctx(o))

        loc.unlink()
        w.clock_clear()
        BP("bed4", "go on")
        wantp = tzfmt(PIN + 420, "America/Los_Angeles", "%H:%M")
        w.t("without a tz in location.json the clock is Pacific", f"bed at {wantp} noted", w.msg(BP("bed4", wantp)))
        w.clock_clear()

        # A METRICS_NOW that is not a plain integer is ignored: the hook stays
        # on the real clock and the value is never evaluated.
        pwned = S / "pwned"
        w.hook(w.payload(tpb, "bedx", S, "UserPromptSubmit", "go on"), "prompt",
               env={"METRICS_NOW": f"a[$(touch {pwned})]", "METRICS_STOP_HOUR": "24"})
        w.t("a non-integer METRICS_NOW runs nothing", "no", "yes" if pwned.exists() else "no")
        w.t("and the hook still records its session on the real clock", "yes",
            "yes" if w.read(w.shard("live", "bedx", ".json"))["updated_at"][:4] == utc(time.time(), "%Y") else "no")
        return self.done(w)

    # --- 6c. decision load never reaches the model ---------------------------------
    def section_decisions(self):
        w = self.world()
        S = w.scratch
        quiet = {"METRICS_SIT_EVERY_MIN": "0"}
        tp = w.turn(S / "decmodel.jsonl", 40000)
        ctx = w.ctx(w.hook(w.payload(tp, "decmodel", S), "prompt", env=quiet))
        w.t("below the first decision rung, nothing reaches the model", "", ctx)
        for _ in range(22):
            w.askturn(tp)
        ctx = w.ctx(w.hook(w.payload(tp, "decmodel", S), "prompt", env=quiet))
        w.hasnt("past every old decision rung, nothing about decisions reaches the model",
                "decisions pushed to the user", ctx)
        return self.done(w)

    # --- 7. the sitting line carries context and git state ----------------------
    def section_sitting_git(self):
        w = self.world()
        S = w.scratch
        repo7 = w.repo("repo7", "feat/nags")
        tp7 = w.turn(S / "sit7.jsonl", 41000)
        (repo7 / "scratch-file").touch()
        w.clock(61, 10)
        o7 = w.msg(w.hook(w.payload(tp7, "sit7", repo7), "prompt",
                          env={"METRICS_MEAL_WINDOWS": "", "METRICS_SUN_AFTER_HOUR": "24"}))
        w.has("the sitting line carries the context", "^⏱ 1h0[0-9] · context 41k", o7)
        w.has("and shows the dirty tree at its end", "^⏱ 1h0[0-9] · context 41k ⎇ 1~$", o7)
        return self.done(w)

    # --- 8. the 📦 line is stop-continuity.py's verdict, read back -------------
    def section_verdict(self):
        w = self.world()
        S = w.scratch
        repo8 = w.repo("repo8", "feat/ahead")
        tp8 = w.turn(S / "repo8.jsonl", 1000)

        def S8(sid, **env):
            return w.msg(w.hook(w.payload(tp8, sid, repo8, "Stop"), "stop", show=True,
                                env={"METRICS_STOP_HOUR": "24", **env}))

        def after_box(m):
            lines = m.split("\n")
            i = next(i for i, ln in enumerate(lines) if "📦" in ln)
            return lines[i + 1] if i + 1 < len(lines) else ""

        w.plant("stop8a", "not archivable: `feat/ahead` has no upstream (never pushed)")
        m8 = S8("stop8a")
        w.has("a planted reason is the 📦 line",
              r"^📦 not archivable: `feat/ahead` has no upstream \(never pushed\)\. \(feat/ahead stop8a\)$", m8)
        w.has("and the line under it explains it", "^→ never pushed: ", after_box(m8))
        w.plant("stop8b")
        m8b = S8("stop8b")
        w.has("a planted archivable verdict is the 📦 line", r"^📦 archivable\. \(feat/ahead stop8b\)$", m8b)
        w.hasnt("and nothing explains it", "^→ ", m8b)
        w.plant("stop8c", "not archivable: worktree dirty, 2 commit(s) unpushed")
        m8c = S8("stop8c")
        w.t("two reasons, one explanation line each", 2, sum(1 for ln in m8c.split("\n") if ln.startswith("→ ")))
        now8 = int(time.time())
        w.plant("stop8d", "archivable", now8 - 100)
        m8d = S8("stop8d", STOP_VERDICT_SINCE=str(now8))
        w.has("a verdict older than this Stop reads as did not finish",
              r"^📦 not archivable: the Stop hook did not finish\. ", m8d)
        w.has("and is explained as such", "^→ no verdict this turn: ", after_box(m8d))
        m8e = S8("stop8d", STOP_VERDICT_SINCE=str(now8 - 100))
        w.has("the same verdict at the boundary is current", r"^📦 archivable\. ", m8e)
        m8f = S8("stop8none")
        w.has("no verdict at all reads as did not finish", r"^📦 not archivable: the Stop hook did not finish\. ", m8f)
        w.plant("stop8g", "not archivable: something no explanation knows")
        w.has("an unknown reason is still shown", "something no explanation knows", S8("stop8g"))
        return self.done(w)

    # --- 9. the turns line survives a clean tree --------------------------------
    def section_turns_line(self):
        w = self.world()
        S = w.scratch
        repo9 = w.repo("repo9", "main")
        tp9 = w.turn(S / "repo9.jsonl", 1000)
        stop24 = {"METRICS_STOP_HOUR": "24"}
        o9 = w.msg(w.hook(w.payload(tp9, "show9", repo9, "Stop"), "stop", show=True, env=stop24))
        w.has("a clean tree still prints the turns line", "⇢ [0-9]+ ⚙ [0-9]+", o9)
        w.hasnt("and says nothing about git state", "⎇", o9)
        (repo9 / "scratch-file").touch()
        o9b = w.msg(w.hook(w.payload(tp9, "show9b", repo9, "Stop"), "stop", show=True, env=stop24))
        w.has("a dirty tree appends git state to the same line", "⇢ [0-9]+ ⚙ [0-9]+ ⎇ 1~", o9b)

        # --- 9b. the turns line is byte-identical to the jq it replaced.
        def old_second(sid):
            return subprocess.run(
                ["jq", "-r", "-L", str(HOOKS),
                 'include "lib-metrics-fmt"; turns + ((work // "") as $w | if $w == "" then "" else " " + $w end)',
                 str(w.shard("live", sid, ".json"))], capture_output=True, text=True).stdout.rstrip("\n")

        def rendered_second(m):
            hit = re.search("⇢.*", m)
            return hit.group(0) if hit else ""

        w.t("clean tree: turns line matches the jq it replaced", old_second("show9"), rendered_second(o9))
        w.t("dirty tree: turns line matches the jq it replaced", old_second("show9b"), rendered_second(o9b))
        return self.done(w)

    # --- 10. the block survives $OUT being deleted mid-run -----------------------
    # dotfiles#152: stop-continuity.py deletes the cache concurrently; the
    # display comes from memory, not a re-read of the cache file.
    def section_out_deleted(self):
        w = self.world()
        S = w.scratch
        origin = S / "origin10.git"
        w.git(S, "init", "-q", "--bare", str(origin))
        repo10 = w.repo("repo10", "main")
        w.git(repo10, "remote", "add", "origin", str(origin))
        w.git(repo10, "push", "-q", "-u", "origin", "main")
        w.git(repo10, "checkout", "-q", "-b", "feat/race")
        w.git(repo10, "commit", "-q", "--allow-empty", "-m", "work")
        w.git(repo10, "push", "-q", "-u", "origin", "feat/race")
        tp10 = w.turn(S / "race.jsonl", 1000)
        w.gh("#!/bin/sh\nsleep 0.3\necho 1\n")
        out10 = w.shard("live", "race", ".json")
        p = w.start(w.payload(tp10, "race", repo10, "Stop"), "stop", show=True, env={"METRICS_STOP_HOUR": "24"})
        deadline = time.time() + 60
        while not out10.exists() and time.time() < deadline:
            time.sleep(0.001)
        if out10.exists():
            out10.unlink()
        o10, err = p.communicate(timeout=120)
        w.has("the block still opens with $OUT removed mid-run", "^(»|⛁)", w.msg(o10))
        w.t("$OUT was actually gone when the hook read it", "absent", "present" if out10.exists() else "absent")
        return self.done(w)

    # --- 11. calm states, and the ⏰ tier ---------------------------------------
    # DAY forces the night window shut, so a real Pacific hour past 22:00
    # cannot trip the night reason (#362, #347).
    def section_calm(self):
        w = self.world()
        S = w.scratch
        day = {"METRICS_STOP_HOUR": "24", "METRICS_NIGHT_END_HOUR": "0"}
        tp11 = w.turn(S / "calm.jsonl", 1000)

        def T(sid, **env):
            return w.msg(w.hook(w.payload(tp11, sid, S), "posttooluse", show=True, env=env))

        o11 = T("calm", **day)
        w.has("friction at zero shows its calm glyph", r"🌌\(x0\)", o11)
        w.has("decisions at zero show theirs", r"🧘\(x0\)", o11)
        w.has("and blocked is unchanged", r"🔧✅\(x0\)", o11)
        w.hasnt("a calm block carries no verdict tail", " — ", o11)
        tp11p = w.turn(S / "calm-prompt.jsonl", 1000)
        o11p = w.msg(w.hook(w.payload(tp11p, "calmprompt", S), "prompt", show=True))
        w.has("UserPromptSubmit renders the block too", "^(»|⛁)", o11p)

        s = int(time.time()) - 9000
        w.write(w.sitf, {"sitting_start": s, "last_prompt": s})
        o11b = T("calm2", **day)
        w.has("past the hot rung the glyph changes", "⏱2h30(⏱️|🌙){3}⏰⏰", o11b)
        o11c = T("calm3", METRICS_SIT_HOT_RUNG="9", **day)
        w.has("and the rung is a knob like every other", "⏱2h30(⏱️|🌙){5}", o11c)
        w.has("the sitting reason glyph trips at the hot rung", "— [^ ]*⏱️", o11b)
        o11d = T("calm4", METRICS_SIT_HOT_RUNG="9", **day)
        w.hasnt("and stays quiet while the rung is raised past it", " — ", o11d)
        o11n = T("calm5", METRICS_STOP_HOUR="0", METRICS_NIGHT_END_HOUR="24", METRICS_SIT_HOT_RUNG="9")
        w.has("at night a sitting clock alone trips the night reason", "— 🌙$", o11n)
        return self.done(w)

    # --- 12. PostToolUse drives the engine and may carry an injection ------------
    def section_posttooluse(self):
        w = self.world()
        S = w.scratch
        tp12 = w.turn(S / "ptu.jsonl", 40000)
        w.hook(w.payload(tp12, "ptu", S), "prompt")
        w.turn(tp12, 152000)
        o12 = w.hook(w.payload(tp12, "ptu", S), "posttooluse", show=True)
        w.has("a rung crossed by a tool call injects on that call", "Context at 152k", w.ctx(o12))
        w.t("and the injection names PostToolUse, not the prompt event", "PostToolUse",
            w.field(o12, "hookSpecificOutput", "hookEventName"))
        w.has("while the block still renders in the same object", "— 💸", w.msg(o12))
        w.turn(tp12, 153000)
        o12b = w.hook(w.payload(tp12, "ptu", S), "posttooluse", show=True)
        w.t("the next tool call injects nothing -- no new rung", "", w.ctx(o12b))
        w.has("though the block is unaffected", "— 💸", w.msg(o12b))
        # The repeat arm, at 3 rather than the shipped 20.
        for n in (2, 3):
            w.turn(tp12, 153000 + n)
            o12c = w.hook(w.payload(tp12, "ptu", S), "posttooluse", show=True,
                          env={"METRICS_MODEL_CONTEXT_REPEAT": "3"})
        w.has("a raised rung is said again after the repeat count",
              "for 3 tool calls: a stopping point is due", w.ctx(o12c))
        w.turn(tp12, 154000)
        o12d = w.hook(w.payload(tp12, "ptu", S), "posttooluse", show=True, env={"METRICS_MODEL_CONTEXT_REPEAT": "3"})
        w.t("and the counter resets, so it does not repeat every call", "", w.ctx(o12d))
        # A Stop takes no injection.
        tp12s = w.turn(S / "ptu-stop.jsonl", 152000)
        o12e = w.hook(w.payload(tp12s, "ptustop", S), "stop", show=True)
        w.t("a Stop never carries an additionalContext", "", w.ctx(o12e))
        # Prompts still own the counters wound by the user's rhythm.
        before = w.sit_start()
        w.hook(w.payload(tp12, "ptu", S), "posttooluse", show=True)
        w.t("a tool call leaves the sitting clock where it found it", before, w.sit_start())
        return self.done(w)

    # --- 13. day decisions: counted machine-wide, never nagged (#301) -----------
    def section_day_decisions(self):
        w = self.world()
        S = w.scratch
        dayf = w.state / "metrics" / "day-decisions.json"
        tp = w.turn(S / "day-a.jsonl", 40000)
        for _ in range(22):
            w.askturn(tp)
        o13b = w.hook(w.payload(tp, "day-a", S), "prompt", show=True, env={"METRICS_SIT_EVERY_MIN": "0"})
        w.t("no day line on screen at any count", "", "".join(re.findall("☀.*", w.msg(o13b))))
        w.t("no gate line on screen at any count", "", "".join(re.findall("⚖ [0-9].*", w.msg(o13b))))
        w.t("and nothing about decisions reaches the model", "", "".join(re.findall("[0-9]* decisions.*", w.ctx(o13b))))
        w.t("but the day counter still counts", "22", w.read(dayf)["sessions"]["day-a"]["total"])
        # A gap past METRICS_DECISION_GAP_MIN anywhere starts a fresh day.
        w.update(dayf, last_prompt=int(time.time()) - 200 * 60)
        tpd = w.turn(S / "day-c.jsonl", 40000)
        w.hook(w.payload(tpd, "day-c", S), "prompt", show=True,
               env={"METRICS_DECISION_GAP_MIN": "180", "METRICS_SIT_EVERY_MIN": "0"})
        w.t("a gap past the limit clears the day, so the store holds only the new session", "day-c",
            next(iter(w.read(dayf)["sessions"]), ""))
        return self.done(w)

    # --- 14. the nag lock never blocks the hook (dotfiles#161) -------------------
    def section_lock(self):
        w = self.world()
        S = w.scratch
        tp = w.turn(S / "lock.jsonl", 103000)
        lockdir = w.state / "metrics" / "live" / "lockcase.lock"
        lockdir.mkdir(parents=True)
        (lockdir / "meta").write_text(f"pid={os.getpid()}\nhostname={os.uname().nodename}\n")
        out14, rc14 = w.run(w.payload(tp, "lockcase", S), "posttooluse", show=True)
        w.t("a held lock never blocks the hook", 0, rc14)
        w.has("the block still renders normally", "⛁", w.msg(out14))
        nag = w.shard("live", "lockcase", ".nag.json")
        w.t("and the nag write is skipped while the lock is held", "no", "yes" if nag.is_file() else "no")
        shutil.rmtree(lockdir)
        w.hook(w.payload(tp, "lockcase", S), "posttooluse", show=True)
        w.t("once the lock is free, the same session writes normally", "yes", "yes" if nag.is_file() else "no")
        w.t("and releases the lock dir behind it", "no", "yes" if lockdir.is_dir() else "no")
        return self.done(w)

    # --- 15. what followed a sitting rung ----------------------------------------
    # Each ⏱ crossing is stamped once, at the session's next prompt: minutes to
    # it, whether it was a `stay`, whether the gap ran past the sitting gap.
    def section_time_after(self):
        w = self.world()
        S = w.scratch
        tp = w.turn(S / "after.jsonl", 1000)

        def backdate(sid, minutes):
            f = w.shard("crossings", sid, ".jsonl")
            ts = utc(time.time() - minutes * 60, "%Y-%m-%dT%H:%M:%SZ")
            rows = [dict(r, ts=ts) if r["kind"] == "time" else r for r in w.rows(sid)]
            f.write_text("".join(json.dumps(r) + "\n" for r in rows))

        def after(sid):
            return "\n".join(json.dumps([r["at"], r["min"], r["stay"], r["quiet"]], separators=(",", ":"))
                             for r in w.rows(sid, "time_after"))

        def say(sid, prompt=""):
            w.hook(w.payload(tp, sid, S, "UserPromptSubmit" if prompt else "", prompt), "prompt")

        w.sitting("aft", 61, 5)
        say("aft")
        w.t("the crossing prompt stamps nothing", "", after("aft"))
        backdate("aft", 3)
        say("aft", "  Stay.")
        w.t("the next prompt stamps minutes, stay, not quiet", "[60,3,true,false]", after("aft"))
        say("aft")
        w.t("and a crossing is stamped once", 1, len(w.rows("aft", "time_after")))

        w.sitting("aft2", 61, 5)
        say("aft2")
        backdate("aft2", 40)
        say("aft2", "stay here and fix it")
        w.t("a gap past the sitting gap is quiet; a sentence is not a stay", "[60,40,false,true]", after("aft2"))

        w.sitting("aft3", 61, 5)
        say("aft3")
        backdate("aft3", 1)
        say("aft3", "/stay 30")
        w.t("`stay <minutes>` is a stay", "[60,1,true,false]", after("aft3"))
        return self.done(w)

    # --- 16. how a sitting rung's sitting ended -----------------------------------
    # A `stay <n>` keeps its minutes; each crossing gets minutes to the
    # sitting's final prompt, on Stop and at the next sitting start, and whether
    # a `stay <n>` deadline was overrun. A Stop that changes nothing appends nothing.
    def section_time_last(self):
        w = self.world()
        S = w.scratch
        tp = w.turn(S / "after.jsonl", 1000)

        def shift_ts(sid, kind, minutes):
            f = w.shard("crossings", sid, ".jsonl")
            rows = []
            for r in w.rows(sid):
                if r["kind"] == kind:
                    t0 = calendar.timegm(time.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ"))
                    r = dict(r, ts=utc(t0 - minutes * 60, "%Y-%m-%dT%H:%M:%SZ"))
                rows.append(r)
            f.write_text("".join(json.dumps(r) + "\n" for r in rows))

        def said(sid, prompt):
            w.hook(w.payload(tp, sid, S, "UserPromptSubmit", prompt), "prompt")

        def stop(sid):
            w.hook(w.payload(tp, sid, S, "Stop"), "stop")

        def last(sid):
            return "\n".join(json.dumps([r["min_to_last"], r["overrun"]], separators=(",", ":"))
                             for r in w.rows(sid, "time_last"))

        w.sitting("end1", 61, 5)
        said("end1", "go")
        shift_ts("end1", "time", 10)
        said("end1", "stay 30")
        w.t("`stay <n>` keeps its minutes", 30, "\n".join(str(r["stay_min"]) for r in w.rows("end1", "time_after")))
        stop("end1")
        w.t("Stop stamps minutes to the last prompt, deadline not overrun", "[10,false]", last("end1"))
        stop("end1")
        w.t("and an unchanged reading is not stamped again", 1, len(w.rows("end1", "time_last")))

        w.sitting("end2", 61, 5)
        said("end2", "go")
        shift_ts("end2", "time", 15)
        said("end2", "stay 2")
        shift_ts("end2", "time_after", 5)
        stop("end2")
        w.t("a prompt past the `stay <n>` deadline is an overrun", "[15,true]", last("end2"))

        w.sitting("end3", 61, 5)
        said("end3", "go")
        shift_ts("end3", "time", 50)
        w.sitting("end4", 80, 40)
        said("end4", "back")
        w.t("the next sitting start stamps every chat, from the old last prompt", "[10,null]", last("end3"))
        return self.done(w)

    # --- 17. a live curia sitting silences the sitting nags -----------------------
    # A LIVE marker naming the session withholds the screen and model sitting
    # lines; a marker naming another session does not; counting carries on.
    def section_curia(self):
        w = self.world()
        S = w.scratch
        tp2 = w.turn(S / "sit.jsonl", 1000)
        cx = w.state / "curia" / "cx"
        cx.mkdir(parents=True)

        def iso(ago=0):
            return utc(time.time() - ago, "%Y-%m-%dT%H:%M:%SZ")

        def P(sid, tp=tp2):
            return w.hook(w.payload(tp, sid, S), "prompt")

        w.sitting("cur1", 61, 10)
        (cx / "LIVE").write_text(f"cur1 {iso()}\n")
        out17 = P("cur1")
        w.hasnt("a live curia names the session: no sitting line", "⏱ 1h0", w.msg(out17))
        w.t("and nothing reaches the model", "", w.ctx(out17))
        w.t("and the sitting is still counted", "yes", "yes" if w.sitf.is_file() else "no")
        w.sitting("cur2", 61, 10)
        w.has("a LIVE naming another session leaves this one nagging", "⏱ 1h0[0-9]", w.msg(P("cur2")))
        # Two hours must not arm the Stop hand-off block while the curia is live.
        w.sitting("cur3", 121, 10)
        (cx / "LIVE").write_text(f"cur3 {iso()}\n")
        P("cur3")
        w.t("a live curia past two hours does not arm the Stop nag", "false",
            json.dumps(w.nag_field("cur3", "since_nag")))
        w.sitting("cur4", 121, 10)
        P("cur4")
        w.t("and without one it does", "true", json.dumps(w.nag_field("cur4", "since_nag")))
        # A long pause in a live sitting stays silent; only a marker past the
        # 8-hour backstop stops silencing.
        idle = S / "idle.jsonl"
        shutil.copy(tp2, idle)
        os.utime(idle, (time.time() - 360, time.time() - 360))
        w.sitting("cur5", 61, 10)
        (cx / "LIVE").write_text(f"cur5 {iso(1800)}\n")
        w.hasnt("a sitting past 25 min with a 6 min pause stays silent", "⏱", w.msg(P("cur5", idle)))
        w.sitting("cur6", 61, 10)
        (cx / "LIVE").write_text(f"cur6 {iso(9 * 3600)}\n")
        w.has("a marker older than 8 hours no longer silences the session", "⏱ 1h0[0-9]", w.msg(P("cur6", idle)))
        # Gentle lines are held while the curia is live and said once when it is not.
        held = w.shard("live", "cur1", ".held")
        w.t("the sitting line was held, not dropped", "yes", "yes" if held.is_file() and held.stat().st_size else "no")
        time.sleep(1)
        (cx / "CLOSED").write_text(f"cur1 {iso()}\n")
        w.hook(w.payload(tp2, "cur1", S, "Stop"), "stop", show=True)
        w.t("a Stop after the close leaves the held line for the next prompt", "yes",
            "yes" if held.is_file() and held.stat().st_size else "no")
        w.has("at the close (CLOSED beside a fresh LIVE) the held sitting line is delivered",
              "⏱ 1h0[0-9]", w.msg(P("cur1")))
        w.hasnt("and not repeated on the prompt after", "⏱", w.msg(P("cur1")))
        time.sleep(1)
        (cx / "LIVE").write_text(f"cur1 {iso()}\n")
        w.sitting("cur1", 121, 10)
        w.hasnt("a newer LIVE supersedes the CLOSED: silent again", "⏱", w.msg(P("cur1")))

        # Bedtime: held, then delivered once.
        night = {"METRICS_STOP_HOUR": "0", "METRICS_NIGHT_END_HOUR": "0", "METRICS_NOW": str(PIN)}

        def BP(sid):
            return w.hook(w.payload(tp2, sid, S, "UserPromptSubmit", "go on"), "prompt", env=night)

        w.update(w.sitf, bed_at=PIN + 240, bed_asked_eve=utc(PIN, "%Y-%m-%d"))
        (cx / "LIVE").write_text(f"bed3 {iso()}\n")
        o = BP("bed3")
        w.t("a bedtime warning is silent during a live curia", "", w.msg(o) + w.ctx(o))
        (cx / "LIVE").unlink()
        w.has("and delivered once at the close", "4 min to [0-9][0-9]:[0-9][0-9]", w.msg(BP("bed3")))
        w.t("and not again", "", w.msg(BP("bed3")))
        return self.done(w)

    # --- beyond the bash suite: what the port added ---------------------------------
    def section_failure_is_traced(self):
        """A failure never blocks the tool call and never vanishes: the hook
        exits 0, prints nothing, and leaves one line in metrics/hook-errors/."""
        w = self.world()
        S = w.scratch
        bad = S / "bad.jsonl"
        bad.write_text("not json\n")
        out, rc = w.run(w.payload(bad, "badjson", S, "PostToolUse"), "posttooluse", show=True)
        w.t("a transcript jq cannot read exits 0", 0, rc)
        w.t("and prints nothing", "", out)
        rows = [json.loads(ln) for ln in w.errors()]
        w.t("and leaves one line in the session's trace file", 1, len(rows))
        w.t("naming the hook, the event and the session", "metrics-live posttooluse badjson",
            f"{rows[0]['hook']} {rows[0]['event']} {rows[0]['session_id']}")
        w.has("and what failed", "jq exited", rows[0]["error"])
        w.t("in the session's shard", "yes",
            "yes" if (w.state / "metrics" / "hook-errors" / "ba" / "badjson.jsonl").is_file() else "no")
        return w.checks

    def section_git_filter(self):
        """The git event recomputes only on a call that changed git state."""
        w = self.world()
        S = w.scratch
        tp = w.turn(S / "git.jsonl", 1000)
        cache = w.shard("live", "gitev", ".json")
        w.hook(w.payload(tp, "gitev", S, tool_input={"command": "ls -la"}), "git")
        w.t("a read-only command is filtered out", "no", "yes" if cache.exists() else "no")
        w.hook(w.payload(tp, "gitev", S, tool_input={"command": "git commit -m x"}), "git")
        w.t("a commit recomputes the cache", "yes", "yes" if cache.exists() else "no")
        return self.done(w)

    SECTIONS = [n for n in list(locals()) if n.startswith("section_")]

    def test_sections(self):
        with concurrent.futures.ThreadPoolExecutor(len(self.SECTIONS)) as ex:
            futures = {name: ex.submit(getattr(self, name)) for name in self.SECTIONS}
        for name, fut in futures.items():
            with self.subTest(section=name):
                fut.result()


if __name__ == "__main__":
    unittest.main()
