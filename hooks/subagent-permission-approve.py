#!/usr/bin/env python3
"""PermissionRequest: approve a sub-agent's request, unless a hook asked for it.

Why: the desktop app can drop a session out of bypass mode mid-run. From then
on, each sub-agent's tool call that needs permission waits on a dialog nobody
is watching, and a background sub-agent's call is denied outright. The
PreToolUse guards (languette first) are where calls are judged, so a request
that only a permission rule raised is approved here.

A PreToolUse hook's "ask" raises this same event, and its input does not say
so. A request is approved only when all four hold; otherwise the hook prints
nothing and the dialog shows as it would have:

- permission_mode is "default": the dropped-out case. In plan or acceptEdits
  the user chose the mode, and plan's point is not acting;
- agent_id is present: the call is a sub-agent's (a main-session call has
  none, even under --agent, which sets only agent_type; both carry the
  parent's session_id);
- permission_suggestions is non-empty: a hook's ask carries none (seen on
  Claude Code 2.1.300, docs silent);
- languette's decision record has no "ask" for this request: same session and
  tool, and either within the last WINDOW seconds or, for Bash, the same
  masked command (a queued dialog can show after the window). The command is
  masked by the built-in rules only, so one a project rule masks falls back to
  the window. Best-effort:
  with record_decisions off there is no record at all, and a record can be
  dropped under lock contention, so on such a machine the suggestions check
  above is the only one that holds.

Each sub-agent request's outcome is appended to the state dir's
metrics/permission-approvals/<session>.jsonl, beside permission-request-log:
    {"ts": "...", "session_id": "...", "agent_id": "a4aa...", "agent_type":
     "general-purpose", "tool": "Bash", "verdict": "allow"}
verdict is allow, no-suggestions or languette-ask (a request outside the
default mode is not logged).

Fails closed: any error before the answer prints nothing, so the dialog shows.
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


def request_command(ev, record):
    """The request's Bash command masked as languette records it; None when not Bash or unmaskable."""
    cmd = (ev.get("tool_input") or {}).get("command")
    if record is None or ev.get("tool_name") != "Bash" or not isinstance(cmd, str):
        return None
    try:
        return record.mask(cmd)[0]
    except Exception:  # noqa: BLE001
        return None


def languette_asked(ev, now, path, command=None):
    """True when languette recorded an ask for this request: same session and tool,
    within WINDOW seconds of now or with the same masked command.
    The rotated .1 is read too: a rotation can land between the ask and this hook."""
    session = ev.get("session_id")
    for p in (path, path + ".1"):
        for ln in tail_lines(p):
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("session") != session or r.get("verdict") != "ask" or r.get("tool") != ev.get("tool_name"):
                continue
            if command is not None and (r.get("command") or {}).get("text") == command:
                return True
            try:
                t = calendar.timegm(time.strptime(r.get("t", ""), "%Y-%m-%dT%H:%M:%SZ"))
            except ValueError:
                return True  # an ask we cannot place in time is an ask
            if now - t <= WINDOW:
                return True
    return False


def verdict(ev, now, path, record=None):
    """allow, or why not; None for a main-session request or one outside the default mode."""
    if ev.get("permission_mode") != "default" or not ev.get("agent_id"):
        return None
    if not ev.get("permission_suggestions"):
        return "no-suggestions"
    return "languette-ask" if languette_asked(ev, now, path, request_command(ev, record)) else "allow"


def log(ev, v):
    """One line per sub-agent request; never lets a logging failure reach the caller."""
    try:
        sd = lib_state.state_dir()
        if not sd:
            return
        import when
        from state import append_row
        sid = str(ev.get("session_id") or "unknown")
        append_row(os.path.join(sd, "metrics", "permission-approvals"), sid,
                   {"ts": when.stamp(), "session_id": sid, "agent_id": ev.get("agent_id"),
                    "agent_type": ev.get("agent_type"), "tool": ev.get("tool_name"), "verdict": v})
    except Exception as e:  # noqa: BLE001 -- the answer is already out
        lib_state.trace_failure("subagent-permission-approve", "PermissionRequest", e, stage="log")


def main():
    ev = lib_state.event()
    if ev.get("hook_event_name") != "PermissionRequest":
        return
    record = lib_state.languette_record()
    v = verdict(ev, time.time(), lib_state.records_path(os.environ), record)
    if v == "allow":
        hookio.emit(hookio.specific("PermissionRequest", decision={"behavior": "allow"}))
    if v:
        log(ev, v)


if __name__ == "__main__":
    lib_state.run_hook("subagent-permission-approve", "PermissionRequest", main)
