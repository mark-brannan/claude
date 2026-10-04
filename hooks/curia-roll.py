#!/usr/bin/env python3
# SOFT SHOULD: id generation belongs in lib/ids.py, the one home for every
# entity's id (card 17910884757abba648). This script still makes a roll-entry stamp itself;
# move it there when convenient, no deadline.
"""UserPromptSubmit, PostToolUse(AskUserQuestion): append the user's words, verbatim, to the roll of the
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
writes LIVE, so it is matched by the id it names instead. Task notifications
and agent messages also fire UserPromptSubmit and stay out. A dialog's
free-text answers and notes are one entry; a picked label stays out, and so
does the harness's answer to a dismissed dialog.

The app attaches its own notices to a prompt as leading <system-reminder>
blocks (the worktree notice, the fork notice). Those are not the user's words:
they are stripped, with the newlines after them, by the same pattern as
build-roll.py's HARNESS, so the live roll and a rebuilt one agree. A prompt
that is blank once they are gone writes nothing.

The roll is append-only (one-entry-point curia, 2026-10-02, the words log),
save that words sharing a stamp are one entry, joined by a blank line, as
build-roll.py merges them (Solace, 2026-10-02). Until a curia's
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


AGENT_TEXT = ("<task-notification>", "<agent-message", "Another Claude session sent a message:")
# Keep in step with HARNESS in state/global/curia/build-roll.py.
HARNESS = re.compile(
    r"<system-reminder>\n(?:You are operating in a git worktree\.|This conversation was forked from)"
    r".*?</system-reminder>\n*",
    re.S,
)


# What the harness puts in place of an answer when the user dismisses a dialog.
# Keep in step with DISMISSED in state/global/transcript-archive/extract.py.
DISMISSED = "[User dismissed — do not proceed, wait for next instruction]"


def strip_harness(text):
    """The text without its leading harness reminders, as build-roll.py's words()."""
    while (m := HARNESS.match(text)):
        text = text[m.end():]
    return text


def entry(prompt, now):
    longest = max((len(r) for r in re.findall(r"`+", prompt)), default=0)
    fence = "`" * max(3, longest + 1)
    stamp = now.strftime("%Y%m%dt%H%M%Sz")
    return f"\n### {stamp}\n{fence}\n{prompt}\n{fence}\n"


def dialog_words(questions, answers, annotations=None):
    words = []
    for q in questions or []:
        labels = {o.get("label") for o in q.get("options") or []}
        a, ann = ((d or {}).get(q.get("question")) for d in (answers, annotations))
        if a == DISMISSED:  # whole answer only: the sentence holds a ", ", so no split
            a = ""
        if isinstance(a, str):  # a multi-select keeps only its typed parts
            a = ", ".join(p for p in a.split(", ") if p not in labels) if q.get("multiSelect") else "" if a in labels else a
        note = ann.get("notes") if isinstance(ann, dict) else None
        words += [w for w in (a, note) if isinstance(w, str) and w.strip()]
    return "\n\n".join(words)


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


def append(roll, prompt, now):
    # The whole entry under an exclusive lock: two sessions sitting in the
    # same curia on this machine interleave whole entries, never bytes. The
    # last entry, if it has this stamp, is overwritten in place with both
    # words: longer, and the same bytes up to them unless the fence widens,
    # so a kill mid-write keeps them. A stamp quoted in words is no heading.
    text = entry(prompt, now)
    fd = os.open(roll, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        old = os.pread(fd, os.fstat(fd).st_size, 0)
        at = len(old)
        m = re.search(rb"\n### (\d{8}t\d{6}z)\n(`{3,})\n((?:(?!\n\2\n).)*)\n\2\n\Z", old, re.S)
        if m and text.startswith(f"\n### {m.group(1).decode()}\n"):
            try:  # an undecodable entry, never this hook's, is appended after
                text, at = entry(m.group(3).decode("utf-8", "surrogatepass") + "\n\n" + prompt, now), m.start()
            except UnicodeDecodeError:
                pass
        data = text.encode("utf-8", "surrogatepass")
        while data:
            n = os.pwrite(fd, data, at)
            data, at = data[n:], at + n
    finally:
        os.close(fd)


def main():
    ev = lib_state.event()
    session_id = ev.get("session_id")
    # The live 2.1.x payload names it `prompt`; the hooks reference page
    # names it `user_input`. Read both rather than bet on one.
    prompt = ev.get("prompt", ev.get("user_input"))
    if ev.get("tool_name") == "AskUserQuestion":  # answers on input or result
        got = {k: v for p in (ev.get("tool_input"), ev.get("tool_response")) if isinstance(p, dict) for k, v in p.items() if v}
        prompt = dialog_words(got.get("questions"), got.get("answers"), got.get("annotations")) or None
    elif isinstance(prompt, str):
        prompt = strip_harness(prompt)
        if prompt.lstrip().startswith(AGENT_TEXT) or not prompt.strip():
            return
    if not isinstance(session_id, str) or not session_id or not isinstance(prompt, str):
        return
    state_dir = lib_state.state_dir()
    if not state_dir:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    # A set: a resumed session can both type `/curia <id>` and be in its LIVE.
    opener = "" if ev.get("tool_name") else prompt
    for folder in set(sittings(state_dir, session_id, opener)):
        if os.path.isfile(os.path.join(folder, "digest.md")):
            append(os.path.join(folder, "roll.md"), prompt, now)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 -- never block a prompt
        pass
    sys.exit(0)
