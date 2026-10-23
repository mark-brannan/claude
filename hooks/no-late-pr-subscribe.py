#!/usr/bin/env python3
"""Blocks subscribe_pr_activity once this session's context has grown past the
point where watching is cheaper than starting fresh.

Why: subscribing is free while idle, but every wake re-sends the session's
whole accumulated context as cache-read input, and the session only grows
from there. A watcher armed at 30k tokens is cheap; the same watcher armed
at 150k pays that 150k back on every comment, every check, for the life of
the PR. Past the threshold the fire-and-forget path is strictly cheaper:
push, open the PR, end the turn, archive the chat, pick the PR up fresh.

This is the enforcement half of the "Babysitting a PR is cheap; polling for
it is not" rule in ~/.claude/rules/code.md, which was prose-only and so was
only followed when it happened to be in context.

The threshold is a fraction of the window, not a fixed 100k, because a fixed
number means different things on different plans: 100k is 50% of the default
200k window but 10% of the 1M window Opus auto-upgrades to on Max, where it
would refuse watching for no reason. 60% is the number:
  - a realistic wake costs 5-15k (event payload, CI logs, diff, a fix turn),
    so 40% headroom on a 200k window is roughly 6-10 wakes
  - cloud/web sessions -- exactly the class that subscribes to PR activity --
    compact as they *approach* the limit rather than at it, and what
    compaction drops is the reasoning behind the diff under review
  - prompt cache lives 1h on a subscription; PR events routinely arrive
    further apart than that, so a large share of wakes are cache misses that
    reprocess the whole context at ~10x the cached rate
Plus a hard floor: never subscribe with less than 60k of headroom, whatever
the window, so the fraction cannot authorize a watch that has no room to run.
Sources: code.claude.com/docs/en/{model-config,costs,context-window}.

Token count is not passed to hooks directly. It is derived the same way
statusline-metrics.py derives it: the last assistant `usage` block in the
transcript, whose input + cache_read + cache_creation is the context that
request actually carried. Only the tail is scanned -- transcripts run to
tens of MB and the newest usage record is always near the end.
"""
import collections
import json
import os
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402,F401  (puts lib/ on sys.path)
import hookio  # noqa: E402


def env_int(name, default):
    """The env var as an int; the default when unset or empty."""
    v = os.environ.get(name, "")
    return int(v) if v != "" else default


def limit():
    """(tokens, basis): the threshold and the words saying where it came from."""
    # Override any of these per-session. WINDOW must be raised by hand for a 1M
    # session -- the hook payload does not carry the model's context window.
    # An explicit absolute limit wins outright, before the other vars are parsed,
    # so a malformed WINDOW cannot mask a valid TOKEN_LIMIT (as in the old .sh).
    if os.environ.get("CLAUDE_PR_WATCH_TOKEN_LIMIT"):
        return int(os.environ["CLAUDE_PR_WATCH_TOKEN_LIMIT"]), ""
    window = env_int("CLAUDE_PR_WATCH_CONTEXT_WINDOW", 200000)
    percent = env_int("CLAUDE_PR_WATCH_CONTEXT_PERCENT", 60)
    floor = env_int("CLAUDE_PR_WATCH_MIN_HEADROOM", 60000)
    # Whichever binds first: the fraction, or the headroom floor.
    lim = min(window * percent // 100, window - floor)
    return lim, f" ({percent}% of a {window // 1000}k window)"


def context_tokens(transcript):
    """The largest input + cache_read + cache_creation among the assistant
    usage blocks in the transcript's last 500 lines (0 when there are none).
    Raises OSError/ValueError/TypeError when unreadable; main() fails open."""
    with open(transcript, "rb") as f:
        tail = collections.deque(f, 500)
    best = 0
    for line in tail:
        if not line.strip():
            continue
        rec = json.loads(line)
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        msg = rec.get("message")
        usage = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(usage, dict):
            continue
        best = max(best, sum(usage.get(k) or 0 for k in
                             ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
    return best


def main():
    try:
        lim, basis = limit()
    except ValueError:
        return 0
    if lim <= 0:
        return 0
    transcript = hookio.read().get("transcript_path") or ""
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        return 0
    try:
        ctx = context_tokens(transcript)
    except (OSError, ValueError, TypeError):
        return 0  # fail open: no measurement, no block
    if not isinstance(ctx, int) or ctx < lim:
        return 0
    k, limk = ctx // 1000, lim // 1000
    hookio.emit(hookio.deny(
        f"Blocked by ~/.claude/hooks/no-late-pr-subscribe.py: this session is at ~{k}k tokens, "
        f"at or over the ~{limk}k watch threshold{basis}. Every wake on this subscription would "
        "re-send that whole context, and it only grows from here. Take the fire-and-forget path "
        "instead: push, open the PR, then end the turn with the follow-up prompt that would "
        f'continue the work, plus "You should archive this chat now. It\'s at ~{k}k tokens." '
        "No webhook, no wake -- pick the PR up fresh in a new session."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
