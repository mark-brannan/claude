#!/usr/bin/env python3
# Tests for stop-continuity.py, the Stop hook. Run: python3 hooks/stop-continuity.test.py
#
# Black-box: every case runs the hook as Claude Code does, a subprocess fed
# a Stop payload on stdin, in a scratch HOME and TMPDIR with a fake gh first
# on PATH. A straight translation of the shell suite it replaced: every case
# and every assertion is kept, in the same order within each section.
#
# What matters: `archivable` is said only when every condition holds; each
# reason is named, in the contract's order; a resume block survives a Stop,
# because the hook rewrites the whole checkpoint and eating the hand-off the
# model was told to write would be silent and total.
#
# The salvage commit's destination (dotfiles#285: a `wip/<session>` ref, never
# the branch the session's PR is on) and its refusals (dotfiles#196: CI, stale
# base, revert of the branch's own work; dotfiles#280: a stale untracked
# leftover from before the checkout synced) have a throwaway repo of their
# own. The metrics shape is not covered here.
#
# Cost per push: under ten seconds on a laptop, a step in CI's existing
# tool-tests job, so no new job and nothing drawn from the account's
# concurrent-job cap. The sections share nothing -- each builds its own
# scratch world -- so they run side by side, one thread each; a section
# stops at its first failed assertion and the others carry on.
import concurrent.futures
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOKS = Path(__file__).resolve().parent
HOOK = HOOKS / "stop-continuity.py"
WI = HOOKS.parent / "bin" / "work-item"
TP = str(HOOKS / "fixtures" / "friction-calm.jsonl")
SID = "stopcont-0000-1111-2222"
PR7 = '[{"url":"https://github.com/o/r/pull/7"}]'

# --- a fake gh: GH_PRS is what `gh pr list` answers ---------------------------
FAKE_GH = r'''#!/bin/sh
[ "${GH_FAIL:-0}" = 1 ] && { echo "gh: not logged in" >&2; exit 1; }
# GH_LOG, when set, records each call with its grandparent's argv -- the
# script that wanted the answer (branch-home-gate.sh --check vs --card).
if [ -n "${GH_LOG:-}" ]; then
  gp=$(ps -o ppid= -p $PPID 2>/dev/null | tr -d ' ')
  echo "$* <- $(ps -o args= -p "$gp" 2>/dev/null)" >> "$GH_LOG"
fi
case "$1 ${2:-}" in
  "pr list")    printf '%s\n' "${GH_PRS:-[]}" ;;
  "issue list") printf '%s\n' "${GH_ISSUES:-[]}" ;;
  *) exit 1 ;;
esac
'''


def sh(*argv, env=None, cwd=None, input=None):
    """Run argv; its stdout, stripped of trailing newlines, as $(...) would."""
    p = subprocess.run(argv, env=env, cwd=cwd, input=input, capture_output=True, text=True)
    return p.stdout.rstrip("\n")


class World:
    """One scratch HOME/TMPDIR with the fake gh on PATH."""

    def __init__(self, root):
        self.S = Path(root)
        self.HOME = self.S / "home"
        self.TMPDIR = self.S / "tmp"
        self.BIN = self.S / "bin"
        for d in (self.HOME, self.TMPDIR, self.BIN):
            d.mkdir(parents=True)
        (self.BIN / "gh").write_text(FAKE_GH)
        (self.BIN / "gh").chmod(0o755)
        self.base = dict(os.environ, HOME=str(self.HOME), TMPDIR=str(self.TMPDIR),
                         GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
                         CLAUDE_STOP_COMMIT="off",  # the salvage commit is not under test
                         # A state dir that is deliberately NOT a git repo:
                         # state_is_repo is false, so the hook stops before the
                         # commit-and-push section and the verdict written by the
                         # salvage step is the one under test.
                         CLAUDE_STATE_REPO="", STOP_PUSH_BACKOFF_SECS="0",
                         PATH=f"{self.BIN}{os.pathsep}{os.environ.get('PATH', '')}")
        for k in ("GH_PRS", "GH_FAIL", "GH_LOG", "CLAUDE_CODE_REMOTE", "STOP_VERDICT_SINCE"):
            self.base.pop(k, None)
        self.GS = self.HOME / ".claude" / "state" / "global"
        self.AUTO = self.GS / "log" / "auto"
        self.PICKD = self.GS / "pickup"
        self.ITEMS = self.GS / "items"

    def env(self, **kw):
        e = dict(self.base)
        for k, v in kw.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = str(v)
        return e

    def git(self, d, *args):
        return sh("git", "-C", str(d), *args, env=self.base)

    def gitq(self, d, *args):
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", *args], env=self.base,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def payload(self, sid, cwd, tp=TP, extra=""):
        return '{"transcript_path":"%s","session_id":"%s","cwd":"%s"%s}' % (tp, sid, cwd, extra)

    def run_hook(self, sid, cwd, tp=TP, timeout=None, **env):
        """The hook's exit status (124 past timeout)."""
        try:
            return subprocess.run([sys.executable, str(HOOK)], input=self.payload(sid, cwd, tp).encode(),
                                  env=self.env(**env), stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            return 124

    def ckpt(self, sid, auto=None):
        """The checkpoint a Stop of sid wrote, as `ls ... | head -1` finds it."""
        found = sorted(glob.glob(f"{auto or self.AUTO}/*/*{sid[:8]}.md"))
        return found[0] if found else ""

    def make_work(self, name="work"):
        """The repo the session worked: main pushed, claude/work one commit
        ahead of it and pushed too. Returns (origin, work)."""
        origin, work = self.S / f"{name}-origin.git", self.S / name
        sh("git", "init", "-q", "--bare", str(origin), env=self.base)
        sh("git", "init", "-q", "-b", "main", str(work), env=self.base)
        self.gitq(work, "remote", "add", "origin", str(origin))
        (work / "f").write_text("one\n")
        self.gitq(work, "add", "f")
        self.gitq(work, "commit", "-m", "base")
        self.gitq(work, "push", "-u", "origin", "main")
        self.gitq(work, "checkout", "-b", "claude/work")
        with open(work / "f", "a") as fh:
            fh.write("two\n")
        self.gitq(work, "add", "f")
        self.gitq(work, "commit", "-m", "work")
        self.gitq(work, "push", "-u", "origin", "claude/work")
        return origin, work

    def make_state(self, name):
        """A state clone with a seed commit, pushed to its own bare origin."""
        origin, repo = self.S / f"{name}-origin.git", self.S / name
        sh("git", "init", "-q", "--bare", str(origin), env=self.base)
        sh("git", "init", "-q", "-b", "main", str(repo), env=self.base)
        self.gitq(repo, "remote", "add", "origin", str(origin))
        (repo / "state" / "global").mkdir(parents=True)
        (repo / "state" / "global" / ".seed").write_text("seed\n")
        self.gitq(repo, "add", "state")
        self.gitq(repo, "commit", "-m", "seed")
        self.gitq(repo, "push", "-u", "origin", "main")
        return origin, repo

    def transcript(self, name, *lines):
        """The fixture's first three records, then lines: a new last prompt."""
        head = sh("jq", "-c", ".", TP, env=self.base).split("\n")[:3]
        p = self.S / name
        p.write_text("\n".join(head + list(lines)) + "\n")
        return str(p)

    def signing_key(self):
        """An ssh key a commit can actually be signed with; no gpg agent."""
        key = self.S / "sign"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "t", "-f", str(key)],
                       stdin=subprocess.DEVNULL, check=True)
        return f"{key}.pub"


def read(p):
    try:
        return Path(p).read_text()
    except OSError:
        return ""


def verdict(ckpt):
    m = re.search(r"^\*\*Verdict:\*\* (.*)$", read(ckpt), re.M)
    return m.group(1) if m else ""


def jfield(path, key):
    try:
        v = json.loads(Path(path).read_text()).get(key)
    except (OSError, ValueError):
        return ""
    return "" if v is None else str(v)


def field(item, key):
    m = re.search(rf"^{key}: (.*)$", read(item), re.M)
    return m.group(1) if m else ""


def body(item):
    lines = read(item).split("\n")
    if "---" not in lines:
        return ""
    return "\n".join(lines[lines.index("---") + 1:]).rstrip("\n")


class StopContinuityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def world(self, name):
        return World(Path(self.tmp) / name)

    def has(self, label, pattern, path):
        self.assertRegex(read(path), re.compile(pattern, re.M), label)

    def hasnt(self, label, pattern, path):
        self.assertNotRegex(read(path), re.compile(pattern, re.M), label)

    # ------------------------------------------------------------- verdict
    def verdict_basics(self):
        w = self.world("verdict1")
        _, WORK = w.make_work()
        sessions = w.GS / "metrics" / "sessions"

        # --- everything in order: archivable --------------------------------
        w.run_hook(SID, WORK, GH_PRS=PR7)
        CKPT = w.ckpt(SID)
        self.assertTrue(CKPT, "a checkpoint was written")
        self.assertEqual(verdict(CKPT), "archivable", "clean, pushed, PR: archivable")
        rec = sessions / SID[:2] / f"{SID}.json"
        self.assertEqual(jfield(rec, "verdict"), "archivable", "the metrics record says the same")
        # metrics-live.sh refuses a verdict older than its Stop sequence's
        # start, so the record has to say when this one was reached.
        at = jfield(rec, "verdict_at")
        self.assertGreaterEqual(int(at or 0), int(time.time()) - 60,
                                f"the metrics record stamps verdict_at in epoch seconds, got [{at}]")
        self.has("the worktree is recorded for resume-list", rf"^- worktree .{re.escape(str(WORK))}.$", CKPT)

        # --- outside any repo -------------------------------------------------
        # The 📦 notice now shows this verdict, so its reason has to read as
        # one: there is no branch to name.
        NOGIT = w.S / "nogit"
        NOGIT.mkdir()
        NGSID = "nogit000-1111-2222-3333"
        w.run_hook(NGSID, NOGIT)
        self.assertEqual(jfield(sessions / NGSID[:2] / f"{NGSID}.json", "verdict"),
                         "not archivable: not a git repo", "not a git repo: the verdict says so")

        # --- one gh round trip per Stop ---------------------------------------
        # The verdict's home check and the pickup item's `pr:` lookup ask the
        # same question. The verdict's answer is handed to the pickup item
        # (lib/state.py's archivable returns the home line it read); in the
        # shell hook a variable set inside `$(archivable_reasons ...)` died
        # with the subshell, which is how the reuse silently never fired once
        # (PR #388, design pass).
        GH_LOG = w.S / "gh.log"
        GH_LOG.write_text("")
        w.run_hook("ghlog000-1111-2222-3333", WORK, GH_LOG=GH_LOG, GH_PRS=PR7)
        # claim-stamp.sh's own `--card` lookup is a separate, deliberate call
        # and is not counted here; the verdict's `--check` is what must run once.
        n = sum(1 for ln in read(GH_LOG).splitlines()
                if re.match(r"pr list --head.*branch-home-gate\.sh --check", ln))
        self.assertEqual(n, 1, "the verdict asks gh for the head once per Stop")
        items = sorted(glob.glob(f"{w.PICKD}/*-ghlog000.md"))
        self.assertEqual(f"pr: {field(items[0], 'pr')}" if items else "",
                         "pr: https://github.com/o/r/pull/7", "and the pickup item still learns the PR")
        self.assertFalse(glob.glob(f"{w.TMPDIR}/claude-stop-home.*"), "the home file does not outlive the Stop")

        # --- no PR and no pointer ---------------------------------------------
        w.run_hook(SID, WORK)
        self.has("no home is named", r"^\*\*Verdict:\*\* not archivable: no PR and no pointer", w.ckpt(SID))

        # --- a dirty worktree, and unpushed commits, named in the contract's order
        with open(WORK / "f", "a") as fh:
            fh.write("three\n")
        w.gitq(WORK, "add", "f")
        w.gitq(WORK, "commit", "-m", "unpushed")
        with open(WORK / "f", "a") as fh:
            fh.write("four\n")
        w.run_hook(SID, WORK, GH_PRS=PR7)
        self.assertEqual(verdict(w.ckpt(SID)), "not archivable: worktree dirty, 1 commit(s) unpushed",
                         "dirty before unpushed")

    def verdict_branches(self):
        w = self.world("verdict2")
        _, WORK = w.make_work()

        def v():
            w.run_hook(SID, WORK, GH_PRS=PR7)
            return verdict(w.ckpt(SID))

        def commit(text, msg):
            with open(WORK / "f", "a") as fh:
                fh.write(text + "\n")
            w.gitq(WORK, "add", "f")
            w.gitq(WORK, "commit", "-m", msg)

        # --- a branch that was never pushed at all ----------------------------
        # No upstream means `rev-list @{u}..HEAD` fails rather than answering
        # 0, so a fallback of 0 would call a clean, home-having branch
        # archivable while every commit still lives only on local disk.
        w.gitq(WORK, "checkout", "-b", "claude/never-pushed")
        commit("five", "local-only")
        self.assertEqual(v(), "not archivable: `claude/never-pushed` has no upstream (never pushed)",
                         "never pushed is not archivable")
        w.gitq(WORK, "checkout", "claude/work")

        # --- a fresh branch, no upstream, zero commits ahead of main ----------
        # branch-home-gate.sh already treats this as "nothing to strand"; the
        # verdict should agree instead of flagging the same branch as
        # never-pushed.
        w.gitq(WORK, "checkout", "-b", "claude/fresh-review", "main")
        self.assertEqual(v(), "archivable", "zero commits ahead, no upstream: archivable")
        w.gitq(WORK, "checkout", "claude/work")

        # --- a detached HEAD, on and off a remote branch (#128/#143) ----------
        # The carve-out lib/state.py's unpushed_state owns: a commit that
        # already lives on some remote branch is not stranded by being checked
        # out detached, but one that lives nowhere else is exactly the case
        # the verdict exists for.
        w.gitq(WORK, "checkout", "--detach", "origin/claude/work")
        self.assertEqual(v(), "archivable", "detached on a remote branch: archivable")
        commit("six", "detached-only")
        self.assertEqual(v(), "not archivable: detached HEAD, no upstream to compare against",
                         "detached off any remote branch: not archivable")
        w.gitq(WORK, "checkout", "claude/work")

        # --- @{u} is main, the commit lives on a stack/ branch (mergify stack push)
        w.gitq(WORK, "checkout", "-b", "claude/stacked", "main")
        w.gitq(WORK, "branch", "-u", "origin/main")
        commit("seven", "stacked")
        self.assertEqual(v(), "not archivable: 1 commit(s) unpushed", "on no remote branch: not archivable")
        w.gitq(WORK, "push", "origin", "claude/stacked:refs/heads/stack/claude-stacked")
        self.assertEqual(v(), "archivable", "pushed to stack/, @{u}=main: archivable")
        w.gitq(WORK, "checkout", "claude/work")

        # --- "cannot verify" is never a pass -----------------------------------
        w.run_hook(SID, WORK, GH_FAIL=1)
        self.has("unverified is not archivable", r"^\*\*Verdict:\*\* not archivable: branch home unverified",
                 w.ckpt(SID))

    # ---------------------------------------------------- resume and pickup
    def resume_and_pickup(self):
        w = self.world("pickup")
        _, WORK = w.make_work()

        def stop(**kw):
            w.run_hook(SID, WORK, **{"GH_PRS": PR7, **kw})
            return w.ckpt(SID)

        # --- a resume block survives the rewrite -------------------------------
        CKPT = stop()
        with open(CKPT, "a") as fh:
            fh.write("\n## Resume\n\n- next: Finish the resume-list fixtures\n- link: o/r#7\n"
                     "- model: opus\n- effort: high\n")
        CKPT = stop()
        self.has("the heading survives", r"^## Resume$", CKPT)
        self.has("next survives", r"^- next: Finish the resume-list fixtures$", CKPT)
        self.has("effort survives", r"^- effort: high$", CKPT)
        self.assertEqual(len(re.findall(r"^## Resume$", read(CKPT), re.M)), 1, "exactly one resume block")
        self.assertEqual(len(re.findall(r"^\*\*Verdict:\*\* ", read(CKPT), re.M)), 1, "exactly one verdict line")
        self.has("the block did not swallow the rest of the file", r"^## Commits this session$", CKPT)

        # --- and so does a consumed marker, so the record of who took it stays
        Path(CKPT).write_text(re.sub(r"^- effort: high$",
                                     "- effort: high\n- consumed: session abcd1234 at 2026-09-09T13:00:00Z",
                                     read(CKPT), flags=re.M))
        CKPT = stop()
        self.has("consumed marker survives", r"^- consumed: session abcd1234", CKPT)

        # --- the pickup item: one per session, machine-written, body model-editable
        # Written on every Stop from the transcript and git, so a session that
        # ends any way at all leaves an item for /pickup. The body is the
        # hand-off a model may write, and it survives the rewrite only because
        # the hook overwrites nothing but the text it last wrote itself.
        stop()
        found = sorted(glob.glob(f"{w.PICKD}/*-{SID[:8]}.md"))
        self.assertTrue(found, "a pickup item was written")
        ITEM = found[0]
        self.assertRegex(Path(ITEM).stem, rf"^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9]{{2}}-[0-9]{{2}}-{SID[:8]}$",
                         "the id is the session start minute plus the short session id")
        self.assertEqual(field(ITEM, "status"), "open", "status opens")
        self.assertEqual(body(ITEM), field(ITEM, "prompt"), "the body defaults to the last prompt line")
        self.assertTrue(field(ITEM, "prompt"), "the prompt line is the transcript's last human line")
        self.assertEqual(field(ITEM, "pr"), "https://github.com/o/r/pull/7", "the pushed branch with a PR records it")
        self.has("branch state names ahead and clean", r"^branch: work claude/work \(0 ahead, clean\)$", ITEM)

        # A model edits the body: the next Stop keeps it.
        Path(ITEM).write_text(f"status: open\nupdated: x\nsession: {SID}\nmodel: m\nbranch: b\n"
                              f"pr: {field(ITEM, 'pr')}\nwhere: w\nprompt: {field(ITEM, 'prompt')}\n---\n"
                              "finish the fixtures, then open the PR\n")
        stop()
        self.assertEqual(body(ITEM), "finish the fixtures, then open the PR", "an edited body survives the rewrite")
        self.assertEqual(field(ITEM, "pr"), "https://github.com/o/r/pull/7", "a found PR is kept without a second lookup")

        # An until: header, written by a model, survives the rewrite like
        # prompt: does; an item that never had one gets no until: line.
        self.hasnt("no until: line on an item that has none", r"^until:", ITEM)
        with open(ITEM, "a") as fh:
            fh.write("until: a line in the body\n")
        stop()
        header = read(ITEM).split("\n---\n")[0]
        self.assertNotRegex(header, re.compile(r"^until:", re.M),
                            "an until: line in the body is not hoisted into the header")
        text = read(ITEM).replace("until: a line in the body\n", "")
        text = re.sub(r"^(where: .*)$", r"\1\nuntil: https://github.com/o/r/issues/9", text, flags=re.M)
        Path(ITEM).write_text(text)
        stop()
        self.assertEqual(field(ITEM, "until"), "https://github.com/o/r/issues/9", "until: survives the rewrite")
        self.assertEqual(body(ITEM), "finish the fixtures, then open the PR", "the body is still intact beside until:")

        # A done status is kept while the prompt is unchanged.
        Path(ITEM).write_text(re.sub(r"^status: open$", "status: done", read(ITEM), flags=re.M))
        stop()
        self.assertEqual(field(ITEM, "status"), "done", "status is kept while the prompt is unchanged")

        # A body that still reads as the hook left it follows the prompt; a
        # new prompt reopens the item.
        TP2 = w.transcript("pickup-transcript.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"pick up the fixture work '
                           'and finish it","timestamp":"2026-09-26T12:00:00.000Z"}')
        Path(ITEM).write_text(f"status: done\nupdated: x\nsession: {SID}\nmodel: m\nbranch: b\npr: none\n"
                              "where: w\nprompt: old prompt\n---\nold prompt\n")
        w.run_hook(SID, WORK, tp=TP2, GH_PRS=PR7)
        ITEM = sorted(glob.glob(f"{w.PICKD}/*-{SID[:8]}.md"))[0]
        self.assertEqual(body(ITEM), "pick up the fixture work and finish it", "an untouched body follows the new prompt")
        self.assertEqual(field(ITEM, "status"), "open", "a new prompt reopens the item")

    # ------------------------------------------------- the session's item
    def session_item(self):
        # Requirements section 14, cases 14.1 to 14.6. stop-item.py decides;
        # every write goes through bin/work-item. Session ids here start with
        # eight hex, as a real one does: the store names its writer by them.
        w = self.world("items")
        _, WORK = w.make_work()
        ITEMS = w.ITEMS

        def wi(sid, *args):
            return sh(sys.executable, str(WI), *args,
                      env=w.env(CLAUDE_CODE_SESSION_ID=sid, WORK_ITEM_DIR=ITEMS))

        def mine(id8):  # items whose id ends in the id8
            return sorted(glob.glob(f"{ITEMS}/*{id8}.md"))

        def nlog(path):
            t = read(path).split("\n")
            i = next((n for n, ln in enumerate(t) if ln.startswith("## Log")), len(t))
            return sum(1 for ln in t[i + 1:] if ln.split())

        def brief_of(path):
            out, f = [], False
            for ln in read(path).split("\n"):
                if ln.startswith("## Brief"):
                    f = True
                    continue
                if ln.startswith("## "):
                    f = False
                if f:
                    out.append(ln)
            return "\n".join(out).rstrip("\n")

        w.run_hook("a1b2c3d4-0000-1111-2222", WORK, GH_PRS=PR7)
        self.assertEqual(len(mine("a1b2c3d4")), 1, "14.1: a session with no item mints one")
        MINT = mine("a1b2c3d4")[0]
        MID = Path(MINT).stem
        log = read(MINT).split("## Log", 1)[1].strip().split("\n")[0].split()
        self.assertEqual(" ".join(log[1:4]), "a1b2c3d4 status=open owner=agent",
                         "14.1: its first log line is status=open from this session")
        self.assertEqual(re.search(r"^home=(.*)$", wi("a1b2c3d4", "fold", MID), re.M).group(1), "o/r#7",
                         "14.5: the PR is its home")
        SPICK = sorted(glob.glob(f"{w.PICKD}/*-a1b2c3d4.md"))[0]
        self.assertEqual(brief_of(MINT), f"{field(SPICK, 'prompt')}\n\nPR: https://github.com/o/r/pull/7",
                         "14.6: the brief is the last prompt's first line, then the PR")
        self.has("14.1: the checkpoint names the minted item", rf"^{MID}: minted, home=o/r#7$", w.ckpt("a1b2c3d4"))

        n0 = nlog(MINT)
        w.run_hook("a1b2c3d4-0000-1111-2222", WORK, GH_PRS=PR7)
        self.assertEqual(len(mine("a1b2c3d4")), 1, "14.2: a later Stop mints no second item")
        self.assertEqual(nlog(MINT), n0, "14.2: nothing changed, nothing logged")

        # A new last prompt: the brief is written once and never rewritten,
        # and nothing is logged.
        TP2 = w.transcript("pickup-transcript.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"pick up the fixture work '
                           'and finish it","timestamp":"2026-09-26T12:00:00.000Z"}')
        b0 = brief_of(MINT)
        w.run_hook("a1b2c3d4-0000-1111-2222", WORK, tp=TP2, GH_PRS=PR7)
        self.assertEqual(brief_of(MINT), b0, "14.6: the brief is unchanged")
        self.assertEqual(nlog(MINT), n0, "14.2: and no line is logged")
        self.hasnt("14.4: the hook writes no status=ready", "status=ready", MINT)

        # No PR yet: the link is the session's checkpoint log, and there is no home.
        w.run_hook("c9c8c7c6-0000-1111-2222", WORK)
        NOPR = mine("c9c8c7c6")[0]
        self.has("no PR: the brief links the checkpoint",
                 r"^Checkpoint: \[checkpoint\]\(\.\./log/auto/.*c9c8c7c6\.md\)$", NOPR)
        self.hasnt("no PR: no home line", "home=", NOPR)

        # 14.3: a session that claimed an item writes onto it and mints nothing.
        CARD = wi("99990000-aaaa", "create", "--id", "178557840199990000", "--brief",
                  "see https://example.invalid/1", "a card to claim")
        wi("99990000-aaaa", "log", CARD, "status=ready")
        wi("b5b6b7b8-0000", "claim", CARD)
        w.run_hook("b5b6b7b8-0000-1111-2222", WORK, GH_PRS=PR7)
        self.assertEqual(mine("b5b6b7b8"), [], "14.3: nothing minted")
        self.has("14.3: the claimed item gets this session's line, the PR its home",
                 r" b5b6b7b8 stop home=o/r#7$", ITEMS / f"{CARD}.md")
        self.assertEqual(brief_of(ITEMS / f"{CARD}.md"), "see https://example.invalid/1", "14.3: its brief is left alone")
        n1 = nlog(ITEMS / f"{CARD}.md")
        w.run_hook("b5b6b7b8-0000-1111-2222", WORK, GH_PRS=PR7)
        self.assertEqual(nlog(ITEMS / f"{CARD}.md"), n1, "14.3: and only once while nothing changes")

        # A session that minted and then claims another writes onto the claimed one.
        CARD2 = wi("99990000-aaaa", "create", "--id", "178557840299990000", "--brief",
                   "see https://example.invalid/2", "a second card")
        wi("99990000-aaaa", "log", CARD2, "status=ready")
        wi("a1b2c3d4-0000", "claim", CARD2)
        n2 = nlog(MINT)
        w.run_hook("a1b2c3d4-0000-1111-2222", WORK, GH_PRS=PR7)
        self.has("mint, then claim: the claimed item gets the line", r" a1b2c3d4 stop home=o/r#7$",
                 ITEMS / f"{CARD2}.md")
        self.assertEqual(nlog(MINT), n2, "mint, then claim: the minted item is not written")
        self.assertEqual(len(mine("a1b2c3d4")), 1, "mint, then claim: still one minted item")

        # A last prompt that is one dash-led word still mints: it is a value, not a flag.
        TPD = w.transcript("dash-transcript.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"-h",'
                           '"timestamp":"2026-09-26T12:00:00.000Z"}')
        w.run_hook("e5e6e7e8-0000-1111-2222", WORK, tp=TPD, GH_PRS=PR7)
        self.has("a dash-led last prompt still mints", r"^[0-9]*e5e6e7e8: minted, home=o/r#7$", w.ckpt("e5e6e7e8"))

        # A session id that is not hex: skipped, and the checkpoint says so.
        w.run_hook(SID, WORK, GH_PRS=PR7)
        self.has("a non-hex session id is skipped, and said", r"^skipped: session id ", w.ckpt(SID))

    # ------------------------------------------------------- curia digests
    def curia_digests(self):
        # The transcript names a curia (`confer <id>` here); the Stop hook
        # stamps a floor block at the end of the file -- model text above
        # survives -- and nothing else. Idempotent across Stops. The user's
        # words are not its to write: roll.md is the curia-roll hook's, and
        # the digest refers to it by stamp.
        w = self.world("curia")
        _, WORK = w.make_work()
        CURD = w.GS / "curia" / "test-question"
        CURD.mkdir(parents=True)
        # The "Human's words" section is what the live digests still carry
        # until the curia lint curates it out: the place the hook used to
        # append quotes.
        (CURD / "digest.md").write_text(
            "# Curia: test question\n\n- id: `test-question`\n- status: open\n\n## Where this stands\n\n"
            "Model text that must survive.\n\n## Decided\n\n## Human's words\n\nLeft from before the words log.\n")
        (CURD / "roll.md").write_text("\n### 20260926t110000z\n```\nwords\n```\n")
        ROLL_BEFORE = read(CURD / "roll.md")
        TP3 = w.transcript("curia-transcript.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"confer test-question '
                           'please","timestamp":"2026-09-26T12:00:00.000Z"}')
        w.run_hook(SID, WORK, tp=TP3, GH_PRS=PR7)
        TH = CURD / "digest.md"
        self.has("the floor block is written", r"^<!-- floor", TH)
        self.has("the floor carries last-touched and the session", rf"^- last touched: .* session {SID[:8]} ", TH)
        self.has("the floor carries the branch state", r"^- branch: work claude/work \(0 ahead, clean\)", TH)
        self.has("model text above the floor survives", r"^Model text that must survive\.$", TH)
        self.assertEqual(read(TH).rstrip("\n").split("\n")[-1], "<!-- /floor -->",
                         "the floor is the last thing in the digest")
        self.assertTrue("confer test-question please" not in read(TH) and "(hook)" not in read(TH),
                        "the user's words are not copied into the digest")

        BLANKS1 = read(TH).split("\n").count("")
        # A second Stop rewrites, never duplicates.
        w.run_hook(SID, WORK, tp=TP3, GH_PRS=PR7)
        self.assertEqual(len(re.findall(r"^<!-- floor", read(TH), re.M)), 1, "one floor block after two Stops")
        self.assertEqual(read(TH).split("\n").count(""), BLANKS1, "the blank lines do not grow across Stops")

        # Reading a digest is not sitting on it: a session whose tool calls
        # cat or ls the digest file, with no prompt naming the curia, leaves
        # it untouched. Once bare `/curia` lists every curia (#403), every
        # sitting would otherwise stamp every curia with its own floor.
        cat = {"type": "assistant", "uuid": "a-cat", "timestamp": "2026-09-26T14:00:01.000Z",
               "message": {"role": "assistant", "model": "m", "content": [
                   {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": f"cat {TH}; ls {CURD}"}},
                   {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": str(TH)}}]}}
        TP5 = w.transcript("curia-transcript-cat.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"what is open on the '
                           'board?","timestamp":"2026-09-26T14:00:00.000Z"}', json.dumps(cat))
        SID2 = "catsess0-1111-2222-3333"
        before = read(TH)
        w.run_hook(SID2, WORK, tp=TP5, GH_PRS=PR7)
        self.assertEqual(read(TH), before, "a cat/ls of the digest does not stamp it")
        self.assertNotIn(f"session {SID2[:8]}", read(TH), "no floor for the reading session")

        # A curia not yet moved to digest.md still gets its floor on thread.md.
        OLDD = w.GS / "curia" / "old-question"
        OLDD.mkdir(parents=True)
        (OLDD / "thread.md").write_text("# Curia: old question\n\n## Where this stands\n\nOld text.\n")
        TP6 = w.transcript("curia-transcript-old.jsonl",
                           '{"type":"queue-operation","operation":"enqueue","content":"confer old-question",'
                           '"timestamp":"2026-09-26T15:00:00.000Z"}')
        w.run_hook(SID, WORK, tp=TP6, GH_PRS=PR7)
        self.has("a thread.md-only curia still gets the floor", r"^<!-- floor", OLDD / "thread.md")
        self.assertFalse((OLDD / "digest.md").exists(), "and no digest.md is invented beside it")
        self.assertEqual(read(CURD / "roll.md"), ROLL_BEFORE, "the words log roll.md is never written by the Stop hook")

        # A named curia whose digest does not exist is skipped without a write.
        self.assertEqual(sorted(os.listdir(w.GS / "curia")), ["old-question", "test-question"],
                         "no digest is invented for an unknown id")

    # ------------------------------------------- sc_salvage (dotfiles#196)
    def salvage(self):
        # Everything else runs with CLAUDE_STOP_COMMIT=off. These use a
        # throwaway repo of their own, pushed to a bare origin, so a commit
        # made here can't leak into the verdict fixtures. `hookpath` is the
        # branch's own work: base has it one way, the branch changed it, and
        # the failure mode under test is the base version coming back over it.
        w = self.world("salvage")
        SORIGIN, SWORK = w.S / "salvage-origin.git", w.S / "salvage-work"
        sh("git", "init", "-q", "--bare", str(SORIGIN), env=w.base)
        sh("git", "init", "-q", "-b", "main", str(SWORK), env=w.base)
        w.git(SWORK, "config", "user.name", "t")
        w.git(SWORK, "config", "user.email", "t@example.invalid")
        # The salvage commit forces commit.gpgsign=true, so the fixture needs
        # a key it can actually sign with; ssh signing needs no gpg agent.
        pub = w.signing_key()
        w.git(SWORK, "config", "gpg.format", "ssh")
        w.git(SWORK, "config", "user.signingkey", pub)
        w.gitq(SWORK, "remote", "add", "origin", str(SORIGIN))
        (SWORK / "f").write_text("base\n")
        (SWORK / "hookpath").write_text("guard: no\n")
        w.gitq(SWORK, "add", "f", "hookpath")
        w.gitq(SWORK, "commit", "-m", "base")
        w.gitq(SWORK, "push", "-u", "origin", "main")
        w.gitq(SWORK, "remote", "set-head", "origin", "main")
        w.gitq(SWORK, "checkout", "-b", "claude/salvage")
        with open(SWORK / "f", "a") as fh:
            fh.write("work\n")
        (SWORK / "hookpath").write_text("guard: yes\n")
        w.gitq(SWORK, "add", "f", "hookpath")
        w.gitq(SWORK, "commit", "-m", "work")
        w.gitq(SWORK, "push", "-u", "origin", "claude/salvage")
        WIP = f"wip/{SID}"
        snap = {}

        def stop_salvage(**kw):
            # GITHUB_ACTIONS and CI are unset first: this suite runs under
            # Actions, and the hook's CI refusal would otherwise win every case
            # below. The CI case sets them back on purpose.
            w.run_hook(SID, SWORK, **{"GITHUB_ACTIONS": None, "CI": None, "CLAUDE_STOP_COMMIT": "on",
                                      "GH_PRS": PR7, **kw})
            return w.ckpt(SID)

        def rev(repo, ref):
            p = subprocess.run(["git", "-C", str(repo), "rev-parse", ref], env=w.base, capture_output=True, text=True)
            return p.stdout.strip() if p.returncode == 0 else "none"

        def porcelain():
            return w.git(SWORK, "status", "--porcelain")

        def snapshot():
            snap.update(local=rev(SWORK, "HEAD"), origin=rev(SORIGIN, "claude/salvage"), wip=rev(SORIGIN, WIP))

        def untouched(label, want):  # nothing committed or pushed
            self.assertEqual(rev(SWORK, "HEAD"), snap["local"], f"{label}: local HEAD untouched")
            self.assertEqual(rev(SORIGIN, "claude/salvage"), snap["origin"], f"{label}: origin untouched")
            self.assertEqual(rev(SORIGIN, WIP), snap["wip"], f"{label}: the wip ref untouched")
            self.assertEqual(porcelain(), want, f"{label}: the edit is still sitting there, uncommitted")

        def salvaged(label, want):
            # The commit went to the wip ref and nowhere near the branch the
            # session (and its PR) is on (dotfiles#285).
            self.assertEqual(rev(SWORK, "HEAD"), snap["local"], f"{label}: the branch head is unchanged locally")
            self.assertEqual(rev(SORIGIN, "claude/salvage"), snap["origin"],
                             f"{label}: the branch head is unchanged on origin")
            self.assertNotEqual(rev(SORIGIN, WIP), "none", f"{label}: origin has the wip ref")
            self.assertEqual(rev(SWORK, f"{WIP}^"), snap["local"], f"{label}: the wip commit sits on the branch head")
            self.assertEqual(porcelain(), want, f"{label}: the files are still in the working tree")
            self.assertEqual(w.git(SORIGIN, "log", "--oneline", "--grep=^wip: session", "claude/salvage"), "",
                             f"{label}: no wip: commit reached the branch")

        def append(name, text):
            with open(SWORK / name, "a") as fh:
                fh.write(text + "\n")

        # --- happy path: dirty tree, HEAD even with @{u} -> salvaged to the wip ref
        # The failure this replaces: the same commit went onto the session's
        # branch and was pushed to the open PR (dotfiles#177, #196, #280).
        snapshot()
        append("f", "dirty")
        CKPT = stop_salvage()
        self.has("salvage happy path: salvaged to the wip ref and pushed", rf"salvaged to .{WIP}. and pushed it", CKPT)
        salvaged("salvage happy path", " M f")
        self.assertEqual(w.git(SORIGIN, "show", f"{WIP}:f").split("\n")[-1], "dirty",
                         "the wip commit carries the uncommitted content")
        # The signature itself, not %G?: verifying an ssh signature would need
        # an allowedSignersFile this fixture has no reason to carry.
        self.assertRegex(w.git(SWORK, "cat-file", "-p", WIP), re.compile(r"^gpgsig", re.M),
                         "the salvage commit is signed")
        # A second Stop in the same session: the ref moves on, still off the branch.
        snapshot()
        append("f", "dirtier")
        stop_salvage()
        salvaged("a second Stop", " M f")
        self.assertEqual(w.git(SORIGIN, "show", f"{WIP}:f").split("\n")[-1], "dirtier",
                         "the second Stop superseded the first on the wip ref")
        w.gitq(SWORK, "checkout", "--", "f")

        # --- no signing key: refused rather than pushed unsigned (dotfiles#183)
        # A cloud session has no key. Unsigned is how the salvage commit kept
        # landing unsigned commits on open pull requests, so the commit must
        # fail instead.
        snapshot()
        w.git(SWORK, "config", "--unset", "gpg.format")
        w.git(SWORK, "config", "--unset", "user.signingkey")
        append("f", "unsigned-edit")
        CKPT = stop_salvage()
        self.has("no signing key: refused", r"refused: commit failed .hook or signing.", CKPT)
        untouched("no signing key", " M f")
        w.git(SWORK, "config", "gpg.format", "ssh")
        w.git(SWORK, "config", "user.signingkey", pub)
        w.git(SWORK, "checkout", "-q", "--", "f")

        # --- under CI: refused before anything else is looked at ---------------
        # The shared PR reviewer is Claude Code inside GitHub Actions with
        # these hooks seeded; its checkout is dirty by construction. Nothing a
        # bot has is ours.
        snapshot()
        append("f", "ci-edit")
        CKPT = stop_salvage(GITHUB_ACTIONS="true")
        self.has("GITHUB_ACTIONS: refused", r"refused: running under CI", CKPT)
        untouched("GITHUB_ACTIONS", " M f")
        CKPT = stop_salvage(CI="1")
        self.has("CI: refused", r"refused: running under CI", CKPT)
        untouched("CI", " M f")
        w.gitq(SWORK, "checkout", "--", "f")

        # --- a revert of the branch's own work: refused, files named -----------
        # claude-code-action's restore, or a tool writing from a stale copy:
        # the branch changed hookpath, and now base's version is back over it.
        snapshot()
        (SWORK / "hookpath").write_text(w.git(SWORK, "show", "origin/main:hookpath") + "\n")
        CKPT = stop_salvage()
        self.has("revert to base: refused and the file is named",
                 r"refused: the working tree puts .origin/main..s version back over this branch.s changes to: hookpath",
                 CKPT)
        untouched("revert to base", " M hookpath")
        # ... even when a real edit rides along with it: the revert still wins.
        append("f", "more")
        CKPT = stop_salvage()
        self.has("revert plus a real edit: still refused", r"that is a revert, not new work", CKPT)
        untouched("revert plus a real edit", " M f\n M hookpath")
        w.gitq(SWORK, "checkout", "--", "f", "hookpath")
        # A file the branch never changed, put back to base's content, is not
        # a revert of anything -- it is simply unchanged, and the tree is not
        # dirty. A file the branch changed, edited to something that is
        # neither version, is new work and commits.
        snapshot()
        (SWORK / "hookpath").write_text("guard: yes, differently\n")
        CKPT = stop_salvage()
        self.has("a real edit to a branch-changed file: salvaged", rf"salvaged to .{WIP}. and pushed it", CKPT)
        salvaged("a real edit to a branch-changed file", " M hookpath")
        w.gitq(SWORK, "checkout", "--", "hookpath")

        # --- an untracked path base once had: refused, not committed (dotfiles#280)
        # A worktree created before an upstream commit deleted a tracked file
        # carries it on disk as an untracked leftover for the rest of the
        # worktree's life. Give the branch's own history a commit that added
        # stale.txt (so HEAD's ancestry has it, same as inheriting it from old
        # main) and a later one that removed it (so HEAD's own tree is clean,
        # same as after a rebase past the upstream deletion) -- then put the
        # bytes back by hand: exactly what a stale leftover looks like on
        # disk, whatever operation actually produced it.
        w.gitq(SWORK, "checkout", "claude/salvage")
        (SWORK / "stale.txt").write_text("history\n")
        w.gitq(SWORK, "add", "stale.txt")
        w.gitq(SWORK, "commit", "-m", "add stale.txt")
        w.gitq(SWORK, "rm", "-q", "stale.txt")
        w.gitq(SWORK, "commit", "-m", "remove stale.txt")
        w.gitq(SWORK, "push", "origin", "claude/salvage")
        (SWORK / "stale.txt").write_text("history\n")  # the stale leftover: untracked, on disk

        snapshot()
        append("f", "dirty")
        CKPT = stop_salvage()
        self.has("stale untracked leftover: refused, path named",
                 r"refused: untracked path\(s\) were tracked .* stale\.txt", CKPT)
        untouched("stale untracked leftover", " M f\n?? stale.txt")

        # ... a genuinely new untracked file, never tracked anywhere, still commits.
        (SWORK / "stale.txt").unlink()
        w.gitq(SWORK, "checkout", "--", "f")
        (SWORK / "new-file.txt").write_text("brand-new\n")
        snapshot()
        CKPT = stop_salvage()
        self.has("a genuinely new untracked file: salvaged", rf"salvaged to .{WIP}. and pushed it", CKPT)
        salvaged("a genuinely new untracked file", "?? new-file.txt")
        self.assertEqual(w.git(SORIGIN, "show", f"{WIP}:new-file.txt"), "brand-new", "the new file is on the wip ref")
        (SWORK / "new-file.txt").unlink()

        # ... the branch's own add-delete-recreate of the same path: path
        # history looks identical to the stale-leftover case above, but the
        # bytes are new -- this is the session's own work, not dotfiles#280's
        # upstream-deletion leftover, and the content check is what tells them
        # apart.
        (SWORK / "stale.txt").write_text("new content, not history\n")
        snapshot()
        CKPT = stop_salvage()
        self.has("recreate with new content: salvaged, not refused", rf"salvaged to .{WIP}. and pushed it", CKPT)
        salvaged("recreate with new content", "?? stale.txt")
        self.assertEqual(w.git(SORIGIN, "show", f"{WIP}:stale.txt"), "new content, not history",
                         "the recreated file carries the new content, not the old")
        (SWORK / "stale.txt").unlink()

        # --- HEAD behind @{u}: refused, not committed, not pushed (dotfiles#196)
        # Simulate the remote moving on without this checkout -- a hand
        # re-push, a second session, anything -- by pushing a new commit
        # straight to origin from a scratch clone.
        CLONE = w.S / "salvage-clone"
        sh("git", "clone", "-q", str(SORIGIN), str(CLONE), env=w.base)
        w.gitq(CLONE, "checkout", "claude/salvage")
        with open(CLONE / "f", "a") as fh:
            fh.write("newer\n")
        w.gitq(CLONE, "add", "f")
        w.gitq(CLONE, "commit", "-m", "newer-upstream")
        w.gitq(CLONE, "push", "origin", "claude/salvage")

        snapshot()
        append("f", "stale-edit")
        CKPT = stop_salvage()
        self.has("behind @{u}: refused", r"refused: .claude/salvage. is 1 commit\(s\) behind .origin/claude/salvage.",
                 CKPT)
        untouched("behind @{u}", " M f")

    # ------------------------------------------------- the state repo push
    def state_push(self):
        w = self.world("state")
        _, WORK = w.make_work()

        def stamp(clone):  # the push-debounce stamp: in the clone's git dir, never tracked
            return Path(clone) / ".git" / "claude-last-state-push"

        def subject(origin):
            return re.sub(r" \(.*", "", w.git(origin, "log", "-1", "--format=%s", "main"))

        # --- no flock: a Stop still commits and pushes the state repo ----------
        # macOS ships no flock, and a bare `flock -w 90 9 || exit 0` silently
        # skipped everything below the checkpoint write on every Mac Stop. The
        # push lock is state_lock_wait's mkdir now. A flock that fails -- as a
        # missing one does -- shadows the real one on Linux, so this proves
        # the macOS path everywhere.
        self.assertFalse([ln for ln in HOOK.read_text().splitlines() if re.search(r"^[^#]*\bflock\b", ln)],
                         "the hook never calls flock")
        flock_called = w.S / "flock-called"
        (w.BIN / "flock").write_text('#!/bin/sh\ntouch "${FLOCK_CALLED:-/dev/null}"; exit 127\n')
        (w.BIN / "flock").chmod(0o755)
        SRORIGIN, SREPO = w.make_state("state-repo")
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO, FLOCK_CALLED=flock_called)
        self.assertEqual(subject(SRORIGIN), f"State: work session {SID[:8]}",
                         "no flock: the state repo got the session commit")
        self.assertFalse(flock_called.exists(), "no flock: the fake flock was never called")
        self.assertFalse((w.TMPDIR / "claude-state-push.lock.d").exists(),
                         "no flock: the push lock is released after the Stop")
        (w.BIN / "flock").unlink()

        # --- a conflicting state-repo pull is backed out, never left mid-rebase
        # Upstream and this clone both add one path with different bytes: the
        # Stop's own commit conflicts on `pull --rebase`, and a rebase left in
        # place would wedge the clone for every later Stop.
        SRCLONE = w.S / "state-clone"
        sh("git", "clone", "-q", "-b", "main", str(SRORIGIN), str(SRCLONE), env=w.base)
        rel = "state/global/both.txt"
        (SRCLONE / rel).write_text("upstream\n")
        w.gitq(SRCLONE, "add", rel)
        w.gitq(SRCLONE, "commit", "-m", "upstream-conflict")
        w.gitq(SRCLONE, "push", "origin", "main")
        (SREPO / rel).write_text("local\n")
        stamp(SREPO).unlink(missing_ok=True)  # past the push debounce

        # In the cloud the clone dies with the VM, so a failed push is a reason.
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO, CLAUDE_CODE_REMOTE="true")
        gd = Path(w.git(SREPO, "rev-parse", "--absolute-git-dir"))
        self.assertFalse((gd / "rebase-merge").is_dir(), "conflicting pull: no rebase left in progress")
        self.assertFalse((gd / "rebase-apply").is_dir(), "conflicting pull: no apply-backend rebase left either")
        self.assertEqual(subprocess.run(["git", "-C", str(SREPO), "symbolic-ref", "-q", "HEAD"], env=w.base,
                                        capture_output=True).returncode, 0, "conflicting pull: still on main")
        ck = sorted(glob.glob(f"{SREPO}/state/global/log/auto/*/*-work-{SID[:8]}.md"))
        self.assertTrue(ck and "state-repo push failed" in read(ck[0]),
                        "conflicting pull: the verdict says the push failed")
        rec = SREPO / "state" / "global" / "metrics" / "sessions" / SID[:2] / f"{SID}.json"
        self.assertEqual(jfield(rec, "verdict"), "not archivable: state-repo push failed",
                         "conflicting pull: and so does the metrics record")

        # The local twin: the same failed push on a machine that keeps its
        # clone. The commit is the promise there, and it held (ruled for
        # dotfiles#149).
        stamp(SREPO).unlink(missing_ok=True)
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO)
        self.assertEqual(w.git(SRORIGIN, "log", "-1", "--format=%s", "main"), "upstream-conflict",
                         "conflicting pull, local: the push really failed")
        self.assertEqual(verdict(ck[0]), "archivable", "conflicting pull, local: the verdict stays archivable")
        self.assertEqual(jfield(rec, "verdict"), "archivable", "conflicting pull, local: and so does the metrics record")

        # A failed push stamps the window too: the push above failed a moment
        # ago, so this Stop commits and makes no second pull-and-push attempt.
        def pulls():
            return sum(1 for ln in w.git(SREPO, "reflog", "--format=%gs").split("\n")
                       if ln.startswith("pull --rebase"))
        p0 = pulls()
        (SREPO / "state" / "global" / "more.txt").write_text("more\n")
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO)
        self.assertEqual(pulls(), p0, "failed push: the next Stop in the window does not try again")

        # --- the board's items/ are committed like any other state ------------
        # No lint stands between an item and the commit; the push lock is
        # still released. (The failed push above holds the window, so this
        # checks the commit only.)
        it = "state/global/items/1790000000d654192b.md"
        (SREPO / "state" / "global" / "items").mkdir(parents=True, exist_ok=True)
        (SREPO / it).write_text("- [ ] an item https://example.invalid/8\n")
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO)
        self.assertEqual(subprocess.run(["git", "-C", str(SREPO), "cat-file", "-e", f"HEAD:{it}"], env=w.base,
                                        capture_output=True).returncode, 0, "items/: a new item is committed")
        self.assertFalse((w.TMPDIR / "claude-state-push.lock.d").exists(), "items/: the push lock is released")

    def state_signing(self):
        # --- the state-repo commit is signed iff this machine has a signing key
        # Same test as no-unsigned-push.sh (`git config user.signingkey`): a
        # key means the guard refuses unsigned commits here, so the hook must
        # sign; no key (a cloud VM) means unsigned, and the hook must still
        # commit and not fail.
        w = self.world("signing")
        _, WORK = w.make_work()
        pub = w.signing_key()
        (w.S / "allowed-signers").write_text(f't namespaces="git" {read(pub).strip()}\n')

        def sgrepo(name):  # a fresh state clone with a seed commit
            _, r = w.make_state(f"sg-{name}")
            w.git(r, "config", "gpg.format", "ssh")
            w.git(r, "config", "gpg.ssh.allowedSignersFile", str(w.S / "allowed-signers"))
            return r

        def subject(r):
            return re.sub(r" \(.*", "", w.git(r, "log", "-1", "--format=%s"))

        SGK = sgrepo("key")
        w.git(SGK, "config", "user.signingkey", pub)
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SGK)
        self.assertEqual(subject(SGK), f"State: work session {SID[:8]}", "state commit, key configured: the hook committed")
        self.assertNotEqual(w.git(SGK, "log", "-1", "--format=%G?"), "N",
                            "state commit, key configured: the commit is signed (%G? is not N)")
        self.assertRegex(w.git(SGK, "cat-file", "-p", "HEAD"), re.compile(r"^gpgsig", re.M),
                         "state commit, key configured: and it carries a signature header")

        SGN = sgrepo("nokey")
        w.run_hook(SID, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SGN)
        self.assertEqual(subject(SGN), f"State: work session {SID[:8]}", "state commit, no key: the hook still committed")
        self.assertEqual(w.git(SGN, "log", "-1", "--format=%G?"), "N", "state commit, no key: the commit is unsigned (%G? is N)")
        self.hasnt("state commit, no key: the verdict is not a commit failure", "state-repo commit failed",
                   sorted(glob.glob(f"{SGN}/state/global/log/auto/*/*{SID[:8]}.md"))[0])

    def state_items(self):
        # --- the session's item rides this Stop's state commit, or fails open (14.7, 14.8)
        w = self.world("items14")
        _, WORK = w.make_work()
        SR14O, SR14 = w.make_state("state14")
        w.run_hook("d1d2d3d4-0000-1111-2222", WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SR14)
        it14 = sorted(glob.glob(f"{SR14}/state/global/items/*d1d2d3d4.md"))
        rel = os.path.relpath(it14[0], SR14) if it14 else "state/global/items/none"
        self.assertEqual(subprocess.run(["git", "-C", str(SR14), "cat-file", "-e", f"HEAD:{rel}"], env=w.base,
                                        capture_output=True).returncode, 0,
                         "14.8: the minted item is in this Stop's state commit")

        def stop14(sid):  # one Stop against SR14, push window cleared; its exit status
            (SR14 / ".git" / "claude-last-state-push").unlink(missing_ok=True)
            return w.run_hook(sid, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=SR14)

        def ck14(id8):
            found = sorted(glob.glob(f"{SR14}/state/global/log/auto/*/*{id8}.md"))
            return found[0] if found else ""

        def subject():
            return re.sub(r" \(.*", "", w.git(SR14O, "log", "-1", "--format=%s", "main"))

        # The store refuses the mint: items/ is a file, so it cannot be written.
        shutil.rmtree(SR14 / "state" / "global" / "items")
        (SR14 / "state" / "global" / "items").write_text("not a directory\n")
        self.assertEqual(stop14("e1e2e3e4-0000-1111-2222"), 0, "14.7, refused: exit 0")
        self.assertEqual(subject(), "State: work session e1e2e3e4", "14.7, refused: the state commit is made and pushed")
        self.has("14.7, refused: the checkpoint says why", r"^failed: work-item create refused: ", ck14("e1e2e3e4"))
        self.assertTrue(glob.glob(f"{SR14}/state/global/pickup/*-e1e2e3e4.md"), "14.7, refused: the pickup item still lands")

        # The step itself crashes: a python3 that dies on it, and only on it.
        real = shutil.which("python3")
        (w.BIN / "python3").write_text(f'#!/bin/sh\ncase "$1" in *stop-item.py) exit 139 ;; esac\nexec {real} "$@"\n')
        (w.BIN / "python3").chmod(0o755)
        rc = stop14("f1f2f3f4-0000-1111-2222")
        (w.BIN / "python3").unlink()
        self.assertEqual(rc, 0, "14.7, crashed: exit 0")
        self.assertEqual(subject(), "State: work session f1f2f3f4", "14.7, crashed: the state commit is made and pushed")
        self.has("14.7, crashed: the checkpoint says it did not run", r"^failed: stop-item.py did not run$", ck14("f1f2f3f4"))

    def state_debounce(self):
        # --- the push debounce holds across a pull, however many sessions stop
        # The stamp used to be state/global/.last-state-push, tracked like any
        # state: another machine's Stop committed its own stamp, and a pull
        # here with this clone's stamp modified left conflict markers, read as
        # "never pushed", so the next Stop pushed at once. The stamp is the
        # clone's alone now.
        w = self.world("debounce")
        _, WORK = w.make_work()
        DORIGIN, DREPO, DPEER = w.S / "debounce-origin.git", w.S / "debounce-repo", w.S / "debounce-peer"
        sh("git", "init", "-q", "--bare", str(DORIGIN), env=w.base)
        sh("git", "init", "-q", "-b", "main", str(DREPO), env=w.base)
        w.gitq(DREPO, "remote", "add", "origin", str(DORIGIN))
        (DREPO / "state" / "global").mkdir(parents=True)
        (DREPO / "state" / "global" / ".last-state-push").write_text("1\n")
        w.gitq(DREPO, "add", "state")
        w.gitq(DREPO, "commit", "-m", "seed")
        w.gitq(DREPO, "push", "-u", "origin", "main")
        stamp = DREPO / ".git" / "claude-last-state-push"

        def dstop(sid):  # a local Stop against the debounce clone
            w.run_hook(sid, WORK, GH_PRS=PR7, CLAUDE_STATE_REPO=DREPO)

        def held():
            return sum(1 for ln in w.git(DORIGIN, "log", "--format=%s", "main").split("\n")
                       if ln.startswith("State: work session debounce "))

        dstop("debounce-aaaa-0000-1111")
        self.assertEqual(re.sub(r" \(.*", "", w.git(DORIGIN, "log", "-1", "--format=%s", "main")),
                         "State: work session debounce", "debounce: the first Stop pushes")
        self.assertEqual(w.git(DREPO, "status", "--porcelain", "--", "state/global/.last-state-push"), "",
                         "debounce: the push leaves the tracked tree clean")
        sh("git", "clone", "-q", "-b", "main", str(DORIGIN), str(DPEER), env=w.base)  # another machine
        (DPEER / "state" / "global" / ".last-state-push").write_text("0\n")
        w.gitq(DPEER, "commit", "-am", "peer-stamp")
        w.gitq(DPEER, "push", "origin", "main")
        w.gitq(DREPO, "pull", "--rebase", "--autostash", "-q")
        (DREPO / "state" / "global" / "two.txt").write_text("two\n")
        dstop("debounce-bbbb-0000-1111")
        (DREPO / "state" / "global" / "three.txt").write_text("three\n")
        dstop("debounce-cccc-0000-1111")
        self.assertEqual(w.git(DORIGIN, "log", "-1", "--format=%s", "main"), "peer-stamp",
                         "debounce: Stops in the window after a pull push nothing")
        self.assertEqual(w.git(DREPO, "rev-list", "--count", "origin/main..main"), "2",
                         "debounce: but each one committed locally")
        stamp.write_text("1\n")  # the window has passed
        dstop("debounce-dddd-0000-1111")
        self.assertEqual(held(), 4, "debounce: the next Stop past the window carries every held commit")
        self.assertTrue(stamp.stat().st_size > 0, "debounce: the stamp is in the clone's git dir")

        # A git that answers `rev-parse --absolute-git-dir` with nothing must
        # not move the stamp to the filesystem root, where it is never written
        # and every Stop pushes: the path comes from the directory state_repo
        # found, not from git.
        real = shutil.which("git", path=w.base["PATH"])
        (w.BIN / "git").write_text(f'#!/bin/sh\ncase "$*" in *rev-parse*--absolute-git-dir*) exit 1 ;; esac\n'
                                   f'exec {real} "$@"\n')
        (w.BIN / "git").chmod(0o755)
        (DREPO / "state" / "global" / "five.txt").write_text("five\n")
        dstop("debounce-eeee-0000-1111")
        (w.BIN / "git").unlink()
        self.assertEqual(held(), 4, "no git dir answer: a Stop in the window pushes nothing")

    # ------------------------------------------- a held live lock (#161)
    def live_lock(self):
        # Pre-create $LIVE/<sid>.lock with meta naming this test process's own
        # pid, so state_lock sees a live holder on this host and refuses to
        # reclaim it -- the same shape a concurrent metrics-live.sh nag
        # read-modify-write would leave.
        w = self.world("livelock")
        _, WORK = w.make_work()
        lock = w.GS / "metrics" / "live" / f"{SID}.lock"
        lock.mkdir(parents=True)
        (lock / "meta").write_text(f"pid={os.getpid()}\nhostname={os.uname().nodename}\n")
        rc = w.run_hook(SID, WORK, timeout=10, GH_PRS=PR7)
        self.assertNotEqual(rc, 124, "a held live lock never blocks Stop")
        self.assertTrue(w.ckpt(SID), "the checkpoint is still written when the lock is held")
        shutil.rmtree(lock)

    # -------------------- the incident: the checkpoint and the 📦 notice answer once
    def incident(self):
        # Two Stop hooks ran in parallel: the notice counted every session's
        # unpushed state-repo commits and computed its own verdict while this
        # hook was still committing, so the checkpoint said "archivable" and
        # the notice said "not: state repo N commit(s) unpushed".
        # stop-sequence.py runs them in order and the notice reads this hook's
        # verdict back. A parallel session's unpushed commit sits in the
        # clone; the work branch is clean, pushed, and has a PR.
        w = self.world("incident")
        _, WORK = w.make_work()
        SRORIGIN2, SREPO2 = w.make_state("state-repo2")
        (SREPO2 / "state" / "global" / "log" / "auto").mkdir(parents=True)
        stamp = SREPO2 / ".git" / "claude-last-state-push"
        SID3 = "incident-0000-1111-2222"

        def other(n):  # a parallel session's state commit, not pushed
            (SREPO2 / "state" / "global" / "log" / "auto" / f"2026-10-02T09-00-other-par{n}.md").write_text(f"other {n}\n")
            w.gitq(SREPO2, "add", "state")
            w.gitq(SREPO2, "commit", "-m", f"State: work session par{n}")

        def sequence():  # the real Stop sequence; metrics-live's stdout
            p = subprocess.run([sys.executable, str(HOOKS / "stop-sequence.py")],
                               input=w.payload(SID3, WORK, extra=',"hook_event_name":"Stop"').encode(),
                               env=w.env(GH_PRS=PR7, CLAUDE_STATE_REPO=SREPO2, METRICS_STOP_HOUR=24,
                                         METRICS_NIGHT_END_HOUR=0),
                               capture_output=True)
            return p.stdout.decode()

        def box(out):
            try:
                msg = json.loads(out).get("systemMessage", "")
            except ValueError:
                msg = ""
            return "\n".join(ln for ln in msg.split("\n") if "📦" in ln)

        def ck_verdict():
            return verdict(sorted(glob.glob(f"{SREPO2}/state/global/log/auto/*/*-work-{SID3[:8]}.md"))[0])

        # Debounced: a push went out a moment ago, so this Stop only commits
        # locally, and the clone ends holding the other session's commit and
        # this one's.
        other(1)
        stamp.write_text(f"{int(time.time())}\n")
        out = sequence()
        self.assertGreaterEqual(int(w.git(SREPO2, "rev-list", "--count", "@{u}..HEAD") or 0), 2,
                                "incident, debounced: the clone holds unpushed commits")
        self.assertEqual(ck_verdict(), "archivable", "incident, debounced: the checkpoint says archivable")
        self.assertEqual(box(out), f"📦 archivable. (claude/work {SID3[:8]})", "incident, debounced: and the 📦 line agrees")
        self.assertNotIn("state repo", box(out), "incident, debounced: the 📦 line never names the state repo")

        # A push in the same Stop: the sentinel is gone, so this Stop pushes
        # its own commit and the parallel session's with it, while the notice
        # waits its turn.
        other(2)
        stamp.unlink(missing_ok=True)
        out = sequence()
        self.assertEqual(re.sub(r" \(.*", "", w.git(SRORIGIN2, "log", "-1", "--format=%s", "main")),
                         f"State: work session {SID3[:8]}", "incident, pushed: origin got this Stop's commit")
        self.assertTrue(w.git(SRORIGIN2, "log", "--format=%s", "main", "--grep=session par2", "-1"),
                        "incident, pushed: and the parallel session's with it")
        self.assertEqual(ck_verdict(), "archivable", "incident, pushed: the checkpoint says archivable")
        self.assertEqual(box(out), f"📦 archivable. (claude/work {SID3[:8]})", "incident, pushed: and the 📦 line agrees")
        self.assertNotIn("state repo", box(out), "incident, pushed: the 📦 line never names the state repo")

    SECTIONS = ("verdict_basics", "verdict_branches", "resume_and_pickup", "session_item", "curia_digests",
                "salvage", "state_push", "state_signing", "state_items", "state_debounce", "live_lock",
                "incident")

    def test_sections(self):
        with concurrent.futures.ThreadPoolExecutor(len(self.SECTIONS)) as ex:
            futures = {name: ex.submit(getattr(self, name)) for name in self.SECTIONS}
        for name, fut in futures.items():
            with self.subTest(section=name):
                fut.result()


if __name__ == "__main__":
    unittest.main()
