#!/usr/bin/env python3
"""SessionStart: re-run the cloud seed so a reused container tracks this repo
instead of the commit it was provisioned from.

The environment's setup script runs once, when the container is created, and
the container is then checkpointed and reused. So without this a rule edited
here reaches only the sessions that get a cold VM -- and the ones that don't
look identical to the ones that do, which is the failure this repo has already
been bitten by twice (the deleted hook that kept running, and the settings.json
fallback that ran a stranger's copy).

What it can and cannot do, and the difference matters:
  - hooks, rules/ and settings.json are read from disk when they fire, so a
    refresh here reaches THIS session for everything after session start.
  - CLAUDE.md was already loaded before this hook ran. A change to it would
    otherwise sit on disk unread until the next session, so when the refresh
    actually rewrites it the new copy is emitted as additionalContext. That
    costs a second copy in context, which is why it is emitted only on the
    sessions where it changed -- rare by construction, since most refreshes
    change nothing at all.

Remote-only (CLAUDE_CODE_REMOTE=true). On a real machine ~/.claude is a git
clone and the installer refuses there anyway, but returning before the
installer keeps a local session start free of it.

The installer's progress lines go nowhere: stdout here is charged to every
session, so the exit status is ignored and only a changed CLAUDE.md speaks.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to the
state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import os
import subprocess
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402

HEADER = (
    "## Standing orders were refreshed after this session started\n"
    "\n"
    "`~/.claude/CLAUDE.md` changed on the seed refresh, so the copy loaded\n"
    "at session start is stale. This is the current one; it supersedes it.\n"
    "\n"
)


def orders_bytes(path):
    """The file's bytes, or None when it is absent or unreadable."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def main():
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return
    home = os.path.expanduser("~")
    seed = os.environ.get("CLAUDE_SEED") or os.path.join(home, ".local/share/claude-seed")
    setup = os.path.join(seed, "bin", "cloud-session-setup.sh")
    orders = os.path.join(home, ".claude", "CLAUDE.md")
    if not os.path.isfile(setup):
        return

    before = orders_bytes(orders)
    subprocess.run(["sh", setup], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, env=dict(os.environ, CLOUD_SESSION="1"))
    after = orders_bytes(orders)

    if after is None or after == before:
        return
    hookio.emit(hookio.context("SessionStart", HEADER + after.decode("utf-8", "replace")))


if __name__ == "__main__":
    lib_state.run_hook("session-start-seed-refresh", "SessionStart", main)
