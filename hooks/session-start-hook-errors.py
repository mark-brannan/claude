#!/usr/bin/env python3
"""SessionStart: name the hooks that traced a swallowed error in the last day.

Why (claude#241): a hook never blocks a tool call on its own bug, so its
failure is a line in the state repo's metrics/hook-errors/ (lib/hooktrace.py),
and a line nobody reads is no better than stderr. This puts one sentence in
front of the session when any hook traced since yesterday, and stays silent
when none did. bin/self-check shows the same rows on demand.

CONVENIENCE: never blocks a session, always exits 0; a crash goes to stderr.
"""
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

WINDOW = 86400


def main():
    import hooktrace
    import state
    sd = state.state_dir()
    if not sd:
        return
    rows = hooktrace.recent(sd, WINDOW)
    if not rows:
        return
    text = (f"Hooks traced {len(rows)} swallowed error(s) in the last day: {hooktrace.summary(rows)}. "
            f"Rows: {sd}/metrics/hook-errors/. `self-check` shows them too.")
    print(json.dumps({"systemMessage": text,
                      "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a convenience hook never stops a session
        print(f"session-start-hook-errors: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)
