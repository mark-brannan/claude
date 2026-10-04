"""Where durable state lives on this machine, for the Python tools and hooks.
Imported, never run directly; stdlib only.

The bash hooks' answer is lib-state.sh's state_repo. This module asks that
same function rather than keeping a second copy of its search path: two
lists would drift, and a Python tool would then write state somewhere the
bash hooks never read. lib/ sits beside hooks/ in a checkout and under
~/.claude alike, so ../hooks/lib-state.sh is the one source in both.

The one home for this lookup (dotfiles#517). hooks/lib_state.py re-exports
it; bin tools put this directory on sys.path and `import state`.
"""
import os
import subprocess

LIB_STATE_SH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "hooks", "lib-state.sh")


def _lib(fn):
    """Run one lib-state.sh function and return what it printed, or None."""
    try:
        out = subprocess.run(["bash", "-c", '. "$1" && ' + fn, "_", LIB_STATE_SH],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 and out.stdout else None


def state_repo():
    """The private state repo's working tree, or None if it isn't here."""
    return _lib("state_repo")


def state_dir():
    """Where state files go: the repo's state/global, else lib-state.sh's
    local fallback. None only if bash or lib-state.sh could not run."""
    return _lib("state_dir")
