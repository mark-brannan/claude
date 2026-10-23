"""Where durable state lives on this machine, and the shared answers about
it, for the Python tools and hooks. Imported, never run directly; stdlib
only.

The bash hooks' twin is hooks/lib-state.sh, which ~20 shell scripts still
source. The functions here are ports of the ones the Python side needs --
state_repo, state_dir, state_is_repo, state_shard_path, the state_lock
family, unpushed_state, dirty_paths, archivable_reasons, decision_rate,
names_branch, items_dir, board_union --
and must answer exactly as their shell twins do: shell hooks still read
"archivable" and the rest from lib-state.sh, and the two must never disagree
(dotfiles#149). lib/state-parity.test.py runs both over the same fixtures
and fails on any difference. Change one, change both. GIT_EVENT_RE,
buffered_state, verdict_explain and day_decisions have no shell twin: only
metrics-live.py reads them.

The locks are the shell's mkdir protocol, not lib/lock.py: abandon-branch.py
takes the same directories, claim-stamp.py through this module.

The one home for this lookup (dotfiles#517). hooks/lib_state.py re-exports
it; bin tools put this directory on sys.path and `import state`.
"""
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
def dirty_paths(root):
    """git's porcelain lines as it printed them, trailing newline and all."""
    sr = state_repo() or ""
    if sr and _pwd_p(root) == _pwd_p(sr):
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
    """text names branch as a whole token, not merely as a substring, as
    lib-state.sh's names_branch: every maximal run of branch-name characters
    is a token, and one must equal the branch. claude/homed-extra does not
    name claude/homed. The charset strips prose punctuation such as a
    trailing comma or backquote; a period is a branch character, so a
    branch that ends a sentence is not named, in either language."""
    return bool(branch) and branch in re.findall(r"[A-Za-z0-9._/+@-]+", text or "")


def items_dir():
    """The work-item store's directory: $WORK_ITEM_DIR, else items/ in the
    state dir, as lib-state.sh's items_dir."""
    return os.environ.get("WORK_ITEM_DIR") or f"{state_dir()}/items"


def board_union(hook_dir=HOOK_DIR):
    """The store as one board text, as lib-state.sh's board_union: every
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


def _item_rows(hook_dir):
    """work-item list's rows for the store (`id owner status holder updated
    repo line`, split on tabs); [] when there is no items/ or it cannot be
    read, as lib-state.sh's item_rows."""
    d = items_dir()
    if not os.path.isdir(d):
        return []
    for wi in (os.environ.get("WORK_ITEM_BIN", ""), f"{hook_dir}/../bin/work-item",
               f"{os.environ.get('HOME', '')}/.claude/bin/work-item"):
        if wi and os.path.isfile(wi):
            break
    else:
        return []
    out = _cap([sys.executable, wi, "list"], env=dict(os.environ, WORK_ITEM_DIR=d))
    return [ln.split("\t") for ln in out.split("\n") if ln]


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
# already clean: both can shell out to `gh` (branch-home-gate.py up to two
# 30s calls per mode, and session-live asks for its --card after the home
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


# state_lock / state_unlock -- mkdir atomic test-and-set, the same protocol
# and the same `meta` file as lib-state.sh's (copied there from grind's
# per-repo lock; no flock: macOS has none), so a lock taken here holds
# against abandon-branch.py taking it, and the other way
# round. meta carries pid+host; a same-host
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
# stop-continuity.py and abandon-branch.py share, fixed at import as the
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


# buffered_state -- in the state repo only, one line naming what dirty_paths
# left out: the uncommitted files under state/. stop-continuity.py has already
# committed this Stop's by the time the readout runs, so what is left was
# written since, or its commit failed; the next Stop commits it. Leaving them
# out of the verdict is right; leaving them unsaid is not: a hand-off or card
# still on disk is worth knowing about. Metrics are counted, everything else
# is named. "" elsewhere, and when nothing is buffered.
def buffered_state(root):
    sr = state_repo()
    if not sr or _pwd_p(root) != _pwd_p(sr):
        return ""
    text = _git("-C", root, "-c", "core.quotePath=off", "status", "--porcelain",
                "--untracked-files=all", "--", "state/")[1]
    paths = []
    for p in _porcelain_paths(text):
        p = p[len("state/global/"):] if p.startswith("state/global/") else p
        p = p[len("state/"):] if p.startswith("state/") else p
        paths.append(p)
    if not paths:
        return ""
    named = ", ".join(p for p in paths if not p.startswith("metrics/"))
    nm = sum(1 for p in paths if p.startswith("metrics/"))
    if nm:
        named = f"{named + ', ' if named else ''}+ {nm} metrics file{'' if nm == 1 else 's'}"
    return f"→ buffered in the state repo, not committed yet (the next Stop commits it): {named}"


# verdict_explain -- one line per reason the verdict names: what is at risk,
# then what to do. Matched by pattern, not split on commas: a reason's own
# text can hold one. A reason with no line here is still printed in the
# verdict itself. Given the tree, the dirty line names the files.
_EXPLAIN = (
    (("not a git repo",),
     "→ not a git repo: the session ran outside any repo, so there was no branch to check."),
    (("worktree dirty",), None),
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
_DIRTY_TAIL = "Normal mid-task: the agent commits them when the work lands. Archive the worktree only after that."


def verdict_explain(verdict, root=""):
    """The explanation lines, newline-joined; "" when no reason has one."""
    lines = []
    for needles, line in _EXPLAIN:
        if not any(n in verdict for n in needles):
            continue
        if line is not None:
            lines.append(line)
            continue
        paths = _porcelain_paths(dirty_paths(root)) if root else []
        if paths:
            shown = ", ".join(paths[:3]) + (f", +{len(paths) - 3} more" if len(paths) > 3 else "")
            lines.append(f"→ worktree dirty: {len(paths)} uncommitted file(s) ({shown}). {_DIRTY_TAIL}")
        else:
            lines.append(f"→ worktree dirty: uncommitted files in this worktree. {_DIRTY_TAIL}")
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
