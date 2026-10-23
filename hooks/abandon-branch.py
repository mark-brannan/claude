#!/usr/bin/env python3
"""Deletes a branch locally and on its remote, deliberately. Split out of
branch-home-gate.py; see dotfiles#115.

Usage: abandon-branch.py [-C <path>] [<branch>]
  -C <path>   the repo to act in (default: cwd)
  <branch>    the branch to delete (default: the one checked out at <path>)

Refuses in $HOME (yadm gate); only deletes the local branch once the
remote side is a confirmed absence or a confirmed deletion, never on an
indeterminate ls-remote (network, auth, a dead remote).
"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

import gitrun  # noqa: E402
import state  # noqa: E402


def say(msg):
    print(f"abandon-branch: {msg}", file=sys.stderr)


def git(root, *args, **kw):
    return gitrun.run("-C", root, *args, **kw)


def open_pr_hits(root, branch):
    """The open PRs that have branch as base or head, as "#N title" lines;
    None when the list could not be read. Fails closed: gh missing, no auth,
    or a list long enough to be truncated all give None."""
    try:
        p = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "1000",
                            "--json", "number,title,baseRefName,headRefName"],
                           cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if p.returncode or not p.stdout.strip():
            return None
        prs = json.loads(p.stdout)
        if not isinstance(prs, list) or len(prs) >= 1000:
            return None
        return [f"#{pr['number']} {pr['title']}" for pr in prs
                if pr.get("baseRefName") == branch or pr.get("headRefName") == branch]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def main(argv):
    work_root = "."
    args = list(argv)
    while args:
        a = args[0]
        if a == "-C":
            if len(args) < 2:
                say("-C needs a path")
                return 2
            work_root = args[1]
            del args[:2]
        elif a.startswith("-C"):
            work_root = a[2:]
            del args[0]
        elif a == "--":
            del args[0]
            break
        elif a.startswith("-"):
            say(f"unknown option {a}")
            return 2
        else:
            break
    branch = args[0] if args else ""

    p = git(work_root, "rev-parse", "--show-toplevel")
    if p.returncode:
        say("not a git repo")
        return 1
    work_root = p.stdout.rstrip("\n")
    if not branch:
        p = git(work_root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = p.stdout.rstrip("\n") if not p.returncode else ""
    if branch in ("", "HEAD"):
        say("no branch (detached HEAD?) -- pass one explicitly")
        return 1
    if branch in ("main", "master"):
        say(f"refusing to abandon {branch}")
        return 1

    if work_root == os.environ.get("HOME", ""):
        say(f"refused -- {work_root} is $HOME (yadm gate). Delete it by hand from a worktree.")
        return 1

    # Same lock stop-continuity.py takes before it commits and pushes, so the
    # two never interleave and a salvage push cannot resurrect the branch we
    # are deleting. Best effort: a lock not taken in 90s proceeds unlocked.
    state.state_lock_wait(state.STATE_PUSH_LOCK, 90)
    try:
        return abandon(work_root, branch)
    finally:
        state.state_unlock()


def abandon(work_root, branch):
    p = git(work_root, "rev-parse", "--short", branch)
    sha = p.stdout.rstrip("\n") if not p.returncode and p.stdout.strip() else "?"

    remote_rc = git(work_root, "ls-remote", "--exit-code", "--heads", "origin", branch).returncode
    # Exit 2 means ls-remote reached origin and found no matching ref: the
    # branch is confirmed absent there. Any other nonzero (network, auth, a
    # dead remote) is "could not check", not "not there" -- and must not be
    # treated as license to delete the only copy.
    if remote_rc == 0:
        # Deleting the base or head of an open PR closes it, and the
        # stacked-base scanner never sees this push (dotfiles#227).
        hits = open_pr_hits(work_root, branch)
        if hits is None:
            say(f"refused -- could not check open PRs on `{branch}` (gh missing, no auth, no network).")
            return 1
        if hits:
            say(f"refused -- `{branch}` is the base or head of open PR(s):\n"
                + "\n".join(hits) + "\nMerge or retarget first.")
            return 1
        # Refspec form, not --delete: a ref name is never mistaken for a flag.
        pushed = git(work_root, "push", "-q", "origin", f":refs/heads/{branch}", timeout=60)
        remote = "deleted" if pushed.returncode == 0 else "NOT deleted (push failed)"
    elif remote_rc == 2:
        remote = "not on the remote"
    else:
        remote = f"NOT deleted (could not verify remote, ls-remote exit {remote_rc})"

    # Only delete the local branch once the remote side is a confirmed absence
    # or a confirmed deletion -- never on an indeterminate remote check.
    local_state = "deleted" if remote in ("deleted", "not on the remote") else f"kept ({remote})"
    p = git(work_root, "rev-parse", "--abbrev-ref", "HEAD")
    cur = p.stdout.rstrip("\n") if not p.returncode else ""
    if local_state == "deleted" and cur == branch:
        # The branch is checked out here, so detach first. Uncommitted changes
        # survive a detach; the commits stay reachable through the reflog.
        if git(work_root, "checkout", "-q", "--detach").returncode:
            local_state = "NOT deleted (could not detach HEAD)"
    if local_state == "deleted":
        if git(work_root, "branch", "-q", "-D", branch).returncode:
            local_state = "NOT deleted (checked out in another worktree?)"

    print(f"abandon-branch: abandoned `{branch}` at {sha} -- local {local_state}, remote {remote}. "
          f"`git checkout -b {branch} {sha}` restores it while the reflog holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
