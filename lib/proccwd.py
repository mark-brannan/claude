"""Which directories running processes sit in, for the prune tools that must
not delete one out from under a live shell. Imported, never run directly;
stdlib only.

Linux reads /proc/<pid>/cwd. macOS asks `lsof -a -d cwd -Fn`, best effort:
another user's processes are unseen. Anywhere neither works, live_cwds
returns None, and the caller removes nothing.
"""
import os
import shutil
import subprocess
import sys


def live_cwds(proc="/proc"):
    """Every running process's cwd, resolved, as a set; None when unreadable."""
    if os.path.islink(os.path.join(proc, "self", "cwd")):
        cwds = set()
        for pid in os.listdir(proc):
            if pid.isdigit():
                try:
                    cwds.add(os.readlink(os.path.join(proc, pid, "cwd")).removesuffix(" (deleted)"))
                except OSError:
                    pass
        return cwds
    if sys.platform == "darwin":
        try:
            p = subprocess.run([shutil.which("lsof") or "/usr/sbin/lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True,
                               text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        cwds = {l[1:] for l in p.stdout.splitlines() if l.startswith("n")}
        return cwds or None
    return None


def in_use(path, cwds):
    """True when some cwd is path or below it. Pass a resolved path: the
    cwds are resolved, so a path through a symlink never matches."""
    p = path.rstrip("/") + "/"
    return any(c == path or c.startswith(p) for c in cwds)
