#!/usr/bin/env python3
"""SessionStart: hand the session its board and its recent history.

The standing orders say new sessions open by pulling from a board. That only
happens reliably if the board is already in front of the session -- asking
Claude to go find it costs a prompt from the user, which is the thing this is
supposed to remove. So this reads the state repo and injects a short brief.

Deliberately terse. Every line here is charged to every session in every
repo, so it carries only what changes what the session does first: open
work, what the last sessions left behind, and how much deciding the user has
already been asked to do this week.

The board is not read here. `worklist --brief` owns that view -- live PR and
issue state plus the `## Needs ruling` and `## Claude's` cards, <= 3 KB by its
contract, served from cache so it is fast. This hook only caps the wait at
6 s (a hung gh call must never hold session start) and clips the output at
4 KB, so a broken worklist cannot become a 40 KB tax. A missing worklist is
reported, not worked around; there is no fallback dump.

Never clones. A private clone needs credentials a hook cannot count on and
would stall session start on the network; absence is reported with the fix
instead of silently papered over.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import glob
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402
import state  # noqa: E402

WORKLIST_CAP = 6  # seconds a `worklist --brief` may take
BOARD_CLIP = 4096  # bytes of its output kept
PULL_CAP = 25  # seconds the courtesy `git pull` may take

NO_STATE = """## Continuity: state repo NOT available

`claude_prompts_scratch` is not checked out here, so the board, the prior
checkpoints and the metrics are all missing, and `stop-continuity.py` will
write to `~/.claude/state/global` (local, unpushed, lost when this container
is reclaimed).

Fix it now: `mcp__Claude_Code_Remote__add_repo` with owner `mark-brannan`,
repo `claude_prompts_scratch`, access `push`, then clone it to
`/workspace/claude_prompts_scratch` -- a path `state_repo` already searches.
Do this every cold session; there is no environment setting that does it for
you. Cloud environments configure only name, network access, environment
variables and a setup script -- repositories attach per session, and the
GitHub proxy 403s any repo not attached, so a setup script cannot clone this.
"""

PREAMBLE = """## Continuity brief

State repo: `{sr}` (board, checkpoints and metrics live here; the Stop
hook commits and pushes to it automatically -- no need to be asked).
"""

LOAD_TAIL = """
`scoping` is cheap (asked before work exists),
`gate` is expensive (open-ended, mid-flight, needs the user to reload
context). Prefer front-loading questions; board the rest.
"""


def num(n):
    """A JSON number as jq prints it: 60.0 is 60."""
    return str(int(n)) if isinstance(n, float) and n == int(n) else str(n)


def jq_str(v):
    """v as `jq -r` prints it."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return num(v)
    return json.dumps(v, ensure_ascii=False)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def truthy(v):
    """jq's truth: only null and false are false. Not `v not in (None,
    False)`, which drops 0 too, since 0 == False in Python."""
    return v is not None and v is not False


def sync_status_line(home):
    """One line on the config sync, cloud sessions only: a real machine
    is yadm-managed and never has the file, so DEGRADED there would be a
    false alarm."""
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return ""
    path = os.path.join(home, ".claude", ".sync-status.json")
    if not os.path.isfile(path):
        return "config: DEGRADED — no .sync-status.json (installer never ran, or predates P1)"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError
    except (OSError, ValueError):
        d = None
    get = (lambda k: jq_str(d.get(k))) if d is not None else (lambda k: "")
    complete, sha, channel, at = get("complete"), get("sha")[:7], get("channel"), get("installed_at")
    if complete != "true":
        return f"config: DEGRADED — incomplete install ({channel}@{sha}, {at})"
    return f"config: {channel}@{sha} (installed {at})"


def kill(p):
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    p.wait()


def pull(sr):
    """Freshen the state repo, never blocking session start on it."""
    try:
        p = subprocess.Popen(["git", "-C", sr, "pull", "--rebase", "--autostash", "-q"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return
    try:
        p.wait(PULL_CAP)
    except subprocess.TimeoutExpired:
        kill(p)


def board_view(home):
    """worklist --brief under a wall-clock cap, clipped, with a line saying
    why when it did not finish cleanly."""
    wl = os.path.join(home, ".claude", "bin", "worklist")
    if not (os.path.isfile(wl) and os.access(wl, os.X_OK)):
        return ("worklist not installed -- live board view unavailable; this is not a clean state "
                "(run dotsync / cloud-session-setup.sh)\n")
    with tempfile.TemporaryFile() as out:
        try:
            p = subprocess.Popen([wl, "--brief"], stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            return ""
        try:
            rc = p.wait(WORKLIST_CAP)
        except subprocess.TimeoutExpired:
            kill(p)
            rc = -9
        head = ""
        if rc < 0 or rc > 128:
            head = (f"worklist --brief did not return in {WORKLIST_CAP} s -- board view unavailable "
                    "this session; run `worklist --brief` yourself\n")
        elif rc == 3:
            # worklist's own code for a store it cannot read: the GitHub view
            # stands, the cards are what is missing.
            head = ("worklist --brief exited 3 -- the work-item store cannot be read, so no cards "
                    "are shown below; it is not an empty board\n")
        elif rc != 0:
            head = f"worklist --brief exited {rc} -- board view unavailable this session; run `worklist --brief` yourself\n"
        out.seek(0)
        return head + out.read(BOARD_CLIP).decode("utf-8", "replace")


def flat_and_sharded(d, pattern):
    """dir/<pattern> and dir/*/<pattern>: a flat (pre-split) file and a
    sharded one are read together."""
    return sorted(glob.glob(os.path.join(d, pattern)) + glob.glob(os.path.join(d, "*", pattern)))


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def slurp(paths):
    """Every JSON value in the files, as `jq -s` reads their concatenation,
    or None when any of it does not parse (jq then prints nothing)."""
    dec = json.JSONDecoder()
    out = []
    for p in paths:
        s, i = read_text(p), 0
        while True:
            while i < len(s) and s[i] in " \t\r\n":
                i += 1
            if i >= len(s):
                break
            try:
                v, i = dec.raw_decode(s, i)
            except ValueError:
                return None
            out.append(v)
    return out


def objs(vals):
    """vals as dicts when every one is an object or null (what `.field`
    accepts in jq), else None."""
    if vals is None or any(not (v is None or isinstance(v, dict)) for v in vals):
        return None
    return [v or {} for v in vals]


def ts_ge(ts, since):
    """jq's `.ts >= $since` for a string $since: strings by codepoint,
    arrays and objects sort above strings, everything else below."""
    if isinstance(ts, str):
        return ts >= since
    return isinstance(ts, (list, dict))


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def sed_range(lines, start, end):
    """sed -n '/start/,/end/p': each range opens on a start line and closes
    on the first later line matching end, both lines included."""
    out, inside = [], False
    for x in lines:
        if not inside:
            if start(x):
                inside = True
                out.append(x)
        else:
            out.append(x)
            if end(x):
                inside = False
    return out


def mtime_ns(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def checkpoints(sd):
    d = os.path.join(sd, "log", "auto")
    if not os.path.isdir(d):
        return ""
    # ls -t: newest first, ties by name
    recent = sorted(flat_and_sharded(d, "*.md"), key=lambda f: (-mtime_ns(f), f))[:3]
    if not recent:
        return ""
    out = ["\n### Where recent sessions left off\n\n"]
    for f in recent:
        lines = read_text(f).split("\n")
        if lines[-1] == "":
            lines.pop()
        out.append(f"**{os.path.basename(f)[:-3]}**\n")
        out.extend(f"{x}\n" for x in sed_range(lines, lambda x: x.startswith("- session"), lambda x: x == "")[:6])
        unc = sed_range(lines, lambda x: x.startswith("## Uncommitted at Stop"), lambda x: x.startswith("## "))
        out.extend(f"    {x}\n" for x in [x for x in unc if not x.startswith("## ") and x != ""][:6])
        out.append("\n")
    return "".join(out)


def jq_order(v):
    """A sort key in jq's order for the scalars these files hold."""
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1 + v, 0)
    if is_num(v):
        return (3, v)
    return (4, str(v))


def decision_load(sd):
    d = os.path.join(sd, "metrics", "decisions")
    if not os.path.isdir(d):
        return ""
    since = days_ago(7)
    counts = {}
    for f in flat_and_sharded(d, "*.jsonl"):
        for line in read_text(f).split("\n"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                break
            if not (r is None or isinstance(r, dict)):
                break
            r = r or {}
            if ts_ge(r.get("ts"), since):
                t = jq_str(r.get("type"))
                counts[t] = counts.get(t, 0) + 1
    if not counts:
        return ""
    # sort | uniq -c | awk: count, then the first word of the type
    text = ", ".join(f"{counts[t]} {(t.split() or [''])[0]}" for t in sorted(counts))
    perh = last = ""
    sess = objs(slurp(flat_and_sharded(os.path.join(sd, "metrics", "sessions"), "*.json")))
    if sess is not None:
        def span(r):
            s = r.get("prompt_span_seconds")
            return s if is_num(s) else 0

        def total(r, k):
            v = r.get(k)
            t = v.get("total") if isinstance(v, dict) else None
            return t if is_num(t) else None

        week = [r for r in sess if ts_ge(r.get("ts"), since) and span(r) >= 60]
        wd = sum(total(r, "decisions") or 0 for r in week)
        ws = sum(span(r) for r in week)
        if ws > 0 and ws == int(ws):
            perh = " · %.1f decisions per session-hour" % (wd * 3600 / ws)
        long_ = sorted((r for r in sess if span(r) >= 60), key=lambda r: jq_order(r.get("ts")))
        if long_:
            r = long_[-1]

            def tsv(v):
                return "" if v is None else num(v)
            rate = state.decision_rate(tsv(total(r, "decisions")), tsv(span(r)))
            if rate:
                last = f"last session: {rate} · friction {tsv(total(r, 'friction'))}\n"
    return "\n### Decision load, last 7 days\n\n" + text + perh + "\n" + last + LOAD_TAIL


def med(xs):
    """jq's `sort | (.[(length-1)/2|floor] + .[length/2|floor]) / 2 | floor`;
    a null adds as nothing, as in jq."""
    xs = sorted(xs, key=jq_order)
    n = len(xs)
    a, b = xs[(n - 1) // 2], xs[n // 2]
    if a is None and b is None:
        raise TypeError("null has no floor")
    return math.floor(((a or 0) + (b or 0)) / 2)


def group_by_at(rows):
    """jq's group_by(.at): lists of rows, in .at order."""
    out = {}
    for r in rows:
        out.setdefault(json.dumps(r.get("at")), []).append(r)
    return sorted(out.values(), key=lambda g: jq_order(g[0].get("at")))


def rungs_line(rows, since):
    """One line per rung: median minutes to the next prompt, and stays."""
    parts = []
    for g in group_by_at([r for r in rows if r.get("kind") == "time_after" and ts_ge(r.get("ts"), since)]):
        stay = sum(1 for r in g if truthy(r.get("stay")))
        parts.append(f"{jq_str(g[0].get('at'))}m: median {med([r.get('min') for r in g])}m "
                     f"to next prompt, {stay}/{len(g)} stay")
    return "\nSitting rungs, last 28 days: " + " \u00b7 ".join(parts) + "\n" if parts else ""


def ends_line(rows, since):
    """How each rung's sitting ended: the latest reading per crossing
    counts, a stay's minutes come from its time_after."""
    def key(r):
        return jq_str(r.get("session_id")) + "\0" + jq_str(r.get("crossing_ts"))
    stays = {key(r): r for r in rows if r.get("kind") == "time_after" and r.get("stay_min") is not None}
    ends = {key(r): r for r in rows if r.get("kind") == "time_last" and ts_ge(r.get("ts"), since)}
    parts = []
    for g in group_by_at(list(ends.values())):
        s = [x for x in ((stays.get(key(r)) or {}).get("stay_min") for r in g) if truthy(x)]
        o = [r.get("overrun") for r in g if r.get("overrun") is not None]
        ended = sum(1 for r in g if r.get("min_to_last") <= 10)
        t = (f"{jq_str(g[0].get('at'))}m: median {med([r.get('min_to_last') for r in g])}m "
             f"to sitting end, {ended}/{len(g)} ended it")
        if s:
            over = sum(1 for x in o if truthy(x))
            t += f", stay median {med(s)}m, {over}/{len(o)} overrun"
        parts.append(t)
    return "Sitting ends, last 28 days: " + " \u00b7 ".join(parts) + "\n" if parts else ""


def crossings(sd):
    """What followed each sitting rung, and how each rung's sitting ended
    (metrics-live.py stamp_time_after, stamp_time_last). Measured, never
    nudged. Each line stands alone: as with the two jq calls this was, one
    that cannot be computed leaves the other."""
    d = os.path.join(sd, "metrics", "crossings")
    if not os.path.isdir(d):
        return ""
    since = days_ago(28)
    rows = objs(slurp(flat_and_sharded(d, "*.jsonl")))
    if rows is None:
        return ""
    out = ""
    for line in (rungs_line, ends_line):
        try:
            out += line(rows, since)
        except (TypeError, ValueError, IndexError):
            pass
    return out


def held_back(sr):
    """What the last state commit held back, for this session to raise."""
    rows = state.held_back(sr)
    if not rows:
        return ""
    return ("\n### Held back from the state commit\n\n"
            + "".join(f"- `{p}` — {why}\n" for p, why in rows[:10])
            + (f"- +{len(rows) - 10} more\n" if len(rows) > 10 else "")
            + "\nWhichever session wrote these, offer the user a way to resolve each: "
              "commit it, scrub it, move it or gitignore it.\n")


def main():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    lead = sync_status_line(home)
    lead = lead + "\n\n" if lead else ""
    sr = state.state_repo()
    if sr is None:
        text = lead + NO_STATE
    else:
        sd = os.path.join(sr, "state", "global")
        pull(sr)
        text = lead + PREAMBLE.format(sr=sr) + "\n" + board_view(home)
        text += held_back(sr) + checkpoints(sd) + decision_load(sd) + crossings(sd)
    hookio.emit(hookio.context("SessionStart", text), ascii=False)


if __name__ == "__main__":
    lib_state.run_hook("session-start-continuity", "SessionStart", main)
