"""A session known only by the start of its id (the sid8 a work-item log line,
a claim stamp or a lock line carries), read through lib/state.py's
holder_liveness.

The guard: dead is returned only for a session this machine's registry holds
an entry for, whose process is gone. A session the registry has no entry for
reads None (unseen), never dead: another machine's session has no entry here,
and neither has a running sub-agent, which the client does not register. The
caller falls back to the age of the holder's last mark and never frees an
unseen holder at once. None of the callers records a worktree or cwd to scan
/proc for, so the registry is the only local evidence there is.

CLAUDE_SESSIONS_DIR and CLAUDE_PROC_ROOT point the tools' tests at fixtures."""
import os

import state


def verdict(prefix, grace=0):
    """dead | live | parked | waiting, or None when the registry here holds no
    session whose id starts with prefix (the most held verdict when several)."""
    reg = os.environ.get("CLAUDE_SESSIONS_DIR") or state.sessions_dir()
    proc = os.environ.get("CLAUDE_PROC_ROOT") or "/proc"
    ids = {e["sessionId"] for e in state._registry(reg)
           if prefix and isinstance(e.get("sessionId"), str) and e["sessionId"].startswith(prefix)}
    best = None
    for i in ids:
        v = state.holder_liveness(i, grace, reg, proc)
        if best is None or state._LIVENESS_RANK[v] > state._LIVENESS_RANK[best]:
            best = v
    return best
