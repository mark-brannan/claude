"""The one home for making identifiers, for every entity (work items,
roll stamps, and the rest). Imported, never run directly; stdlib only.

Holds the roll stamp and the work item's id. bin/card-id (shell) is the
command line over both and makes no id of its own; the other entities' id
code follows here, so no tool formats an id of its own. Name functions with
get / create / new, never mint (a concept for prose, not an identifier).
Card 17910884757abba648.

A work item's id is epoch seconds then the creating session's eight hex, no
separator (1790836842077c62eb), never edited, never reused; the shape is the
record's (docs/work-item-lifecycle.md, "The identifier"). The one collision
the shape allows is one session asking twice in the same second, and
new_item_id closes it without touching the shape: the seconds in the id are
the clock, or the next second past this session's last id when the clock has
not moved on (a burst of seven in one second takes seven consecutive seconds
of this session's id space; nothing reads the id as a time). The last second
handed out is one integer per session in a per-user state dir, read and
advanced under lib/lock.py's flock so two processes of one session never
get the same one. Nothing else is kept: no list of ids, no sweep.
"""
import os

import lock


def get_roll_stamp(now):
    """The curia roll's entry stamp for a datetime: UTC to the second, as
    `20261002t054107z`. The caller passes an aware UTC time."""
    return now.strftime("%Y%m%dt%H%M%Sz")


def session_hex(sid):
    """The eight hex a work item's id carries for a session: the session id
    with its dashes dropped, cut to eight, lowercased; '' when what is left
    is not eight hex (no session, or not a session id)."""
    h = (sid or "").replace("-", "")[:8].lower()
    return h if len(h) == 8 and all(c in "0123456789abcdef" for c in h) else ""


def card_id_state_dir(env=None):
    """Where the per-session counters live: $CARD_ID_STATE, else
    $XDG_STATE_HOME/card-id, else ~/.local/state/card-id. Per user by
    construction, never a shared tmp dir."""
    env = os.environ if env is None else env
    if env.get("CARD_ID_STATE"):
        return env["CARD_ID_STATE"]
    base = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "card-id")


def new_item_id(hex8, now, items_dir, state_dir):
    """A fresh work item id for the session whose eight hex is hex8, at epoch
    second `now`, free in the store at items_dir and never handed to this
    session before. Returns (id, note): note is '' when the counter under
    state_dir was consulted and advanced, else one line saying why it was
    not (the dir could not be made, locked or written), in which case the id
    is only stepped past the store, as before the counter existed."""
    t = int(now)

    def step_past_store(t):
        while os.path.exists(os.path.join(items_dir, f"{t}{hex8}.md")):
            t += 1
        return t

    counter = os.path.join(state_dir, f"last.{hex8}")
    try:
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        with lock.locked(counter, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600) as fd:
            have = os.read(fd, 32).strip()
            last = int(have) if have.isdigit() else 0
            t = step_past_store(max(t, last + 1))
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, f"{t}\n".encode())
        return f"{t}{hex8}", ""
    except OSError as e:
        return f"{step_past_store(t)}{hex8}", f"no counter at {counter} ({e.strerror or e}); stepped past the store only"
