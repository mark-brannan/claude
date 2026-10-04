#!/usr/bin/env python3
"""Tests for prune-worktrees. Run: python3 bin/prune-worktrees.test.py
One worktree per keep rule, each failing exactly one leg; a dry run changes
nothing; --delete removes only the landed clean one, prints a working undo,
and prunes plugin entries for gone directories only."""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

PW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prune-worktrees")
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
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")


def git(repo, *a):
    subprocess.run(["git", "-C", repo, "-c", "commit.gpgsign=false", *a],
                   env=ENV, check=True, capture_output=True)


def age(wt):
    """Backdate a worktree's HEAD and reflog by two days."""
    gd = subprocess.run(["git", "-C", wt, "rev-parse", "--path-format=absolute", "--git-dir"],
                        env=ENV, capture_output=True, text=True).stdout.strip()
    old = time.time() - 2 * 86400
    for f in ("HEAD", "logs/HEAD"):
        if os.path.exists(os.path.join(gd, f)):
            os.utime(os.path.join(gd, f), (old, old))


def run(*a):
    r = subprocess.run([sys.executable, PW, "--no-fetch", "--repo", R, *a],
                       env=ENV, capture_output=True, text=True, cwd=S)
    return r.returncode, r.stdout + r.stderr


REMOTE = os.path.join(S, "remote.git")
subprocess.run(["git", "init", "-q", "--bare", REMOTE], env=ENV, check=True)
R = os.path.join(HOME, "work")
subprocess.run(["git", "init", "-q", "-b", "main", R], env=ENV, check=True)
git(R, "remote", "add", "origin", REMOTE)
git(R, "commit", "-q", "--allow-empty", "-m", "base")
git(R, "push", "-q", "-u", "origin", "main")
git(R, "remote", "set-head", "origin", "main")

W = os.path.join(R, ".claude", "worktrees")
wts = {}
for name in ("landed", "dirty", "unlanded", "recent", "locked"):
    wts[name] = os.path.join(W, name)
    git(R, "worktree", "add", "-q", "-b", name, wts[name], "main")
git(wts["landed"], "commit", "-q", "--allow-empty", "-m", "pushed")
git(wts["landed"], "push", "-q", "-u", "origin", "landed")
with open(os.path.join(wts["dirty"], "f"), "w") as f:
    f.write("edit\n")
with open(os.path.join(wts["unlanded"], "g"), "w") as f:
    f.write("work\n")
git(wts["unlanded"], "add", "g")
git(wts["unlanded"], "commit", "-q", "-m", "local only")
git(R, "worktree", "lock", wts["locked"])
for name in ("landed", "dirty", "unlanded", "locked"):
    age(wts[name])
gone = os.path.join(W, "vanished")
git(R, "worktree", "add", "-q", "-b", "vanished", gone, "main")
subprocess.run(["rm", "-rf", gone], check=True)

PL = os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")
os.makedirs(os.path.dirname(PL))
plugins = {"version": 2, "plugins": {"x@y": [
    {"scope": "user", "installPath": "/c"},
    {"scope": "project", "projectPath": wts["recent"], "installPath": "/c"},
    {"scope": "project", "projectPath": os.path.join(S, "nowhere"), "installPath": "/c"},
]}}
with open(PL, "w") as f:
    json.dump(plugins, f)

# --- dry run ----------------------------------------------------------------
rc, out = run("-v")
check(rc == 0, "dry run exits 0", out)
check("would remove .claude/worktrees/landed (on origin/landed)" in out, "landed is a candidate", out)
for name, why in (("dirty", "dirty"), ("unlanded", "unlanded: 1 commit"),
                  ("recent", "touched in the last 24h"), ("locked", "locked")):
    check(f"keep .claude/worktrees/{name} -- {why}" in out, f"{name} kept for {why}", out)
check("would clear metadata" in out and "vanished" in out, "missing dir's metadata named", out)
check("would drop 1 project entry" in out, "one plugin entry named", out)
check(all(os.path.isdir(p) for n, p in wts.items()), "dry run removes nothing")
check(len(json.load(open(PL))["plugins"]["x@y"]) == 3, "dry run leaves plugins alone")
idx = os.path.join(R, ".git", "worktrees", "dirty", "index")
before = os.path.getmtime(idx)
run()
check(os.path.getmtime(idx) == before, "a run does not rewrite a worktree's index")

# --- delete -----------------------------------------------------------------
rc, out = run("--delete")
check(rc == 0, "--delete exits 0", out)
check(not os.path.exists(wts["landed"]), "landed worktree removed", out)
check(all(os.path.isdir(wts[n]) for n in ("dirty", "unlanded", "recent", "locked")),
      "every keeper survives", out)
check(subprocess.run(["git", "-C", R, "rev-parse", "--verify", "-q", "refs/heads/landed"],
                     env=ENV, capture_output=True).returncode == 0, "branch is left for prune-branches")
check("vanished" not in subprocess.run(["git", "-C", R, "worktree", "list"], env=ENV,
                                       capture_output=True, text=True).stdout, "metadata pruned")
entries = json.load(open(PL))["plugins"]["x@y"]
check([e.get("projectPath") for e in entries] == [None, wts["recent"]], "only the gone entry dropped",
      json.dumps(entries))
undo = [l.split("undo: ", 1)[1] for l in out.splitlines() if "removed .claude/worktrees/landed" in l]
check(bool(undo), "undo printed", out)
if undo:
    subprocess.run(shlex.split(undo[0]), env=ENV, cwd="/", capture_output=True)
    check(os.path.isdir(wts["landed"]), "undo restores the worktree", undo[0])

subprocess.run(["rm", "-rf", S])
print(f"prune-worktrees: {'FAIL' if fails else 'ok'} ({fails} failure(s))")
sys.exit(1 if fails else 0)
