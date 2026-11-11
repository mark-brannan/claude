#!/usr/bin/env python3
"""SessionStart: name the scheduled jobs whose last run failed, and the
scratch directories prune-scratch will not delete (git work, or too big to age).

Reads two kinds of local file and nothing else (no network, no git, no
subprocess):
  - ~/.local/state/jobs/NAME.last, one JSON line per job written by
    dotfiles' `jobs run`: a non-zero exit or timed_out is one line naming
    the job, when it ended, its exit and its log ~/.local/state/jobs/NAME.log
  - ~/.local/state/prune-scratch/held.json, written by bin/prune-scratch: a
    non-empty list is one line with the count and the oldest few

Silent when neither has anything to say.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import glob
import json
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
sys.dont_write_bytecode = True

MAX_JOBS = 50       # .last files read at most
MAX_BYTES = 65536   # per file
OLDEST = 3          # held paths shown


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
        name = os.path.basename(last)[:-len(".last")]
        how = "timed out" if rec.get("timed_out") else f"exit {rec.get('exit')}"
        when = rec.get("ended") or rec.get("started") or "unknown time"
        lines.append(f"job {name} failed ({how}) at {when}; log ~/.local/state/jobs/{name}.log")
    return lines


def held_line(state):
    held = read(os.path.join(state, "prune-scratch", "held.json"))
    if not isinstance(held, list) or not held:
        return None
    rows = sorted((h for h in held if isinstance(h, dict)),
                  key=lambda h: -(h.get("age_days") or 0))[:OLDEST]
    shown = "; ".join(f"{h.get('path')} ({h.get('reason')})" for h in rows)
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
