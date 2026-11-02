#!/usr/bin/env python3
"""The takeover notice: a session that takes over a parked holder's branch,
card or work item tells the holder, and the holder's next prompt shows it.

Why: liveness is a process test, and an idle holder whose user has since
prompted elsewhere is parked and free to take over (git-stuff, 2026-11-02).
The taker tells the user in its own session; the holder learns of it here,
the next time anyone types in it, before it works the thing again.

  takeover-notice.py write <holder-sid> <what> [<link>]
      The picker's call. Appends one notice to the holder's file:
      what was taken, by this session (CLAUDE_CODE_SESSION_ID), when, the
      link. With a link it also moves the claim stamp, through claim-stamp's
      own card-release (the holder's) and card-claim (this session's); the
      exit is card-claim's, the notice is written either way.
  takeover-notice.py            UserPromptSubmit hook; JSON on stdin.
      In the holder's session: shows every pending notice once, to the model
      as additionalContext and to the user as systemMessage, then marks the
      file delivered by renaming it. Delivered files are pruned after 7 days
      by the writer, never here.

The file is $XDG_STATE_HOME/claude/takeover/<holder-sid>.jsonl, one JSON
object a line. Local, never the state repo: holder_liveness sees only this
machine, so a takeover it allowed has its holder here.

The hook runs on every prompt in every session, so the no-notice path is one
rename that fails: json, os and sys imported, nothing more, no network. It always
exits 0; a crash is traced to the state repo (lib/hooktrace.py).
"""
import json
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

HERE = os.path.dirname(os.path.realpath(__file__))
HOOK = "takeover-notice"


def notice_path(sid):
    """Every character outside [A-Za-z0-9_-] becomes _, so an id cannot leave
    the directory. The same substitution claim-stamp's record_path makes, but
    that one works on bytes and this on characters; no re here, it is an
    import the every-prompt path would pay for."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    safe = "".join(c if c.isascii() and (c.isalnum() or c in "_-") else "_" for c in sid)
    return f"{base}/claude/takeover/{safe}.jsonl"


def prune(directory, days=7):
    """Delete delivered notices older than `days`. Writer's path only; the
    per-prompt path never lists the directory."""
    import time
    cutoff = time.time() - days * 86400
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        if not name.endswith(".jsonl.delivered"):
            continue
        try:
            if os.stat(f"{directory}/{name}").st_mtime < cutoff:
                os.remove(f"{directory}/{name}")
        except OSError:
            pass


def write(holder, what, link=""):
    import subprocess
    import time
    taker = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not holder or not what or not taker or holder == taker:
        print("takeover-notice: write needs <holder-sid> <what> [<link>] and CLAUDE_CODE_SESSION_ID, "
              "and the holder must not be this session",
              file=sys.stderr)
        return 2
    path = notice_path(holder)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prune(os.path.dirname(path))
    row = {"what": what, "by": taker, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "link": link}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    print(path)
    if not link:
        return 0
    stamp = os.environ.get("TAKEOVER_CLAIM_STAMP") or f"{HERE}/claim-stamp.py"
    subprocess.run([sys.executable, stamp, "card-release", link, holder], stdout=subprocess.DEVNULL)
    return subprocess.run([sys.executable, stamp, "card-claim", link, taker]).returncode


def line(n):
    by = str(n.get("by", "?"))[:8]
    what = " ".join(str(n.get("what", "?")).split())
    link = f" ({' '.join(str(n['link']).split())})" if n.get("link") else ""
    return f"- {what}{link}: taken over by session `{by}` at {n.get('at', '?')}"


def prompt():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    sid = ev.get("session_id") if isinstance(ev, dict) else None
    if not isinstance(sid, str) or not sid:
        return 0
    path = notice_path(sid)
    try:
        os.replace(path, path + ".delivered")
    except FileNotFoundError:
        return 0
    with open(path + ".delivered", encoding="utf-8") as fh:
        rows = []
        for ln in fh:
            try:
                n = json.loads(ln)
            except ValueError:
                continue
            if isinstance(n, dict):
                rows.append(n)
    if not rows:
        return 0
    body = "\n".join(line(n) for n in rows)
    text = ("Takeover notice: while this session sat idle, another session took over work it held:\n"
            f"{body}\n"
            "This session no longer holds it. Do not push to it, claim it or resume it without "
            "asking the user first.")
    print(json.dumps({"systemMessage": text,
                      "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": text}}))
    return 0


def main(argv):
    if argv[:1] == ["write"]:
        return write(*(argv[1:4] + [""] * (3 - len(argv[1:4]))))
    if argv:
        print("usage: takeover-notice.py write <holder-sid> <what> [<link>]  (no args: hook, JSON on stdin)",
              file=sys.stderr)
        return 2
    try:
        return prompt()
    except Exception as e:  # noqa: BLE001 -- a notice must never block a prompt
        try:
            import hooktrace
            hooktrace.trace(HOOK, "prompt", e, event="UserPromptSubmit")
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
