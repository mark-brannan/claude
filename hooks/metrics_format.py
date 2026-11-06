"""Display text for the metrics readouts, as plain f-strings. Imported, never run.

jq parses the transcript; it does not write what you read on screen
(dotfiles#149). One function per field, so editing what you see is editing
an f-string here -- no jq program, no module include, no -L path. A field
with nothing to say returns "" rather than a zero or a "null".
"""
import math


def fmt_turns(turns=0, tools=0):
    """"⇢ 7 ⚙ 42" -- human turns, then tool calls. Never empty: the counts
    are the part of the turns line that always has a value."""
    return f"⇢ {turns or 0} ⚙ {tools or 0}"


def fmt_work(commits=0, dirty=0, unpushed=0):
    """"⎇ 2c3~1↑unpushed  ← not safe to kill" -- commits, dirty files, unpushed.
    Empty on a clean tree, where "0c/0~/0↑" is the common case and says
    nothing. The kill warning rides on unpushed alone: that is the one state
    closing the chat loses work from."""
    s = ""
    if commits and commits > 0:
        s += f"{commits}c"
    if dirty and dirty > 0:
        s += f"{dirty}~"
    if unpushed and unpushed > 0:
        s += f"{unpushed}↑unpushed  ← not safe to kill"
    return f"⎇ {s}" if s else ""


def fmt_usd(cost):
    """"$2.39" -- the session's estimated cost in dollars, sub-agents
    included. Cents below $100, whole dollars from there, where cents are
    noise; "<$0.01" for a cost that rounds to no cents, so a priced session
    never reads as free. Empty when the cache carries no number, so a cache
    from before the field drops it rather than printing "$None".
    Rounds half away from zero, as jq's `round` does: the `usd` def in
    lib-metrics-fmt.jq must print the same bytes."""
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return ""
    if cost <= 0:
        return "$0.00"
    cents = math.floor(cost * 100 + 0.5)
    if cents == 0:
        return "<$0.01"
    if cents >= 10000:
        return f"${math.floor(cost + 0.5)}"
    return f"${cents // 100}.{cents % 100:02d}"


FIG = "\u2007"  # figure space: one digit wide, so a padded figure keeps its column


def compact(n):
    """"1.2k", "12k", "1.2M": a figure past its fixed width, at that width."""
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if n >= div:
            v = n / div
            if v < 9.95:  # :.1f would round 9.95..9.99 up to "10.0", a column too wide
                return f"{v:.1f}{unit}"
            return f"{10 if v < 10 else int(v)}{unit}"
    return str(int(n))


def fmt_usd_fixed(cost):
    """"$  2.39" -- the event block's dollars, cents at every size, padded
    with figure spaces to seven columns; blank at that width with no number."""
    if isinstance(cost, bool) or not isinstance(cost, (int, float)):
        return FIG * 7
    cents = max(0, math.floor(cost * 100 + 0.5))
    if cost > 0 and cents == 0:
        return "<$0.01".rjust(7, FIG)
    body = f"{cents // 100}.{cents % 100:02d}" if cents < 100000 else compact(cents / 100)
    return "$" + body.rjust(6, FIG)


def fmt_tokens_fixed(n):
    """" 46k" -- a token count in four columns: 999k, then 1.2M."""
    n = int(n or 0)
    s = str(n) if n < 1000 else f"{n // 1000}k" if n < 1_000_000 else compact(n)
    return s.rjust(4, FIG)
