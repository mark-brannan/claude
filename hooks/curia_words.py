"""What counts as the user's words in a curia roll, in one place. Imported, never run.

The live hook (curia-roll.py) and the state repo's rebuild of a roll from
transcripts both apply these filters and write and read this entry format, so
they import it rather than keep copies that drift apart. The dependency runs
one way: private state code imports this public module, never the reverse.

Pure: no I/O, no clock, no lib/. The hook supplies the stamp.
"""
import re

# Not the user's words, as the text of a prompt begins.
AGENT_TEXT = ("<task-notification>", "<agent-message", "Another Claude session sent a message:")

# The app's own notices (the worktree notice, the fork notice), attached to a
# prompt as leading <system-reminder> blocks, with the newlines after them.
HARNESS = re.compile(
    r"<system-reminder>\n(?:You are operating in a git worktree\.|This conversation was forked from)"
    r".*?</system-reminder>\n*",
    re.S,
)

# What the harness puts in place of an answer when the user dismisses a dialog.
DISMISSED = "[User dismissed — do not proceed, wait for next instruction]"

# One entry of a roll: a stamp heading, then the words in a fence one backtick
# longer than any run inside them (three at least).
ENTRY = re.compile(r"\n### (\d{8}t\d{6}z)\n(`{3,})\n(.*?)\n\2\n", re.S)
# The same, as bytes and anchored to the end of a roll: its last entry. A
# fence line inside the words never ends them (the lookahead).
LAST_ENTRY = re.compile(rb"\n### (\d{8}t\d{6}z)\n(`{3,})\n((?:(?!\n\2\n).)*)\n\2\n\Z", re.S)


def strip_harness(text):
    """The text without its leading harness reminders."""
    while (m := HARNESS.match(text)):
        text = text[m.end():]
    return text


def is_agent_text(text):
    return text.lstrip().startswith(AGENT_TEXT)


def entry(prompt, stamp):
    """The roll entry for these words under this stamp."""
    longest = max((len(r) for r in re.findall(r"`+", prompt)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"\n### {stamp}\n{fence}\n{prompt}\n{fence}\n"


def last_entry(roll):
    """(start offset, stamp, words) of a roll's last entry, from its bytes, or None."""
    m = LAST_ENTRY.search(roll)
    return (m.start(), m.group(1).decode(), m.group(3)) if m else None
