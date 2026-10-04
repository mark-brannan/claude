"""An exclusive file lock, for the Python tools and hooks. Imported, never
run directly; stdlib only.

flock(2) on an open descriptor: the kernel drops it when the descriptor
closes or the process exits, so a killed writer never leaves a stale lock.
The one home for this helper (dotfiles#517); bin/agent-decision,
bin/work-item and hooks/curia-roll.py use it.
"""
import contextlib
import fcntl
import os
import time


def acquire(fd, wait=None):
    """Take an exclusive lock on fd. wait=None blocks until it is free;
    otherwise retry once a second for up to `wait` seconds. True when held."""
    if wait is None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return True
    for left in range(int(wait), -1, -1):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if left:
                time.sleep(1)
    return False


@contextlib.contextmanager
def locked(path, flags=os.O_RDWR | os.O_CREAT, mode=0o644):
    """Open path with flags, hold an exclusive lock, yield the descriptor,
    and close it (which releases the lock) on the way out."""
    fd = os.open(path, flags, mode)
    try:
        acquire(fd)
        yield fd
    finally:
        os.close(fd)
