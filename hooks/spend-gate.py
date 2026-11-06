#!/usr/bin/env python3
# A runaway worker is bounded by context size and by spend: easy-grind/roll.md#20261022t074012z
"""PreToolUse, every tool: past a spend line or a context line, deny every tool
call but the hand-off write.

Why: a headless `claude -p` worker runs one turn for its whole job, so Stop
hooks never fire while it works, and every budget signal it gets is advisory
text. In claude#59 a worker saw its spend 255 times, up to $14.29 of $15, and
kept going. PreToolUse is the one channel that forces action mid-turn
(claude#69; tested 2026-10-07: the worker wrote its hand-off and ended its
turn one call after the line, for about a cent).

Inert unless a line is set in the environment, so it serves any driver that
sets one (grind sets it per worker at the item's soft cap):

    SPEND_GATE_USD       spend line in dollars, e.g. 5.00
    SPEND_GATE_TOKENS    context line in tokens, e.g. 600000
    SPEND_GATE_HANDOFF   the hand-off file's name (default HANDOFF.md)

Past either line, a Read or a Write of a file named SPEND_GATE_HANDOFF inside
the session's cwd is allowed and everything else is denied, Bash included. Read
is open because the Write tool refuses to overwrite a file the session has not
read, and a retried item starts with the last attempt's hand-off already on
disk (grind snapshots untracked files); without Read the retry could neither
read nor replace it. A line that is not a number is ignored, and traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).

In an interactive session the gate is just as blunt: the line comes from the
environment `claude` was launched from and cannot be lifted from inside (even
AskUserQuestion is denied), so the only way past it is to restart without the
line. A resumed session carries every earlier sitting's spend. A hand-off in
an additional working directory, outside the session's cwd, is denied.

The hook input carries no spend, so it is priced from the transcript:
assistant events deduplicated by message id (a message's content blocks each
arrive as an event carrying the same usage), each token class at the model's
price, the session's subagent transcripts included. A subagent's own tool
calls may name its transcript instead of the session's; that path is walked up
to the session's, so the spend judged is always the whole session's. Context
is the main transcript's last call: its input plus cache tokens.

Two failures, two answers; neither locks the hand-off out:
  - The hook runs but cannot read the transcript: it allows, and traces why
    to metrics/hook-errors/ (claude#69 names this case, claude#241 the trace). It has no figure to judge by,
    and --max-budget-usd stays the backstop.
  - The hook cannot run at all (file missing, python3 missing, a crash)
    while a line is set: the settings.json wrapper denies every call but the
    hand-off Write, the same exemption as here. The worker stops early with a
    hand-off -- cheap, and loud, since every worker blocks at once -- rather
    than running to its hard cap (3x the soft cap) unwatched, the claude#59
    shape this gate exists to end. With no line set, the wrapper allows.
"""
import json
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py


def measure(path):
    """(spend in USD, context tokens of the last call) for the session, its
    sub-agents included, priced by lib/claude_costing. Raises OSError if the
    main transcript cannot be read."""
    # Imported only once a line is set, so the gate stays inert without lib/;
    # past a line, a failed import crashes and the settings.json wrapper denies.
    import claude_costing
    return claude_costing.session_spend(path)


SEEN = {}  # the hook input once read, so a trace can name its session


def trace(stage, err):
    """Record an error the gate swallows to allow the call, through
    hooks/lib_state.py; stderr from a hook that exits 0 reaches no one. Once
    per session: each of these repeats on every tool call until fixed."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lib_state
    lib_state.LAST.update(SEEN)
    lib_state.trace_failure("spend-gate", "PreToolUse", err, stage, once=True)


def line_from_env(name, bad):
    """The line in env var name, or None; a value that is not a number is
    ignored and its error added to bad, for main to trace once the session
    is known."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        bad.append(ValueError(f"{name}={raw!r} is not a number; ignoring it"))
        return None
    return v if v > 0 else None


def is_handoff(file_path, cwd, handoff):
    """The hand-off file: named SPEND_GATE_HANDOFF and inside the session's
    cwd, so a Write to /etc/HANDOFF.md or ~/.ssh/HANDOFF.md is still denied."""
    if not file_path or not cwd or os.path.basename(str(file_path)) != handoff:
        return False
    root = os.path.realpath(cwd)
    target = os.path.realpath(os.path.join(root, str(file_path)))
    return os.path.commonpath([root, target]) == root


def fmt_tokens(n):
    return f"{n / 1000:.0f}k" if n >= 10000 else str(int(n))


def main():
    bad = []
    usd_line = line_from_env("SPEND_GATE_USD", bad)
    tok_line = line_from_env("SPEND_GATE_TOKENS", bad)
    if usd_line is None and tok_line is None and not bad:
        return 0
    handoff = os.environ.get("SPEND_GATE_HANDOFF", "").strip() or "HANDOFF.md"
    try:
        inp = json.load(sys.stdin)
    except ValueError as e:
        trace("input", ValueError(f"hook input is not JSON ({e}); allowing"))
        return 0
    if isinstance(inp, dict) and inp.get("session_id"):
        SEEN["session_id"] = inp["session_id"]
    for err in bad:
        trace("line", err)
    if usd_line is None and tok_line is None:
        return 0
    path = inp.get("transcript_path") or ""
    try:
        spend, ctx = measure(path)
    except OSError as e:
        trace("transcript", OSError(f"cannot read the transcript ({path or 'no path'}: "
                                    f"{e.strerror or e}); allowing"))
        return 0
    past_usd = usd_line is not None and spend >= usd_line
    past_tok = tok_line is not None and ctx >= tok_line
    if not (past_usd or past_tok):
        return 0
    ti = inp.get("tool_input") or {}
    if inp.get("tool_name") in ("Read", "Write") and is_handoff(ti.get("file_path"),
                                                                 inp.get("cwd"), handoff):
        return 0
    where = []
    if usd_line is not None:
        where.append(f"${spend:.2f} of ${usd_line:.2f} (spend)")
    if tok_line is not None:
        where.append(f"{fmt_tokens(ctx)} of {fmt_tokens(tok_line)} tokens (context)")
    reason = (f"Past the line: {' / '.join(where)}. Every tool is denied except a "
              f"Read or Write of {handoff}. Write the hand-off (what is done, what is "
              f"next, how to resume) there and end the turn.")
    # Imported here, past the line, so a seed without lib/ fails only where
    # a denial was due, and the settings.json wrapper denies in its place.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import lib_state  # noqa: F401  (puts lib/ on sys.path)
    import hookio
    hookio.emit(hookio.deny(reason))
    return 0


if __name__ == "__main__":
    sys.exit(main())
