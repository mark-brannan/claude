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
