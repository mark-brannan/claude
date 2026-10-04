"""Shared helpers for the Python hooks. Imported, never run directly.

A shim: the state-dir lookup lives in lib/state.py, its one home
(dotfiles#517), and is re-exported here so the hooks that import lib_state
keep working unchanged. lib/ sits beside hooks/ in a checkout and under
~/.claude alike.

Fails open: if lib/ is missing (a seed whose INSTALL lacks it) the import
fails, state_repo and state_dir return None, and a hook reads that as "no
state here" and exits 0 rather than breaking. One line on stderr says why.
"""
import json
import os
import sys

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "lib"))

try:
    from state import state_dir, state_repo  # noqa: F401  (re-exported)
except ImportError as e:
    print(f"lib_state: lib/state.py not importable ({e}); no state dir", file=sys.stderr)

    def state_repo():
        return None

    def state_dir():
        return None


def event():
    """The hook's event JSON from stdin, or {} when it is absent or malformed."""
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}
