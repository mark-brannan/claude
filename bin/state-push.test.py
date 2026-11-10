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

# No state repo.
rc, out = run(None)
check(rc == 2, "no state repo: exit 2", out)

print("state-push: OK" if not fails else f"state-push: {fails} failure(s)")
sys.exit(1 if fails else 0)
