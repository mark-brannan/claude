#!/usr/bin/env python3
"""Tests for state-push. Run: python3 bin/state-push.test.py
Level with origin: exits 0, prints nothing, no network. Ahead: pushes, also
past an untracked file the incoming commits carry. No state repo: exit 2."""
import os
import subprocess
import sys
import tempfile

SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state-push")
fails = 0


def check(cond, msg, out=""):
    global fails
    if not cond:
        fails += 1
        print(f"FAIL: {msg}")
        if out:
            print("    " + out.replace("\n", "\n    "))


S = tempfile.mkdtemp()
HOME = os.path.join(S, "home")
os.makedirs(HOME)
ENV = dict(os.environ, HOME=HOME, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1",
           GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
           STOP_PUSH_BACKOFF_SECS="0")
ENV.pop("CLAUDE_STATE_REPO", None)


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", *a],
                          env=ENV, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, path, text, msg):
    os.makedirs(os.path.dirname(os.path.join(repo, path)), exist_ok=True)
    with open(os.path.join(repo, path), "w") as f:
        f.write(text)
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", msg)


def run(repo):
    env = dict(ENV, CLAUDE_STATE_REPO=repo) if repo else ENV
    r = subprocess.run([sys.executable, SP], env=env, capture_output=True, text=True, cwd=S)
    return r.returncode, r.stdout + r.stderr


ORIGIN = os.path.join(S, "origin.git")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", ORIGIN], env=ENV, check=True)
SR = os.path.join(S, "state")
OTHER = os.path.join(S, "other")
subprocess.run(["git", "init", "-q", "-b", "main", SR], env=ENV, check=True)
git(SR, "remote", "add", "origin", ORIGIN)
commit(SR, "state/global/a.txt", "a\n", "base")
git(SR, "push", "-q", "-u", "origin", "main")
subprocess.run(["git", "clone", "-q", ORIGIN, OTHER], env=ENV, check=True)

# Level with origin: nothing to do, nothing said.
rc, out = run(SR)
check(rc == 0 and out == "", "level: exit 0, silent", out)

# Ahead, and the other clone pushed a file this clone holds untracked.
commit(SR, "state/global/b.txt", "b\n", "local-ahead")
commit(OTHER, "state/global/live.json", "theirs\n", "other-adds-live")
git(OTHER, "push", "-q", "origin", "main")
with open(os.path.join(SR, "state/global/live.json"), "w") as f:
    f.write("ours\n")
rc, out = run(SR)
check(rc == 0 and "pushed" in out, "ahead: exit 0, says pushed", out)
check(git(SR, "rev-list", "--left-right", "--count", "HEAD...origin/main") == "0\t0",
      "ahead: level with origin afterwards")
check(git(ORIGIN, "log", "-1", "--format=%s", "main") == "local-ahead", "ahead: the local commit landed")
with open(os.path.join(SR, "state/global/live.json")) as f:
    check(f.read() == "ours\n", "collision: the local bytes are back")

# A conflicted pull the hook's own run left stopped (killed before its
# --abort) is aborted and pushed; one a person stopped by hand is left alone.
def stopped_rebase(own):
    git(OTHER, "pull", "-q", "--rebase")
    commit(OTHER, "state/global/a.txt", "theirs\n", "other-edits-a")
    git(OTHER, "push", "-q", "origin", "main")
    commit(SR, "state/global/a.txt", "ours\n", "local-edits-a")
    subprocess.run(["git", "-C", SR, "pull", "-q", "--rebase", "--autostash"], env=ENV, capture_output=True)
    gd = git(SR, "rev-parse", "--absolute-git-dir")
    check(os.path.isfile(os.path.join(gd, "rebase-merge", "head-name")), "setup: the pull stopped on its conflict")
    if own:
        open(os.path.join(gd, "claude-pull-running"), "w").close()
    git(OTHER, "revert", "--no-edit", "HEAD")  # the conflict is gone upstream now
    git(OTHER, "push", "-q", "origin", "main")
    return gd


gd = stopped_rebase(own=False)
rc, out = run(SR)
check(rc == 1 and "not pushed (" in out, "a person's rebase: not pushed, says why", out)
check(os.path.isdir(os.path.join(gd, "rebase-merge")), "a person's rebase: left in place")
for a in (("rebase", "--abort"), ("fetch", "-q"), ("reset", "-q", "--hard", "origin/main")):
    subprocess.run(["git", "-C", SR, *a], env=ENV, capture_output=True)  # a broken scenario above costs one FAIL
gd = stopped_rebase(own=True)
rc, out = run(SR)
check(rc == 0 and "pushed" in out, "the hook's own rebase: aborted, then pushed", out)
check(not os.path.exists(os.path.join(gd, "rebase-merge")), "the hook's own rebase: cleared")
check(not os.path.exists(os.path.join(gd, "claude-pull-running")), "the hook's own rebase: the mark is off")
check(git(ORIGIN, "log", "-1", "--format=%s", "main") == "local-edits-a", "the hook's own rebase: the local commit landed")

# The job finds a detached clone before any Stop does: main's own commit is
# merged back and pushed with the detached line, no rescue branch left.
commit(SR, "state/global/stranded.txt", "s\n", "stranded-on-main")
git(SR, "checkout", "-q", "--detach", "origin/main")
commit(SR, "state/global/detached.txt", "d\n", "detached-work")
rc, out = run(SR)
check(rc == 0 and "pushed" in out, "detached: reattached and pushed", out)
check(git(ORIGIN, "ls-tree", "-r", "--name-only", "main").count("ed.txt") == 2, "detached: both lines reached origin")
check(git(SR, "branch", "--list", "rescue/*") == "", "detached: no rescue branch left")

# No state repo.
rc, out = run(None)
check(rc == 2, "no state repo: exit 2", out)

print("state-push: OK" if not fails else f"state-push: {fails} failure(s)")
sys.exit(1 if fails else 0)
