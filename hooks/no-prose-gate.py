#!/usr/bin/env python3
"""Stop: block a turn whose closing line asks permission to do what was
ordered ("Want me to...?", "Shall I...?", "Proceed?", "Go?", "Merge it?")
when no AskUserQuestion ran since the human last spoke. Once per turn:
stop_hook_active on the retry exits 0, as in pr-threads-gate.py. On
2026-10-01 it matched 328 of 1116 prose asks in state metrics/decisions.

Reads the last 400 transcript lines; the turn is what follows the last real
human message (not isMeta). The closing line is last_assistant_message from
the payload, else the last assistant text in the turn, last non-blank line.

Prints the block decision as one JSON line, or nothing. CONVENIENCE: it nags,
it never traps. No transcript, or any error, exits 0; a swallowed error is
traced (lib/hooktrace.py).
"""
import json
import re
import sys
from collections import deque

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path; reads the event)

TAIL = 400
QUESTION = re.compile(r"\?[*_ ]*$")
ASK = re.compile(
    r"(^|[^a-z])(want me to|shall (i|we)|should i|ok(ay)? to|may i|go ahead|proceed"
    r"|merge it|push it|ship it|good to (go|add|merge|push|ship)"
    r"|want (it|that|this|them)( [a-z]+){0,2}\?)|(^|[.!:-] *)go\?",
    re.I,
)
REASON = (
    'no-prose-gate: the turn ends asking permission ("%s") without AskUserQuestion. '
    "Inside the order: do it now, then report. A one-way door: ask with AskUserQuestion "
    "and options. Anything else: take the default, put a ruling card (default, undo, "
    "until, risk) in the global board's ## Needs ruling via /card-write, and carry on. "
    "Then end the turn again; this gate does not fire twice."
)


def _blocks(row):
    c = (row.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def _is_human(row):
    if row.get("type") != "user" or row.get("isMeta"):
        return False
    c = (row.get("message") or {}).get("content")
    return isinstance(c, str) or any(b.get("type") == "text" for b in _blocks(row))


def tail_rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = deque(f, TAIL)
    rows = []
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue  # a cut-off first line of the tail
        if isinstance(r, dict):
            rows.append(r)
    return rows


def closing_line(rows, msg):
    """The turn's last non-blank line, or "" when AskUserQuestion ran in it."""
    h = -1
    for i, r in enumerate(rows):
        if _is_human(r):
            h = i
    turn = rows[h + 1:]
    asst = [r for r in turn if r.get("type") == "assistant"]
    if any(b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion"
           for r in asst for b in _blocks(r)):
        return ""
    if not msg:
        texts = [str(b.get("text")) for r in asst for b in _blocks(r)
                 if b.get("type") == "text" and isinstance(b.get("text"), str)]
        msg = texts[-1] if texts else ""
    lines = [x for x in msg.split("\n") if re.search(r"\S", x)]
    return lines[-1] if lines else ""


def main():
    ev = lib_state.event()
    if not ev:
        return
    hookio = lib_state.hookio
    if hookio.stop_hook_active(ev):
        return
    tp = ev.get("transcript_path")
    if not isinstance(tp, str) or not tp:
        return
    try:
        rows = tail_rows(tp)
    except OSError:
        return  # no transcript: nothing to judge
    msg = ev.get("last_assistant_message")
    last = closing_line(rows, msg if isinstance(msg, str) else "")
    if QUESTION.search(last) and ASK.search(last):
        hookio.emit(hookio.block(REASON % last))


if __name__ == "__main__":
    lib_state.run_hook("no-prose-gate", "Stop", main)
