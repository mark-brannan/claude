"""A hook's input and output: the payload Claude Code hands it on stdin and
the JSON it answers with on stdout. Imported, never run directly; stdlib only.

The one home for the shapes the Python hooks speak (claude#213), so a port
from shell builds its answer here rather than retyping it:

    ev = hookio.read()                          # {} when stdin is absent or not an object
    if hookio.stop_hook_active(ev): return      # a Stop gate's loop breaker
    hookio.emit(hookio.block(reason))           # Stop / SubagentStop: keep the turn going
    hookio.emit(hookio.context("SessionStart", text, system=shown))
    hookio.emit(hookio.allow(text))             # PreToolUse: allow, with a note
    hookio.emit(hookio.deny(reason))            # PreToolUse: refuse the call

The builders return plain dicts, so a hook that says several things at once
merges them before one emit (metrics-live: a systemMessage, a block and a
context in one line). Key order is the order Claude Code's docs show and the
hooks have always written: systemMessage, then decision and reason, then
hookSpecificOutput with hookEventName first.

emit's encoding switches exist because each hook wrote its own line before
this module; a hook keeps its bytes by naming the ones it used. A new hook
takes the defaults.
"""
import json
import sys


def read(stream=None):
    """The hook payload from stream (stdin by default) as a dict; {} when it
    is absent, unreadable, not JSON or not an object. Never raises."""
    try:
        data = json.load(sys.stdin if stream is None else stream)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def stop_hook_active(ev):
    """True when Claude Code says this Stop is the retry after a block: a gate
    that blocks then lets this one through, so it blocks at most once a turn.
    Only a JSON true counts, as `jq -r '.stop_hook_active // false' = true`."""
    return isinstance(ev, dict) and ev.get("stop_hook_active") is True


def block(reason):
    """Stop or SubagentStop: refuse the stop and hand the model reason."""
    return {"decision": "block", "reason": reason}


def specific(event, **fields):
    """{"hookSpecificOutput": {"hookEventName": event, **fields}}. The event
    must be the one Claude Code dispatched, or it drops the output silently."""
    return {"hookSpecificOutput": {"hookEventName": event, **fields}}


def context(event, text, system=None):
    """additionalContext for the model at event (SessionStart,
    UserPromptSubmit, PostToolUse); system, when given, is the line the user
    sees as systemMessage."""
    out = {} if system is None else {"systemMessage": system}
    out.update(specific(event, additionalContext=text))
    return out


def allow(text):
    """PreToolUse: allow the call and attach text for the model."""
    return specific("PreToolUse", permissionDecision="allow", additionalContext=text)


def deny(reason):
    """PreToolUse: refuse the call; reason goes to the model."""
    return specific("PreToolUse", permissionDecision="deny", permissionDecisionReason=reason)


def emit(out, ascii=True, compact=False, errors="strict"):
    """Write out as one JSON line on stdout and flush. ascii escapes non-ASCII
    as json.dumps does by default; compact drops the spaces after , and :;
    errors is how a lone surrogate is encoded to UTF-8."""
    seps = (",", ":") if compact else None
    line = json.dumps(out, ensure_ascii=ascii, separators=seps) + "\n"
    sys.stdout.flush()
    sys.stdout.buffer.write(line.encode("utf-8", errors))
    sys.stdout.flush()
