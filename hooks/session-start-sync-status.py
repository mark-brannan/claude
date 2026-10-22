#!/usr/bin/env python3
"""SessionStart: report the dotfiles sync's last result when the ~/.claude
clone is behind origin/main or the sync skipped it.

Why (claude#166): the */5 cron `dotfiles-sync.sh` fast-forwards ~/.claude,
but skips a dirty or diverged clone, and a skip reached only syslog. Over
seven days it skipped 181 of 204 runs that found the clone behind, so
sessions ran stale hooks and skills with nobody told. This puts the sync's
own one-line status in front of the session and the user when it matters,
and stays silent when the clone is current.

Two triggers, either one:
  - the clone's HEAD is behind its origin/main, as last fetched (no network
    call here: the cron fetches)
  - the `claude:` part of `dotfiles-sync.sh --status` starts with "skipped"

No clone, or no sync script: silent; there is nothing to report on.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import json
import os
import subprocess
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
try:
    import gitrun  # noqa: E402
except ImportError:  # a seed without lib/: how far behind is unknown
    gitrun = None

sys.dont_write_bytecode = True

TIMEOUT = 5


def run(args):
    """stdout of args, stripped, or None when it fails or hangs."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def behind(clone):
    """Commits on origin/main the clone's HEAD lacks, 0 when unknown."""
    if gitrun is None:
        return 0
    p = gitrun.run("-C", clone, "rev-list", "--count", "HEAD..origin/main", timeout=TIMEOUT)
    n = p.stdout.strip()
    return int(n) if p.returncode == 0 and n.isdigit() else 0


def claude_part(status):
    """The `claude: ...` phrase of a status line, or ""."""
    for part in status.split("; "):
        if part.startswith("claude: "):
            return part[len("claude: "):]
    return ""


def main():
    home = os.path.expanduser("~")
    clone = os.path.join(home, ".claude")
    sync = os.path.join(home, ".local", "bin", "dotfiles-sync.sh")
    if not os.path.isdir(os.path.join(clone, ".git")) or not os.path.isfile(sync):
        return
    status = run(["sh", sync, "--status"]) or ""
    n = behind(clone)
    skipped = claude_part(status).startswith("skipped")
    if not n and not skipped:
        return
    lag = f"~/.claude is {n} commit(s) behind origin/main" if n else "~/.claude was skipped by the last sync"
    text = (f"{lag}, so this session may run stale hooks and skills. "
            f"Last sync (`dotfiles-sync.sh --status`): {status or 'no output'}")
    out = {"systemMessage": text,
           "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-sync-status", "SessionStart", main)
