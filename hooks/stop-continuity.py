#!/usr/bin/env python3
"""Stop hook: record the session, then commit and push it. Every time.

This is the load-bearing half of continuity. The standing orders say chats
are ephemeral executors and durable state lives in files -- but a rule that
only fires when someone says "wrap up" loses every session that ends any
other way, which on an ephemeral cloud container is most of them. So this
runs unconditionally on Stop and needs nothing from the conversation.

It writes eight things, all derived from the transcript and from git:
(each <dir>/<id>.* below sits in <dir>/<first two of id>/; lib/state.py
state_shard_path)
  metrics/sessions/<id>.json    cost and shape of the session
  metrics/decisions/<id>.jsonl  each decision pushed to the user, typed by cost
  metrics/friction/<id>.jsonl   each friction event, typed by cost -- see
                                 claude_prompts_scratch/state/global/log/
                                 2026-08-21-friction-metric-spec.md
  metrics/blocked/<id>.jsonl    each tool call the permission layer refused
  metrics/critical-review/<id>.jsonl  each /critical-review typed, its cost
                                 and outcome, via lib/critical_review.py
  log/auto/<date>-<repo>-<id>.md  a resumable checkpoint the next session reads
  pickup/<start>-<id>.md        this session's pickup item, which /pickup reads
  items/<id>.md                 this session's work item, via stop-item.py
  curia/<id>/digest.md          a floor stamped on any curia digest the
                                 session touched

One file per session, not one shared append-only log: parallel sessions are
normal here, and per-session paths mean two of them never touch the same
file and so never conflict on push.

A port of stop-continuity.sh (dotfiles#517), byte for byte in what it
writes. The transcript is still read by session-metrics.jq, through jq;
everything after that is plain Python, and the shared answers --
archivable, the locks, where state lives -- are lib/state.py's, which
lib/state-parity.test.py holds equal to lib-state.sh's.

Always exits 0. A metrics hook that can fail a session is worse than no
metrics hook. Stdlib only.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

# The whitespace [[:space:]] matches under gawk and GNU grep in a UTF-8
# locale (glibc's iswspace), and the ASCII subset tr's byte-wise class takes.
WS = " \t\n\v\f\r              　"
WS_ASCII = " \t\n\v\f\r"


# ------------------------------------------------------------ jq, by hand
# The transcript's metrics come back from jq as one JSON document; every
# later jq step of the shell hook is done here. Numbers keep the literal
# text jq printed (jq preserves a literal it did not compute on), so a
# re-serialized record is jq -c's byte for byte.
class Num:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def parse(text):
    return json.loads(text, parse_int=Num, parse_float=Num)


def parse_stream(text):
    """Every JSON value in text, as jq reads a file of them."""
    dec = json.JSONDecoder(parse_int=Num, parse_float=Num)
    vals, i = [], 0
    while True:
        while i < len(text) and text[i] in " \t\n\r":
            i += 1
        if i == len(text):
            return vals
        v, i = dec.raw_decode(text, i)
        vals.append(v)


def jq_c(v):
    """jq -c's rendering of one value."""
    if isinstance(v, Num):
        return v.text
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False).replace("\x7f", "\\u007f")
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ",".join(jq_c(x) for x in v) + "]"
    return "{" + ",".join(jq_c(k) + ":" + jq_c(x) for k, x in v.items()) + "}"


def jq_pretty(v, ind=0):
    """jq's default (indented) rendering, which jq -r uses for containers."""
    pad = "  " * (ind + 1)
    if isinstance(v, list) and v:
        return "[\n" + ",\n".join(pad + jq_pretty(x, ind + 1) for x in v) + "\n" + "  " * ind + "]"
    if isinstance(v, dict) and v:
        return ("{\n" + ",\n".join(pad + jq_c(k) + ": " + jq_pretty(x, ind + 1) for k, x in v.items())
                + "\n" + "  " * ind + "}")
    return jq_c(v)


def tostr(v):
    """A value interpolated into a jq string, \\(v)."""
    return v if isinstance(v, str) else jq_c(v)


def raw(v):
    """A value as jq -r prints it, less the newline."""
    return v if isinstance(v, str) else jq_pretty(v)


def get(v, *keys):
    for k in keys:
        v = v.get(k) if isinstance(v, dict) else None
    return v


def alt(v, default):
    """v // default"""
    return default if v is None or v is False else v


def each(v):
    """.[]: an array's elements, an object's values; nothing for the rest."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def jq_add(a, b):
    """a + b for the object cases the hook uses, or None when jq would err."""
    if a is None:
        return b
    if isinstance(a, dict):
        return {**a, **b}
    return None


# ------------------------------------------------------------ shell, by hand
def sub(s):
    """Text as $(...) captures it: NUL bytes dropped, trailing newlines cut."""
    return s.replace("\0", "").rstrip("\n")


def basename(p):
    s = p.rstrip("/")
    if not s:
        return "/" if p else ""
    return s.rsplit("/", 1)[-1]


def records(text):
    """The lines awk and sed read: split on \\n, no empty last one for a
    trailing newline."""
    if text == "":
        return []
    lines = text.split("\n")
    return lines[:-1] if text.endswith("\n") else lines


def prefix_lines(text, pre):
    """sed 's/^/pre/' over text, keeping a missing final newline missing."""
    lines = records(text)
    out = "\n".join(pre + ln for ln in lines)
    return out + "\n" if text.endswith("\n") else out


_AWK_ESC = {"\\": "\\", '"': '"', "/": "/", "a": "\a", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t", "v": "\v"}


def awk_v(s):
    """A value as gawk's -v assignment sees it, escape sequences processed."""
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c != "\\" or i + 1 == len(s):
            out.append(c)
            i += 1
            continue
        n = s[i + 1]
        if n in _AWK_ESC:
            out.append(_AWK_ESC[n])
            i += 2
        elif n in "01234567":
            m = re.match(r"[0-7]{1,3}", s[i + 1:]).group(0)
            out.append(chr(int(m, 8) & 0xFF))
            i += 1 + len(m)
        elif n == "x" and re.match(r"[0-9A-Fa-f]", s[i + 2:i + 3]):
            m = re.match(r"[0-9A-Fa-f]{1,2}", s[i + 2:]).group(0)
            out.append(chr(int(m, 16)))
            i += 2 + len(m)
        else:
            out.append(n)
            i += 2
    return "".join(out)


def read(path):
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        return f.read()


def write(path, text, mode="w"):
    with open(path, mode, encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)


def append(path, text):
    try:
        write(path, text, "a")
    except OSError:
        pass


def rm_f(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def tr_name(s):
    """tr -c 'A-Za-z0-9_-' '_', byte by byte."""
    return "".join(chr(b) if (chr(b).isascii() and (chr(b).isalnum() or chr(b) in "_-")) else "_"
                   for b in s.encode("utf-8", "surrogateescape"))


def tmpdir():
    return os.environ.get("TMPDIR") or "/tmp"


def cap(argv, **kw):
    """$(argv 2>/dev/null): its stdout, byte for byte, as $(...) keeps it."""
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **kw)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, sub(p.stdout.decode("utf-8", "surrogateescape"))


def quiet(argv, **kw):
    """argv >/dev/null 2>&1; its exit status."""
    try:
        return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw).returncode
    except (OSError, subprocess.SubprocessError):
        return 127


# The child bounded() is waiting on, if any. It runs in a session of its
# own, so a signal to this hook's group never reaches it: _bye must stop it
# before the push lock comes off, or a `git push` or `pull --rebase` would
# outlive the lock and race the next Stop's in the same clone.
_child = None


def stop_group(p, grace=5, collect=True):
    """TERM p's whole process group, KILL it after grace seconds; its output
    when collect. A signal handler passes collect=False: the communicate()
    it interrupted still owns the pipes, so it only waits."""
    out = b""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(p.pid, sig)
        except OSError:
            pass
        try:
            if collect:
                out, _ = p.communicate(timeout=grace)
            else:
                p.wait(timeout=grace)
            break
        except subprocess.TimeoutExpired:
            out = b""
    return out


def bounded(argv, secs, capture=False):
    """timeout <secs> argv, as timeout(1) runs it: its own process group,
    signalled whole on expiry, 124 then. (rc, stdout) -- stdout as $(...)
    keeps it, partial on a timeout, when capture."""
    global _child
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return 127, ""
    _child = p
    try:
        out, _ = p.communicate(timeout=secs)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        out = stop_group(p)
        rc = 124
    finally:
        _child = None
    return rc, sub((out or b"").decode("utf-8", "surrogateescape"))


def git(*args):
    """git's (returncode, stdout as $(...) keeps it), every byte kept."""
    p = gitrun.exact(*args)
    return p.returncode, sub(p.stdout)


def git_ok(*args):
    return gitrun.run(*args, binary=True).returncode == 0


def git_bounded(secs, *args):
    return bounded(["git", *args], secs)[0]


# ------------------------------------------------------------ the Stop
class Stop:
    def __init__(self, sid, tp, cwd):
        self.sid, self.tp, self.cwd = sid, tp, cwd
        t = time.gmtime()
        self.now = time.strftime("%Y-%m-%dT%H:%M:%SZ", t)
        self.today = time.strftime("%Y-%m-%d", t)
        self.verdict = ""
        self.reasons = None  # archivable's answer, cached across set_verdict calls
        self.home = None     # and the home line it read, for the pickup item
        self.pi_branch_line = "none"
        self.pi_pr = "none"

    def s(self, *keys, default=""):
        """$(printf '%s' "$metrics" | jq -r '.session.<keys> // <default>')"""
        return sub(raw(alt(get(self.metrics, "session", *keys), default)))

    def run(self):
        sid, cwd = self.sid, self.cwd
        jqprog = f"{HOOK_DIR}/session-metrics.jq"
        if not os.path.isfile(jqprog):
            return

        # Working repo (the one being worked on), distinct from the state repo.
        self.work_root = git("-C", cwd, "rev-parse", "--show-toplevel")[1]
        self.work_repo = basename(self.work_root) if self.work_root else basename(cwd)
        self.work_branch = git("-C", cwd, "rev-parse", "--abbrev-ref", "HEAD")[1]
        work_root, work_repo = self.work_root, self.work_repo

        rc, out = cap(["jq", "-s", "--arg", "sid", sid, "--arg", "repo", work_repo,
                       "--arg", "branch", self.work_branch, "--arg", "cwd", cwd,
                       "--arg", "now", self.now,
                       "--arg", "slug", f"{self.today}-{work_repo}-{sid[:8]}",
                       "-f", jqprog, self.tp])
        if rc != 0 or not out:
            return
        self.metrics = metrics = parse(out)

        self.SD = SD = state.state_dir()
        LIVE = f"{SD}/metrics/live"
        self.SESSF = state.state_shard_path(f"{SD}/metrics/sessions", f"{sid}.json", sid)
        DECF = state.state_shard_path(f"{SD}/metrics/decisions", f"{sid}.jsonl", sid)
        FRICF = state.state_shard_path(f"{SD}/metrics/friction", f"{sid}.jsonl", sid)
        BLKF = state.state_shard_path(f"{SD}/metrics/blocked", f"{sid}.jsonl", sid)
        self.ckpt = ckpt = state.state_shard_path(f"{SD}/log/auto",
                                                  f"{self.today}-{work_repo}-{sid[:8]}.md", sid)
        try:
            for d in (self.SESSF, DECF, FRICF, BLKF, ckpt):
                os.makedirs(os.path.dirname(d), exist_ok=True)
            os.makedirs(LIVE, exist_ok=True)
        except OSError:
            return

        # The per-session lock metrics-live.sh's nag read-modify-write also
        # takes (dotfiles#161). main() releases whatever is held on every way
        # out; a failed acquisition degrades to running unlocked rather than
        # skipping the write -- a metrics hook never blocks Stop.

        # Commit count comes from git, never from grepping the transcript for
        # "git commit": a heredoc that writes a script containing that string
        # is indistinguishable from actually running it.
        self.started = started = self.s("started_at")
        ncommits = "0"
        if work_root:
            rc, ncommits = git("-C", work_root, "rev-list", "--count",
                               f"--since={started or '1 day ago'}", "HEAD")
            if rc != 0:  # `|| echo 0`, after whatever git did print
                ncommits = ncommits + "\n0" if ncommits else "0"
        try:
            session = jq_add(get(metrics, "session"), {"commits": parse(ncommits or "0")})
            write(self.SESSF, "" if session is None else jq_c(session) + "\n")
        except (ValueError, OSError):
            try:
                write(self.SESSF, "")
            except OSError:
                pass
        for path, key in ((DECF, "decisions"), (FRICF, "friction"), (BLKF, "blocked")):
            try:
                write(path, "".join(jq_c(x) + "\n" for x in each(get(metrics, key))))
            except OSError:
                pass
        # One row per /critical-review the user typed, to
        # metrics/critical-review/<id>.jsonl; a failure there never costs the rest.
        try:
            import critical_review
            critical_review.record_session(sid, self.tp, cwd)
        except Exception:
            pass

        # The live snapshot has served its purpose; the finished session file
        # supersedes it, so drop it rather than leaving two records of one
        # session. Locked against a concurrent metrics-live.sh writing the
        # same path (#161 finding 4); a lock that could not be taken still
        # gets the delete, just unprotected -- deleting nothing is not a safer
        # failure than a stale file.
        state.state_lock(f"{LIVE}/{sid}.lock")
        rm_f(state.state_shard_path(LIVE, f"{sid}.json", sid))
        state.state_unlock()
        try:
            subprocess.run(["bash", f"{HOOK_DIR}/metrics-rollup.sh"], stderr=subprocess.DEVNULL)
        except OSError:
            pass

        self.checkpoint(LIVE)

        # One pusher at a time. Parallel sessions are the norm, and two
        # concurrent rebase-and-push loops in the same worktree corrupt each
        # other's index. main()'s finally releases it.
        if not state.state_lock_wait(state.STATE_PUSH_LOCK, 90):
            return

        self.sc_salvage()
        # After the salvage, not before: the verdict has to describe the tree
        # the salvage leaves behind. It leaves it dirty on purpose -- the work
        # is safe on the wip ref, not landed on the branch -- so "worktree
        # dirty" stays the truth and the session is not archivable until a
        # human lands it.
        self.set_verdict()

        # The session claim stamp on the branch's card (dotfiles#287).
        # Archivable means this session is done with the branch, so the claim
        # comes off; anything else means it is still holding it, so the
        # timestamp is bumped -- which is what makes another machine able to
        # tell a live session from a dead one.
        #
        # Free when this session never claimed anything: both paths read a
        # per-session record under TMPDIR first and return without a network
        # call when there is none, and the refresh is debounced besides. Stop
        # fires on every turn, so that has to stay true.
        cs = f"{HOOK_DIR}/claim-stamp.sh"
        if self.work_root and os.access(cs, os.X_OK):
            verb = "release" if self.verdict == "archivable" else "refresh"
            quiet(["sh", cs, verb, "-C", self.work_root, sid])

        self.pickup_item()
        self.session_item()
        self.curia_digests()
        self.state_repo_commit()

    # ---------------------------------------------------------- checkpoint
    def checkpoint(self, LIVE):
        m, sid, ckpt, work_root = self.metrics, self.sid, self.ckpt, self.work_root
        # The resume block (dotfiles#110) is the one part of this file a
        # *model* writes, and this hook rewrites the whole file on every Stop
        # -- so it has to be lifted out of the old copy and put back, or the
        # next Stop silently eats the hand-off the model was told to write.
        # Everything from the `## Resume` heading to the next `## ` heading is
        # carried verbatim, including the `- consumed:` marker a resuming
        # session appends. Locked (#161 finding 2): metrics-live.sh's
        # resume_ckpt() greps this same file, and the truncate below must not
        # land mid-read.
        state.state_lock(f"{LIVE}/{sid}.lock")
        resume_block = ""
        if os.path.isfile(ckpt):
            block, f = [], False
            try:
                old = read(ckpt)
            except OSError:
                old = ""
            for ln in records(old):
                if re.fullmatch("## Resume[" + WS + "]*", ln):
                    f = True
                    block.append(ln)
                    continue
                if f and ln.startswith("## "):
                    break
                if f:
                    block.append(ln)
            resume_block = sub("".join(ln + "\n" for ln in block))

        s = get(m, "session")
        o = [f"# Auto-checkpoint — {self.work_repo} @ `{self.work_branch}`", ""]
        # The verdict is the first thing in the file because it is the one
        # line a reader needs: archivable means archive, no wrap-up. It cannot
        # be computed yet -- the salvage commit and the state-repo push have
        # not happened -- so it starts as a refusal and set_verdict()
        # substitutes it below. A Stop that dies in between leaves this line,
        # which is the truth: nothing was decided.
        o += ["**Verdict:** not archivable: the Stop hook did not finish", "",
              "Machine-written by `stop-continuity.py`; rewritten on every Stop, so",
              "this is the session's current state, not a history. Narrative entries",
              "belong in `log/` proper.", ""]
        if work_root:
            o.append(f"- worktree `{work_root}`")

        def v(*keys, default=None):
            x = get(s, *keys)
            return tostr(x if default is None else alt(x, default))
        o += [f"- session `{v('session_id')}` · {v('model', default='?')} · started {v('started_at', default='?')}",
              f"- {v('user_turns')} prompts, {v('assistant_turns')} turns, {v('tool_calls')} tool calls",
              f"- {v('output_tokens')} output tokens, context peak {v('context_peak')}",
              f"- decisions: {v('decisions', 'total')} total ({v('decisions', 'scoping')} scoping, "
              f"{v('decisions', 'inline')} inline, {v('decisions', 'gate')} gate)",
              f"- friction: {v('friction', 'total')} total ({v('friction', 'correction')} correction, "
              f"{v('friction', 'override')} override, {v('friction', 'rebuke')} rebuke, "
              f"{v('friction', 'pushback')} pushback)",
              f"- blocked: {v('blocked', 'total', default=Num('0'))} tool calls refused "
              f"({v('blocked', 'classifier', default=Num('0'))} classifier, "
              f"{v('blocked', 'rule', default=Num('0'))} rule, "
              f"{v('blocked', 'user', default=Num('0'))} user-declined)"]

        rate = state.decision_rate(self.s("decisions", "total", default=Num("0")),
                                   self.s("prompt_span_seconds", default=Num("0")))
        if rate:
            o.append(f"- decision rate: {rate}")

        if resume_block:
            o += ["", resume_block]

        if work_root:
            o += ["", "## Commits this session", ""]
            c = git("-C", work_root, "log", "--oneline",
                    f"--since={self.started or '1 day ago'}", "-20")[1]
            o.append(prefix_lines(c + "\n", "- ").rstrip("\n") if c else "- none")

            o += ["", "## Uncommitted at Stop", ""]
            u = sub("".join(ln + "\n" for ln in records(state.dirty_paths(work_root))[:40]))
            o.append(f"```\n{u}\n```" if u else "clean")

            up = git("-C", work_root, "rev-list", "--count", "@{u}..HEAD")[1]
            if up and up != "0":
                o += ["", f"**{up} commit(s) not pushed.**"]

        text = "\n".join(o) + "\n"

        # branch-home-gate.sh writes one line per outcome to a per-session
        # file under TMPDIR; this is where it becomes durable. The checkpoint
        # is rewritten on every Stop, so the gate cannot append to it directly.
        bh = f"{tmpdir()}/claude-branch-home.{tr_name(sid)}"
        try:
            bh_text = read(bh) if os.path.getsize(bh) > 0 else ""
        except OSError:
            bh_text = ""
        if bh_text:
            text += "\n## Branch home\n\n" + prefix_lines(bh_text, "- ")

        dq = sub("".join(f"- ({tostr(get(d, 'type'))}) {tostr(get(d, 'question'))}\n"
                         for d in each(get(m, "decisions"))))
        if dq:
            text += "\n## Decisions pushed to the user\n\n" + dq + "\n"

        try:
            write(ckpt, text)
        except OSError:
            pass
        state.state_unlock()

    # ------------------------------------------------------------ work repo
    # Salvage whatever the session left uncommitted in the repo it worked on:
    # commit it to this session's own `wip/<session-id>` ref and push that,
    # never the branch the session is working on. Silent when there is
    # nothing to do; every refusal after that is named in the checkpoint so
    # it can carry whatever detail turns out to be useful.
    def sc_note(self, msg):
        append(self.ckpt, f"\n## Stop-commit\n\n{msg}\n")

    # Whether a commit made here should be signed: yes exactly when this
    # machine has a signing key, the same test no-unsigned-push.sh uses (`git
    # config user.signingkey`) so the two can never disagree. A commit made
    # unsigned on a machine with a key is what that guard then refuses to
    # push, forcing every other session here to re-sign it; a cloud VM has no
    # key and stays unsigned. The value for `-c commit.gpgsign=`. (The
    # work-repo salvage commit below does not use this: it is fail-closed and
    # forces `true`, keyless or not.)
    @staticmethod
    def sign_if_key(d):
        return "true" if git_ok("-C", d, "config", "user.signingkey") else "false"

    # ------------------------------------------------------------ the verdict
    # set_verdict [extra reason] -- computes the archive verdict (dotfiles#110)
    # and writes it into the checkpoint's placeholder line and into the
    # session's metrics record. Idempotent: it rewrites whatever verdict line
    # is already there, so it can be called again once the state-repo push
    # has been tried.
    #
    # "wrap up" is expensive and was being paid every session, including
    # sessions whose work already had a home. Archivable means archive; wrap
    # up only when the session holds something no issue, PR or card carries.
    # Four conditions, reasons named in this order:
    #   1. the branch has a home -- an open PR, or a pointer card/issue (#108).
    #      branch-home-gate.sh --check answers it, so this verdict and that
    #      gate can never disagree about what counts as a home;
    #   2. the worktree is clean;
    #   3. nothing is unpushed;
    #   4. this session's state is committed to the state repo -- locally is
    #      enough on a machine that keeps its clone, and the push batches. A
    #      cloud VM's clone dies with the VM, so there the push must also
    #      succeed. Other sessions' unpushed commits in the same clone are
    #      theirs, never a reason here. Passed in by the caller: not known
    #      until the bottom.
    # "Could not verify" is never a pass, here as in the gate.
    #
    # This is the one verdict. metrics-live.sh's 📦 notice runs after this
    # hook (stop-sequence.py) and reads it back from the metrics record,
    # verdict_at included, rather than computing its own (dotfiles#149's
    # second answer).
    def set_verdict(self, extra=""):
        # Cached across calls: nothing about work_root changes between the
        # salvage and the state-repo push below, and the home check costs a
        # `gh` round trip. archivable() is lib/state.py's -- the
        # home/dirty/unpushed check shared with metrics-live.sh's live nag, so
        # the two can never disagree about what "archivable" means (#149).
        if self.reasons is None:
            if self.work_root:
                self.reasons, self.home = state.archivable(self.work_root, self.work_branch,
                                                           self.sid, HOOK_DIR)
            else:
                # The label metrics-live.sh's notice used before it read this
                # verdict back; "no PR and no pointer for ``" named a branch
                # that isn't there.
                self.reasons = "not a git repo"
        reasons = ", ".join(r for r in (self.reasons, extra) if r)
        self.verdict = f"not archivable: {reasons}" if reasons else "archivable"

        # Substitute rather than append: the line is at a known place and a
        # second verdict line would be a second answer.
        line = awk_v(f"**Verdict:** {self.verdict}")
        try:
            lines = records(read(self.ckpt))
        except OSError:
            lines = None
        if lines is not None:
            for i, ln in enumerate(lines):
                if ln.startswith("**Verdict:** "):
                    lines[i] = line
                    break
            tmpc = f"{self.ckpt}.verdict.{os.getpid()}"
            try:
                write(tmpc, "".join(ln + "\n" for ln in lines))
                os.replace(tmpc, self.ckpt)
            except OSError:
                rm_f(tmpc)

        sf = self.SESSF
        if os.path.isfile(sf):
            tmpj = f"{sf}.{os.getpid()}"
            try:
                add = {"verdict": self.verdict, "verdict_at": int(time.time())}
                vals = [jq_add(x, add) for x in parse_stream(read(sf))]
                if any(x is None for x in vals):
                    raise ValueError("not an object")
                write(tmpj, "".join(jq_c(x) + "\n" for x in vals))
                os.replace(tmpj, sf)
            except (ValueError, OSError):
                rm_f(tmpj)

    def sc_salvage(self):
        work_root, sid = self.work_root, self.sid
        # --- silent exits: the normal case for most sessions -----------------
        # Not inside a git repo at all.
        if not work_root:
            return
        # The state repo is committed by its own section below.
        if work_root == (state.state_repo() or ""):
            return
        # Deliberately switched off.
        if (os.environ.get("CLAUDE_STOP_COMMIT") or "on") == "off":
            return
        # Nothing uncommitted (tracked or untracked).
        if not git("-C", work_root, "status", "--porcelain")[1]:
            return

        # Re-read the branch: the value captured at hook start can be stale by
        # now if anything detached HEAD since (e.g. a hand-run
        # abandon-branch.sh), and pushing the name it used to have would put
        # an abandoned branch straight back on the remote.
        self.work_branch = work_branch = git("-C", work_root, "rev-parse", "--abbrev-ref", "HEAD")[1]

        # --- named refusals: something is dirty but we will not touch it -----
        # Settled policy, ruled by Solace on 2026-09-22 in issue #61: there is
        # no policy table and none is coming. The conservative default lives
        # here, in this public repo, reviewable beside the code it governs;
        # the only inputs from outside are reduce-only (CLAUDE_STOP_COMMIT=off,
        # the CI refusal), so nothing outside this file can grant the hook
        # privilege it does not have. Only the private state repo goes direct
        # to main -- its own code path at the bottom of this script, not a
        # policy entry -- and the fallback for everything else is the
        # `wip/<session>` ref below, never the session's own branch. These
        # refusals fail closed on purpose: the files stay on disk, with the
        # reason in the checkpoint.
        # dotfiles: the worktree is $HOME and only yadm's pre_commit gate may
        # commit there.
        if work_root == os.environ.get("HOME", ""):
            return self.sc_note("refused: checkout is $HOME (yadm gate); not committing")
        # The default branch is never committed to unattended.
        if work_branch in ("main", "master", "HEAD", ""):
            return self.sc_note(f"refused: on `{work_branch}`; uncommitted work left in place")
        # Only a checkout Claude Code created: a .claude/worktrees path or a
        # claude/ branch. A human's checkout on a human branch is not ours to
        # commit into.
        claude_made = "/.claude/worktrees/" in work_root or work_branch.startswith("claude/")
        if not claude_made:
            return self.sc_note(f"refused: `{work_root}` on `{work_branch}` does not look Claude-made")
        # Nowhere to push.
        if not git_ok("-C", work_root, "remote", "get-url", "origin"):
            return self.sc_note("refused: no origin remote")
        # Never from CI. The shared PR reviewer runs Claude Code inside GitHub
        # Actions with this hook seeded from main, on a checkout whose .claude/
        # paths claude-code-action has restored to the base branch's versions,
        # with an app token that can push. Its Stop has nothing to salvage,
        # and what it did salvage were the "wip: session ... at Stop" reverts
        # of dotfiles#196.
        if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
            return self.sc_note("refused: running under CI (GITHUB_ACTIONS/CI set); a bot's checkout is not a session's work")
        # Never on top of a stale base. If the remote has moved since this
        # checkout last synced (a re-push by hand, another session, anything),
        # the push below would be rejected as non-fast-forward and the note
        # would tell a reader to "push by hand" -- and the obvious hand push
        # of a stale base is a force-push over the newer work. Fetch and
        # check first.
        if (git_bounded(60, "-C", work_root, "fetch", "-q", "origin", work_branch) == 0
                and git_ok("-C", work_root, "rev-parse", "-q", "--verify",
                           f"refs/remotes/origin/{work_branch}")):
            behind = git("-C", work_root, "rev-list", "--count", f"HEAD..origin/{work_branch}")[1]
            if re.fullmatch(r"[ \t]*[0-9]+[ \t]*", behind) and int(behind) > 0:
                return self.sc_note(f"refused: `{work_branch}` is {behind} commit(s) behind "
                                    f"`origin/{work_branch}`; not committing on a stale base")
        # Never a revert of the branch's own work. The tree can be "dirty"
        # because something put the base branch's version of a file back over
        # the branch's -- claude-code-action's restore above, a tool writing
        # from a stale copy -- and committing that publishes a reversion the
        # push cannot detect: it is a fast-forward. So fetch base (a stale
        # tracking ref would compare against content nobody restored) and,
        # for every modified tracked file the branch had changed, refuse if
        # the working copy now matches base byte for byte, naming the files.
        # A session that really wants base's content back commits it by hand.
        base = git("-C", work_root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")[1]
        base = base or "origin/main"
        if not git_ok("-C", work_root, "rev-parse", "-q", "--verify", base):
            base = "origin/master"
        git_bounded(60, "-C", work_root, "fetch", "-q", "origin", base[len("origin/"):]
                    if base.startswith("origin/") else base)
        if git_ok("-C", work_root, "rev-parse", "-q", "--verify", base):
            reverted = ""
            for f in git("-C", work_root, "diff", "--name-only", "HEAD", "--", ".")[1].split("\n"):
                if not f:
                    continue
                # The branch changed this file, and the working copy is base's again.
                if git_ok("-C", work_root, "diff", "--quiet", base, "HEAD", "--", f):
                    continue
                if git_ok("-C", work_root, "diff", "--quiet", base, "--", f):
                    reverted += f" {f}"
            if reverted:
                return self.sc_note(f"refused: the working tree puts `{base}`'s version back over this "
                                    f"branch's changes to:{reverted} -- that is a revert, not new work; "
                                    "not committing")

        # dotfiles#280: a worktree checked out before some upstream commit
        # deleted a file still carries that file on disk, untracked, and `git
        # add -A` cannot tell it from real new work. Path history alone
        # doesn't settle it either -- a branch that itself added, deleted and
        # is now legitimately recreating the same path leaves an identical
        # trail. What distinguishes the two is content: only when the
        # untracked file was tracked at some commit in HEAD's own history, is
        # missing from `$base`, *and* the working copy still matches that
        # commit's content byte for byte is it the old leftover rather than
        # new work -- a session's freshly written file essentially never
        # matches old bytes by chance. A shallow checkout can hide the commit
        # that first added a long-lived path, so unshallow first; unable to,
        # refuse rather than guess. Paths are read NUL-delimited so control
        # characters and non-ASCII names survive intact.
        if git_ok("-C", work_root, "rev-parse", "-q", "--verify", base):
            if (git("-C", work_root, "rev-parse", "--is-shallow-repository")[1] == "true"
                    and git_bounded(60, "-C", work_root, "fetch", "-q", "--unshallow", "origin") != 0):
                return self.sc_note("refused: repo is shallow and could not be unshallowed -- can't tell "
                                    "a real stale leftover from new work; not committing")
            stale = ""
            untracked = gitrun.exact("-C", work_root, "ls-files", "-z", "--others",
                                     "--exclude-standard").stdout
            for f in untracked.split("\0"):
                if not f:
                    continue
                ever_tracked = git("-C", work_root, "log", "-1", "--format=%H", "HEAD", "--", f)[1]
                if not ever_tracked:
                    continue
                if git_ok("-C", work_root, "cat-file", "-e", f"{base}:{f}"):
                    continue
                # The last commit to touch the path may be the one that
                # deleted it, so there is no blob there to compare -- fall
                # back to its parent, the last commit where the path actually
                # existed.
                last_live = ever_tracked
                if not git_ok("-C", work_root, "cat-file", "-e", f"{last_live}:{f}"):
                    last_live = f"{last_live}^"
                blob = gitrun.run("-C", work_root, "show", f"{last_live}:{f}", binary=True).stdout
                try:
                    with open(f"{work_root}/{f}", "rb") as fh:
                        if fh.read() != blob:
                            continue
                except OSError:
                    continue
                stale += f" {f}"
            if stale:
                return self.sc_note("refused: untracked path(s) were tracked in this branch's history, are "
                                    f"gone from `{base}` now, and still match their last tracked content -- "
                                    "stale leftovers from before this checkout last synced, not new work; "
                                    f"not committing:{stale}")

        # --- the commit: repo hooks run as configured, signing is required ---
        # `commit.gpgsign=true` rather than the machine's setting: a cloud
        # session has no signing key, so "as configured" meant unsigned, and
        # the salvage commit is how unsigned commits kept reaching open pull
        # requests. Fail closed -- the commit is refused and the files are
        # left for a machine that can sign.
        #
        # The commit is made on the current branch because that is the only
        # way the repo's own hooks and signing config run over it -- and it is
        # moved straight off again, below, before anything is pushed. The
        # branch never keeps it.
        wip_ref = f"wip/{sid}"
        head_before = git("-C", work_root, "rev-parse", "HEAD")[1]
        if (not head_before
                or not git_ok("-C", work_root, "add", "-A")
                or git_bounded(30, "-C", work_root, "-c", "commit.gpgsign=true", "commit", "-q",
                               "-m", f"wip: session {sid[:8]} at Stop ({self.today})",
                               "-m", "Co-Authored-By: Claude <noreply@anthropic.com>") != 0):
            git_ok("-C", work_root, "reset", "-q")
            return self.sc_note("refused: commit failed (hook or signing) — files left as they were")

        # --- and off the branch again: the destination is this session's wip ref
        # dotfiles#285, and the #61 ruling behind it. The session's branch is
        # the head of an open PR; a machine commit pushed there is what #177,
        # #196 and #280 have in common, and no reader can tell it from work a
        # human meant to publish. So the commit lands on
        # `refs/heads/wip/<session-id>` -- a ref no PR points at, named for
        # the one session that writes it -- and the branch is put back where
        # it was with a mixed reset, which leaves the files in the working
        # tree exactly as the session left them. Salvage, not publication:
        # the next session picks the ref up from the checkpoint.
        salvaged = git("-C", work_root, "rev-parse", "HEAD")[1]
        wrote_ref = git_ok("-C", work_root, "update-ref", f"refs/heads/{wip_ref}", salvaged)
        # Unconditional, and before the ref write is judged: whatever else
        # happened, the work branch must not be left carrying the commit.
        if not git_ok("-C", work_root, "reset", "-q", head_before):
            return self.sc_note(f"committed `{salvaged or '?'}` but could not put `{work_branch}` back at "
                                f"`{head_before}` — that commit is sitting on the branch; move or drop it "
                                "before pushing")
        if not wrote_ref:
            return self.sc_note(f"refused: could not write `refs/heads/{wip_ref}` — nothing committed, "
                                "files left as they were")

        # --force, and only ever this ref: `wip/<session-id>` has exactly one
        # writer, and each Stop's snapshot is a sibling of the last (same
        # parent, supersetting content), so a fast-forward push would fail
        # from the second Stop of every session onwards.
        if git_bounded(120, "-C", work_root, "push", "-q", "--force", "origin", "--",
                       f"refs/heads/{wip_ref}:refs/heads/{wip_ref}") == 0:
            self.sc_note(f"salvaged to `{wip_ref}` and pushed it (`{salvaged}`); `{work_branch}` is "
                         "untouched and the files are still in the working tree")
        else:
            self.sc_note(f"salvaged to `{wip_ref}` (`{salvaged}`) but the push failed — the commit is "
                         f"local only; `{work_branch}` is untouched")

    # ------------------------------------------------------- the pickup item
    # One item per session in pickup/, which /pickup reads in place of the
    # old checkpoint resume block (dotfiles#110). The resume block depended
    # on a model remembering to write it, and a session that ends any other
    # way -- context ceiling, a closed laptop, a reaped container -- hands
    # off to nobody. This needs nothing from the model: status, branch
    # state, PR, model and the first line of the last user prompt are all
    # machine facts, and `pickup-list` shows them newest first. The body is
    # the hand-off a model may write over the hook's default (the prompt
    # line); on later Stops the hook only replaces a body that still reads
    # exactly as it last set it, so an edited body survives every rewrite and
    # the model never has to flag that it edited.
    #
    # The id is the session's start minute plus its short id, so every Stop
    # of a session finds the same file and two sessions never share one.
    # `pr:` is looked up only while empty and only once the branch is on
    # origin (a PR cannot exist before that), and a miss is cached ten
    # minutes so a pushed branch with no PR does not pay a gh call every turn.
    def pickup_item(self):
        sid, work_root = self.sid, self.work_root
        d = f"{self.SD}/pickup"
        try:
            os.makedirs(d, exist_ok=True)
        except OSError:
            return
        start = self.s("started_at") or self.now
        stamp = re.sub(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}).*", r"\1T\2-\3",
                       start, flags=re.M)
        f = f"{d}/{sub(stamp)}-{sid[:8]}.md"
        prompt = self.s("last_prompt")

        old_prompt = old_body = old_status = old_pr = old_until = ""
        if os.path.isfile(f):
            try:
                lines = records(read(f))
            except OSError:
                lines = []

            def first(key):
                return next((ln[len(key):] for ln in lines if ln.startswith(key)), "")
            old_prompt, old_status, old_pr = first("prompt: "), first("status: "), first("pr: ")
            # Header only: a hand-off body may well hold a line starting "until: ".
            for ln in lines:
                if ln == "---":
                    break
                if ln.startswith("until: "):
                    old_until = ln[len("until: "):]
                    break
            if "---" in lines:
                old_body = sub("".join(ln + "\n" for ln in lines[lines.index("---") + 1:]))

        body = old_body
        if not body.translate({ord(c): None for c in WS_ASCII}) or body == old_prompt:
            body = prompt
        status = old_status
        # A new prompt reopens a session's item: the last thing talked about
        # is what the next session picks up, whatever the item said before.
        if not status or prompt != old_prompt:
            status = "open"

        self.pi_pr = old_pr or "none"
        if work_root:
            ust = state.unpushed_state(work_root, self.work_branch)
            if ust.startswith("ahead "):
                ust_desc = f"{ust[len('ahead '):]} ahead"
            else:
                ust_desc = {"never-pushed": "never pushed", "safe": "nothing ahead"}.get(ust, "ahead unknown")
            dirty = "dirty" if state.dirty_paths(work_root).rstrip("\n") else "clean"
            self.pi_branch_line = f"{self.work_repo} {self.work_branch} ({ust_desc}, {dirty})"
            miss = f"{tmpdir()}/claude-pickup-pr-miss.{tr_name(sid)}"
            gate = f"{HOOK_DIR}/branch-home-gate.sh"
            try:
                fresh_miss = time.time() - os.stat(miss).st_mtime < 600
            except OSError:
                fresh_miss = False
            if self.pi_pr == "none" and ust == "ahead 0" and os.access(gate, os.X_OK) and not fresh_miss:
                # The verdict's own home check (archivable, lib/state.py) kept
                # its line; reuse it rather than paying the gh round trip
                # twice in one Stop.
                home = self.home or cap(["sh", gate, "--check", work_root])[1]
                if home.startswith("home: https://"):
                    found = []
                    for ln in home.split("\n"):
                        mt = re.match(r"https://[^ ]+", ln[len("home: "):] if ln.startswith("home: ") else ln)
                        if mt:
                            found.append(mt.group(0))
                    self.pi_pr = "\n".join(found)
                else:
                    try:
                        write(miss, "")
                    except OSError:
                        pass
                self.pi_pr = self.pi_pr or "none"

        where = self.ckpt[len(self.SD) + 1:] if self.ckpt.startswith(self.SD + "/") else self.ckpt
        text = (f"status: {status}\nupdated: {self.now}\nsession: {sid}\nmodel: {self.s('model', default='?')}\n"
                f"branch: {self.pi_branch_line}\npr: {self.pi_pr}\nwhere: {where}\n")
        # until: is written by a model or the user (a date, an event or a
        # PR/issue link); the hook only carries it across rewrites, and writes
        # no empty line for an item that has none.
        if old_until:
            text += f"until: {old_until}\n"
        text += f"prompt: {prompt}\n---\n{body}\n"
        tmp = f"{f}.{os.getpid()}"
        try:
            write(tmp, text)
            os.replace(tmp, f)
        except OSError:
            rm_f(tmp)

    # ------------------------------------------------------- the session's item
    # The session's record as one work item in items/ (requirements section
    # 14): minted at its first Stop, or written onto the item it claimed,
    # before the state commit below so this Stop commits it. The deciding is
    # stop-item.py's; every write goes through bin/work-item. It fails open:
    # its one outcome line, or why it did not run, goes in the checkpoint,
    # and the pickup item above stands either way.
    # --name=value, not --name value: a prompt of one dash-led word ("-h")
    # would otherwise be read as a flag, and argparse refuses the whole call.
    def session_item(self):
        si_out = bounded(["python3", f"{HOOK_DIR}/stop-item.py", f"--session={self.sid}",
                          f"--items={self.SD}/items", f"--pr={self.pi_pr}", f"--checkpoint={self.ckpt}",
                          f"--work-root={self.work_root}", f"--repo={self.work_repo}",
                          f"--started={self.started}", f"--prompt={self.s('last_prompt')}",
                          f"--model={self.s('model')}"], 60, capture=True)[1]
        append(self.ckpt, f"\n## Session item\n\n{si_out or 'failed: stop-item.py did not run'}\n")

    # ------------------------------------------------------- curia digests
    # A session that touched a curia -- a state/global/curia/<id> path, a
    # `/curia <id>` or `confer <id>` in the transcript -- leaves the machine
    # floor on that curia's digest.md, so a sitting that dies any way at all
    # still hands off. One write per Stop, under the pickup item's
    # body-ownership protocol: a floor block at the end of the file (last
    # touched, branch, PR), hook-owned by its markers, model text above it
    # untouched. The user's words are not written here: curia-roll.py
    # appends them to the curia's roll.md, and digest.md refers to them by
    # stamp.
    def curia_floor(self, t, model):
        tmp = f"{t}.{os.getpid()}"
        try:
            lines, drop = [], False
            for ln in records(read(t)):
                if ln.startswith("<!-- floor"):
                    drop = True
                    continue
                if ln == "<!-- /floor -->":
                    drop = False
                    continue
                if not drop:
                    lines.append(ln)
            while lines and not lines[-1].strip(WS):
                lines.pop()
            out = "".join(ln + "\n" for ln in lines) + ("\n" if lines else "")
            out += ("<!-- floor: stop-continuity.py; text above survives, this block does not -->\n"
                    f"- last touched: {awk_v(self.now)} · session {awk_v(self.sid[:8])} · {awk_v(model)}\n"
                    f"- branch: {awk_v(self.pi_branch_line)} · pr: {awk_v(self.pi_pr)}\n"
                    "<!-- /floor -->\n")
            write(tmp, out)
            os.replace(tmp, t)
        except OSError:
            rm_f(tmp)

    def curia_digests(self):
        model = self.s("model", default="?")
        refs = sub("".join(raw(x) + "\n" for x in each(get(self.metrics, "session", "curia_refs"))
                           if x is not None and x is not False))
        for ref in re.split(r"[ \t\n]+", refs):
            if not ref:
                continue
            thread = f"{self.SD}/curia/{ref}/digest.md"
            # thread.md is the name before digest.md; read it until every
            # curia is moved. roll.md is the words log, written only by its
            # hook: never touched here.
            if not os.path.isfile(thread):
                thread = f"{self.SD}/curia/{ref}/thread.md"
            if not os.path.isfile(thread):
                continue
            self.curia_floor(thread, model)

    # ------------------------------------------------------------ state repo
    def state_repo_commit(self):
        SR = state.state_repo()
        if SR is None:
            return
        try:
            os.chdir(SR)
        except OSError:
            return

        # A fresh cloud clone has no git filters wired: the clean/smudge
        # programs (sops and friends) are not on PATH, so `git add` through an
        # unconfigured filter writes mangled content and the damage is only
        # visible later. Refuse instead, and say so in the checkpoint rather
        # than skipping quietly.
        try:
            attrs = records(read(".gitattributes")) if os.path.isfile(".gitattributes") else []
        except OSError:
            attrs = []
        if any(re.search(f"(^|[{WS}])filter=", ln) for ln in attrs):
            names = set()
            for ln in attrs:
                mt = re.fullmatch(f".*[{WS}]filter=([A-Za-z0-9_.-]+).*", ln)
                if mt:
                    names.add(mt.group(1))
            for f in sorted(names):
                if not git_ok("config", "--get", f"filter.{f}.clean"):
                    append(self.ckpt,
                           f"\n**NOT COMMITTED** — git filter `{f}` is declared in .gitattributes\n"
                           "but not configured in this clone, so committing would mangle content.\n"
                           "Run the repo's filter setup, or commit by hand from a real machine.\n")
                    self.set_verdict(f"state repo not committed (git filter `{f}` unconfigured)")
                    return

        # Everything under state/ goes in, the board's items/ included.
        git_ok("add", "state/")
        if git_ok("diff", "--cached", "--quiet"):
            return  # nothing changed

        # Bounded like the salvage commit: signing calls out to gpg or
        # ssh-agent, and a locked agent must not hang the Stop. A failed
        # signature is not retried unsigned -- that is the commit the push
        # guard refuses; the state stays staged for the next Stop and the
        # verdict says why.
        if git_bounded(30, "-c", f"user.name={os.environ.get('GIT_AUTHOR_NAME') or 'Claude'}",
                       "-c", f"user.email={os.environ.get('GIT_AUTHOR_EMAIL') or 'noreply@anthropic.com'}",
                       "-c", f"commit.gpgsign={self.sign_if_key('.')}",
                       "commit", "-q", "-m",
                       f"State: {self.work_repo} session {self.sid[:8]} ({self.today})") != 0:
            self.set_verdict("state-repo commit failed")
            return

        # Debounce the push, not the commit: every Stop still commits locally
        # (cheap, never lost), but this clone pushes at most once per debounce
        # window, however many sessions stop. A cloud session pushes whenever
        # archivable, so its last commit is never left on a VM about to be
        # reaped; a local one batches, because its commit is already safe in
        # the clone and a later Stop carries it.
        #
        # The stamp lives in the clone's git dir, never in the tracked tree.
        # Under state/ it was committed by the next Stop, shared with every
        # other machine, and rewritten by any `pull --rebase --autostash` that
        # brought in another machine's stamp -- or left as conflict markers,
        # which read as "never pushed" and let the next Stop push at once. It
        # records the attempt, not the success: a push that keeps failing is
        # retried once per window, not on every Stop.
        cloud = os.environ.get("CLAUDE_CODE_REMOTE") == "true"
        # "$SR/.git" is the directory state_repo found, not a git query that
        # can come back empty and put the stamp at the filesystem root.
        sentinel = f"{SR}/.git/claude-last-state-push"
        debounce_secs = 300
        if (not cloud or self.verdict != "archivable") and os.path.isfile(sentinel):
            try:
                last_push = sub(read(sentinel))
            except OSError:
                last_push = "0"
            if not re.fullmatch(r"[0-9]+", last_push):
                last_push = "0"
            if int(time.time()) - int(last_push) < debounce_secs:
                return  # committed locally; next push (debounced or archivable) carries it
        try:
            write(sentinel, f"{int(time.time())}\n")
        except OSError:
            pass

        # The pause between attempts; STOP_PUSH_BACKOFF_SECS exists for the
        # test suite, which fails pushes on purpose and need not wait them out.
        try:
            backoff = float(os.environ.get("STOP_PUSH_BACKOFF_SECS") or 3)
        except ValueError:
            backoff = 3
        for attempt in (1, 2):
            # A conflicted rebase left in place wedges this clone for every
            # later Stop and every hand commit; back out, and let the push
            # below fail and say so.
            if git_bounded(120, "pull", "--rebase", "--autostash", "-q") != 0:
                git_ok("rebase", "--abort")
            if git_bounded(120, "push", "-q", "origin", "HEAD") == 0:
                return
            time.sleep(attempt * backoff)
        # In the cloud the optimistic verdict is now known to be wrong.
        # Correcting it leaves the checkpoint one commit behind the state repo
        # -- the next Stop carries both the correction and this commit.
        # Locally the commit is the promise, and it held.
        if cloud:
            self.set_verdict("state-repo push failed")


def _bye(signum, frame):
    # The child first, then the lock (main's finally): see _child.
    if _child is not None:
        try:
            stop_group(_child, grace=2, collect=False)
        except Exception:
            pass
    raise SystemExit(0)


def main():
    if shutil.which("jq") is None:
        return
    try:
        ev = parse(sys.stdin.buffer.read().decode("utf-8", "surrogateescape"))
    except ValueError:
        ev = None

    def field(k):
        return sub(raw(alt(get(ev, k), "")))
    tp, sid, cwd = field("transcript_path"), field("session_id"), field("cwd")
    if not (tp and os.path.isfile(tp)) or not sid:
        return
    if not cwd:
        cwd = os.environ.get("PWD", "")
        try:
            if not cwd or not os.path.samefile(cwd, "."):
                cwd = os.getcwd()
        except OSError:
            cwd = os.getcwd()
    Stop(sid, tp, cwd).run()


if __name__ == "__main__":
    # One exit path, so a later step extends it rather than retyping it: any
    # lock still held comes off however the hook ends, and every ending is 0.
    signal.signal(signal.SIGTERM, _bye)
    signal.signal(signal.SIGINT, _bye)
    try:
        import gitrun
        import state
        main()
    except BaseException:
        pass
    finally:
        try:
            state.state_unlock()
        except Exception:
            pass
    sys.exit(0)
