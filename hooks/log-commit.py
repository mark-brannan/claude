#!/usr/bin/env python3
"""PostToolUse, Bash: append one JSON line per real git commit, so commits are
traceable back to the session and machine that made them.

Fires on every Bash call and returns at once unless the command text holds
`git` and, later on the same line, `commit`. It filters on the command text,
not the matcher (matcher-side filtering does not work here: the matcher is
shared with measure-git-events.sh).

One line, in the state dir's commits.jsonl:
    {"ts":"2026-01-01T00:00:00Z","session_id":"...","remote_session_id":"",
     "repo":"claude","branch":"main","commit":"<sha>","claude_code_version":""}
repo is the checkout's top-level directory name; commit is HEAD after the
call. The state dir is session content, kept in the private state repo and
never in this public one; lib/state.py says where it is.

Prints nothing. Fails open: any error exits 0 and the call is untouched, but
it is said on stderr. A quiet exit (no cwd, not a repo, no commit yet) is
not an error.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

import lib_state  # noqa: E402  (puts lib/ on sys.path; reads the state dir and the event)

COMMIT = re.compile(r"\bgit\b.*\bcommit\b")  # per line: `.` does not cross a newline


def main():
    ev = lib_state.event()
    if ev.get("tool_name") != "Bash":
        return
    cmd = str((ev.get("tool_input") or {}).get("command") or "")
    if not COMMIT.search(cmd):
        return
    cwd = str(ev.get("cwd") or "")
    if not cwd:
        return
    if not os.path.isdir(cwd):
        print(f"log-commit: cwd {cwd!r} is not a directory", file=sys.stderr)
        return

    import gitrun
    if not gitrun.ok("rev-parse", "--git-dir", cwd=cwd):
        return  # not a repo: the commit was elsewhere
    head = gitrun.run("rev-parse", "HEAD", cwd=cwd)
    if head.returncode:
        return  # a repo with no commit yet
    top = gitrun.out("rev-parse", "--show-toplevel", cwd=cwd)
    sid = ev.get("session_id")
    if sid is None or sid is False:
        sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    sd = lib_state.state_dir()
    if not sd:  # no state lib here (lib_state said why on stderr): nowhere to log
        return
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": str(sid),
        "remote_session_id": os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID", ""),
        "repo": os.path.basename(top or cwd),
        "branch": gitrun.out("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd),
        "commit": head.stdout.strip(),
        "claude_code_version": os.environ.get("CLAUDE_CODE_VERSION", ""),
    }
    os.makedirs(sd, exist_ok=True)
    with open(os.path.join(sd, "commits.jsonl"), "a") as f:
        f.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a logger never blocks a call
        print(f"log-commit: {e}", file=sys.stderr)
    sys.exit(0)
