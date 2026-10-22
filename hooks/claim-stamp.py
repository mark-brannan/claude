#!/usr/bin/env python3
"""Writes, refreshes and removes the session claim stamp on a branch's card --
the open PR, or the open issue that names the branch. One comment, one
session, visible to every machine.

Why a remote stamp: nothing else says which session holds a branch in a way
a second machine can see. The languette plugin's `guard-worktrees` and
`branch_brief` see local worktrees only, so two sessions on two machines could
both pick up the same branch and neither would know until a push was rejected.
2026-09-22 (dotfiles#287): stamp the card itself, so an accidental parallel
session is visible at open, and anything deciding whether a branch is free
has a remote claim to read rather than a clock to guess from. Supersedes the
local-heartbeat shape proposed in dotfiles#167.

The stamp is a comment, not an edit to the body. A body edit races with
humans and with Mergify's `Depends-On:` header, and clobbering prose to say
"someone is working here" is a bad trade; a comment is addressable by id,
patched in place rather than re-posted, and deleted outright on release.

One comment per session, keyed by session id in the marker. Two sessions on
one card therefore leave two stamps -- which is the truth, and the exact
state this exists to make visible. The second one prints a warning naming
the first.

CONVENIENCE, NOT A GATE: every path but the card claim exits 0. No gh, gh
unauthenticated, no card, a failed API call -- all are silent no-ops. A
session must never be unable to start or end because a claim could not be
written. The gates (branch-home-gate.py here, the languette plugin's
guard-private-terms) fail closed; this one does not, deliberately. A crash
is traced to the state repo's metrics/hook-errors/ (lib/hooktrace.py).

Never runs under CI: the shared PR reviewer runs Claude Code inside GitHub
Actions with these hooks seeded from main, and a bot's checkout holds no
claim on anything.

Usage:
  claim-stamp.py claim   [-C <dir>] <session-id>   warn if held, then stamp
  claim-stamp.py refresh [-C <dir>] <session-id>   bump this session's stamp
  claim-stamp.py release [-C <dir>] [--scan] <session-id>
                                                   delete this session's stamp
  claim-stamp.py read    [-C <dir>] [<url>]        print every stamp on the card,
                                                   the branch's or <url>'s:
      live|stale <sid8> <machine> <age>m <url>, one tab-separated line each;
      `free <url>` when the card has none; `no card`; or
      `unverified: <why>` when the stamps could not be read
  claim-stamp.py session-start                     SessionStart hook; JSON on stdin
  claim-stamp.py card-claim <url> <session-id>     claim a board card by its link;
      refuses, exit 1, while another session's claim on it is live
  claim-stamp.py card-release <url> [<session-id>] drop one session's claim, or all
  claim-stamp.py card-claims [<url>]               every card claim, `read`'s shape

`refresh` is the one called on every Stop, so it must be free when there is
nothing to refresh: it reads a per-session record under TMPDIR and returns
without a single network call when this session has not claimed anything.
When it has, the refresh is debounced to once per CLAIM_REFRESH_SECS.

PROPOSED, NOT RULED (dotfiles#287): a stamp older than CLAIM_STALE_SECS
(default 2h) is stale -- its session died without releasing it. `claim`
deletes stale stamps it finds, which is the only garbage collection there
is; nothing else ever removes a comment a dead session left. Age is taken
from the epoch in the stamp's own marker, never from the comment's
updated_at: the stamp is the truth, the comment metadata is not.

Ported from claim-stamp.sh (claude#213). The stamp's marker, the per-session
record, the card ledger's files and every subcommand's output are the
shell's, byte for byte, so bin/ readers and claims written before the port
still parse.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

HERE = os.path.dirname(os.path.realpath(__file__))
HOOK = "claim-stamp"
MARKER = "<!-- claim-stamp"

# The marker's fields, read by gh's own jq, so a reader needs nothing local.
# Everything a caller needs to judge a claim comes out of the marker, so no
# consumer has to parse the human line.
STAMPS_JQ = '''
    .[] | select(.body | test("<!-- claim-stamp "))
    | [ (.id|tostring)
      , ((.body | capture("sid=(?<v>[A-Za-z0-9_-]+)").v) // "?")
      , ((.body | capture("epoch=(?<v>[0-9]+)").v) // "0")
      , ((.body | capture("machine=(?<v>[A-Za-z0-9_-]+)").v) // "?")
      ] | @tsv'''

# Bounded, always. A hook that hangs on a network call is worse than one that
# does nothing: SessionStart holds the first prompt and Stop holds the turn.
TIMEOUT = 25


def _int_env(name, default):
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


STALE_SECS = _int_env("CLAIM_STALE_SECS", 7200)
REFRESH_SECS = _int_env("CLAIM_REFRESH_SECS", 300)
LABEL = os.environ.get("CLAIM_LABEL") or "claimed"


def now_epoch():
    return int(time.time())


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def tdiv(a, b):
    """Shell arithmetic's a / b: truncated toward zero."""
    q = abs(a) // b
    return q if a >= 0 else -q


def run(argv, stdin=None, cwd=None):
    """(ok, stdout as $(...) captures it). Never raises: a missing tool, a
    timeout or a non-zero exit is not ok."""
    try:
        p = subprocess.run(argv, input=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           cwd=cwd, timeout=TIMEOUT,
                           stdin=None if stdin is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, ""
    return p.returncode == 0, p.stdout.decode("utf-8", "surrogateescape").rstrip("\n")


def machine_id():
    """An opaque, stable per-machine token. A GitHub comment on a public repo
    is a publish, and real hostnames stay out of published text -- so the
    stamp carries a hash of the hostname, which distinguishes two machines
    without naming either."""
    try:
        h = socket.gethostname() or os.uname().nodename
    except OSError:
        h = "unknown"
    return "host-" + hashlib.sha256(h.encode("utf-8", "surrogateescape")).hexdigest()[:6]


def record_path(sid):
    """Per-session record: the card this session claimed, the comment it owns
    and when it last refreshed. Under TMPDIR, never under the state dir --
    stop-continuity.py commits and pushes that, so a per-session file there
    would be repo churn in every session (the convention branch-home-gate.py
    and pr-ownership-context.py already use). The name is tr -c's: every
    byte outside [A-Za-z0-9_-] becomes one _."""
    safe = re.sub(rb"[^A-Za-z0-9_-]", b"_", sid.encode("utf-8", "surrogateescape"))
    return f"{os.environ.get('TMPDIR') or '/tmp'}/claude-claim-stamp.{safe.decode()}"


def sid8(sid):
    return sid[:8]


def ifs_read(text, n):
    """`IFS=<tab> read -r v1 .. vn` over text's first line: (fields, ok).
    Tab is IFS whitespace, so runs of tabs are one separator and the ends are
    trimmed; the last field keeps the rest of the line. ok is read's status:
    false when the line has no newline."""
    line, nl, _ = text.partition("\n")
    line = line.strip("\t")
    parts = re.split(r"\t+", line, maxsplit=n - 1) if line else []
    parts += [""] * (n - len(parts))
    return parts, bool(nl)


def read_file(path):
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            return fh.read()
    except OSError:
        return None


def write_file(path, text):
    try:
        with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            fh.write(text)
        return True
    except OSError:
        return False


def rm(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


# ---------------------------------------------------------------- the card
def card_of(d):
    """`pr <url>`, `issue <url>`, `none`, or `unverified: <why>` --
    branch-home-gate.py owns the lookup, so a claim and the Stop gate can
    never disagree about which card a branch belongs to. It is read-only in
    this mode and touches no marker."""
    return run(["python3", f"{HERE}/branch-home-gate.py", "--card", d])[1]


def card_url(card):
    """The URL out of a `pr <url>` or `issue <url>` answer, else None."""
    if card.startswith("pr ") or card.startswith("issue "):
        return card.split(" ", 1)[1]
    return None


_URL = re.compile(r"^https?://[^/]+/([^/]+)/([^/]+)/(pull|issues)/([0-9]+)([/?].*)?$")


def card_parts(url):
    """(owner, repo, number) from a github.com issue or pull URL, else None.
    Both kinds of card take comments at the same endpoint,
    repos/O/R/issues/N/comments, so nothing below needs to know which."""
    m = _URL.match(url or "")
    return (m.group(1), m.group(2), m.group(4)) if m else None


# --------------------------------------------------------------- the stamp
def read_stamps(owner, repo, number):
    """(ok, [(id, sid8, epoch, machine), ...]). Not ok when the read failed:
    that must never read as "no stamps"."""
    ok, out = run(["gh", "api", f"repos/{owner}/{repo}/issues/{number}/comments",
                   "--paginate", "--jq", STAMPS_JQ])
    rows = []
    for ln in out.split("\n"):
        f, _ = ifs_read(ln + "\n", 4)
        if f[0]:
            rows.append(tuple(f))
    return ok, rows


def epoch_of(e):
    return int(e) if re.fullmatch(r"[0-9]+", e or "") else 0


def stamp_body(sid, branch):
    s, m = sid8(sid), machine_id()
    return (f"{MARKER} sid={s} epoch={now_epoch()} machine={m} -->\n"
            f"**Claimed:** `{s}` · `{branch}` · `{m}` · {now_iso()}\n"
            "\n"
            "A session holds this work. The Stop hook refreshes the timestamp; `/wrapup`\n"
            f"and the archive verdict delete this comment. Older than {tdiv(STALE_SECS, 3600)}h and\n"
            "the claim is stale -- the session that wrote it died without releasing it.")


def _body_json(sid, branch):
    return json.dumps({"body": stamp_body(sid, branch)}).encode()


def post_stamp(owner, repo, number, sid, branch):
    """The new comment's id, or "" when the post failed."""
    return run(["gh", "api", "-X", "POST", f"repos/{owner}/{repo}/issues/{number}/comments",
                "--input", "-", "--jq", ".id"], stdin=_body_json(sid, branch))[1]


def patch_stamp(owner, repo, cid, sid, branch):
    return run(["gh", "api", "-X", "PATCH", f"repos/{owner}/{repo}/issues/comments/{cid}",
                "--input", "-"], stdin=_body_json(sid, branch))[0]


def delete_stamp(owner, repo, cid):
    return run(["gh", "api", "-X", "DELETE", f"repos/{owner}/{repo}/issues/comments/{cid}"])[0]


# The label is the cheap filter -- `pr-label-audit --json` reports it, and a
# label query costs one search where reading every card's comments costs one
# call per card. The stamp stays the truth: a label with no stamp under it
# means a session died between the two writes, not that the branch is held.
def add_label(owner, repo, number):
    run(["gh", "api", "-X", "POST", f"repos/{owner}/{repo}/issues/{number}/labels",
         "-f", f"labels[]={LABEL}"])


def remove_label(owner, repo, number):
    run(["gh", "api", "-X", "DELETE", f"repos/{owner}/{repo}/issues/{number}/labels/{LABEL}"])


# ------------------------------------------------------------- preconditions
def usable():
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
        return False
    if (os.environ.get("CLAUDE_CLAIM_STAMP") or "on") == "off":
        return False
    return shutil.which("gh") is not None


def git_branch(d):
    ok, out = run(["git", "-C", d, "rev-parse", "--abbrev-ref", "HEAD"])
    return out if ok else None


# ------------------------------------------------------------------ actions
def warn_held(stamps, sid, branch):
    """The warning a contested claim deserves, or "". Every stamp that is
    neither this session's nor stale is named, with its age in minutes, so
    the reader can tell a session that started a minute ago from one that has
    been holding the branch for an hour."""
    s8, now, out = sid8(sid), now_epoch(), []
    for _id, s, e, m in stamps:
        if s == s8:
            continue
        age = now - epoch_of(e)
        if age >= STALE_SECS:
            continue
        out.append(f"session `{s}` on `{m}` claimed `{branch}` {tdiv(age, 60)} minute(s) ago")
    return "\n".join(out)


def do_claim(d, sid):
    """(held warning, card url); ("", "") when nothing was claimed."""
    if not usable():
        return "", ""
    branch = git_branch(d)
    if branch in (None, "", "HEAD", "main", "master"):
        return "", ""
    url = card_url(card_of(d))
    if url is None:
        return "", ""  # none, unverified, or nothing at all: no card to stamp
    parts = card_parts(url)
    if not parts:
        return "", ""
    owner, repo, number = parts
    ok, stamps = read_stamps(owner, repo, number)
    if not ok:
        return "", ""

    # Garbage-collect first: a stamp past the stale threshold belongs to a
    # session that died without releasing it, and nothing else ever removes
    # one. Doing it here rather than on a timer means the collector runs
    # exactly when someone cares -- at the moment another session asks
    # whether the branch is free.
    now = now_epoch()
    for cid, s, e, _m in stamps:
        if s != sid8(sid) and now - epoch_of(e) >= STALE_SECS:
            delete_stamp(owner, repo, cid)

    held = warn_held(stamps, sid, branch)

    # This session's own stamp, if it already has one on this card: patch it
    # rather than post a second. A session that restarts (a new SessionStart
    # on the same id) must not leave a trail of its own claims.
    mine = next((cid for cid, s, _e, _m in stamps if s == sid8(sid)), "")
    if mine:
        patch_stamp(owner, repo, mine, sid, branch)
        cid = mine
    else:
        cid = post_stamp(owner, repo, number, sid, branch)
    if not cid:
        return "", ""
    add_label(owner, repo, number)
    write_file(record_path(sid), f"{owner}/{repo}#{number}\t{cid}\t{now_epoch()}\n")
    return held, url


def split_card(card):
    """owner, repo, number out of a record's `owner/repo#number`, as the
    shell's ${card%%/*} and friends take them apart."""
    owner = card.split("/", 1)[0]
    rest = card.split("/", 1)[1] if "/" in card else card
    return owner, rest.split("#", 1)[0], rest.rsplit("#", 1)[-1]


def do_refresh(sid, d):
    rec = record_path(sid)
    if not os.path.isfile(rec):
        # Nothing claimed: free, no network. The one exception is a session
        # that the Stop hook released on an archivable turn and that then
        # carried on working -- the tombstone says so, and the branch is held
        # again, so it is claimed again. Once per resume, not per turn:
        # do_claim rewrites the record, and a claim that fails leaves the
        # tombstone for the next turn.
        if not os.path.isfile(f"{rec}.released"):
            return
        do_claim(d, sid)
        if os.path.isfile(rec):
            rm(f"{rec}.released")
        return
    if not usable():
        return
    (card, cid, last), ok = ifs_read(read_file(rec) or "", 3)
    if not ok or not cid:
        return
    if now_epoch() - epoch_of(last) < REFRESH_SECS:
        return
    owner, repo, _number = split_card(card)
    branch = git_branch(d) or "?"
    if not patch_stamp(owner, repo, cid, sid, branch):
        return
    write_file(rec, f"{card}\t{cid}\t{now_epoch()}\n")


def do_release(d, sid, scan):
    if not usable():
        return
    rec = record_path(sid)
    owner = repo = number = ""
    if os.path.isfile(rec):
        (card, cid, _last), _ = ifs_read(read_file(rec) or "", 3)
        owner, repo, number = split_card(card)
        if cid:
            delete_stamp(owner, repo, cid)
        rm(rec)
        # A release from the Stop hook is provisional: the session may take
        # another turn. The tombstone lets refresh re-claim then (see
        # do_refresh); a --scan release is the deliberate one (/wrapup) and
        # leaves nothing.
        if scan:
            rm(f"{rec}.released")
        else:
            write_file(f"{rec}.released", "")
    elif scan:
        # No record -- a wiped TMPDIR, or a release from a session that did
        # not write the stamp itself. Look the card up and delete this
        # session's stamp by its marker, the only identity that survives the
        # record.
        #
        # Behind --scan because the Stop hook releases on every archivable
        # turn, and a scan here would be a card lookup per turn for the
        # overwhelmingly common case of a session that never claimed
        # anything. A caller that knows it is worth the round trip (/wrapup,
        # once) asks for it.
        url = card_url(card_of(d))
        parts = card_parts(url) if url is not None else None
        if not parts:
            return
        owner, repo, number = parts
        for cid, s, _e, _m in read_stamps(owner, repo, number)[1]:
            if s == sid8(sid):
                delete_stamp(owner, repo, cid)
    else:
        return
    if not owner:
        return
    # The label goes last and only when no stamp is left: a second session
    # may still hold this card, and dropping its label would hide a live
    # claim from every label-based filter. Only on a lookup that actually
    # answered: a failed read returns nothing, which would read as "no stamps
    # left" and strip the label off a card a live session is still holding.
    ok, rest = read_stamps(owner, repo, number)
    if ok and not rest:
        remove_label(owner, repo, number)


def do_read(d, url=""):
    """A lookup that failed must not read as "zero stamps": consumers
    deciding whether a worktree is free map `unverified` to unknown, an empty
    list to free. A <url> names the card outright, for a reader with no
    checkout of the branch: prt reads every open PR's stamps this way."""
    if not usable():
        return
    if not url:
        card = card_of(d)
        url = card_url(card)
        if url is None:
            if card == "none":
                print("no card")
            elif card.startswith("unverified"):
                print(card)
            else:
                print("unverified: card lookup failed")
            return
    parts = card_parts(url)
    if not parts:
        print(f"unverified: bad card url {url}")
        return
    ok, stamps = read_stamps(*parts)
    if not ok:
        print(f"unverified: could not read the stamps on {url}")
        return
    now = now_epoch()
    for _id, s, e, m in stamps:
        age = now - epoch_of(e)
        state = "stale" if age >= STALE_SECS else "live"
        print(f"{state}\t{s}\t{m}\t{tdiv(age, 60)}m\t{url}")
    # A card with no stamp says so, so a reader can tell "nobody holds it"
    # from a read that printed nothing because it never ran.
    if not stamps:
        print(f"free\t{url}")


# -------------------------------------------------------------- card claims
# A card on the board's `## Claude's` is a unit of work with no branch, so
# the branch lookup above cannot find it: a card is claimed by its link
# (one-entry-point curia, the user, 2026-10-01). The truth is a ledger in the
# state repo, one file per card and session, which the Stop hook pushes like
# every other state file -- so a listing reads it with no network call, and
# a card whose link is not a GitHub issue or PR can still be claimed. Where
# the link is one, the stamp and label go on it too, as for a branch.
#
# Unlike a branch claim this is a deliberate act, not a hook: the ledger is
# written whether or not gh is usable, and it is the one write here that
# fails loudly, because a take that did not land hands the card to two.
#
# A ledger file is <cksum of the url>-<sid8>.tsv holding one line,
# url<TAB>sid8<TAB>epoch<TAB>machine<TAB>comment-id.
def claims_dir():
    try:
        import state
        return f"{state.state_dir()}/claims"
    except ImportError:
        return f"{os.environ.get('HOME', '')}/.claude/state/global/claims"


def claim_key(url):
    import cksum
    return str(cksum.cksum(url.encode("utf-8", "surrogateescape")))


def ledger_files(pattern):
    return sorted(f for f in glob.glob(pattern) if os.path.isfile(f))


def card_ledger(url=""):
    """live|stale <sid8> <machine> <age>m <url>, one line per claim on record
    (on url only, when given)."""
    now, out = now_epoch(), []
    for f in ledger_files(f"{glob.escape(claims_dir())}/*.tsv"):
        (u, s, e, m, _c), ok = ifs_read(read_file(f) or "", 5)
        if not ok or (url and u != url):
            continue
        age = now - epoch_of(e)
        st = "stale" if age >= STALE_SECS else "live"
        out.append(f"{st}\t{s}\t{m}\t{tdiv(age, 60)}m\t{u}")
    return out


def err(msg):
    print(f"claim-stamp: {msg}", file=sys.stderr)
    return 1


def do_card_claim(url, sid):
    if not url or not sid:
        return err("card-claim needs <url> <session-id>")
    import state
    s8, d, key = sid8(sid), claims_dir(), claim_key(url)
    # The check and the write under one lock, or two sessions on this machine
    # both read the card free and both take it. A take on another machine
    # reaches this ledger only with its Stop push; that race stays open.
    if not state.state_lock(f"{os.environ.get('TMPDIR') or '/tmp'}/claim-stamp-card-{key}.lock.d"):
        return err(f"{url} is being claimed right now; try again")
    try:
        return _card_claim_locked(url, sid, s8, d, key)
    finally:
        state.state_unlock()


def _card_claim_locked(url, sid, s8, d, key):
    held = [ln.split("\t") for ln in card_ledger(url)]
    held = [f for f in held if f[0] == "live" and f[1] != s8]
    if held:
        for f in held:
            print(f"taken: session `{f[1]}` on `{f[2]}` claimed {f[4]} {f[3]} ago", file=sys.stderr)
        return 1
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return err(f"cannot write {d}")
    parts = card_parts(url)
    # A stale claim on this card is a session that died holding it; its stamp
    # goes with it, or the issue collects one per dead session.
    mine_file = f"{d}/{key}-{s8}.tsv"
    for f in ledger_files(f"{glob.escape(d)}/{key}-*.tsv"):
        if f == mine_file:
            continue
        (_u, _s, _e, _m, c), _ = ifs_read(read_file(f) or "", 5)
        if c and usable() and parts:
            delete_stamp(parts[0], parts[1], c)
        rm(f)
    cid = ""
    if usable() and parts:
        owner, repo, number = parts
        mine = next((i for i, s, _e, _m in read_stamps(owner, repo, number)[1] if s == s8), "")
        if mine:
            if patch_stamp(owner, repo, mine, sid, "card"):
                cid = mine
        else:
            cid = post_stamp(owner, repo, number, sid, "card")
        if cid:
            add_label(owner, repo, number)
    if not write_file(mine_file, f"{url}\t{s8}\t{now_epoch()}\t{machine_id()}\t{cid}\n"):
        return err(f"cannot write the claim on {url}")
    return 0


def do_card_release(url, sid=""):
    if not url:
        return err("card-release needs <url>")
    d, key = claims_dir(), claim_key(url)
    s8 = sid8(sid) if sid else ""
    for f in ledger_files(f"{glob.escape(d)}/{key}-*.tsv"):
        (u, s, _e, _m, c), ok = ifs_read(read_file(f) or "", 5)
        if not ok or u != url or (s8 and s != s8):
            continue
        if not rm(f):
            return 1
        parts = card_parts(url)
        if c and usable() and parts:
            owner, repo, number = parts
            delete_stamp(owner, repo, c)
            ok, rest = read_stamps(owner, repo, number)
            if ok and not rest:
                remove_label(owner, repo, number)
    return 0


def release_cards(sid):
    """/wrapup's deliberate release (--scan) drops this session's card claims
    too: one left to go stale keeps its stamp and label on the issue."""
    urls = []
    for f in ledger_files(f"{glob.escape(claims_dir())}/*-{glob.escape(sid8(sid))}.tsv"):
        urls += [ln.split("\t", 1)[0] for ln in (read_file(f) or "").splitlines()]
    for u in urls:
        if u:
            do_card_release(u, sid)


def refresh_cards(sid):
    """Every card claim this session holds is refreshed with its branch
    claim, so a card worked longer than CLAIM_STALE_SECS is not handed to a
    second session. Local unless a stamp needs patching; free when there are
    none."""
    for f in ledger_files(f"{glob.escape(claims_dir())}/*-{glob.escape(sid8(sid))}.tsv"):
        (u, s, e, m, c), ok = ifs_read(read_file(f) or "", 5)
        if not ok:
            continue
        if now_epoch() - epoch_of(e) < REFRESH_SECS:
            continue
        parts = card_parts(u)
        if c and usable() and parts:
            patch_stamp(parts[0], parts[1], c, sid, "card")
        write_file(f, f"{u}\t{s}\t{now_epoch()}\t{m}\t{c}\n")


# ------------------------------------------------------------- SessionStart
def session_start():
    import hookio
    ev = hookio.read()
    sid, scwd = ev.get("session_id"), ev.get("cwd")
    sid = "" if sid in (None, False) else (sid if isinstance(sid, str) else json.dumps(sid))
    scwd = scwd if isinstance(scwd, str) else ""
    if not sid:
        return 0
    held, url = do_claim(scwd or os.getcwd(), sid)
    # Silence is the normal outcome. The only thing worth a session's context
    # is the contested case: another session is holding this branch right now.
    if not held:
        return 0
    hookio.emit(hookio.context("SessionStart", f"""## WARNING: this branch is already claimed

{held}

The claim is a stamp on {url or 'the card'}, refreshed by that session's Stop
hook. It is not stale, so assume the other session is alive: say so to the user in
one line, name the session and the card, and do not push to this branch until
you know the other session has let go.
"""))
    return 0


# ------------------------------------------------------------------ dispatch
USAGE = "usage: claim-stamp.py claim|refresh|release|read|session-start [-C <dir>] [<session-id>]"


def dispatch(argv):
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    d, scan = os.getcwd(), False
    while args:
        a = args[0]
        if a == "-C" and len(args) > 1:
            d, args = args[1], args[2:]
        elif a.startswith("-C") and a != "-C":
            d, args = a[2:], args[1:]
        elif a == "--scan":
            scan, args = True, args[1:]
        elif a == "--":
            args = args[1:]
            break
        else:
            break
    arg = (args + ["", ""])[:2]

    if cmd == "claim":
        if args:
            held, _url = do_claim(d, args[0])
            if held:
                print(held)
        return 0
    if cmd == "refresh":
        if args:
            refresh_cards(args[0])
            do_refresh(args[0], d)
        return 0
    if cmd == "card-claim":
        return do_card_claim(*arg)
    if cmd == "card-release":
        return do_card_release(*arg)
    if cmd == "card-claims":
        for ln in card_ledger(arg[0]):
            print(ln)
        return 0
    if cmd == "release":
        if args:
            if scan:
                release_cards(args[0])
            do_release(d, args[0], scan)
        return 0
    if cmd == "read":
        do_read(d, arg[0])
        return 0
    if cmd == "session-start":
        return session_start()
    print(USAGE, file=sys.stderr)
    return 2


def main(argv):
    try:
        rc = dispatch(argv)
        sys.stdout.flush()
        return rc
    except Exception as e:  # noqa: BLE001 -- a convenience never breaks a session
        try:
            import hooktrace
            hooktrace.trace(HOOK, argv[0] if argv else "dispatch", e,
                            event="SessionStart" if argv[:1] == ["session-start"] else "")
        except Exception as e2:  # noqa: BLE001 -- the last place left to say it
            print(f"{HOOK}: {type(e).__name__}: {e} (trace not written: {e2})", file=sys.stderr)
        # The card claim is the one deliberate act that fails loudly.
        return 1 if argv[:1] in (["card-claim"], ["card-release"]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
