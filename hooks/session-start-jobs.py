#!/usr/bin/env python3
"""SessionStart: name the scheduled jobs whose last run failed, and the
scratch directories prune-scratch will not delete (git work, or too big to age).

Reads two kinds of local file and nothing else (no network, no git, no
subprocess):
  - ~/.local/state/jobs/NAME.last, one JSON line per job written by
    dotfiles' `cron-jobs run`: a non-zero exit or timed_out is one line naming
    the job, when it ended, its exit and its log ~/.local/state/jobs/NAME.log
  - ~/.local/state/prune-scratch/held.json, written by bin/prune-scratch: a
    non-empty list is one line with the count and the oldest few, at most
    once a day per machine unless the count grew since it was last shown
    (stamped in ~/.local/state/prune-scratch/held-shown.json, the one write)

Silent when neither has anything to say.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import glob
import json
import os
import sys
import time

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
sys.dont_write_bytecode = True

MAX_JOBS = 50       # .last files read at most
MAX_BYTES = 65536   # per file
OLDEST = 3          # held paths shown
QUIET_SECS = 86400  # between two showings of an unchanged held list
FIELD_CAP = 160     # chars per shown field: these land in every session's context


def clean(v):
    """A field from a file as one short line: control characters become spaces."""
    text = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in str(v))
    return text if len(text) <= FIELD_CAP else text[:FIELD_CAP - 1] + "…"


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.loads(f.read(MAX_BYTES))
    except (OSError, ValueError):
        return None


def failed_jobs(state):
    lines = []
    for last in sorted(glob.glob(os.path.join(state, "jobs", "*.last")))[:MAX_JOBS]:
        rec = read(last)
        if not isinstance(rec, dict):
            continue
        if rec.get("exit") in (0, None) and not rec.get("timed_out"):
            continue
        name = clean(os.path.basename(last)[:-len(".last")])
        how = "timed out" if rec.get("timed_out") else f"exit {clean(rec.get('exit'))}"
        when = clean(rec.get("ended") or rec.get("started") or "unknown time")
        lines.append(f"job {name} failed ({how}) at {when}; log ~/.local/state/jobs/{name}.log")
    return lines


def held_line(state):
    held = read(os.path.join(state, "prune-scratch", "held.json"))
    if not isinstance(held, list) or not held:
        return None
    stamp_path = os.path.join(state, "prune-scratch", "held-shown.json")
    stamp = read(stamp_path)
    now = time.time()
    if isinstance(stamp, dict):
        at, count = stamp.get("at"), stamp.get("count")
        if (isinstance(at, (int, float)) and isinstance(count, int)
                and now - at < QUIET_SECS and len(held) <= count):
            return None
    try:
        import atomic  # lib/, on sys.path above
        atomic.write(stamp_path, json.dumps({"at": now, "count": len(held)}) + "\n")
    except OSError:
        pass  # unstamped: shown again next session, never lost
    rows = sorted((h for h in held if isinstance(h, dict)),
                  key=lambda h: -(h.get("age_days") or 0))[:OLDEST]
    shown = "; ".join(f"{clean(h.get('path'))} ({clean(h.get('reason'))})" for h in rows)
    return (f"prune-scratch is holding {len(held)} old scratch dir(s) it will not delete "
            f"(~/.local/state/prune-scratch/held.json); oldest: {shown}")


def main():
    state = os.path.join(os.path.expanduser("~"), ".local", "state")
    lines = failed_jobs(state)
    h = held_line(state)
    if h:
        lines.append(h)
    if not lines:
        return
    text = "\n".join(lines)
    import hookio  # lib/, on sys.path above
    hookio.emit(hookio.context("SessionStart", text, system=text), ascii=False)


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-jobs", "SessionStart", main)
