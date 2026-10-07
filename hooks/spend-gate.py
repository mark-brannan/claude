#!/usr/bin/env python3
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

Past either line, a Write whose file_path basename is SPEND_GATE_HANDOFF is
allowed and everything else is denied, Bash included. A line that is not a
number is ignored, with a note on stderr.

The hook input carries no spend, so it is priced from the transcript:
assistant events deduplicated by message id (a message's content blocks each
arrive as an event carrying the same usage), each token class at the model's
price. Context is the last call's input plus cache tokens.

Two failures, two answers; neither locks the hand-off out:
  - The hook runs but cannot read the transcript: it allows, with a one-line
    note on stderr (claude#69 names this case). It has no figure to judge by,
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

# Dollars per 1M tokens, by model name substring; unrecognised names price as
# Sonnet. The same base prices as bin/grind's model_price_in/model_price_out
# (its live heartbeat estimate) -- change both together. Cache reads are 0.1x
# input; cache writes 1.25x for the 5-minute cache and 2x for the 1-hour one,
# which is what Claude Code writes by default: the claude#69 test run's
# total_cost_usd ($0.41907) reproduces to the cent at these figures.
PRICES = (
    ("opus", 5.00, 25.00),
    ("fable", 10.00, 50.00),
    ("mythos", 10.00, 50.00),
    ("haiku", 1.00, 5.00),
)
SONNET = (2.00, 10.00)
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens", "cache_5m", "cache_1h")


def price_of(model):
    for key, pin, pout in PRICES:
        if key in (model or ""):
            return pin, pout
    return SONNET


def measure(path):
    """(spend in USD, context tokens of the last call) from a transcript.

    Raises OSError if the transcript cannot be read."""
    msgs = {}
    with open(path, "rb") as f:
        for line in f:
            # Cheap prefilter: most lines are tool results and user turns.
            if b'"assistant"' not in line or b'"usage"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "assistant":
                continue
            m = e.get("message") or {}
            u = m.get("usage") or {}
            mid = m.get("id") or e.get("uuid")
            cur = msgs.get(mid)
            if cur is None:
                cur = msgs[mid] = dict.fromkeys(FIELDS, 0)
                cur["model"] = m.get("model") or ""
            split = u.get("cache_creation") or {}
            vals = {
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "cache_read_input_tokens": u.get("cache_read_input_tokens"),
                "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
                "cache_5m": split.get("ephemeral_5m_input_tokens"),
                "cache_1h": split.get("ephemeral_1h_input_tokens"),
            }
            for k, v in vals.items():
                if isinstance(v, (int, float)) and v > cur[k]:
                    cur[k] = v
    spend = 0.0
    ctx = 0
    for u in msgs.values():  # dicts keep insertion order: the last is newest
        pin, pout = price_of(u["model"])
        write = u["cache_creation_input_tokens"]
        w1h = min(u["cache_1h"], write)
        w5m = write - w1h  # unsplit writes price as the 5-minute cache
        spend += (u["input_tokens"] * pin + u["output_tokens"] * pout
                  + u["cache_read_input_tokens"] * pin * 0.1
                  + w5m * pin * 1.25 + w1h * pin * 2.0)
        ctx = u["input_tokens"] + u["cache_read_input_tokens"] + write
    return spend / 1e6, ctx


def line_from_env(name):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
    except ValueError:
        print(f"spend-gate: {name}={raw!r} is not a number; ignoring it", file=sys.stderr)
        return None
    return v if v > 0 else None


def fmt_tokens(n):
    return f"{n / 1000:.0f}k" if n >= 10000 else str(int(n))


def main():
    usd_line = line_from_env("SPEND_GATE_USD")
    tok_line = line_from_env("SPEND_GATE_TOKENS")
    if usd_line is None and tok_line is None:
        return 0
    handoff = os.environ.get("SPEND_GATE_HANDOFF", "").strip() or "HANDOFF.md"
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        print("spend-gate: hook input is not JSON; allowing", file=sys.stderr)
        return 0
    path = inp.get("transcript_path") or ""
    try:
        spend, ctx = measure(path)
    except OSError as e:
        print(f"spend-gate: cannot read the transcript ({path or 'no path'}: "
              f"{e.strerror or e}); allowing", file=sys.stderr)
        return 0
    past_usd = usd_line is not None and spend >= usd_line
    past_tok = tok_line is not None and ctx >= tok_line
    if not (past_usd or past_tok):
        return 0
    ti = inp.get("tool_input") or {}
    if inp.get("tool_name") == "Write" and \
            os.path.basename(str(ti.get("file_path") or "")) == handoff:
        return 0
    where = []
    if usd_line is not None:
        where.append(f"${spend:.2f} of ${usd_line:.2f} (spend)")
    if tok_line is not None:
        where.append(f"{fmt_tokens(ctx)} of {fmt_tokens(tok_line)} tokens (context)")
    reason = (f"Past the line: {' / '.join(where)}. Every tool is denied except one "
              f"Write to {handoff}. Write the hand-off (what is done, what is next, "
              f"how to resume) there and end the turn.")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
