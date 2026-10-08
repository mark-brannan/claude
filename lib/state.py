"""Where durable state lives on this machine, and the shared answers about
it, for the Python tools and hooks. Imported, never run directly; stdlib
only.

The bash hooks' twin is hooks/lib-state.sh, which ~20 shell scripts still
source. The functions here are ports of the ones the Python side needs --
state_repo, state_dir, state_is_repo, state_shard_path, the state_lock
family, unpushed_state, dirty_paths, archivable_reasons, decision_rate --
and must answer exactly as their shell twins do: metrics-live.sh draws its
live nag from the shell archivable_reasons while stop-continuity.py takes
the Stop verdict from this one, and the two must never disagree about
"archivable" (dotfiles#149). lib/state-parity.test.py runs both over the
same fixtures and fails on any difference. Change one, change both.

The locks are the shell's mkdir protocol, not lib/lock.py: metrics-live.sh,
abandon-branch.sh and claim-stamp.sh take the same directories from bash.

The one home for this lookup (dotfiles#517). hooks/lib_state.py re-exports
it; bin tools put this directory on sys.path and `import state`.
"""
import os
import re
import shutil
import subprocess
import time

import gitrun

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


# Answer "does this branch hold commits that exist nowhere but here?" for a
# repo root and the branch name (`HEAD` or empty when detached).
#
# It lives here because two hooks have to agree on the answer: metrics-live.sh
# draws the ⎇ nag and the archival verdict from it, stop-continuity.py's
# set_verdict decides from it whether the session is safe to kill. When each
# had its own copy they drifted -- #148 had to port two carve-outs back into
# metrics-live.sh that the Stop hook had grown in #126 and #128/#143.
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
def dirty_paths(root):
    """git's porcelain lines as it printed them, trailing newline and all."""
    sr = state_repo() or ""
    if sr and _pwd_p(root) == _pwd_p(sr):
        return _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain",
                    "--", ".", ":(exclude)state/")[1]
    return _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain")[1]


# archivable_reasons -- the reasons a session on this branch is not yet
# archivable, comma-joined; empty when it is. Order: worktree dirty,
# unpushed commits, branch home, session live.
#
# Lives here for the same reason unpushed_state does: metrics-live.sh's live
# nag and stop-continuity.py's Stop-hook verdict must never disagree about
# what "archivable" means (dotfiles#149). Before this they didn't even
# agree on what a "home" is -- metrics-live.sh re-checked PR-or-card
# inline and never looked for a pointer issue, the one branch-home-gate.sh
# already finds.
#
# branch-home-gate.sh and claim-stamp.sh live in hook_dir and are shelled
# out to, not sourced, so their own state (branch-home-gate.sh's
# once-per-session gate, claim-stamp.sh's per-session record) never leaks
# into this read-only check.
#
# Home is checked before session-live, and both only when dirty/unpushed are
# already clean: both can shell out to `gh` (branch-home-gate.sh up to two
# 30s calls, claim-stamp.sh one), so a dirty mid-work tree -- the common
# case, and the one Stop fires on every turn -- never pays that cost.
#
# session live (dotfiles#167): git state alone is how a live session's
# worktree got archived out from under it (PR #162, the scar the languette
# plugin's guard-worktrees names). The signal is the claim stamp
# claim-stamp.sh already posts on the branch's card and refreshes on every
# Stop (dotfiles#287); it, not this function, decides fresh vs stale
# (CLAIM_STALE_SECS). self_sid is the caller's own: its own stamp is never a
# reason, or a session could never become archivable by watching its own
# refresh. Omit it (a sweep, a human) and every fresh stamp counts.
#
# Not this function's job: "not a git repo" (there is no branch here to
# judge) and anything that only becomes true after a push is attempted --
# both are the caller's own facts to add.
def archivable(work_root, work_branch, self_sid="", hook_dir=HOOK_DIR):
    """(reasons, home): archivable_reasons, plus the branch-home-gate.sh
    line it read, or None when it never got that far. The Stop hook's
    pickup item wants the same home line and must not pay
    branch-home-gate.sh's gh round trip a second time in one Stop."""
    reasons = []
    home = None
    if dirty_paths(work_root).rstrip("\n"):
        reasons.append("worktree dirty")

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
        home = _cap(["sh", f"{hook_dir}/branch-home-gate.sh", "--check", work_root])
        if home.startswith("home:"):
            pass
        elif home.startswith("unverified:"):
            why = home[len("unverified: "):] if home.startswith("unverified: ") else home
            reasons.append(f"branch home unverified ({why})")
        else:
            reasons.append(f"no PR and no pointer for `{work_branch}`")

    cs = f"{hook_dir}/claim-stamp.sh"
    if not reasons and os.access(cs, os.X_OK):
        self8 = self_sid[:8]
        for line in _cap(["sh", cs, "read", "-C", work_root]).split("\n"):
            f = line.split("\t")
            if f[0] == "live" and (f[1] if len(f) > 1 else "") != self8:
                reasons.append("session live")
                break

    return ", ".join(reasons), home


def archivable_reasons(work_root, work_branch, self_sid="", hook_dir=HOOK_DIR):
    return archivable(work_root, work_branch, self_sid, hook_dir)[0]


# state_lock / state_unlock -- mkdir atomic test-and-set, the same protocol
# and the same `meta` file as lib-state.sh's (copied there from grind's
# per-repo lock; no flock: macOS has none), so a lock taken here holds
# against metrics-live.sh, abandon-branch.sh and claim-stamp.sh taking it
# from bash, and the other way round. meta carries pid+host; a same-host
# dead pid is reclaimed via rename-then-rm. A dir with no meta at all (a
# kill between mkdir and the meta write) has no pid to check; one older
# than STATE_LOCK_STALE_SECS (default 5) is reclaimed regardless. One lock
# at a time, as in the shell: the caller releases it on every exit path.
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
                pass  # gone already: the rename below fails, as the shell's mv does
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
# stop-continuity.py and abandon-branch.sh share, fixed at import as the
# shell fixes it when sourced.
STATE_PUSH_LOCK = f"{os.environ.get('TMPDIR') or '/tmp'}/claude-state-push.lock.d"


def state_lock_wait(d, secs=90):
    n = secs
    while not state_lock(d):
        if n <= 0:
            return False
        n -= 1
        time.sleep(1)
    return True


_NUM = re.compile(r"[ \t\n]*[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?")


def _awk_num(s):
    """A string as awk reads it as a number: its leading numeric part, or 0."""
    m = _NUM.match(str(s))
    return float(m.group(0)) if m else 0.0


# decision_rate -- "<n> decisions in 1h10 (2.6/h)", or "" when the session
# clock (first prompt to last) is under a minute. Measured, never alarmed
# (one-entry-point §5, 2026-09-30): the two places that call it are the
# session-start brief and the Stop checkpoint, nothing else. Without the
# shell's trailing newline.
def decision_rate(decisions=0, span=0):
    d, s = _awk_num(decisions), _awk_num(span)
    if s < 60:
        return ""
    m = int(s / 60 + 0.5)
    one = re.fullmatch(r"[ \t\n]*" + _NUM.pattern + r"[ \t\n]*", str(decisions)) and d == 1
    return "%d decision%s in %dh%02d (%.1f/h)" % (d, "" if one else "s", m // 60, m % 60,
                                                   d * 3600 / s)
