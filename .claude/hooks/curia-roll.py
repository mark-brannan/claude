#!/usr/bin/env python3
"""UserPromptSubmit: append the user's prompt, verbatim, to the roll of the
curia this session is sitting in.

The curia skill writes state/global/curia/<id>/LIVE at the start of a sitting,
holding the session id and a timestamp. A session named in some LIVE file is
sitting in that curia, and every prompt it receives is appended to that
folder's roll.md as one entry:

    ### 20261002t054107z
    ````
    <the prompt, byte for byte>
    ````

The fence is one backtick longer than the longest run of backticks in the
prompt (three at least), so a heading or a ``` inside the prompt stays inside
the entry. The heading is the bare stamp: UTC date and time to the second with
no separators and a lower-case `t` and `z`, so GitHub's anchor for the entry is
`#20261002t054107z` and a reference to it is `<curia>/roll.md#<stamp>`
(Solace, 2026-10-02; the session id was dropped from the heading the same
day). A newline is always added after the prompt before the closing fence:
strip exactly one to get the prompt back.

The prompt that opens a sitting, `/curia <id> ...`, arrives before the skill
writes LIVE, so it is matched by the id it names instead.

The roll is append-only (one-entry-point curia, 2026-10-02, the words log):
nothing here reads, edits or reorders what is already in it. Until a curia's
folder is moved to the roll/digest layout, roll.md is still the curated
document, so a folder without digest.md is skipped.

Always exits 0 and prints nothing: a roll failure must never block a prompt,
and UserPromptSubmit stdout would land in the model's context.
"""
import datetime
import fcntl
import glob
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_state  # noqa: E402


def entry(prompt, now):
    longest = max((len(r) for r in re.findall(r"`+", prompt)), default=0)
    fence = "`" * max(3, longest + 1)
    stamp = now.strftime("%Y%m%dt%H%M%Sz")
    return f"\n### {stamp}\n{fence}\n{prompt}\n{fence}\n"


def sittings(state_dir, session_id, prompt):
    """Every curia folder this prompt belongs to: the one a `/curia <id>`
    prompt opens, and each whose LIVE file names this session."""
    m = re.match(r"\s*/curia\s+([A-Za-z0-9][\w.-]*)", prompt)
    if m and os.path.isdir(os.path.join(state_dir, "curia", m.group(1))):
        yield os.path.join(state_dir, "curia", m.group(1))
    for live in sorted(glob.glob(os.path.join(state_dir, "curia", "*", "LIVE"))):
        try:
            with open(live, encoding="utf-8", errors="replace") as f:
                tokens = f.read().split()
        except OSError:
            continue
        if session_id in tokens:
            yield os.path.dirname(live)


def append(roll, text):
    # The whole entry under an exclusive lock: two sessions sitting in the
    # same curia on this machine interleave whole entries, never bytes.
    fd = os.open(roll, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = text.encode("utf-8", "surrogatepass")
        while data:
            data = data[os.write(fd, data):]
    finally:
        os.close(fd)


def main():
    ev = lib_state.event()
    session_id = ev.get("session_id")
    # The live 2.1.x payload names it `prompt`; the hooks reference page
    # names it `user_input`. Read both rather than bet on one.
    prompt = ev.get("prompt", ev.get("user_input"))
    if not isinstance(session_id, str) or not session_id or not isinstance(prompt, str):
        return
    state_dir = lib_state.state_dir()
    if not state_dir:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    # A set: a resumed session can both type `/curia <id>` and be in its LIVE.
    for folder in set(sittings(state_dir, session_id, prompt)):
        if os.path.isfile(os.path.join(folder, "digest.md")):
            append(os.path.join(folder, "roll.md"), entry(prompt, now))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 -- never block a prompt
        pass
    sys.exit(0)
