"""Where a hook leaves the error it swallowed, and how a later session reads
it back. Imported, never run directly; stdlib only (state.py beside it).

A hook never blocks a tool call on its own bug, but stderr from a hook that
exits 0 reaches no one. So each swallowed error becomes one JSON line in the
state repo's metrics/hook-errors/, sharded by session like the other metrics
files, and hooks/session-start-hook-errors.py and bin/self-check read it back.
The one home for the writer (claude#241); every ported hook calls trace().

Row: {"ts", "hook", "event", "session_id", "stage", "error"}.
"""
import json
import os
import sys
import time

import state

SUBDIR = "metrics/hook-errors"
ERROR_MAX = 500


def _ts(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def trace(hook, stage, err, session_id="", event=""):
    """Record one swallowed error. stderr only when that write fails too.
    Never raises."""
    sid = str(session_id or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    line = json.dumps({"ts": _ts(), "hook": hook, "event": event, "session_id": sid,
                       "stage": stage, "error": f"{type(err).__name__}: {err}"[:ERROR_MAX]},
                      ensure_ascii=False, separators=(",", ":"))
    try:
        sd = state.state_dir()
        if not sd:
            raise OSError("no state dir")
        d = f"{sd}/{SUBDIR}"
        path = state.state_shard_path(d, f"{sid or 'unknown'}.jsonl", sid)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e2:  # noqa: BLE001 -- the last place left to say it
        print(f"{hook}: {line} (trace not written: {e2})", file=sys.stderr)


def _list(d, want_dirs):
    try:
        return [n for n in os.listdir(d)
                if os.path.isdir(f"{d}/{n}") == want_dirs and (want_dirs or n.endswith(".jsonl"))]
    except OSError:
        return []


def recent(state_dir, since_seconds=86400, now=None):
    """Rows traced in the last since_seconds, oldest first; unreadable files
    and lines are skipped."""
    now = time.time() if now is None else now
    cutoff = _ts(now - since_seconds)
    d = f"{state_dir}/{SUBDIR}"
    rows = []
    for sub in (d, *(f"{d}/{n}" for n in _list(d, True))):
        for name in _list(sub, False):
            path = f"{sub}/{name}"
            try:
                if os.path.getmtime(path) < now - since_seconds:
                    continue
                with open(path, encoding="utf-8") as fh:
                    for ln in fh:
                        try:
                            row = json.loads(ln)
                        except ValueError:
                            continue
                        if isinstance(row, dict) and str(row.get("ts", "")) >= cutoff:
                            rows.append(row)
            except OSError:
                continue
    return sorted(rows, key=lambda r: str(r.get("ts", "")))


def summary(rows):
    """One line naming each hook that traced, its count and its newest error.
    '' for none."""
    by = {}
    for r in rows:
        by.setdefault(str(r.get("hook", "?")), []).append(r)
    parts = []
    for hook, rs in sorted(by.items()):
        last = rs[-1]
        err = str(last.get("error", "")).replace("\n", " ")[:100]
        parts.append(f"{hook} x{len(rs)} (latest, stage {last.get('stage', '?')}: {err})")
    return "; ".join(parts)
