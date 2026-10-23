#!/usr/bin/env python3
"""Blocks scheduled wakeups that are bound to a live session.

Why: a trigger bound to a persistent session re-sends that session's ENTIRE
accumulated context on every firing. The cost grows with each wake, and the
harness asks PR-watching sessions to re-arm a check-in before ending a turn,
so the shape reproduces itself. On 2026-08-18 this put five self-re-arming
wakeups on one PR against a session holding 2.6M tokens of read history, and
burned two five-hour limit windows.

Originally symphony's project hook; hoisted to user level 2026-08-19 so it
covers every repo, not just the one where the incident happened.

What is still allowed:
  - subscribe_pr_activity  -- webhook-driven, free while idle, faster too
  - create_trigger with create_new_session_on_fire=true -- each fire starts
    from a clean context instead of compounding
  - CronCreate / /loop -- session-scoped, 7-day expiry, self-terminating

Fails closed, and where it differs from the shell hook it differs toward deny
(create_new_session_on_fire="true", a string, now denies; the shell allowed it).
This guard exists only to deny; its job is safety, not
function. The settings.json matcher ends in `|| true`, so a crash (an
unreadable lib/, say) would be silently swallowed into an ALLOW. Any error
here therefore answers with an explicit deny, in hand-written JSON that does
not lean on the code that failed.
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

SEND_LATER = (
    "Blocked by ~/.claude/hooks/no-persistent-polling.py: send_later binds a wakeup to this "
    "session and re-sends its full context on every fire, which compounds without bound. Use "
    "subscribe_pr_activity to wake on real events instead, or create_trigger with "
    "create_new_session_on_fire=true. If a check is still running, say so and end the turn -- "
    "the webhook will wake the session when it finishes."
)
TRIGGER = (
    "Blocked by ~/.claude/hooks/no-persistent-polling.py: a trigger bound to an existing "
    "session re-sends that session's whole context each time it fires. Set "
    "create_new_session_on_fire=true (and omit persistent_session_id) so each firing starts "
    "from a clean context, or use subscribe_pr_activity for event-driven waking."
)
BROKEN = (
    "Blocked by no-persistent-polling.py: the scheduled-wakeup request could not be evaluated "
    "(%s). Denying to fail closed. Fix the hook, or use subscribe_pr_activity to wake on real events."
)


def verdict(ev):
    """The deny reason for this call, or None to let it through."""
    tool = ev.get("tool_name")
    tool = tool if isinstance(tool, str) else ""
    ti = ev.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    if tool.endswith("__send_later"):
        return SEND_LATER
    if tool.endswith("__create_trigger"):
        fresh = ti.get("create_new_session_on_fire")
        persist = ti.get("persistent_session_id")
        # Only null, false and "" mean absent (jq's `// ""`, then -n). 0, {} and [] are
        # falsy in Python but present to the shell hook, which denied them; so do we.
        absent = persist is None or persist is False or (isinstance(persist, str) and persist == "")
        if fresh is not True or not absent:
            return TRIGGER
    return None


def main():
    import hookio
    reason = verdict(hookio.read())
    if reason:
        hookio.emit(hookio.deny(reason))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 -- fail closed, by design
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": BROKEN % type(e).__name__}}
        print(json.dumps(out))
    sys.exit(0)
