#!/usr/bin/env python3
"""PermissionRequest: approve a sub-agent's request, unless a hook asked for it.

Why: the desktop app can drop a session out of bypass mode mid-run (it did on
2026-11-02, session eb3cc26a, from bypassPermissions to default). From then
on, each sub-agent's tool call that needs permission waits on a dialog nobody
is watching, and a background sub-agent's call is denied outright. The
PreToolUse guards (languette first) are where calls are judged, so a request
that only a permission rule raised is approved here.

A PreToolUse hook's "ask" raises this same event, and its input does not say
so. A request is approved only when all three hold; otherwise the hook prints
nothing and the dialog shows as it would have:

- agent_id is present: the call is a sub-agent's (a main-session call has
  none; both carry the parent's session_id);
- permission_suggestions is non-empty: a hook's ask carries none (seen on
  Claude Code 2.1.300, docs silent);
- languette's decision record has no "ask" for this session in the last
  WINDOW seconds: a direct check on languette, independent of the one above.
  A guard's ask on a parallel sub-agent holds this one back too.

Fails closed: any error prints nothing, so the dialog shows.
"""
import calendar
import json
import os
import sys
import time

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402

WINDOW = 10        # seconds back from now that an ask counts
TAIL = 256 << 10   # bytes read from the end of each record file


def records_path(env):
    base = env.get("XDG_STATE_HOME") or os.path.join(env["HOME"], ".local", "state")
    return os.path.join(base, "languette", "decisions.jsonl")


def tail_lines(path):
    """The last TAIL bytes of path as lines, the first (likely cut) dropped; [] if absent."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL))
            data = f.read()
    except FileNotFoundError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > TAIL else lines


def languette_asked(session, now, path):
    """True when languette recorded an ask for session within WINDOW seconds of now.
    The rotated .1 is read too: a rotation can land between the ask and this hook."""
    for p in (path, path + ".1"):
        for ln in tail_lines(p):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("session") != session or r.get("verdict") != "ask":
                continue
            try:
                t = calendar.timegm(time.strptime(r.get("t", ""), "%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                return True  # an ask we cannot place in time is an ask
            if now - t <= WINDOW:
                return True
    return False


def approve(ev, now, path):
    if not ev.get("agent_id"):
        return False
    if not ev.get("permission_suggestions"):
        return False
    return not languette_asked(ev.get("session_id"), now, path)


def main():
    ev = lib_state.event()
    if ev.get("hook_event_name") != "PermissionRequest":
        return
    if approve(ev, time.time(), records_path(os.environ)):
        hookio.emit(hookio.specific("PermissionRequest", decision={"behavior": "allow"}))


if __name__ == "__main__":
    lib_state.run_hook("subagent-permission-approve", "PermissionRequest", main)
