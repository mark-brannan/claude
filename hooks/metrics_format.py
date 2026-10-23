"""Display text for the metrics readouts, as plain f-strings. Imported, never run.

jq parses the transcript; it does not write what you read on screen
(dotfiles#149). One function per field, so editing what you see is editing
an f-string here -- no jq program, no module include, no -L path. A field
with nothing to say returns "" rather than a zero or a "null".
"""


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
