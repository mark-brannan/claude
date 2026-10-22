#!/usr/bin/env python3
"""Recompute the session's metrics now, cache them where the statusline can
read them, run the crossing engine, and print the event block.

AGENTS MUST read metrics-live-requirements.md before making changes.

Usage: metrics-live.py [event] [max-age-seconds] [show]
stdin: any hook payload carrying transcript_path/session_id/cwd. Always exits 0.

Why a cache file at all: session-metrics.jq slurps the whole transcript, fine
a few times a turn but not on every statusline render. The statusline prints
what is on disk and recomputes only past its own staleness age.

Wired to UserPromptSubmit, PostToolUse, Stop (through stop-sequence.py) and
SubagentStop, each rendering the block (#137: high frequency is the explicit
ask). What fires once is the crossing engine: a line is said when a threshold
is first crossed, then nothing until the next one. One file per session, keyed
by session_id: parallel sessions are normal here.

A failure never blocks a tool call: it is swallowed, and leaves one line in
<state>/metrics/hook-errors/ (lib/hooktrace.py, through trace()), so a silent readout can
be told from a broken one (#206).

FROZEN -- THAW CAREFULLY. Every block tagged with that phrase (the ⛁ context,
⚡ friction and ⏱ sitting-clock crossings, and any glyph family added beside
them) is frozen: do not modify without direct, explicit interaction with the
user. Changes are small and contained, one glyph or family at a time; never
drop a glyph, family or behaviour without the user's call. That includes
cadence: never make the readout appear less often as a "cleanup" (#137).
Before touching a frozen line, propose it in chat with rendered before/after
examples from metrics-live.examples.sh, and carry them in the PR body.
"""
import datetime
import glob
import json
import math
import os
import random
import re
import string
import subprocess
import sys
import time

HOOK_DIR = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HOOK_DIR)
sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
import lib_state  # noqa: E402

try:
    import atomic  # noqa: E402
    import gitrun  # noqa: E402
    import state  # noqa: E402
    import when  # noqa: E402
except ImportError as e:  # a seed without lib/: lib_state has said so on stderr
    print(f"metrics-live: lib/ not importable ({e})", file=sys.stderr)
    state = None

try:
    import hooktrace  # noqa: E402
except ImportError:  # a seed without lib/hooktrace.py: stderr is all there is
    hooktrace = None

JQPROG = os.path.join(HOOK_DIR, "session-metrics.jq")
FORMAT_SH = os.path.join(HOOK_DIR, "metrics-format.sh")
PACIFIC = "America/Los_Angeles"

# Who and where, for trace(): filled in as soon as the payload is read.
WHERE = {"event": "", "session_id": ""}


class Failed(Exception):
    """A child process that did not do its job."""


def trace(stage, err):
    """Record one swallowed error through lib/hooktrace.py (metrics/hook-errors/)."""
    if hooktrace is None:
        print(f"metrics-live: {stage}: {type(err).__name__}: {err}", file=sys.stderr)
        return
    hooktrace.trace("metrics-live", stage, err, WHERE["session_id"], WHERE["event"])


def soft(stage, fn, *args, default=None):
    """fn(*args), or default after tracing whatever it raised."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 -- a hook must not fail its caller
        trace(stage, e)
        return default


# ------------------------------------------------------------------ small parts
def num(v, default=0):
    """A JSON value as the shell read it through `// 0`: null and false are
    the default, a number is truncated, a numeric string is read."""
    if v is None or v is False:
        return default
    if isinstance(v, (bool, int, float)):
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*-?[0-9]+\s*", v):
        return int(v)
    return default


def text(v):
    """A JSON value as `.x // ""` gives it: null and false are empty."""
    if v is None or v is False:
        return ""
    return v if isinstance(v, str) else json.dumps(v)


def read_json(path, stage):
    """A JSON file's value; None when it is absent, or traced when it is not JSON."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        trace(stage, Failed(f"{path}: {e}"))
        return None


def read_bytes(path):
    """A file's bytes, or b"" when it has gone since it was listed: a
    sub-agent transcript can be removed between the glob and the read."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return b""


def obj(v):
    return v if isinstance(v, dict) else {}


def write_atomic(path, data):
    atomic.write(path, data)


def compact(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def pretty(v):
    return json.dumps(v, ensure_ascii=False, indent=2) + "\n"


def run_out(argv, stdin=b""):
    """argv's stdout as text; Failed, with the first line of stderr, when it
    exits non-zero."""
    p = subprocess.run(argv, input=stdin, capture_output=True)
    if p.returncode:
        err = p.stderr.decode("utf-8", "replace").strip().split("\n")[0]
        raise Failed(f"{os.path.basename(argv[0])} exited {p.returncode}{': ' + err if err else ''}")
    return p.stdout.decode("utf-8", "replace")


def git_out(*args):
    """git's stdout, stripped, whatever its exit: what $(git ... 2>/dev/null) held."""
    return gitrun.exact(*args).stdout.strip()


_BAD_ZONES = set()


def zone(name):
    import zoneinfo
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
        if name not in _BAD_ZONES:  # one trace line per run, not per clock read
            _BAD_ZONES.add(name)
            trace("zone", Failed(f"time zone {name!r} unknown ({e}); using UTC"))
        return datetime.timezone.utc  # what date(1) does with a TZ it does not know


def at(ts, tz=None):
    """The epoch as a datetime: in tz, or the host's local time."""
    if tz is None:
        return datetime.datetime.fromtimestamp(ts).astimezone()
    return datetime.datetime.fromtimestamp(ts, zone(tz))


def utc_iso(ts):
    return when.stamp(ts)


def from_iso(s):
    """A ts this hook wrote ("...Z") as an epoch; ValueError otherwise."""
    return when.unstamp(s)


def stamp_epoch(s):
    """A LIVE/CLOSED stamp (ISO 8601) as an epoch, or 0 when it is not one."""
    try:
        d = when.parse(s)
    except ValueError as e:
        if s:  # "" is a marker line with no stamp, not a bad one
            trace("curia", Failed(f"stamp {s!r} is not ISO 8601 ({e}); read as 0"))
        return 0
    if d.tzinfo is None:
        d = d.astimezone()
    return int(d.timestamp())


def kfmt(n):
    return f"{int(n / 1000)}k" if n >= 1000 else "%d" % n


def hm(m):
    return "%dh%02d" % (m // 60, m % 60) if m >= 60 else "%dm" % m


def glyphs(n, g):
    """The glyph up to 5 times, then "(xN)", so a long escalation still reads
    as a number rather than a wall of characters."""
    return g * min(n, 5) + (f"(x{n})" if n > 5 else "")


def fib_rungs(total):
    return sum(1 for L in (1, 2, 3, 5, 8) if total >= L)


def time_rungs(total):
    return sum(1 for L in (25, 47, 62, 90, 120) if total >= L)


def rung_of(ladder, step, v):
    """The highest rung at or below v, or 0 under the first. The ladder
    extends by step past its last configured rung forever."""
    hit = last = 0
    for L in ladder:
        if v >= L:
            hit = L
        last = L
    if step > 0 and last > 0 and v >= last:
        L = last + step
        while v >= L:
            hit = L
            L += step
    return hit


def ints(s):
    return [int(x) for x in s.split()]


class Knobs:
    """Every threshold, each overridable from the environment. A value that
    is not a number is traced and the default used."""

    def __init__(self):
        self.context_lines = self.ladder("METRICS_CONTEXT_LINES", "60000 90000 120000 150000 185000")
        self.context_stop_at = self.number("METRICS_CONTEXT_STOP_AT", 150000)
        self.context_step = self.number("METRICS_CONTEXT_STEP", 35000)
        self.sit_every_min = self.number("METRICS_SIT_EVERY_MIN", 60)
        self.sit_gap_min = self.number("METRICS_SIT_GAP_MIN", 15)
        # Sitting rungs from here up draw ⏰ instead of ⏱️/🌙. 3 = past 90 min.
        self.sit_hot_rung = self.number("METRICS_SIT_HOT_RUNG", 3)
        # The sitting line's tail, picked by the clock first and the list second.
        # Meal windows are local hours, start inclusive, end exclusive; "" disables.
        self.meal_windows = self.windows("METRICS_MEAL_WINDOWS", "12-14 18-20")
        self.sun_after_hour = self.number("METRICS_SUN_AFTER_HOUR", 13)
        self.stay_default_min = self.number("METRICS_STAY_DEFAULT_MIN", 30)
        self.friction_n = self.number("METRICS_FRICTION_N", 3)
        self.friction_turns = self.number("METRICS_FRICTION_TURNS", 20)
        # Model-facing ladders, separate from the screen ones: the screen line
        # is a glance, the injection an instruction. Edge-triggered alike.
        self.model_context_lines = self.ladder("METRICS_MODEL_CONTEXT_LINES", "105000 125000 175000 200000")
        self.model_context_step = self.number("METRICS_MODEL_CONTEXT_STEP", 50000)
        # Tool calls of silence after a context rung was raised and not acted
        # on, before it is said again: the engine's one deliberate repeat. 0 disables.
        self.model_context_repeat = self.number("METRICS_MODEL_CONTEXT_REPEAT", 20)
        # The gap that starts a fresh day for the day counter (#301).
        self.decision_gap_min = self.number("METRICS_DECISION_GAP_MIN", 180)
        # Night: from STOP_HOUR to NIGHT_END_HOUR, local. One pair of knobs for
        # the Stop arm, the block's night glyph and the bedtime question.
        self.stop_hour = self.number("METRICS_STOP_HOUR", 22)
        self.night_end_hour = self.number("METRICS_NIGHT_END_HOUR", 5)
        # Minutes before the named bedtime that the warning lands.
        self.bed_warn_min = self.number("METRICS_BED_WARN_MIN", 5)

    @staticmethod
    def number(name, default):
        v = os.environ.get(name) or str(default)
        try:
            return int(v)
        except ValueError:
            trace("knobs", Failed(f"{name}={v!r} is not a number; using {default}"))
            return default

    @staticmethod
    def windows(name, default):
        """Hour windows "lo-hi" as (lo, hi) pairs; a malformed one is traced
        and skipped, the rest kept."""
        out = []
        for w in os.environ.get(name, default).split():
            lo, _, hi = w.partition("-")
            try:
                out.append((int(lo), int(hi)))
            except ValueError:
                trace("knobs", Failed(f"{name}: {w!r} is not a window like 12-14; skipped"))
        return out

    @staticmethod
    def ladder(name, default):
        v = os.environ.get(name) or default
        try:
            return ints(v)
        except ValueError:
            trace("knobs", Failed(f"{name}={v!r} is not a list of numbers; using {default}"))
            return ints(default)


# ------------------------------------------------------------------- the hook
class Hook:
    def __init__(self, argv, ev):
        self.event_arg = argv[1] if len(argv) > 1 else ""
        self.max_age = num(argv[2] if len(argv) > 2 else "0")
        self.show = argv[3] if len(argv) > 3 else ""
        self.ev = ev
        self.tp = text(ev.get("transcript_path"))
        self.sid = text(ev.get("session_id"))
        self.cwd = text(ev.get("cwd")) or text(obj(ev.get("workspace")).get("current_dir"))
        self.hook_name = text(ev.get("hook_event_name"))
        self.agent_id = text(ev.get("agent_id"))
        self.prompt = text(ev.get("prompt"))
        self.sys_lines, self.model_lines, self.arch_lines = [], [], []

    # -- the run, in order -----------------------------------------------------
    def run(self):
        if not (self.tp and os.path.isfile(self.tp) and self.sid):
            return
        self.cwd = self.cwd or os.getcwd()
        # Inside a sub-agent a tool hook carries agent_id yet points
        # transcript_path at the PARENT session, so the block would report the
        # parent's context to an agent that cannot act on it (#40). Stay silent
        # and leave the crossings for the parent. SubagentStop is the parent's.
        if self.hook_name == "PostToolUse" and self.agent_id:
            return
        # The event defaults to hook_event_name, lowercased, so a new hook needs
        # no entry here.
        self.event = self.event_arg or (self.hook_name or "tool").lower()
        WHERE["event"] = self.event
        # The statusline is not an event Claude Code renders a systemMessage for.
        if self.event == "statusline":
            self.show = ""
        if self.event == "git" and not self.is_git_event():
            return
        self.k = Knobs()
        self.sdir = lib_state.state_dir()
        self.live = f"{self.sdir}/metrics/live"
        self.out = state.state_shard_path(self.live, f"{self.sid}.json", self.sid)
        # Throttle: the statusline asks constantly and only recomputes past MAX_AGE.
        if self.max_age > 0 and os.path.isfile(self.out):
            if int(time.time()) - int(os.stat(self.out).st_mtime) < self.max_age:
                return
        # METRICS_NOW pins the engine's clock to an epoch, for tests; only a
        # plain integer is taken. The cache-age check and the block's night
        # read stay on the real clock.
        pin = os.environ.get("METRICS_NOW", "")
        self.now_ts = int(pin) if re.fullmatch(r"[0-9]+", pin) else int(time.time())
        self.now = utc_iso(self.now_ts)
        self.work_root = git_out("-C", self.cwd, "rev-parse", "--show-toplevel")
        self.work_repo = os.path.basename(self.work_root or self.cwd.rstrip("/"))
        self.work_branch = git_out("-C", self.cwd, "rev-parse", "--abbrev-ref", "HEAD")

        self.metrics = self.compute()
        soft("git", self.git_state)
        os.makedirs(os.path.dirname(self.out), exist_ok=True)
        soft("cache", self.write_cache)
        self.engine()

    def is_git_event(self):
        """A git event means a git-state change, not every Bash call: the
        command or the tool name matches state.GIT_EVENT_RE, either one."""
        cmd = text(obj(self.ev.get("tool_input")).get("command"))
        tool = text(self.ev.get("tool_name"))
        return any(re.search(state.GIT_EVENT_RE, ln)
                   for ln in f"{cmd}\n{tool}".split("\n"))

    def compute(self):
        """session-metrics.jq over the transcript, with the sub-agent
        transcripts that sit beside it slurped in as $subs (#206)."""
        base = self.tp[:-len(".jsonl")] if self.tp.endswith(".jsonl") else self.tp
        subs = b"".join(read_bytes(f) + b"\n" for f in sorted(glob.glob(f"{base}/subagents/agent-*.jsonl")))
        out = run_out(["jq", "-s", "--slurpfile", "subs", "/dev/stdin",
                       "--arg", "sid", self.sid, "--arg", "repo", self.work_repo,
                       "--arg", "branch", self.work_branch, "--arg", "cwd", self.cwd,
                       "--arg", "now", self.now, "-f", JQPROG, self.tp], stdin=subs or b"\n")
        metrics = json.loads(out)
        if not isinstance(metrics, dict):
            raise Failed(f"session-metrics.jq gave {type(metrics).__name__}, not an object")
        return metrics

    def git_state(self):
        """The part that decides whether the chat is safe to kill."""
        self.dirty = self.unpushed = self.no_upstream = self.ncommits = 0
        # Read the cached start SHA before anything here can raise: write_cache
        # saves self.start_sha whatever happened, and an empty one would
        # overwrite the session's real start, so `commits` would count from
        # the current HEAD for the rest of the session.
        self.start_sha = text(obj(read_json(self.out, "cache")).get("start_sha"))
        if not self.work_root:
            return
        self.dirty = state.dirty_paths(self.work_root).count("\n")
        # lib/state.py owns the answer, carve-outs and all, so this hook and
        # stop-continuity.py cannot disagree about it (#149).
        ust = state.unpushed_state(self.work_root, self.work_branch)
        if ust.startswith("ahead "):
            self.unpushed = num(ust[len("ahead "):])
        elif ust == "never-pushed":
            self.no_upstream = 1
        # Commits counted from the SHA this session started at, not by time:
        # `--since` counts a fresh clone's whole history as this session's.
        self.start_sha = self.start_sha or git_out("-C", self.work_root, "rev-parse", "HEAD")
        if self.start_sha:
            self.ncommits = num(git_out("-C", self.work_root, "rev-list", "--count",
                                        f"{self.start_sha}..HEAD"))

    def write_cache(self):
        merged = dict(obj(self.metrics.get("session")))
        merged.update(last_event=self.event, updated_at=self.now, start_sha=self.start_sha,
                      dirty=self.dirty, unpushed=self.unpushed, commits=self.ncommits)
        write_atomic(self.out, compact(merged) + "\n")

    # -- engine state ----------------------------------------------------------
    def load_state(self):
        # The sitting clock is machine-wide: three chats open are one person in
        # one chair. Per machine and never a record (gitignored in the state
        # repo). Two prompts in one second can clobber each other's write;
        # whole-file and atomic, so the reader sees one clock, never a torn one.
        self.sitf = f"{self.sdir}/metrics/sitting.json"
        sit = obj(read_json(self.sitf, "sitting"))
        self.sit_start = num(sit.get("sitting_start"))
        self.last_prompt = num(sit.get("last_prompt"))
        self.quiet_until = num(sit.get("quiet_until"))
        # bed_asked_eve: the local date of the evening the question was put;
        # bed_at: the epoch it was answered with, 0 until then.
        self.bed_asked_eve = text(sit.get("bed_asked_eve"))
        self.bed_at = num(sit.get("bed_at"))

        # Crossings are per session, beside the cache but not in it:
        # stop-continuity.py deletes the cache at session end, and the
        # crossings have to outlive it.
        self.nagf = state.state_shard_path(self.live, f"{self.sid}.nag.json", self.sid)
        nag = obj(read_json(self.nagf, "nag"))
        self.handoff_sum = text(nag.get("handoff_sum"))
        self.ctx_line = num(nag.get("context_line"))
        self.ctx_rungs = num(nag.get("context_rungs"))
        self.ctx_stop_line = num(nag.get("context_stop_line"))
        # time_line is per session: the clock is shared, its report is each
        # chat's own. time_line_sitting is the sitting it was spent in; -1 is
        # a file from before the clock moved out of it, spent rather than trusted.
        self.time_line = num(nag.get("time_line"))
        self.tl_sitting = num(nag.get("time_line_sitting"), -1)
        self.fric_tripped = bool(nag.get("friction_tripped"))
        self.since_nag = bool(nag.get("since_nag"))
        self.resume_ts = num(nag.get("resume_ts"))
        self.nag_pending = bool(nag.get("nag_pending"))
        self.late_nagged = bool(nag.get("late_nagged"))
        self.m_ctx_at = num(nag.get("model_context_at"))
        self.m_sit_at = num(nag.get("model_sitting_at"))
        self.m_sit_said = num(nag.get("model_sitting_said"), self.m_sit_at)
        self.m_ctx_tools = num(nag.get("model_context_tools"))
        self.bed_warn_at = num(nag.get("bed_warn_at"))
        self.bed_past_at = num(nag.get("bed_past_at"))
        if self.tl_sitting != self.sit_start:
            self.time_line, self.tl_sitting = 0, self.sit_start
        # A nag file from before context_rungs/context_stop_line existed has
        # context_line alone: derive both from it rather than trust a zero
        # that only means "this field didn't exist yet".
        if self.ctx_rungs == 0 and self.ctx_line > 0:
            self.ctx_rungs = len(self.context_ladder(self.ctx_line))
        if self.ctx_stop_line == 0 and self.ctx_line >= self.k.context_stop_at:
            self.ctx_stop_line = self.ctx_line

    def context_ladder(self, upto):
        """The screen ladder's rungs at or below upto: the configured lines,
        then context_step forever past the last."""
        lines = self.k.context_lines
        ladder = [L for L in lines if L <= upto]
        if self.k.context_step > 0 and lines and lines[-1] > 0:
            L = lines[-1] + self.k.context_step
            while L <= upto:
                ladder.append(L)
                L += self.k.context_step
        return ladder

    def save_sitting(self):
        os.makedirs(os.path.dirname(self.sitf), exist_ok=True)
        # The last_* fields are for diagnosis only; nothing reads them.
        root = self.work_root
        slug = os.path.basename(root) if "/.claude/worktrees/" in root else ""
        write_atomic(self.sitf, pretty({
            "sitting_start": self.sit_start, "last_prompt": self.last_prompt,
            "quiet_until": self.quiet_until, "bed_asked_eve": self.bed_asked_eve,
            "bed_at": self.bed_at,
            "last_prompt_local": at(self.last_prompt, PACIFIC).strftime("%Y-%m-%d %H:%M %Z"),
            "last_session_id": self.sid, "last_repo": self.work_repo,
            "last_branch": self.work_branch, "last_worktree_slug": slug,
            "last_checkpoint": f"{time.strftime('%Y-%m-%d', time.gmtime(self.last_prompt))}"
                               f"-{self.work_repo}-{self.sid[:8]}.md",
            "last_cwd": self.cwd, "last_prompt_preview": self.prompt[:80]}))

    def save_nag(self):
        # Never blocks the hook: a lock held by a concurrent invocation of this
        # same session (dotfiles#161) skips this write rather than waiting.
        if not state.state_lock(f"{self.live}/{self.sid}.lock"):
            return
        try:
            os.makedirs(os.path.dirname(self.nagf), exist_ok=True)
            write_atomic(self.nagf, pretty({
                "handoff_sum": self.handoff_sum, "context_line": self.ctx_line,
                "context_rungs": self.ctx_rungs, "context_stop_line": self.ctx_stop_line,
                "time_line": self.time_line, "time_line_sitting": self.tl_sitting,
                "friction_tripped": self.fric_tripped, "since_nag": self.since_nag,
                "resume_ts": self.resume_ts, "nag_pending": self.nag_pending,
                "late_nagged": self.late_nagged, "model_context_at": self.m_ctx_at,
                "model_sitting_at": self.m_sit_at, "model_sitting_said": self.m_sit_said,
                "model_context_tools": self.m_ctx_tools,
                "bed_warn_at": self.bed_warn_at, "bed_past_at": self.bed_past_at}))
        finally:
            state.state_unlock()

    def record_crossing(self, kind, at_, txt):
        os.makedirs(os.path.dirname(self.crossf), exist_ok=True)
        with open(self.crossf, "a", encoding="utf-8") as fh:
            fh.write(compact({"session_id": self.sid, "ts": self.now, "kind": kind,
                              "at": at_, "text": txt}) + "\n")

    def crossing(self, kind, at_, txt):
        soft("crossings", self.record_crossing, kind, at_, txt)

    # -- what the lines say --------------------------------------------------
    def work_str(self):
        """Git state folded into a nag line; empty on a clean tree."""
        if not (self.ncommits > 0 or self.dirty > 0 or self.unpushed > 0 or self.no_upstream > 0):
            return ""
        s = "⎇ "
        if self.ncommits > 0:
            s += f"{self.ncommits}c"
        if self.dirty > 0:
            s += f"{self.dirty}~"
        if self.no_upstream > 0:
            s += "no-upstream"
        elif self.unpushed > 0:
            s += f"{self.unpushed}↑"
        return s

    def location(self):
        return obj(read_json(f"{self.sdir}/location.json", "location"))

    def sunset_min(self):
        """Minutes until today's sunset at location.json's lat/lon, or None
        when unfilled or the sun is down. NOAA's sunrise equation, solved for
        the solar noon nearest now."""
        loc = self.location()
        lat, lon = text(loc.get("lat")), text(loc.get("lon"))
        if not lat or not lon:
            return None
        lat, lon, now = float(lat), float(lon), self.now_ts
        r = math.atan2(0, -1) / 180
        jd = now / 86400 + 2440587.5
        n = int(jd - 2451545.0009 + lon / 360 + 0.5)
        js = 2451545.0009 - lon / 360 + n
        m = math.fmod(357.5291 + 0.98560028 * (js - 2451545), 360)
        c = 1.9148 * math.sin(m * r) + 0.02 * math.sin(2 * m * r) + 0.0003 * math.sin(3 * m * r)
        lam = math.fmod(m + c + 282.9372, 360)
        jt = js + 0.0053 * math.sin(m * r) - 0.0069 * math.sin(2 * lam * r)
        sd = math.sin(lam * r) * math.sin(23.4397 * r)
        cd = math.sqrt(1 - sd * sd)
        cw = (math.sin(-0.833 * r) - math.sin(lat * r) * sd) / (math.cos(lat * r) * cd)
        if cw < -1 or cw > 1:
            return None
        w = math.atan2(math.sqrt(1 - cw * cw), cw) / r
        left = int(((jt + w / 360 - 2440587.5) * 86400 - now) / 60)
        return left if left > 0 else None

    def sit_tail(self):
        """The sitting line's tail: outward, never an instruction. Clock first
        (a meal window, then the daylight left), the list second."""
        h = at(self.now_ts).hour
        for lo, hi in self.k.meal_windows:
            if lo <= h < hi:
                return "what did you eat today?"
        if h >= self.k.sun_after_hour:
            left = soft("sunset", self.sunset_min)
            if left is not None:
                return "sun sets in %dh %02d" % (left // 60, left % 60) if left >= 60 \
                    else "sun sets in %d min" % left
        try:
            with open(f"{self.sdir}/outside.txt", encoding="utf-8") as fh:
                lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
        except FileNotFoundError:
            return ""
        return random.choice(lines) if lines else ""

    def lhhmm(self, ts):
        """HH:MM on the local (bedtime) clock."""
        return at(ts, self.ltz).strftime("%H:%M")

    def bed_resolve(self, h, m):
        """The epoch of the next time the local clock reads h:mm, read the way
        a person says it at night: "11" is 23:00, "1" is 01:00, "12:30" is
        00:30. Built from local midnight by arithmetic, so a DST change between
        now and then is off by the hour."""
        cands = [h] + ([h + 12] if h < 12 else []) + ([0] if h == 12 else [])
        best = 0
        for hh in cands:
            for c in (self.l_midnight + hh * 3600 + m * 60,
                      self.l_midnight + 86400 + hh * 3600 + m * 60):
                if c > self.now_ts and (best == 0 or c < best):
                    best = c
        return best

    # -- measurement of what followed a sitting rung -------------------------
    @staticmethod
    def jsonl(path):
        with open(path, encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]

    def stamp_time_after(self):
        """What followed each ⏱ crossing, stamped once at the session's next
        prompt: minutes to it, whether it was a `stay`, whether the gap ran
        past the sitting gap. Measured only; nothing here speaks."""
        if not os.path.isfile(self.crossf):
            return
        rows = self.jsonl(self.crossf)
        stay = is_stay(self.prompt)
        digits = re.sub(r"[^0-9]", "", self.prompt) if stay else ""
        sm = int(digits) if digits else None
        done = {r.get("crossing_ts") for r in rows if r.get("kind") == "time_after"}
        out = []
        for r in rows:
            if r.get("kind") != "time" or r.get("ts") in done:
                continue
            s = self.now_ts - from_iso(r["ts"])
            out.append({"session_id": r.get("session_id"), "ts": self.now, "kind": "time_after",
                        "at": r.get("at"), "crossing_ts": r["ts"], "min": s // 60,
                        "stay": stay, "stay_min": sm, "quiet": s > self.k.sit_gap_min * 60})
        if out:
            with open(self.crossf, "a", encoding="utf-8") as fh:
                fh.write("".join(compact(o) + "\n" for o in out))

    def stamp_time_last(self, files, fin, ss):
        """Minutes from each of the sitting's crossings to its final prompt,
        and whether a `stay <n>` was overrun. Stamped on Stop and at the next
        sitting start when changed; the latest one counts."""
        for f in files:
            soft("time_last", self.stamp_time_last_file, f, fin, ss)

    def stamp_time_last_file(self, f, fin, ss):
        rows = self.jsonl(f)
        last = {r.get("crossing_ts"): r for r in rows if r.get("kind") == "time_last"}
        aft = {r.get("crossing_ts"): r for r in rows if r.get("kind") == "time_after"}
        out = []
        for r in rows:
            if r.get("kind") != "time":
                continue
            c = r["ts"]
            cs = from_iso(c)
            if not ss <= cs <= fin:
                continue
            a = aft.get(c) or {}
            overrun = None if a.get("stay_min") is None \
                else fin > from_iso(a["ts"]) + a["stay_min"] * 60
            row = {"session_id": r.get("session_id"), "ts": self.now, "kind": "time_last",
                   "at": r.get("at"), "crossing_ts": c, "min_to_last": (fin - cs) // 60,
                   "overrun": overrun}
            prev = last.get(c) or {}
            if [prev.get("min_to_last"), prev.get("overrun")] != [row["min_to_last"], overrun]:
                out.append(row)
        if out:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write("".join(compact(o) + "\n" for o in out))

    def recent_crossing_files(self):
        """Every session's crossings file touched since the sitting started."""
        cutoff = time.time() - ((self.now_ts - self.sit_start) // 60 + 1) * 60
        files = glob.glob(f"{self.crossd}/*.jsonl") + glob.glob(f"{self.crossd}/*/*.jsonl")
        return [f for f in files if os.path.isfile(f) and os.stat(f).st_mtime > cutoff]

    # -- gates -----------------------------------------------------------------
    def in_flight(self):
        """Human nags (sitting, friction) gate on this; machine nags (context)
        do not. Memoized; can shell out to `gh`."""
        if self.in_flight_memo is None:
            self.in_flight_memo = state.archivable_reasons(
                self.work_root, self.work_branch, self.sid, HOOK_DIR) if self.work_root else ""
        return bool(self.in_flight_memo)

    def in_curia(self):
        """True while a curia sitting's LIVE marker names this session, and no
        CLOSED for it is stamped at or after that marker. A marker older than
        8 hours belongs to a session resumed long after a sitting never closed."""
        for f in glob.glob(f"{self.sdir}/curia/*/LIVE"):
            stamp = first_field(f, self.sid)
            if stamp is None:
                continue
            stamp_ts = stamp_epoch(stamp)
            cstamp = first_field(f[:-len("LIVE")] + "CLOSED", self.sid)
            if cstamp and stamp_epoch(cstamp) >= stamp_ts:
                continue
            if self.now_ts - stamp_ts < 28800:
                return True
        return False

    def hold(self, kind, txt):
        """Gentle lines (sitting clock, bedtime) are held while a curia is
        live and said once when it is not: one line per kind, the latest wins."""
        keep = []
        if os.path.isfile(self.heldf):
            with open(self.heldf, encoding="utf-8") as fh:
                keep = [ln for ln in fh.read().split("\n") if ln and not ln.startswith(f"{kind}\t")]
        os.makedirs(os.path.dirname(self.heldf), exist_ok=True)
        write_atomic(self.heldf, "".join(f"{ln}\n" for ln in keep + [f"{kind}\t{txt}"]))

    def held(self, kind):
        try:
            with open(self.heldf, encoding="utf-8") as fh:
                return any(ln.startswith(f"{kind}\t") for ln in fh)
        except FileNotFoundError:
            return False

    # -- the crossing engine ---------------------------------------------------
    def engine(self):
        self.crossd = f"{self.sdir}/metrics/crossings"
        self.crossf = state.state_shard_path(self.crossd, f"{self.sid}.jsonl", self.sid)
        self.heldf = state.state_shard_path(self.live, f"{self.sid}.held", self.sid)
        self.in_flight_memo = None
        self.load_state()

        # Only the wired events drive the engine; the statusline never
        # consumes a crossing. can_inject: where Claude Code accepts
        # additionalContext (Stop says its piece through the block reason).
        # is_prompt gates what the user's own rhythm winds: the sitting clock.
        ev = self.event
        is_prompt = ev in ("prompt", "userpromptsubmit")
        can_inject = is_prompt or ev == "posttooluse"
        run_engine = can_inject or ev in ("stop", "subagentstop")
        # The hookEventName must match the event Claude Code dispatched, or
        # the injection is discarded silently.
        inject_event = "PostToolUse" if ev == "posttooluse" else "UserPromptSubmit"
        self.curia_live = False

        if run_engine:
            self.run_engine(is_prompt, can_inject)

        block_reason = soft("stop", self.stop_nag, default="") if self.hook_name == "Stop" else ""

        if run_engine:
            soft("nag", self.save_nag)

        model_line = "\n".join(self.model_lines) if can_inject else ""
        sys_text = "\n".join(self.sys_lines)
        arch_text = "\n".join(self.arch_lines)
        out = {}
        if self.show == "show":
            block = soft("block", self.block, default="")
            out["systemMessage"] = "\n".join(t for t in (sys_text, block, arch_text) if t)
        elif sys_text or arch_text:
            out["systemMessage"] = "\n".join(t for t in (sys_text, arch_text) if t)
        elif not (model_line or block_reason):
            return
        if block_reason:
            out.update(decision="block", reason=block_reason)
        if model_line:
            out["hookSpecificOutput"] = {"hookEventName": inject_event, "additionalContext": model_line}
        sys.stdout.buffer.write((compact(out) + "\n").encode("utf-8"))

    def run_engine(self, is_prompt, can_inject):
        """Each part under soft(): one that raises is traced under its own
        stage, and the rest still run, so the nag file and the block that
        follow are never lost to it."""
        self.can_inject = can_inject
        self.curia_live = soft("curia", self.in_curia, default=False)
        if not self.curia_live and can_inject:
            soft("held", self.deliver_held)
        soft("clock", self.local_clock)
        if is_prompt:
            soft("wind", self.wind_clock)
        elif self.event == "stop":
            self.stamp_time_last([self.crossf] if os.path.isfile(self.crossf) else [],
                                 self.last_prompt, self.sit_start)
        self.sit_quiet = self.quiet_until > self.now_ts

        sess = obj(self.metrics.get("session"))
        ctx = num(sess.get("context_peak"))
        soft("context", self.context_crossings, ctx)
        if is_prompt:
            soft("sitting_line", self.sitting_line, ctx)
            soft("sitting_model", self.sitting_model)
        if can_inject:
            soft("bedtime", self.bedtime)
        if is_prompt:
            # The machine-wide day counter (#301): measured, never alarmed.
            soft("day_decisions", state.day_decisions, self.sid,
                 num(obj(sess.get("decisions")).get("total")), 0, self.now_ts,
                 self.k.decision_gap_min * 60)
            soft("friction", self.friction, num(sess.get("user_turns")))

    def deliver_held(self):
        if not (os.path.isfile(self.heldf) and os.path.getsize(self.heldf)):
            return
        with open(self.heldf, encoding="utf-8") as fh:
            for ln in fh.read().split("\n"):
                _, _, t = ln.partition("\t")
                if t:
                    self.sys_lines.append(t)
        os.remove(self.heldf)

    def local_clock(self):
        """The clock the bedtime reads: location.json's tz, else Pacific. An
        hour before night_end_hour still belongs to last night's evening."""
        k = self.k
        # Pacific and not night until read, so a failure here leaves the
        # parts that read the clock running on a sane one.
        self.ltz, self.l_midnight, self.bed_night, self.l_eve = PACIFIC, self.now_ts, False, ""
        self.ltz = text(self.location().get("tz")) or PACIFIC
        local = at(self.now_ts, self.ltz)
        self.l_midnight = self.now_ts - local.hour * 3600 - local.minute * 60 - local.second
        self.bed_night = local.hour >= k.stop_hour or local.hour < k.night_end_hour
        self.l_eve = local.strftime("%Y-%m-%d")
        if local.hour < k.night_end_hour:
            self.l_eve = at(self.now_ts - 86400, self.ltz).strftime("%Y-%m-%d")

    def wind_clock(self):
        """The sitting clock is wound by prompts and nothing else: a Stop fires
        on the agent's schedule, so a session whose first wired event is a
        Stop must not start a clock nobody sat down at. The gap that resets it
        is between prompts anywhere on the machine."""
        k = self.k
        soft("time_after", self.stamp_time_after)
        if self.last_prompt > 0 and self.now_ts - self.last_prompt > k.sit_gap_min * 60:
            self.stamp_time_last(self.recent_crossing_files(), self.last_prompt, self.sit_start)
            self.sit_start = self.now_ts
            self.time_line = 0
        self.last_prompt = self.now_ts
        if self.sit_start <= 0:
            self.sit_start = self.now_ts
        self.tl_sitting = self.sit_start
        # The stay valve: `stay` or `stay <minutes>`, exactly, quiets the
        # sitting line and its injection until then. Machine-wide.
        m = re.fullmatch(r"[ \t\n\r\f\v]*stay(?:[ \t\n\r\f\v]+([0-9]+))?[ \t\n\r\f\v]*", self.prompt)
        if m:
            stay_min = int(m.group(1)) if m.group(1) else k.stay_default_min
            self.quiet_until = self.now_ts + stay_min * 60
            sit_min = (self.now_ts - self.sit_start) // 60
            t = f"⏱ {hm(sit_min)} · staying {stay_min}, quiet until {hm(sit_min + stay_min)}"
            self.sys_lines.append(t)
            self.crossing("stay", stay_min, t)
            self.model_lines.append("The user said stay: acknowledge in one line, nothing else.")
        # Bedtime: the question goes on screen once per evening, machine-wide,
        # on the first prompt after the night hour, never repeated: no answer
        # is an answer. A bare clock time typed after it, and nothing else, is
        # the reply, any number of times.
        b = re.fullmatch(r"[ \t\n\r\f\v]*([0-9]{1,2})(?::([0-9]{2}))?[ \t\n\r\f\v]*", self.prompt)
        if (self.bed_asked_eve and self.bed_asked_eve == self.l_eve and b
                and int(b.group(1)) <= 23 and int(b.group(2) or 0) <= 59):
            self.bed_at = self.bed_resolve(int(b.group(1)), int(b.group(2) or 0))
            t = f"bed at {self.lhhmm(self.bed_at)} noted"
            self.sys_lines.append(t)
            self.crossing("bed_set", self.bed_at, t)
            self.model_lines.append(f"The user named a bedtime, {self.lhhmm(self.bed_at)}: "
                                    "acknowledge in one line, nothing else.")
        elif self.bed_night and self.bed_asked_eve != self.l_eve:
            self.bed_asked_eve, self.bed_at = self.l_eve, 0
            t = "what time would you like to go to bed?"
            self.sys_lines.append(t)
            self.crossing("bed_ask", 0, t)
        soft("sitting", self.save_sitting)

    def context_crossings(self, ctx):
        k = self.k
        # FROZEN -- THAW CAREFULLY. See the module docstring for the rule this tags.
        # context -- rungs ascending, so a jump past several reports each in
        # order. Counted, never spoken: one notice per event, and that notice is
        # the block, whose ⛁ cluster is the only place a rung reaches the screen.
        for L in self.context_ladder(ctx):
            if L > self.ctx_line:
                self.ctx_rungs += 1
                if L >= k.context_stop_at:
                    self.ctx_stop_line = L
                self.crossing("context", L, "")
                self.ctx_line, self.since_nag = L, True
        if not self.can_inject:
            return
        # The model's context ladder, edge-triggered: once per rung, on the
        # event that crossed it (dotfiles#282). On can_inject, not is_prompt:
        # context climbs while the model works, and a rung crossed mid-turn is
        # the moment worth saying so.
        r = rung_of(k.model_context_lines, k.model_context_step, ctx)
        if r > self.m_ctx_at:
            if self.m_ctx_at == 0:
                self.model_lines.append(f"Context at {kfmt(ctx)}, past {kfmt(r)}: a stopping point is due.")
            else:
                self.model_lines.append(f"Context at {kfmt(ctx)}, past {kfmt(r)} "
                                        f"(last offered at {kfmt(self.m_ctx_at)}).")
            self.m_ctx_at, self.m_ctx_tools = r, 0
        elif self.event == "posttooluse" and self.m_ctx_at > 0 and k.model_context_repeat > 0:
            # The one deliberate repeat: a rung raised and not acted on is said
            # again after model_context_repeat tool calls, since a long
            # autonomous run can burn a rung without ever reaching a prompt.
            self.m_ctx_tools += 1
            if self.m_ctx_tools >= k.model_context_repeat:
                self.model_lines.append(f"Context at {kfmt(ctx)}, past {kfmt(self.m_ctx_at)} for "
                                        f"{self.m_ctx_tools} tool calls: a stopping point is due.")
                self.m_ctx_tools = 0

    def sitting_line(self, ctx):
        # FROZEN -- THAW CAREFULLY.
        # sitting clock -- read on a prompt and nowhere else. Elapsed time and an
        # outward tail, no verdict. Quiet after `stay` leaves the rung unspent.
        k = self.k
        if not (k.sit_every_min > 0 and self.sit_start > 0 and not self.sit_quiet):
            return
        sit_min = (self.now_ts - self.sit_start) // 60
        n = sit_min // k.sit_every_min * k.sit_every_min
        if not (n >= k.sit_every_min and n > self.time_line):
            return
        # Two hours arms the Stop block's hand-off, unless work is in flight:
        # landing it comes first.
        if n >= k.sit_every_min * 2 and not self.in_flight() and not self.curia_live:
            self.since_nag = True
        t = f"⏱ {hm(sit_min)} · context {kfmt(ctx)}"
        tail = self.sit_tail()
        if tail:
            t = f"{t} · {tail}"
        w = self.work_str()
        if w:
            t = f"{t} {w}"
        if not self.curia_live:
            self.sys_lines.append(t)
            self.crossing("time", n, t)
        else:
            self.hold("time", t)
        self.time_line = n

    @property
    def pickup_duty(self):
        # The file is named by its suffix: the Stop hook keys it on the
        # session's short id, and a model that has to guess picks another's.
        return (f"Write the single next step as the body (below `---`) of this session's "
                f"pickup item, {self.sdir}/pickup/*-{self.sid[:8]}.md, without showing it.")

    # A pointer, not a procedure: the orders say how to stop. The test checks
    # the lead still exists in the standing orders.
    SIT_ORDERS = 'Standing orders: "At a sitting rung".'

    def sitting_model(self):
        """The model side of the sitting clock, on the screen line's
        thresholds. A rung of 0 means the clock restarted, which spends the
        injection. m_sit_said gates the repeat (dotfiles#282); m_sit_at is the
        last rung whose stop was shaped, left unspent by work in flight."""
        k = self.k
        if not (k.sit_every_min > 0 and self.sit_start > 0 and not self.curia_live):
            return
        m_min = (self.now_ts - self.sit_start) // 60
        r = rung_of([k.sit_every_min], k.sit_every_min, m_min)
        if r == 0:
            self.m_sit_at = self.m_sit_said = 0
        elif not self.sit_quiet and self.in_flight() and r > self.m_sit_said:
            self.model_lines.append(
                f"Sitting {hm(m_min)} at this machine, past {hm(r)}, with work in flight "
                f"({self.in_flight_memo}). Don't raise the time yet: land this first, without "
                f"asking -- commit, push, open the PR. This rung comes back once it lands. {self.SIT_ORDERS}")
            self.m_sit_said = r
        elif not self.sit_quiet and not self.in_flight() and r > self.m_sit_at:
            self.model_lines.append(f"Sitting {hm(m_min)} at this machine, past {hm(r)}. "
                                    f"{self.pickup_duty} {self.SIT_ORDERS}")
            self.m_sit_at = self.m_sit_said = r

    def bedtime(self):
        """After the reply: the warning bed_warn_min before it, and the hour
        itself, each said once per bedtime set. Gated on the night, so a
        bedtime left from last night is not read out this morning. On
        can_inject: the hour arrives on the wall clock, not the user's rhythm."""
        if not (self.bed_at > 0 and self.bed_night):
            return
        now, bed = self.now_ts, self.bed_at
        if now >= bed and self.bed_past_at != bed:
            t = f"ok, it's {self.lhhmm(now)}, you said {self.lhhmm(bed)}"
            if not self.curia_live:
                self.sys_lines.append(t)
                self.crossing("bed_past", (now - bed) // 60, t)
                self.model_lines.append(f"It's {self.lhhmm(now)}; the user said bed at {self.lhhmm(bed)}. "
                                        f"Say that once. {self.pickup_duty} {self.SIT_ORDERS}")
            else:
                self.hold("bed", t)
            self.bed_past_at = self.bed_warn_at = bed
        elif now >= bed - self.k.bed_warn_min * 60 and self.bed_warn_at != bed:
            bed_left = (bed - now + 59) // 60
            t = f"{bed_left} min to {self.lhhmm(bed)}"
            if not self.curia_live:
                self.sys_lines.append(t)
                self.crossing("bed_warn", bed_left, t)
                self.model_lines.append(f"Bedtime {self.lhhmm(bed)} is {bed_left} minutes away. "
                                        f"{self.pickup_duty} {self.SIT_ORDERS}")
            elif not self.held("bed"):
                self.hold("bed", t)
            self.bed_warn_at = bed

    def friction(self, turns):
        # FROZEN -- THAW CAREFULLY.
        # friction -- corrections and rebukes inside a window of human turns,
        # so only a prompt trips it, and addressed to the model. Work in flight
        # gets the land-it redirect and leaves fric_tripped unset, so the
        # capacity line still fires, unspent, once the work lands. No crossing
        # for the in-flight repeats.
        k = self.k
        rows = self.metrics.get("friction")
        fric_win = sum(1 for f in (rows if isinstance(rows, list) else [])
                       if obj(f).get("type") in ("correction", "rebuke")
                       and num(obj(f).get("turn_ordinal")) > turns - k.friction_turns)
        if self.fric_tripped or self.curia_live or fric_win < k.friction_n:
            return
        if self.in_flight():
            self.model_lines.append(
                f"{fric_win} corrections or rebukes in the last {k.friction_turns} turns, with work "
                "in flight. Do not raise capacity or offer a stopping point yet: land this without "
                "asking -- commit, push, open the PR -- then apply the capacity rule.")
            return
        fm = (f"{fric_win} corrections or rebukes in the last {k.friction_turns} turns. "
              "Apply the capacity rule from the standing orders, once.")
        self.model_lines.append(fm)
        self.crossing("friction", fric_win, fm)
        self.fric_tripped = self.since_nag = True

    # -- Stop ------------------------------------------------------------------
    def archivable(self):
        """Read back stop-continuity.py's verdict (stop-sequence.py runs it
        first) rather than computing a second one. A verdict older than
        STOP_VERDICT_SINCE is the last turn's: this turn's never came."""
        rec = state.state_shard_path(f"{self.sdir}/metrics/sessions", f"{self.sid}.json", self.sid)
        r = obj(read_json(rec, "verdict"))
        verdict = text(r.get("verdict"))
        vat = r.get("verdict_at")
        whole = isinstance(vat, (int, float)) and not isinstance(vat, bool) and vat >= 0 and vat == int(vat)
        vat = int(vat) if whole else 0
        if not verdict or vat < num(os.environ.get("STOP_VERDICT_SINCE")):
            verdict = "not archivable: the Stop hook did not finish"
        self.verdict = verdict
        reasons = verdict[len("archivable"):] if verdict.startswith("archivable") else verdict
        self.reasons = reasons[len("not archivable: "):] if reasons.startswith("not archivable: ") else reasons
        return not self.reasons

    def pickup_items(self):
        """This session's pickup items as (path, written). A body still
        exactly the prompt line is the hook's default, not a hand-off."""
        items = []
        for f in sorted(glob.glob(f"{self.sdir}/pickup/*-{self.sid[:8]}.md")):
            if not os.path.isfile(f):
                continue
            head, body = split_item(f)
            p = next((ln[len("prompt: "):] for ln in head + body if ln.startswith("prompt: ")), "")
            b = "\n".join(body).rstrip("\n")
            items.append((f, bool(b.strip()) and b != p))
        return items

    def stop_nag(self):
        """The 📦 verdict, the pickup items, and the Stop block that asks for
        a hand-off once per arming. Answers the block reason, or ""."""
        self.archivable()
        slug = os.path.basename(self.work_root) if "/.claude/worktrees/" in self.work_root else ""
        tag = f"{self.work_branch}{'/' + slug if slug else ''} {self.sid[:8]}"
        if not self.reasons:
            self.arch_lines.append(f"📦 archivable. ({tag})")
        else:
            self.arch_lines.append(f"📦 not archivable: {self.reasons}. ({tag})")
            why = state.verdict_explain(self.verdict, self.work_root)
            if why:
                self.arch_lines.append(why)
        buf = state.buffered_state(self.work_root)
        if buf:
            self.arch_lines.append(buf)
        items = self.pickup_items()
        if not items:
            self.arch_lines.append(f"📄 no pickup item for {self.sid[:8]}")
        else:
            # The saved time is when the written body last changed: a checksum
            # of the bodies is kept, and the time restamped when it differs.
            # The item file is rewritten every Stop, so its mtime says nothing.
            bodies = "".join(f"{ln}\n" for f, w in items if w for ln in split_item(f)[1])
            body_sum = str(cksum(bodies.encode("utf-8")))
            if any(w for _, w in items) and (self.resume_ts <= 0 or body_sum != self.handoff_sum):
                self.resume_ts, self.handoff_sum = self.now_ts, body_sum
            for f, w in items:
                if w:
                    link = item_field(f, "link")
                    link = link[len("https://github.com/"):] if link.startswith("https://github.com/") else link
                    self.arch_lines.append(
                        f"📄 {os.path.basename(f)} (saved {at(self.resume_ts).strftime('%H:%M')}: "
                        f"{link} · {item_field(f, 'model')} · {item_field(f, 'effort')})")
                else:
                    snip = next((ln for ln in split_item(f)[1] if ln.split()), "")[:60]
                    self.arch_lines.append(f"📄 {os.path.basename(f)} ({snip or 'empty'})")

        if self.nag_pending:
            # The block was answered. Whether the hand-off exists is a fact on
            # disk; either way the nag is spent, never re-blocked on.
            self.nag_pending = self.since_nag = False
            self.save_nag()
            return ""
        # Headless (claude -p, the SDK) is never asked: nobody reads a pickup
        # item there, and the demanded turn buries the worker's final status.
        if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk-") or self.reasons:
            return ""
        late = at(time.time()).hour >= self.k.stop_hour
        # since_nag is armed by a context or time crossing and by friction, and
        # disarmed by the nag. The hour arms it once per session.
        if not (self.since_nag or (late and not self.late_nagged)):
            return ""
        if late:
            self.late_nagged = True
        if any(w for _, w in items):
            # The hand-off is on disk: the turn wrapped up by itself. Blocking
            # now would make the model, not the user, speak last (dotfiles#391).
            self.since_nag = False
            return ""
        self.nag_pending = True
        self.save_nag()
        paths = ", ".join(f"`{f}`" for f, _ in items)
        return ("Write the hand-off: replace the body (below `---`) of this session's pickup item with "
                f"the next step, then link:, model: and effort: lines. Item: "
                f"{paths or f'none exists yet in {self.sdir}/pickup/'}. Then answer with the body you "
                "wrote, pasted as-is in a fenced block -- the user cannot open files outside the "
                "session's repo -- and nothing else: no summary, no question, nothing new.")

    # -- the event block -------------------------------------------------------
    def block(self):
        """Shown to the user, never sent to the model. Any crossing line rides
        in front of it rather than arriving as a second message."""
        k, sess = self.k, obj(self.metrics.get("session"))
        dec = num(obj(sess.get("decisions")).get("total"))
        fric = num(obj(sess.get("friction")).get("total"))
        blocked = num(obj(sess.get("blocked")).get("total"))
        ctx = num(sess.get("context_peak"))
        out_tokens = num(sess.get("output_tokens"))

        ctx_glyphs = glyphs(self.ctx_rungs, "⛁") if self.ctx_rungs > 0 else "»"
        parts = [f"{ctx_glyphs} {kfmt(out_tokens)}/{kfmt(ctx)}"]
        # A zero that shows beats a field that vanishes: 🧘 decisions, 🌌 friction.
        parts.append(f"{'🤔' if dec > 3 else ''}{'⚖' * fib_rungs(dec)}(x{dec})" if dec > 0 else "🧘(x0)")
        parts.append(f"{'⚡' * fib_rungs(fric)}(x{fric})" if fric > 0 else "🌌(x0)")
        parts.append(f"🔧{'⛔' if blocked > 0 else '✅'}(x{blocked})")

        reason = ""
        if self.ctx_stop_line > 0:
            reason += "💸"
        if dec > 3:
            reason += "🤔"
        if fric >= 2:
            reason += "⚡"
        if self.sit_start > 0:
            sit_min = (self.now_ts - self.sit_start) // 60
            r = time_rungs(sit_min)
            # Night by Pacific time, not the host's: a cloud session runs UTC.
            pac_hour = at(time.time(), PACIFIC).hour
            sg = "🌙" if pac_hour >= k.stop_hour or pac_hour < k.night_end_hour else "⏱️"
            # Louder past the hot rung, night or day: 🌙🌙🌙⏰⏰ keeps both signals.
            parts.append(f"⏱{hm(sit_min)}" + "".join("⏰" if i >= k.sit_hot_rung else sg for i in range(r)))
            if sg == "🌙" and r >= 1:
                reason += "🌙"
            # Sitting proposes stopping at the rung the glyph turns ⏰: one knob.
            if r >= k.sit_hot_rung + 1:
                reason += "⏱️"
        if blocked >= 3:
            reason += "⛔"
        main = " ".join(parts)
        # The tail is the reason glyphs alone, and absent when none trips (#137).
        if reason:
            main = f"{main} — {reason}"
        second = fmt_lines(num(sess.get("user_turns")), num(sess.get("tool_calls")),
                           self.ncommits, self.dirty, self.unpushed)
        return f"{main}\n{second}" if second else main


# ------------------------------------------------------------------- helpers
_PUNCT_SPACE = re.escape(string.punctuation) + r" \t\n\r\f\v"


def is_stay(s):
    """`stay` or `stay <minutes>` and nothing else (any case, optional
    leading slash, trailing punctuation): the user's answer to a sitting rung."""
    return re.fullmatch(r"[ \t\n\r\f\v]*/?stay(?:[ \t\n\r\f\v]+[0-9]+m?)?[" + _PUNCT_SPACE + "]*",
                        s.lower()) is not None


def first_field(path, sid):
    """The second field of the first line whose first field is sid; "" when
    sid is in the file only elsewhere; None when the file is absent or does
    not name sid as a word."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except (FileNotFoundError, IsADirectoryError):
        return None
    if not re.search(r"(?<![\w])" + re.escape(sid) + r"(?![\w])", body):
        return None
    for ln in body.split("\n"):
        f = ln.split()
        if f and f[0] == sid:
            return f[1] if len(f) > 1 else ""
    return ""


def split_item(path):
    """A pickup item's lines before and after its first `---`."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if "---" not in lines:
        return lines, []
    i = lines.index("---")
    return lines[:i], lines[i + 1:]


def cksum(data):
    """POSIX cksum(1)'s CRC, so a checksum the shell hook stored still matches."""
    crc = 0

    def feed(byte):
        nonlocal crc
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7 if crc & 0x80000000 else crc << 1) & 0xFFFFFFFF

    for b in data:
        feed(b)
    n = len(data)
    while n:
        feed(n & 0xFF)
        n >>= 8
    return ~crc & 0xFFFFFFFF


def item_field(path, key):
    """That body line's value (link, model, effort), or ?."""
    for ln in split_item(path)[1]:
        if ln.startswith(f"{key}:"):
            return re.sub(r"^[^:]*:[ \t]*", "", ln) or "?"
    return "?"


def fmt_lines(turns, tools, commits, dirty, unpushed):
    """The block's second line, from metrics-format.sh: display text stays
    plain shell printf the user can edit unassisted."""
    out = run_out(["bash", "-c", '. "$1"; fmt_turns "$2" "$3"; printf "\\n"; fmt_work "$4" "$5" "$6"',
                   "_", FORMAT_SH, str(turns), str(tools), str(commits), str(dirty), str(unpushed)])
    turns_line, _, work = out.partition("\n")
    return f"{turns_line} {work}" if work else turns_line


def main(argv):
    if state is None:
        return 0
    try:
        ev = lib_state.event()
        WHERE["session_id"] = text(ev.get("session_id"))
        Hook(argv, ev).run()
    except Exception as e:  # noqa: BLE001 -- never fail the tool call; say so in the trace
        trace("hook", e)
    finally:
        state.state_unlock()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
