#!/usr/bin/env python3
"""SessionStart: name the hooks that traced a swallowed error in the last day.

Why (claude#241): a hook never blocks a tool call on its own bug, so its
failure is a line in the state repo's metrics/hook-errors/ (lib/hooktrace.py),
and a line nobody reads is no better than stderr. This puts one sentence in
front of the session when any hook traced since yesterday, and stays silent
when none did. bin/self-check shows the same rows on demand.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

WINDOW = 86400
NAME = re.compile(r"[A-Za-z0-9_.-]{1,40}")


def main():
    import hookio
    import hooktrace
    import state
    sd = state.state_dir()
    if not sd:
        return
    rows = hooktrace.recent(sd, WINDOW)
    if not rows:
        return
    # Rows are data a hook wrote from its own failure, so they may carry text
    # an attacker chose. The model sees only names that match NAME and counts;
    # the fuller detail goes to the user's systemMessage and self-check.
    counts = {}
    for r in rows:
        h = str(r.get("hook", ""))
        if NAME.fullmatch(h):
            counts[h] = counts.get(h, 0) + 1
    named = ", ".join(f"{h} x{n}" for h, n in sorted(counts.items())) or "unnamed hooks"
    context = (f"Hooks traced {len(rows)} swallowed error(s) in the last day ({named}). "
               f"Run `self-check` to read them.")
    shown = (f"Hooks traced {len(rows)} swallowed error(s) in the last day: {hooktrace.summary(rows)}. "
             f"Rows: {sd}/metrics/hook-errors/. `self-check` shows them too.")
    hookio.emit(hookio.context("SessionStart", context, system=shown), ascii=False)


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-hook-errors", "SessionStart", main)
