"""Where durable state lives on this machine, and the shared answers about
it, for the Python tools and hooks. Imported, never run directly; stdlib
only.

The one home for the shared answers about state: where it lives, the
work-item store and the board read from it, work records, ruling readiness
and branch_brief. Shell tools reach it through the command line at the
bottom (`python3 lib/state.py <fn> [args]`).

The locks are a mkdir protocol, not lib/lock.py: every hook and skill that
takes the state locks takes them through this module, so they hold against
each other.

The one home for this lookup (dotfiles#517). hooks/lib_state.py re-exports
it; bin tools put this directory on sys.path and `import state`.
"""
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time

import atomic
import gitrun
import jsonl

HOOK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks")


def _cap(argv, **kw):
    """Run argv; its stdout as $(...) would capture it: decoded byte for
    byte, trailing newlines stripped. "" when it could not run."""
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.decode("utf-8", "surrogateescape").rstrip("\n")


def _git(*args):
    """git's (returncode, stdout), every byte kept."""
    p = gitrun.exact(*args)
    return p.returncode, p.stdout


# Resolve the private state repo's working tree, or None if it isn't here.
#
# Order matters: an explicit env var wins, then the paths a cloud session
# checks out a source repo to, then the paths a real machine clones to.
# No cloning is attempted -- a SessionStart hook that clones a private repo
# would need credentials it cannot count on, and would stall session start
# on a network round trip. Absence is reported, not repaired.
def state_repo():
    """The private state repo's working tree, or None if it isn't here."""
    home = os.environ.get("HOME", "")
    for d in (os.environ.get("CLAUDE_STATE_REPO", ""),
              "/home/user/claude_prompts_scratch",
              "/workspace/claude_prompts_scratch",
              f"{home}/claude_prompts_scratch",
              f"{home}/src/claude_prompts_scratch",
              f"{home}/Projects/claude_prompts_scratch",
              f"{home}/code/claude_prompts_scratch"):
        if d and os.path.isdir(f"{d}/.git"):
            return d
    return None


def state_dir():
    """Directory that state files are written under, always. Falls back to a
    local, gitignored directory so a machine without the repo still keeps
    its own copy rather than silently dropping every line."""
    repo = state_repo()
    if repo is not None:
        return f"{repo}/state/global"
    return f"{os.environ.get('HOME', '')}/.claude/state/global"


def state_dir_or_none():
    """state_dir when the state repo is here, else None: for a tool that
    would rather do nothing than write under ~/.claude."""
    repo = state_repo()
    return f"{repo}/state/global" if repo else None


def state_is_repo():
    """True when state_dir is inside the git repo, i.e. worth committing."""
    return state_repo() is not None


def state_shard_path(d, name, sid):
    """The path of a per-session file. A directory that gains a file per
    session splits into subdirectories named by the id's first two
    characters (hex, so 256 at most), so no one directory grows without
    bound and a listing stays quick. Keyed by id, not date: a session that
    runs past midnight keeps one file. A file still at the flat path,
    written before the split, is used where it is until it is moved.
    Readers that list a whole directory glob both: dir/*.json dir/*/*.json."""
    if os.path.exists(f"{d}/{name}"):
        return f"{d}/{name}"
    return f"{d}/{sid[:2] or '_'}/{name}"


def append_row(d, sid, row):
    """One JSON row on the end of session sid's file under d, placed as
    state_shard_path says; the path written."""
    path = state_shard_path(d, f"{sid}.jsonl", sid)
    jsonl.append(path, row)
    return path


# Answer "does this branch hold commits that exist nowhere but here?" for a
# repo root and the branch name (`HEAD` or empty when detached).
#
# It lives here because two hooks have to agree on the answer: metrics-live.py
# draws the ⎇ nag and the archival verdict from it, stop-continuity.py's
# set_verdict decides from it whether the session is safe to kill. When each
# had its own copy they drifted -- #148 had to port two carve-outs back into
# metrics-live that the Stop hook had grown in #126 and #128/#143.
#
# One word, plus a count for the first:
#   ahead <n>     an upstream exists; n commits are on no origin branch (n may be 0)
#   unknown       the count could not be taken
#   never-pushed  no upstream, and there are commits on no origin branch
#   safe          no upstream, but every commit already lives on an origin branch
#
# The count is `HEAD --not --remotes=origin`, never `@{u}..HEAD`: `mergify
# stack push` leaves @{u} at origin/main while the commits go to a differently
# named stack/ branch, so the upstream diff called pushed work unpushed. A
# detached HEAD or a fresh branch with no upstream falls out of the same test.
# `origin/wip/*` is excluded: those are the Stop hook's salvage refs, pushed
# before this verdict is taken, and salvage is not publication -- counting
# them read every salvaged branch as pushed. No origin refs at all reads safe.
def unpushed_state(root, branch=""):
    # No origin refs at all (no remote, never fetched): nothing to be ahead of.
    if not _git("-C", root, "for-each-ref", "--count=1", "refs/remotes/origin")[1].rstrip("\n"):
        return "safe"
    n = _git("-C", root, "rev-list", "--count", "HEAD", "--not",
             "--exclude=origin/wip/*", "--remotes=origin")[1].rstrip("\n")
    if not n:
        return "unknown"
    if _git("-C", root, "rev-parse", "--verify", "-q", "--symbolic-full-name", "@{u}")[0] == 0:
        return f"ahead {n}"
    if re.fullmatch(r"[0-9]+", n.strip()) and int(n) > 0:
        return "never-pushed"
    return "safe"


def _pwd_p(p):
    """`cd p && pwd -P`, or "" when the cd fails."""
    p = p or os.getcwd()
    return os.path.realpath(p) if os.path.isdir(p) else ""


# dirty_paths -- `git status --porcelain` for the tree, less what the hooks
# themselves own. In the state repo that is all of state/: the hooks write
# metrics there on every event, this session's and every other live one's,
# and stop-continuity.py commits them with `git add state/`. A session run
# from the state repo was "worktree dirty" on every Stop, 82 of 82 recorded,
# over files no one but a hook could commit.
def is_state_repo(root):
    """root is the state repo's own clone (a worktree of it is not)."""
    sr = state_repo()
    return bool(root and sr) and _pwd_p(root) == _pwd_p(sr)


def is_cloud():
    """A cloud VM, whose clones die with it."""
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def dirty_paths(root):
    """git's porcelain lines as it printed them, trailing newline and all."""
    if is_state_repo(root):
        return _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain",
                    "--", ".", ":(exclude)state/")[1]
    return _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain")[1]


def card_names(url):
    """The card's two spellings in an item's line: its URL, and the
    owner/repo#n a home= fact is drawn as."""
    names = [url]
    m = re.match(r"^https?://[^/]+/([^/]+/[^/]+)/(pull|issues)/([0-9]+)", url)
    if m:
        names.append(f"{m.group(1)}#{m.group(3)}")
    return names


def _names(line, t):
    """line names t, and t does not run on into more digits: pull/1 must not
    match pull/12."""
    return re.search(re.escape(t) + r"(?![0-9])", line) is not None


def names_branch(text, branch):
    """text names branch as a whole token, not merely as a substring:
    every maximal run of branch-name characters
    is a token, and one must equal the branch. claude/homed-extra does not
    name claude/homed. The charset strips prose punctuation such as a
    trailing comma or backquote; a period is a branch character, so a
    branch that ends a sentence is not named."""
    return bool(branch) and branch in re.findall(r"[A-Za-z0-9._/+@-]+", text or "")


def items_dir():
    """The work-item store's directory: $WORK_ITEM_DIR, else items/ in the
    state dir."""
    return os.environ.get("WORK_ITEM_DIR") or f"{state_dir()}/items"


def board_union(hook_dir=HOOK_DIR):
    """The store as one board text: every
    item as a `- [ ] ` card under `## Needs ruling` (owner human-ruling,
    `### <repo name>` as the group, else `### global`), `## Human's`
    (human-click) or `## Claude's` (agent). "" when the store is empty."""
    r, h, a = [], [], []
    for f in _item_rows(hook_dir):
        f = f + [""] * (7 - len(f))
        g = re.sub(r"^.*/", "", f[5])
        if g in ("", "-"):
            g = "global"
        if f[1] == "human-ruling":
            r.append(f"### {g}\n- [ ] {f[6]}")
        elif f[1] == "human-click":
            h.append(f"- [ ] {f[6]}")
        else:
            a.append(f"- [ ] {f[6]}")
    out = []
    for head, cards in (("## Needs ruling", r), ("## Human's", h), ("## Claude's", a)):
        if cards:
            out += [head, *cards, ""]
    return "\n".join(out) + "\n" if out else ""


def _work_item_bin(hook_dir):
    env_hooks = os.environ.get("HOOK_DIR", "")
    for wi in (os.environ.get("WORK_ITEM_BIN", ""), f"{hook_dir}/../bin/work-item",
               env_hooks and f"{env_hooks}/../bin/work-item",
               f"{os.environ.get('HOME', '')}/.claude/bin/work-item"):
        if wi and os.path.isfile(wi):
            return wi
    return None


def _work_item(d, *args, hook_dir=HOOK_DIR):
    """work-item args over the store d: (stdout, None), or ("", the cause)."""
    wi = _work_item_bin(hook_dir)
    if wi is None:
        return "", "work-item not found"
    try:
        p = subprocess.run([sys.executable, wi, *args], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=dict(os.environ, WORK_ITEM_DIR=d))
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"work-item {args[0]} failed: {e}"
    if p.returncode:
        err = p.stderr.decode("utf-8", "replace").rstrip("\n").split("\n")[-1]
        return "", f"work-item {args[0]} failed (exit {p.returncode}): {err}"
    return p.stdout.decode("utf-8", "surrogateescape").rstrip("\n"), None


def item_rows(hook_dir=HOOK_DIR):
    """(rows, err): work-item list's rows for the store (`id owner status
    holder updated repo line`, split on tabs). No items/ is ([], None); a
    store that cannot be read is ([], the cause), which a reader that must
    not pass a broken board off as an empty one checks. $ITEM_ROWS_FILE,
    when set, holds rows a caller already listed: a shell tool asking
    several questions pays for one listing, not one each."""
    d = items_dir()
    if not os.path.isdir(d):
        return [], None
    primed = os.environ.get("ITEM_ROWS_FILE")
    if primed:
        try:
            with open(primed, encoding="utf-8", errors="surrogateescape", newline="") as fh:
                return [ln.split("\t") for ln in fh.read().split("\n") if ln], None
        except OSError:
            pass
    out, err = _work_item(d, "list", hook_dir=hook_dir)
    return [ln.split("\t") for ln in out.split("\n") if ln], err


def _item_rows(hook_dir):
    return item_rows(hook_dir)[0]


def _live_claim_names(names, self8, hook_dir):
    """Another session holds a live claim on an item whose line names the
    card. work-item decides live vs stale; an unclaimed item has no holder."""
    for f in _item_rows(hook_dir):
        if len(f) > 6 and f[3] and f[3] != self8 and any(_names(f[6], t) for t in names):
            return True
    return False


# archivable_reasons -- the reasons a session on this branch is not yet
# archivable, comma-joined; empty when it is. Order: worktree dirty,
# unpushed commits, branch home, session live.
#
# Lives here for the same reason unpushed_state does: metrics-live.py's live
# nag and stop-continuity.py's Stop-hook verdict must never disagree about
# what "archivable" means (dotfiles#149). Before this they didn't even
# agree on what a "home" is -- metrics-live re-checked PR-or-card
# inline and never looked for a pointer issue, the one branch-home-gate.py
# already finds.
#
# branch-home-gate.py lives in hook_dir and is shelled out to, not sourced,
# so its own state (the once-per-session gate) never leaks into this
# read-only check.
#
# Home is checked before session-live, and both only when dirty/unpushed are
# already clean: both can shell out to `gh` (branch-home-gate.py up to three
# 15s calls per mode, and session-live asks for its --card after the home
# check has), so a dirty mid-work tree -- the common
# case, and the one Stop fires on every turn -- never pays that cost.
#
# session live (dotfiles#167): git state alone is how a live session's
# worktree got archived out from under it (PR #162, the scar the languette
# plugin's guard-worktrees names). The signal is the item store's claim: a
# live claim by another session on an item that names the branch's card
# (its URL, or the owner/repo#n it is drawn as). work-item decides live vs
# stale (WORK_ITEM_STALE_SECS). self_sid is the caller's own: its own
# claim is never a reason, or a session could never become archivable by
# watching its own claim. Omit it (a sweep, a human) and every live claim
# on the card counts.
#
# Not this function's job: "not a git repo" (there is no branch here to
# judge) and anything that only becomes true after a push is attempted --
# both are the caller's own facts to add.
def archivable(work_root, work_branch, self_sid="", hook_dir=HOOK_DIR):
    """(reasons, home): archivable_reasons, plus the branch-home-gate.py
    line it read, or None when it never got that far. The Stop hook's
    pickup item wants the same home line and must not pay
    branch-home-gate.py's gh round trip a second time in one Stop."""
    reasons = []
    home = None
    # The state repo's own clone is not a worktree archiving deletes: on a
    # machine that keeps it, its dirt is a note (buffered_state), not a
    # reason. A cloud VM's clone dies with the VM, so there the state repo's
    # dirt is a reason whichever repo the session worked in, named after the
    # work area's own.
    if not is_state_repo(work_root) and dirty_paths(work_root).rstrip("\n"):
        reasons.append("worktree dirty")
    if is_cloud() and state_repo() and dirty_paths(state_repo()).rstrip("\n"):
        reasons.append("state repo dirty")

    ust = unpushed_state(work_root, work_branch)
    if ust == "ahead 0":
        pass
    elif ust.startswith("ahead "):
        reasons.append(f"{ust[len('ahead '):]} commit(s) unpushed")
    elif ust == "unknown":
        reasons.append("could not count unpushed commits")
    elif ust == "never-pushed":
        if work_branch in ("HEAD", ""):
            reasons.append("detached HEAD, no upstream to compare against")
        else:
            reasons.append(f"`{work_branch}` has no upstream (never pushed)")

    if not reasons:
        home = _cap([sys.executable, f"{hook_dir}/branch-home-gate.py", "--check", work_root])
        if home.startswith("home:"):
            pass
        elif home.startswith("unverified:"):
            why = home[len("unverified: "):] if home.startswith("unverified: ") else home
            reasons.append(f"branch home unverified ({why})")
        else:
            reasons.append(f"no PR and no pointer for `{work_branch}`")

    gate = f"{hook_dir}/branch-home-gate.py"
    if not reasons and os.access(gate, os.X_OK):
        card = _cap([sys.executable, gate, "--card", work_root])
        if card.startswith(("pr ", "issue ")):
            url = card.split(" ", 1)[1]
            if _live_claim_names(card_names(url), self_sid[:8], hook_dir):
                reasons.append("session live")

    return ", ".join(reasons), home


def archivable_reasons(work_root, work_branch, self_sid="", hook_dir=HOOK_DIR):
    return archivable(work_root, work_branch, self_sid, hook_dir)[0]


# state_lock / state_unlock -- mkdir atomic test-and-set (grind's per-repo
# lock protocol; no flock: macOS has none). meta carries pid+host; a same-host
# dead pid is reclaimed via rename-then-rm. A dir with no meta at all (a
# kill between mkdir and the meta write) has no pid to check; one older
# than STATE_LOCK_STALE_SECS (default 5) is reclaimed regardless. One lock
# at a time: the caller releases it on every exit path.
_held = None


def _meta_field(text, key):
    """awk -F= '$1 == key { print $2 }', as $(...) captures it: every
    matching line's second field."""
    vals = []
    for ln in text.split("\n"):
        f = ln.split("=")
        if f[0] == key:
            vals.append(f[1] if len(f) > 1 else "")
    return "\n".join(vals).rstrip("\n")


def _alive(pid):
    """`kill -0 pid` succeeds: a number naming a process we may signal."""
    if not re.fullmatch(r"[0-9]+", pid):
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, OverflowError):
        return False  # EPERM included: kill -0 fails on it too
    return True


def state_lock(d):
    """Take the lock directory d; True when held."""
    global _held
    if not d:
        return False
    meta = f"{d}/meta"
    try:
        host = os.uname().nodename
    except OSError:
        host = "unknown"
    try:
        os.mkdir(d)
    except OSError:
        if os.path.isfile(meta):
            try:
                with open(meta, encoding="utf-8", errors="surrogateescape", newline="") as fh:
                    text = fh.read()
            except OSError:
                text = ""
            pid = _meta_field(text, "pid")
            if not (_meta_field(text, "hostname") == host and pid and not _alive(pid)):
                return False
        else:
            try:
                stale = int(os.environ.get("STATE_LOCK_STALE_SECS") or 5)
            except ValueError:
                stale = 5
            cutoff = int(time.time()) - stale
            try:
                if os.stat(d).st_mtime_ns >= cutoff * 1_000_000_000:
                    return False
            except OSError:
                pass  # gone already: the rename below fails
        moved = f"{d}.stale.{os.getpid()}"
        try:
            os.rename(d, moved)
            shutil.rmtree(moved)
            os.mkdir(d)
        except OSError:
            return False
    try:
        with open(meta, "w", encoding="utf-8") as fh:
            fh.write(f"pid={os.getpid()}\nhostname={host}\n")
    except OSError:
        pass
    _held = d
    return True


def state_unlock():
    """Release whatever state_lock holds; a no-op when nothing is held."""
    global _held
    if _held:
        shutil.rmtree(_held, ignore_errors=True)
    _held = None


# state_lock_wait -- state_lock, retried once a second for up to secs: the
# portable `flock -w`. A bare `flock` here silently exited every Stop hook
# on macOS before the state-repo push. STATE_PUSH_LOCK is the push lock
# stop-continuity.py, abandon-branch.py and the agora skill share, fixed at
# import.
STATE_PUSH_LOCK = f"{os.environ.get('TMPDIR') or '/tmp'}/claude-state-push.lock.d"


def state_lock_wait(d, secs=90):
    n = secs
    while not state_lock(d):
        if n <= 0:
            return False
        n -= 1
        time.sleep(1)
    return True


def push_locked(command):
    """(exit status, "") of `sh -c command` run under STATE_PUSH_LOCK; 1 when
    the lock is still held after 90s."""
    if not state_lock_wait(STATE_PUSH_LOCK, 90):
        return 1, "state.py push_locked: the push lock is held\n"
    try:
        return subprocess.call(["sh", "-c", command]), ""
    finally:
        state_unlock()


_NUM = re.compile(r"[ \t\n]*[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?")


def _awk_num(s):
    """A string as awk reads it as a number: its leading numeric part, or 0."""
    m = _NUM.match(str(s))
    return float(m.group(0)) if m else 0.0


# decision_rate -- "<n> decisions in 1h10 (2.6/h)", or "" when the session
# clock (first prompt to last) is under a minute. Measured, never alarmed
# (one-entry-point §5, 2026-09-30): the two places that call it are the
# session-start brief and the Stop checkpoint, nothing else. No trailing
# newline.
def decision_rate(decisions=0, span=0):
    d, s = _awk_num(decisions), _awk_num(span)
    if s < 60:
        return ""
    m = int(s / 60 + 0.5)
    one = re.fullmatch(r"[ \t\n]*" + _NUM.pattern + r"[ \t\n]*", str(decisions)) and d == 1
    return "%d decision%s in %dh%02d (%.1f/h)" % (d, "" if one else "s", m // 60, m % 60,
                                                   d * 3600 / s)


# The tool calls that change git state: a shell command (Bash
# tool_input.command) or a bare tool name (an MCP tool that writes a repo,
# branch or PR). The line is drawn at "did the repo's history, refs or
# worktree move": `git add`, `fetch`, `clone`, `remote` and the reads are out.
GIT_EVENT_RE = (r"\bgit\s+(commit|push|pull|merge|rebase|cherry-pick|revert|checkout|switch|branch"
                r"|worktree|tag|stash|reset|restore|rm|mv|apply|am)\b|\bgh\s+(pr|release)\b"
                r"|\b(yadm|dotsync)\b|create_pull_request|merge_pull_request|update_pull_request"
                r"|update_pull_request_branch|push_files|create_or_update_file|delete_file"
                r"|create_branch|create_repository|fork_repository")


def _porcelain_paths(text):
    """The paths in `git status --porcelain` lines: a rename's new name, a
    quoted name unquoted."""
    paths = []
    for ln in text.split("\n"):
        if not ln:
            continue
        p = ln[3:]
        if " -> " in p:
            p = p.rsplit(" -> ", 1)[1]
        if len(p) >= 2 and p.startswith('"') and p.endswith('"'):
            p = p[1:-1]
        paths.append(p)
    return paths


# buffered_state -- in the state repo only, what the verdict leaves out.
# First, the uncommitted files under state/. stop-continuity.py has already
# committed this Stop's by the time the readout runs, so what is left was
# written since, or its commit failed; the next Stop commits it. Leaving them
# out of the verdict is right; leaving them unsaid is not: a hand-off or card
# still on disk is worth knowing about. Metrics are counted, everything else
# is named. Then, off the cloud, the files outside state/ (a draft, a README
# edit) the Stop hook's second commit did not take: over 5 MB, refused by the
# clone's pre-commit scan, or written since. Archiving leaves the clone and
# them in place. In the cloud those are the verdict's "state repo dirty"
# instead.
# "" elsewhere, and when nothing is buffered.
def buffered_state(root):
    if not is_state_repo(root):
        return ""
    lines = []
    stray = [] if is_cloud() else _porcelain_paths(dirty_paths(root))
    if stray:
        lines.append(f"→ state repo: {_shown(stray)} outside state/. "
                     "Safe to archive: the clone keeps them. The Stop hook held them back or they came "
                     "after it; the checkpoint names why.")
    text = _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain",
                "--untracked-files=all", "--", "state/")[1]
    paths = []
    for p in _porcelain_paths(text):
        p = p[len("state/global/"):] if p.startswith("state/global/") else p
        p = p[len("state/"):] if p.startswith("state/") else p
        paths.append(p)
    if paths:
        named = ", ".join(p for p in paths if not p.startswith("metrics/"))
        nm = sum(1 for p in paths if p.startswith("metrics/"))
        if nm:
            named = f"{named + ', ' if named else ''}+ {nm} metrics file{'' if nm == 1 else 's'}"
        lines.insert(0, f"→ buffered in the state repo, not committed yet (the next Stop commits it): {named}")
    return "\n".join(lines)


# verdict_explain -- one line per reason the verdict names: what is at risk,
# then what to do. Matched by pattern, not split on commas: a reason's own
# text can hold one. A reason with no line here is still printed in the
# verdict itself. Given the tree, the dirty line names the files.
_EXPLAIN = (
    (("not a git repo",),
     "→ not a git repo: the session ran outside any repo, so there was no branch to check."),
    (("worktree dirty",), None),
    (("state repo dirty",), None),
    ((" commit(s) unpushed",),
     "→ commits unpushed: they exist on this machine only. Push the branch."),
    (("has no upstream (never pushed)",),
     "→ never pushed: the branch exists on this machine only. Push it with -u."),
    (("detached HEAD",),
     "→ detached HEAD: the commits are on no branch. Check out or create one."),
    (("could not count unpushed commits",),
     "→ git could not compare the branch with its upstream. Run git status there."),
    (("no PR and no pointer",),
     "→ no PR and no pointer: nothing tells a future session this branch exists. Open a PR, or card it."),
    (("branch home unverified",),
     "→ home unverified: gh could not check for a PR or card (network or auth). The next Stop retries."),
    (("session live",),
     "→ session live: another session holds this branch. Closing this chat is safe; archiving the worktree is not."),
    (("state repo not committed", "state-repo commit failed"),
     "→ state not committed: this session's checkpoint and item edits are not saved, even locally. Run git status in the state repo."),
    (("state-repo push failed",),
     "→ state not pushed: this cloud VM's state commit is not on GitHub and dies with the VM."),
    (("did not finish",),
     "→ no verdict this turn: the Stop hook stopped before deciding. The next Stop retries."),
)
_DIRTY_TAIL = "Archive the worktree only after the agent commits them."
_DIRTY_TAIL_CLOUD = ("This cloud VM's clone dies with the VM, and the Stop hook has not committed these "
                     "(held back, or written since): commit these and push them to main, or they are lost.")


def _shown(paths):
    """`N uncommitted file(s) (a, b, c, +M more)`."""
    more = f", +{len(paths) - 3} more" if len(paths) > 3 else ""
    return f"{len(paths)} uncommitted file(s) ({', '.join(paths[:3])}{more})"


def verdict_explain(verdict, root=""):
    """The explanation lines, newline-joined; "" when no reason has one."""
    lines = []
    for needles, line in _EXPLAIN:
        if not any(n in verdict for n in needles):
            continue
        if line is not None:
            lines.append(line)
        elif needles[0] == "state repo dirty":
            paths = _porcelain_paths(dirty_paths(state_repo())) if state_repo() else []
            what = _shown(paths) if paths else "uncommitted files in the state repo"
            lines.append(f"→ state repo dirty: {what}. {_DIRTY_TAIL_CLOUD}")
        else:
            paths = _porcelain_paths(dirty_paths(root)) if root else []
            what = _shown(paths) if paths else "uncommitted files in this worktree"
            lines.append(f"→ worktree dirty: {what}. {_DIRTY_TAIL}")
    return "\n".join(lines)


# day_decisions -- fold this session's decision counts into the machine-wide
# store beside sitting.json and answer the day's totals as (total, junk).
# Decision load is spent across a day, not per chat (#99); a prompt gap past
# gap seconds anywhere on the machine starts a fresh day. Keyed by session
# id, holding each session's own running counts rather than a delta, so a
# replayed hook cannot double-count. junk rides beside the total, never
# subtracted. A lock held elsewhere skips the write and answers the store as
# it stands. A store that is not JSON raises, for the caller to report.
def day_decisions(sid, total, junk, now, gap):
    f = f"{state_dir()}/metrics/day-decisions.json"
    os.makedirs(os.path.dirname(f), exist_ok=True)
    if state_lock(f"{f}.lock"):
        try:
            # Read inside the lock: a read before it is the race the lock closes.
            day = {}
            if os.path.exists(f):
                with open(f, encoding="utf-8") as fh:
                    day = json.load(fh)
            if (day.get("last_prompt") or 0) > 0 and now - day["last_prompt"] > gap:
                day = {"day_start": now, "sessions": {}}
            day["last_prompt"] = now
            if day.get("day_start") in (None, False):
                day["day_start"] = now
            day.setdefault("sessions", {})[sid] = {"total": total, "junk": junk}
            atomic.write(f, json.dumps(day, indent=2, ensure_ascii=False) + "\n")
        finally:
            state_unlock()
    if not os.path.exists(f):
        return 0, 0
    with open(f, encoding="utf-8") as fh:
        sessions = (json.load(fh).get("sessions") or {}).values()
    return (sum(s.get("total") or 0 for s in sessions),
            sum(s.get("junk") or 0 for s in sessions))


# ------------------------------------------------------------- units of work
# A pickup item and an agent-owned work item are facets of one thing, the
# unit of work. Every view that lists work reads it through work_records, so
# pickup-list, worklist's resume section and /pickup cannot disagree about
# what an item is.
US = "\x1f"


class StoreError(Exception):
    """The work-item store could not be read."""


def is_card_id(word=""):
    """A work item's identifier: epoch seconds, then eight hex, no separator."""
    return re.fullmatch(r"[0-9]{10}[0-9a-f]{8}", word or "") is not None


def work_claims_load(hook_dir=None):
    """Every card claim on record, one `live|stale <sid8> <machine> <age>m
    <url>` line each (claim-stamp.py owns the ledger), then each item's live
    holder with the item's id for <url>. "" when neither has one."""
    hook_dir = hook_dir or os.environ.get("HOOK_DIR") or f"{os.environ.get('HOME', '')}/.claude/hooks"
    claims = ""
    cs = f"{hook_dir}/claim-stamp.py"
    if os.path.isfile(cs):
        claims = _cap([sys.executable, cs, "card-claims"])
    held = "\n".join(f"live\t{f[3]}\t-\t-\t{f[0]}" for f in item_rows()[0] if len(f) > 3 and f[3])
    return "\n".join(x for x in (claims, held) if x)


def _trim(v):
    return re.sub(r"[ \t\r]+$", "", re.sub(r"^[ \t]+", "", v))


def _mshort(m):
    m = m.lower()
    for name in ("fable", "opus", "sonnet", "haiku"):
        if name in m:
            return name
    return "" if m in ("none", "?", "-") else m


def _cfield(b, k):
    """A card field: the value after " <name>:" up to ";", ")", the next
    field or the end."""
    b = " " + b
    p = b.find(f" {k}:")
    if p < 0:
        p = b.find(f"({k}:")
    if p < 0:
        return ""
    v = b[p + len(k) + 2:].lstrip(" \t")
    m = re.search(r"[;)]", v)
    if m:
        v = v[:m.start()]
    m = re.search(r" [a-z][a-z ]*:", v)
    if m:
        v = v[:m.start()]
    return _trim(v)


def _record(kind, title, st, until, claim, model, effort, link, id_, up):
    return US.join((kind, title, st, until, claim, _mshort(model), _trim(effort), link, id_, up))


def _card_record(up, b, held):
    b = re.sub(r"^[ \t]*(- \[[ xX]\] |- |[0-9]+\. )", "", b, count=1)
    if b.startswith("**"):
        t = b[2:]
        p = t.find("**")
        title = t[:p] if p >= 0 else t
    else:
        title = re.sub(r"\]\([^)]*\)", "", b).replace("[", "")
    link = ""
    m = re.search(r"\]\((https?://[^) ]+|(?:\.\./)*log/[^) ]+)\)", b)
    if m:
        link = m.group(1)
    else:
        m = re.search(r"https?://[^ )>]+", b)
        if m:
            link = m.group(0)
    id_ = _cfield(b, "id") or link
    claim = held[link] if link in held else held.get(id_, "")
    return _record("card", _trim(title), "taken" if claim else "open", _cfield(b, "until"), claim,
                   _cfield(b, "model"), _cfield(b, "effort"), link, id_, up)


def _pickup_record(path):
    try:
        with open(path, encoding="utf-8", errors="surrogateescape", newline="") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return None
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return None
    hf, bf, title, body = {}, {}, "", False
    for ln in lines:
        if not body:
            if ln == "---":
                body = True
                continue
            p = ln.find(": ")
            if p >= 0:
                hf.setdefault(ln[:p], _trim(ln[p + 2:]))
            continue
        if not title and re.search(r"[^ \t\r]", ln):
            title = _trim(ln)
            continue
        m = re.match(r"(until|effort|link|model):", ln)
        if m:
            bf.setdefault(m.group(1), _trim(ln[m.end():]))
    id_ = re.sub(r"\.md$", "", path.rsplit("/", 1)[-1])
    link = bf.get("link", "")
    if not link and hf.get("pr", "") != "none":
        link = hf.get("pr", "")
    return _record("pickup", title, hf.get("status") or "open", bf.get("until", ""), "",
                   bf.get("model") or hf.get("model", ""), bf.get("effort", ""), link, id_,
                   hf.get("updated", ""))


def _live_holders(claims):
    held = {}
    for ln in (claims or "").split("\n"):
        c = ln.split("\t")
        if c[0] == "live" and len(c) > 4 and c[4]:
            held.setdefault(c[4], c[1])
    return held


def work_records(paths=(), cards_text=None, claims=None):
    """Units of work, one line each, fields joined by \\037:

        kind title status until claim model effort link id updated

    kind is `pickup` or `card`; an absent field is empty. A pickup item's
    model, effort, until and link come from its hand-off body (the header's
    model stands in only when the body names none). A card's come from its
    own `model:`, `effort:`, `until:` fields and its first link; its id is its
    `id:` field (else the link), and a live claim on either makes it `taken`,
    claim being the holder's short session id. cards_text is `<updated>\\t<card
    text>` lines (claude_cards' output), read first. claims is
    work_claims_load's text; when None, $WORK_CLAIMS if set (even empty),
    else read here."""
    if not paths and cards_text is None:
        return ""
    if claims is None:
        claims = os.environ.get("WORK_CLAIMS")
    held = _live_holders(work_claims_load() if claims is None else claims)
    out = []
    for ln in (cards_text or "").split("\n"):
        if ln:
            up, _, b = ln.partition("\t") if "\t" in ln else ("", "", ln)
            out.append(_card_record(up, b, held))
    for pth in paths:
        r = _pickup_record(pth)
        if r is not None:
            out.append(r)
    return "".join(r + "\n" for r in out)


def work_record(item, updated=""):
    """One unit of work: a pickup file's path or a card's text, as one line."""
    if os.path.isfile(item):
        return work_records([item])
    return work_records(cards_text=f"{updated}\t{item}")


def item_rows_text():
    """item_rows as work-item printed them; a store that cannot be read
    raises StoreError, never reads as empty."""
    rows, err = item_rows()
    if err:
        raise StoreError(err)
    return "".join("\t".join(r) + "\n" for r in rows)


def done_rows(hook_dir=HOOK_DIR):
    """(rows, err): the rows of every item at `done`, in item_rows' shape:
    the agent finished and logged evidence; only the user's acceptance
    remains."""
    d = items_dir()
    if not os.path.isdir(d):
        return [], None
    out, err = _work_item(d, "list", "--all", hook_dir=hook_dir)
    rows = [ln.split("\t") for ln in out.split("\n") if ln]
    return [r for r in rows if len(r) > 2 and r[2] == "done"], err


def done_board(rows=None):
    """The done rows as one more board section, `## Done`."""
    rows = done_rows()[0] if rows is None else rows
    if not rows:
        return ""
    return "## Done\n" + "".join(f"- [ ] {(r + [''] * 7)[6]}\n" for r in rows) + "\n"


def board_card(card_id):
    """The items whose `id:` is card_id, as `<section>\\t<group>\\t<folded
    card>` lines, the done queue included; None when there is none."""
    if not os.path.isdir(items_dir()):
        return None
    want = re.compile(r"(^|[ (])id:[ \t]*" + re.escape(card_id) + r"([^0-9a-z]|$)")
    hits, txt, sec, grp = [], "", "", ""

    def flush():
        nonlocal txt
        if txt and want.search(txt):
            hits.append(f"{sec}\t{grp}\t{txt}")
        txt = ""
    for ln in (board_union() + done_board()).split("\n"):
        if ln.startswith("## "):
            flush()
            sec, grp = ln[3:], ""
        elif ln.startswith("### "):
            flush()
            grp = ln[4:]
        elif ln.startswith("#") or not ln.strip(" \t"):
            flush()
        elif re.match(r"(- |[0-9]+\. )", ln):
            flush()
            txt = ln.rstrip(" \t")
        elif txt:
            txt += " " + ln.strip(" \t")
    flush()
    return "\n".join(hits) + "\n" if hits else None


def claude_cards():
    """The pickup candidates: every agent-owned item that is ready or
    claimed, one `<updated>\\t<card text>` per card. A ruling waits for the
    user and click work is theirs; open and blocked items cannot be taken."""
    out = []
    for f in item_rows()[0]:
        f = f + [""] * (7 - len(f))
        if f[1] == "agent" and f[2] in ("ready", "claimed"):
            out.append(f"{f[4]}\t{f[6]}\n")
    return "".join(out)


# --- Ruling-card readiness -------------------------------------------------
# A ruling card is ready when its `until:` date has arrived or the PR or
# issue it links is in flight, otherwise waiting. `until:` holds a date, a
# PR/issue link, or an event in words; an event in words waits until a human
# says otherwise. Every date and link in the value is read, and any one of
# them makes the card ready. In flight: a PR in any state, a closed issue,
# or an open issue an open PR closes. No `until:` (a legacy card) is ready,
# and so is a link gh cannot answer for: showing a waiting card costs a
# line, hiding a ready one costs the ruling.
#
# Link state is cached under $XDG_CACHE_HOME/ruling-refs for RULING_REF_TTL
# seconds (900). RULING_REF_CACHE_ONLY=1 never calls gh and takes a stale
# entry over none (worklist --brief). RULING_TODAY overrides today's date.
_UNTIL_END = re.compile(r"[ (;,.*](default|undo|risk|judgment|settle|repos|repo|kind|why you|why this|id):")


def ruling_until(card):
    """The value of a card's `until:` field, or None when it has none."""
    line = next((ln for ln in card.split("\n") if "until:" in ln.lower()), None)
    if line is None:
        return None
    v = line[line.lower().find("until:") + 6:]
    m = _UNTIL_END.search(v.lower())
    if m:
        v = v[:m.start()]
    return re.sub(r"[ \t*.;,]+$", "", re.sub(r"^[ \t*]+", "", v))


_GRAPHQL = """query($owner:String!,$name:String!,$n:Int!){repository(owner:$owner,name:$name){issueOrPullRequest(number:$n){
       __typename ... on PullRequest{state}
       ... on Issue{state closedByPullRequestsReferences(first:10,includeClosedPrs:false){nodes{state}}}}}}"""
_JQ = """
    .data.repository.issueOrPullRequest
    | if . == null then "unknown"
      elif .__typename == "PullRequest" then "pr-" + (.state | ascii_downcase)
      elif .state == "CLOSED" then "issue-closed"
      elif ([.closedByPullRequestsReferences.nodes[] | select(.state == "OPEN")] | length) > 0 then "issue-inflight"
      else "issue-open" end"""
_REF_STATES = ("pr-open", "pr-merged", "pr-closed", "issue-open", "issue-inflight", "issue-closed")


def ruling_ref_state(owner, repo, number):
    """pr-open | pr-merged | pr-closed | issue-open | issue-inflight |
    issue-closed, or unknown when neither the cache nor gh can say."""
    cache_only = os.environ.get("RULING_REF_CACHE_ONLY", "0") == "1"
    home = os.environ.get("HOME", "")
    cdir = f"{os.environ.get('XDG_CACHE_HOME') or home + '/.cache'}/ruling-refs"
    f = f"{cdir}/{owner}_{repo}_{number}"
    now = int(time.time())
    try:
        with open(f, encoding="utf-8") as fh:
            line = fh.read().split("\n")[0]
    except OSError:
        line = ""
    at, _, st = line.partition(" ")
    ttl = int(os.environ.get("RULING_REF_TTL") or 900)
    if line and (cache_only or (at.isdigit() and now - int(at) < ttl)):
        return st
    if cache_only or not shutil.which("gh"):
        return "unknown"
    argv = ["gh", "api", "graphql", "-F", f"owner={owner}", "-F", f"name={repo}", "-F", f"n={number}",
            "-f", f"query={_GRAPHQL}", "--jq", _JQ]
    st = "unknown"
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if p.returncode == 0:
            st = p.stdout.decode("utf-8", "replace").rstrip("\n")
    except (OSError, subprocess.SubprocessError):
        pass
    if st not in _REF_STATES:
        return "unknown"
    try:
        os.makedirs(cdir, exist_ok=True)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(f"{now} {st}\n")
    except OSError:
        pass
    return st


_REF = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/(?:pull|issues)/([0-9]+)"
                  r"|([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([0-9]+)")


def ruling_readiness(card):
    """`ready` or `waiting` for one `## Needs ruling` card, its continuation
    lines already folded onto one line."""
    v = ruling_until(card)
    if v is None:
        return "ready"
    today = os.environ.get("RULING_TODAY") or time.strftime("%Y-%m-%d")
    for d in re.findall(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v):
        if d <= today:
            return "ready"
    # A bare #n names no repo and reads as words.
    for m in _REF.finditer(v):
        o, r, n = m.group(1, 2, 3) if m.group(1) else m.group(4, 5, 6)
        if ruling_ref_state(o, r, n) != "issue-open":
            return "ready"
    return "waiting"


def rulings_ready():
    """Stdin lines `<group>\\t<card>` out as `<readiness>\\t<group>\\t<card>`:
    ruling_readiness for many cards in one process."""
    return "".join(f"{ruling_readiness(ln.partition(chr(9))[2])}\t{ln}\n"
                   for ln in sys.stdin.read().split("\n") if ln)


# ------------------------------------------------------------- branch facts
def pr_base_refs(root, branch, remote="origin"):
    """Base branch names of the open PRs whose head is branch, one per line.
    "" is "no open PR"; None is "the lookup could not be made at all" (no gh,
    no such remote, gh failed). Different answers: flattening one into the
    other is how a stacked PR gets silently rebased onto main. Policy on
    0/1/many stays with the caller."""
    if not shutil.which("gh"):
        return None
    rc, url = _git("-C", root, "remote", "get-url", remote)
    if rc:
        return None
    try:
        p = subprocess.run(["gh", "pr", "list", "-R", url.rstrip("\n"), "--head", branch, "--state", "open",
                            "--json", "baseRefName", "--jq", ".[].baseRefName"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode:
        return None
    return p.stdout.decode("utf-8", "replace").rstrip("\n")


def default_branch(root, remote="origin"):
    """The remote's default branch, short name, or None when this clone has
    never recorded one. Read-only: it never runs `git remote set-head`."""
    rc, ref = _git("-C", root, "symbolic-ref", "-q", "--short", f"refs/remotes/{remote}/HEAD")
    if rc:
        return None
    ref = ref.rstrip("\n")
    return ref[len(remote) + 1:] if ref.startswith(remote + "/") else ref


def _merges_all_clean(g, rng):
    """True when every merge in rng is what re-merging its parents gives:
    no tree edit lives only in a merge. Octopus or unreadable is not clean."""
    rc, ms = g("rev-list", "--merges", rng)
    if rc:
        return False
    for m in (s for s in ms.split("\n") if s):
        ps = g("rev-parse", f"{m}^@")[1].split()
        rc, t = g("merge-tree", "--write-tree", *ps) if len(ps) == 2 else (1, "")
        if rc or t.split("\n")[0].strip() != g("rev-parse", f"{m}^{{tree}}")[1].strip():
            return False
    return True


def branch_brief(root, br):
    """(status, text): the facts a session starting on an existing branch
    keeps getting wrong, one per line, ending in exactly one recommended
    command. Read-only: it never fetches, commits or pushes.

    Lines: worktrees, base, ahead, behind, conflicts, unsigned, merges,
    recommend. A fact that cannot be taken is `unknown`, never a guess:
    without a fetch a base ref this machine has never seen is not known, and
    "0 behind" would lie in the direction that loses work. `unsigned` is the
    presence of a `gpgsig` header (what no-unsigned-push tests), not `%G?`,
    which calls every signed commit unverified on a machine with no
    allowed-signers file. The recommendation ladder is ordered by what is
    unrecoverable: hand-resolved merge commits outrank everything (a rebase drops what
    lives only in a hand-resolved merge's tree), then conflicts, then
    signing; a branch merely behind is left to the queue."""
    def g(*a):
        return _git("-C", root, *a)

    if g("rev-parse", "--verify", "-q", f"refs/heads/{br}")[0]:
        return 1, f"error: no branch {br} in {root}\n"
    out = []
    wts, cur = "", ""
    for ln in g("worktree", "list", "--porcelain")[1].split("\n"):
        if ln.startswith("worktree "):
            cur = ln[9:]
        elif ln == f"branch refs/heads/{br}":
            wts += cur + " "
    out.append(f"worktrees: {wts or 'none'}")

    bases = pr_base_refs(root, br)
    nb = "unknown" if bases is None else str(len([x for x in bases.split("\n") if x]))
    base = ""
    if nb == "1":
        base = bases
        out.append(f"base: {base} (open PR)")
    elif nb == "0":
        base = default_branch(root) or ""
        out.append(f"base: {base or 'unknown'} (default branch, no open PR)")
    elif nb == "unknown":
        base = default_branch(root) or ""
        out.append(f"base: {base or 'unknown'} (assumed: the open-PR lookup failed, so a stacked base would not show)")
    else:
        out.append(f"base: ambiguous -- {nb} open PRs, bases: {bases.replace(chr(10), ' ')}")

    if not base or g("rev-parse", "--verify", "-q", f"origin/{base}")[0]:
        out += ["ahead: unknown", "behind: unknown", "conflicts: unknown", "unsigned: unknown", "merges: unknown",
                "recommend: no base to compare against here -- `git fetch origin` and re-run, or name the base by hand"]
        return 0, "\n".join(out) + "\n"

    rc, lr = g("rev-list", "--left-right", "--count", f"origin/{base}...{br}")
    m = re.match(r"([0-9]+)\s+([0-9]+)", lr) if rc == 0 else None
    behind, ahead = m.groups() if m else ("unknown", "unknown")
    out += [f"ahead: {ahead}", f"behind: {behind}"]

    # merge-tree: 0 clean, 1 conflicted, anything else (a git too old for
    # --write-tree included) is unknown, never "conflicted".
    rc = g("merge-tree", "--write-tree", f"origin/{base}", br)[0]
    conf = "no" if rc == 0 else "yes" if rc == 1 else "unknown"

    rc, revs = g("rev-list", f"origin/{base}..{br}")
    if rc == 0:
        uns = sum(1 for s in revs.split("\n") if s and not re.search(r"^gpgsig", g("cat-file", "-p", s)[1], re.M))
    else:
        uns = "unknown"
    rc, mg = g("rev-list", "--count", "--merges", f"origin/{base}..{br}")
    mg = mg.strip() if rc == 0 else "unknown"
    out += [f"conflicts: {conf}", f"unsigned: {uns}", f"merges: {mg}"]

    rc, mb = g("merge-base", f"origin/{base}", br)
    mb = mb.strip() if rc == 0 else f"origin/{base}"
    if mg == "unknown":
        rec = f"count the merge commits by hand before touching history -- git could not count them between {br} and origin/{base}"
    elif int(mg) > 0 and conf == "no" and uns not in ("unknown", 0) and _merges_all_clean(g, f"origin/{base}..{br}"):
        # No merge holds a hand-resolution, so linearizing drops nothing; base's commits are skipped.
        cmd = f"git rebase -S --force-rebase {mb}"
        if g("config", "user.signingkey")[0] == 0:
            rec = f"{cmd}   # {mg} clean merge commit(s), nothing hand-resolved; push it with git push --force-with-lease"
        else:
            rec = (f"cannot sign on this machine (no user.signingkey) -- {mg} clean merge commit(s); "
                   f"hand over saying `{cmd}` then `git push --force-with-lease` has to run where the key is")
    elif int(mg) > 0 and uns not in ("unknown", 0):
        # Commits above the last merge replay alone; the merge and its tree stay as they are.
        rc, lm = g("rev-list", "--merges", "--topo-order", "-1", f"origin/{base}..{br}")
        lm = lm.strip() if rc == 0 else ""
        rc, below = g("rev-list", f"origin/{base}..{lm}") if lm else (1, "")
        rc2, above = g("rev-list", "--merges", f"{lm}..{br}") if lm else (1, "x")
        if rc == 0 and rc2 == 0 and not above.strip() and not any(
                s and not re.search(r"^gpgsig", g("cat-file", "-p", s)[1], re.M) for s in below.split("\n")):
            cmd = f"git rebase -S --force-rebase {lm[:12]}"
            if g("config", "user.signingkey")[0] == 0:
                rec = f"{cmd}   # {uns} unsigned commit(s) above the last merge; push it with git push --force-with-lease"
            else:
                rec = (f"cannot sign on this machine (no user.signingkey) -- {uns} unsigned commit(s) above the last merge; "
                       f"hand over saying `{cmd}` then `git push --force-with-lease` has to run where the key is")
        elif (rc == 0 and rc2 == 0 and not above.strip() and uns == 1 and lm == g("rev-parse", br)[1].strip()
              and not re.search(r"^gpgsig", g("cat-file", "-p", lm)[1], re.M)):
            # The one unsigned commit is the merge itself, at the tip: an amend re-signs it, tree and parents intact.
            cmd = "git commit --amend -S --no-edit"
            if g("config", "user.signingkey")[0] == 0:
                rec = f"{cmd}   # the unsigned commit is the merge itself, at the tip; push it with git push --force-with-lease"
            else:
                rec = (f"cannot sign on this machine (no user.signingkey) -- the unsigned commit is the merge itself, at the tip; "
                       f"hand over saying `{cmd}` on {br} then `git push --force-with-lease` has to run where the key is")
        else:
            rec = (f"do not rebase and do not resign -- an unsigned commit sits at or below one of the {mg} merge commit(s), "
                   "so the branch cannot be re-signed without losing the merge; hand it over saying so")
    elif int(mg) > 0 and conf != "no":
        rec = (f"do not rebase and do not resign -- {mg} merge commit(s) on the branch; `git merge origin/{base}`, "
               "resolve, commit signed, push as a fast-forward")
    elif conf == "yes":
        rec = f"git merge origin/{base}   # conflicts against the base; resolve, commit, and never linearize the branch afterwards"
    elif conf == "unknown":
        rec = f"check the merge by hand before touching history -- git merge-tree could not answer whether {br} conflicts with origin/{base}"
    elif uns == "unknown":
        rec = f"check the signatures by hand before pushing -- git could not list the commits between origin/{base} and {br}"
    elif uns > 0 and g("config", "user.signingkey")[0] == 0:
        rec = (f"git rebase -S --force-rebase {mb}   # {uns} unsigned commit(s); push it with "
               "git push --force-with-lease")
    elif uns > 0:
        rec = (f"cannot sign on this machine (no user.signingkey) -- {uns} unsigned commit(s) will block the PR; "
               f"hand over saying `git rebase -S --force-rebase {mb}` then `git push --force-with-lease` has to run where the key is")
    else:
        rec = (f"nothing on the base -- signed, no conflict; a branch merely behind origin/{base} is left as is, "
               "the queue updates it (fixup contract, pickup skill section 6)")
    out.append(f"recommend: {rec}")
    return 0, "\n".join(out) + "\n"


# The command line, for the shell tools that need an answer from here:
# `state.py <fn> [args]`. To expose another function, add it
# to CLI. A str result is printed, exit 0; None is "no answer" (exit 1); a
# bool is a predicate, no output, exit 0 for True and 1 for False; a tuple is
# (exit status, text). A store that cannot be read exits 3 with the cause on
# stderr. Argument counts are checked against the signature
# before the call, so an error raised inside a function is never mistaken
# for a usage error.
CLI = {f.__name__: f for f in (
    state_repo, state_dir, state_is_repo, state_shard_path, items_dir, board_union, is_card_id,
    work_claims_load, work_record, board_card, claude_cards, done_board,
    ruling_until, ruling_ref_state, ruling_readiness, rulings_ready,
    pr_base_refs, default_branch, branch_brief, push_locked)}
CLI["item_rows"] = item_rows_text


def done_rows_text():
    """done_rows as work-item printed them; StoreError when unreadable."""
    rows, err = done_rows()
    if err:
        raise StoreError(err)
    return "".join("\t".join(r) + "\n" for r in rows)


CLI["done_rows"] = done_rows_text


def _done_board_cli():
    rows, err = done_rows()
    if err:
        raise StoreError(err)
    return done_board(rows)


CLI["done_board"] = _done_board_cli
CLI["work_records"] = lambda *a: work_records(
    [x for x in a if x != "--cards"], sys.stdin.read() if "--cards" in a else None)


def main(argv):
    if not argv or argv[0] not in CLI:
        print("usage: state.py <%s> [args]" % "|".join(CLI), file=sys.stderr)
        return 2
    fn, args = CLI[argv[0]], argv[1:]
    try:
        inspect.signature(fn).bind(*args)
    except TypeError:
        print("state.py %s: wrong number of arguments" % argv[0], file=sys.stderr)
        return 2
    try:
        out = fn(*args)
    except StoreError as e:
        print(f"BROKEN STORE -- {e}", file=sys.stderr)
        return 3
    if isinstance(out, tuple):  # (exit status, text)
        sys.stdout.write(out[1])
        return out[0]
    if out is None or out is False:
        return 1
    if out is not True:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
