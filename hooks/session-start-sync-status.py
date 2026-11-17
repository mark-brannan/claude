#!/usr/bin/env python3
"""SessionStart: report the dotfiles sync's last result when the ~/.claude
clone is behind origin/main or the sync skipped it.

Why (claude#166): the */5 cron `dotfiles-sync.sh` fast-forwards ~/.claude,
but skips a dirty or diverged clone, and a skip reached only syslog. Over
seven days it skipped 181 of 204 runs that found the clone behind, so
sessions ran stale hooks and skills with nobody told. This puts the sync's
own one-line status in front of the session and the user when it matters,
and stays silent when the clone is current.

Three triggers, any one:
  - the clone's HEAD is behind its origin/main, as last fetched (no network
    call here: the cron fetches)
  - the `claude:` part of `dotfiles-sync.sh --status` starts with "skipped"
  - the clone is wedged: a git lock file, or a merge, rebase, cherry-pick or
    revert in progress, older than STALE. Nothing in ~/.claude legitimately
    holds one that long, and no sync can move the clone until it is cleared,
    so the warning names the file, its age and the commands that clear it,
    rather than relay the sync's guess at the cause (on 2026-11-17 a pull killed mid-update left HEAD.lock
    and refs/heads/main.lock for 16 hours; the sync called it "diverged").

No clone, or no sync script: silent; there is nothing to report on.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import os
import shlex
import subprocess
import sys
import time

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
try:
    import gitrun  # noqa: E402
except ImportError:  # a seed without lib/: how far behind is unknown
    gitrun = None

sys.dont_write_bytecode = True

TIMEOUT = 5
STALE = 300  # seconds: a git operation in ~/.claude finishes well inside it


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


def age(seconds):
    """A duration as its largest whole unit: 7m, 16h, 3d."""
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{int(seconds // size)}{unit}"
    return f"{int(seconds)}s"


def wedge(clone, now):
    """Stale git locks and operations in progress in the clone, oldest
    first, as (path under .git, age, verb): verb is the git command whose
    --abort clears the path, or None for a lock, which is removed."""
    gitdir = os.path.join(clone, ".git")
    markers = dict(gitrun.IN_PROGRESS) if gitrun else {}
    found = []
    for root, dirs, files in os.walk(gitdir):
        if root == gitdir:
            dirs[:] = [d for d in dirs if d != "objects" and d not in markers]
        found += [(os.path.join(root, f), None) for f in files if f.endswith(".lock")]
    found += [(os.path.join(gitdir, m), verb) for m, verb in markers.items()
              if os.path.exists(os.path.join(gitdir, m))]
    stale = []
    for path, verb in found:
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if now - mtime > STALE:
            stale.append((mtime, os.path.relpath(path, gitdir), verb))
    return [(rel, age(now - m), verb) for m, rel, verb in sorted(stale)]


def unwedge(stuck):
    """The shell line that clears a wedge and fast-forwards: locks off
    first, since an --abort takes the index lock, then each abort once."""
    locks = [f"~/.claude/.git/{shlex.quote(rel)}" for rel, _, verb in stuck if not verb]
    steps = [f"rm {' '.join(locks)}"] if locks else []
    steps += [f"git -C ~/.claude {v} --abort" for v in dict.fromkeys(v for _, _, v in stuck if v)]
    return " && ".join(steps + ["git -C ~/.claude merge --ff-only origin/main"])


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
    stuck = wedge(clone, time.time())
    if not n and not skipped and not stuck:
        return
    lag = (f"~/.claude is {n} commit(s) behind origin/main" if n
           else "~/.claude was skipped by the last sync" if skipped else "")
    text = f"{lag}, so this session may run stale hooks and skills. " if lag else ""
    text += f"Last sync (`dotfiles-sync.sh --status`): {status or 'no output'}"
    if stuck:
        named = ", ".join(f".git/{rel} ({old} old)" for rel, old, _ in stuck)
        text = (f"~/.claude is wedged: {named}. No sync can move it until that is cleared; with no git "
                f"process running in ~/.claude, run `{unwedge(stuck)}`. {text}")
    import hookio  # lib/, on sys.path above
    hookio.emit(hookio.context("SessionStart", text, system=text), ascii=False)


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-sync-status", "SessionStart", main)
