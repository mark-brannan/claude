#!/usr/bin/env python3
"""SessionStart: one line when the latest github-limits snapshot has a row
at warn or over; silent below warn or when the snapshot is more than two days old.

Reads only ~/.local/state/github-limits/snapshots.jsonl (written daily by
bin/github-limits-snapshot): no network, no git.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
sys.dont_write_bytecode = True

STALE = timedelta(days=2)  # a stopped daily job must not keep speaking
LINE_CAP = 240  # the line lands in every session's context


def latest(path):
    """The last snapshot that is a JSON object with a list of rows, or None."""
    import jsonl  # lib/, on sys.path above
    last = None
    try:
        for rec in jsonl.read(path):
            if isinstance(rec, dict) and isinstance(rec.get("rows"), list):
                last = rec
    except OSError:
        return None
    return last


def stale(rec):
    """True when the snapshot's UTC `at` is over STALE old; an unreadable `at` is stale."""
    try:
        at = datetime.strptime(rec["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return True
    return datetime.now(timezone.utc) - at > STALE


def line(rec):
    rows = [r for r in rec["rows"] if isinstance(r, dict) and r.get("status") in ("warn", "over")]
    if not rows:
        return None
    rows.sort(key=lambda r: (r["status"] != "over", -(r.get("used") or 0)))
    r = rows[0]
    used = r.get("used")
    pct = "" if used is None else f" ({used:.0%})"
    unit = f" {r['unit']}" if r.get("unit") else ""
    more = f"; +{len(rows) - 1} more" if len(rows) > 1 else ""
    text = (f"github-limits: {r['metric']} {r['value']:,}{unit} of {r['limit']:,}{pct}, {r['status']}"
            f"{more}; snapshot {str(rec.get('at', '?'))[:16]}Z; run `github-limits` for the table")
    text = "".join(" " if ord(c) < 32 or ord(c) == 127 else c for c in text)
    return text if len(text) <= LINE_CAP else text[:LINE_CAP - 1] + "…"


def main():
    path = os.path.join(os.path.expanduser("~"), ".local", "state", "github-limits", "snapshots.jsonl")
    rec = latest(path)
    text = line(rec) if rec and not stale(rec) else None
    if not text:
        return
    import hookio  # lib/, on sys.path above
    hookio.emit(hookio.context("SessionStart", text, system=text), ascii=False)


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-github-limits", "SessionStart", main)
