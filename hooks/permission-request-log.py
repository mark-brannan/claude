#!/usr/bin/env python3
"""PermissionRequest: append one JSON line per permission dialog shown.

Why: an approved dialog leaves no trace in the transcript (only a declined
one does), so how often a session stops to ask cannot be counted after the
fact. This hook counts it as it happens. It decides nothing: it prints
nothing, so the dialog shows as it would have.

One line per request, in the state dir's
metrics/permission-requests/<session>.jsonl:
    {"ts": "2026-01-01T00:00:00Z", "session_id": "...", "cwd": "/home/u/repo",
     "permission_mode": "auto", "tool": "Bash",
     "input": {"command": "GH_TOKEN=<secret> git push"}, "masked": 1}

input is the tool's input with each string masked by languette's decision
record (record.mask, the detector guard-secrets uses, its built-in rules
only; a project's own rules are not read). A string that cannot be masked
cleanly is null, a string past MAX_CHARS is cut there after masking, and
when languette cannot be imported input is null: a record with a hole beats
one with a secret. masked counts the secrets replaced.

Fails open: any error exits 0 and the dialog is untouched.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

MAX_CHARS = 500


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


def languette_record():
    """languette's record module: the recorded install, else the interpreter's; None if neither."""
    roots = [r for r in (languette_root(),) if r] + [None]  # None: an installed package
    for root in roots:
        if root is not None:
            if not os.path.isfile(os.path.join(root, "languette", "record.py")):
                continue
            sys.path.insert(0, root)
        try:
            from languette import record
            return record
        except Exception:  # noqa: BLE001 -- a broken copy is skipped
            if root is not None:
                sys.path.remove(root)
            sys.modules.pop("languette", None)
    return None


def masked_input(ti, record):
    """(tool input with each string masked, secrets replaced) or (None, None)."""
    if record is None:
        return None, None
    n = 0

    def walk(v):
        nonlocal n
        if isinstance(v, str):
            text, k = record.mask(v)
            n += k
            return None if text is None else (text if len(text) <= MAX_CHARS else text[:MAX_CHARS] + "…")
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(ti), n


def line(ev, record, now):
    text, n = masked_input(ev.get("tool_input"), record)
    return {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": str(ev.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown"),
            "cwd": ev.get("cwd"), "permission_mode": ev.get("permission_mode"),
            "tool": ev.get("tool_name"), "input": text, "masked": n}


def main():
    import lib_state
    ev = lib_state.event()
    if not ev:
        return
    sd = lib_state.state_dir()
    if not sd:  # no state lib here (lib_state said why on stderr): nowhere to log
        return
    from state import state_shard_path
    rec = line(ev, languette_record(), datetime.now(timezone.utc))
    sid = rec["session_id"]
    path = state_shard_path(os.path.join(sd, "metrics", "permission-requests"), f"{sid}.jsonl", sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a logger never blocks a dialog
        print(f"permission-request-log: {e}", file=sys.stderr)
    sys.exit(0)
