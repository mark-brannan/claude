"""Shared helpers for the Python hooks. Imported, never run directly.

A shim: the state-dir lookup lives in lib/state.py, its one home
(dotfiles#517), and is re-exported here so the hooks that import lib_state
keep working unchanged. lib/ is found the way lib/libpath.py says.

Fails open: if lib/ is missing from both places (a seed whose INSTALL
lacks it) the import fails, state_repo and state_dir return None, and a
hook reads that as "no state here" and exits 0 rather than breaking; with
lib/hookio.py missing too, event() reads nothing and returns {}. A line on
stderr says why.
"""
import json
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

try:
    from state import state_dir, state_repo  # noqa: F401  (re-exported)
except ImportError as e:
    print(f"lib_state: lib/state.py not importable ({e}); no state dir", file=sys.stderr)

    def state_repo():
        return None

    def state_dir():
        return None

try:
    import hookio
except ImportError as e:
    print(f"lib_state: lib/hookio.py not importable ({e}); no hook input", file=sys.stderr)
    hookio = None


LAST = {}  # the event last read, so a trace can name its session after a crash


def event():
    """The hook's event JSON from stdin (lib/hookio.py), or {} when it is
    absent or malformed, or lib/ is missing."""
    data = hookio.read() if hookio else {}
    LAST.update(data)
    return data


def run_hook(hook, event, main):
    """A hook's whole __main__: run main, trace the error it did not
    catch under hook's name, exit 0 either way. A hook never blocks a
    call on its own bug; the trace is how the bug is seen."""
    try:
        main()
    except Exception as e:  # noqa: BLE001 -- fail open, by design
        trace_failure(hook, event, e)
    sys.exit(0)


def languette_root():
    """The user-scope languette install from installed_plugins.json, or ""."""
    path = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                        "plugins", "installed_plugins.json")
    try:
        with open(path, encoding="utf-8") as f:
            plugins = json.load(f)["plugins"]
        for key, installs in plugins.items():
            if key.startswith("languette@"):
                for i in installs:
                    if i.get("scope") == "user":
                        return i.get("installPath") or ""
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return ""


def trace_failure(hook, event, err, stage="main", once=False):
    """A hook's handler for an error it swallows: trace it through
    lib/hooktrace.py under the session last read, or say it on stderr when
    lib/ is missing from a seed. stage names where it was swallowed; "main"
    is the last-resort handler round the whole hook; once is hooktrace's.
    Never raises."""
    try:
        import hooktrace
        hooktrace.trace(hook, stage, err, str(LAST.get("session_id") or ""), event, once)
    except ImportError:
        print(f"{hook}: {err}", file=sys.stderr)
