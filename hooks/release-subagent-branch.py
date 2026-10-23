#!/usr/bin/env python3
"""SubagentStop: a finished sub-agent lets go of its branch.

Why: Claude Code removes a sub-agent's worktree on exit only when nothing
changed in it. A sub-agent that committed keeps its worktree, and with it
the branch checked out -- for good, since nothing ever comes back to
release it. git then refuses that branch to every other worktree, and the
pickup skill reads the refusal as a live claim: claude#108 sat unworkable
behind a sub-agent that had finished hours before.

A session releases its worktree when it finishes (pushed, PR open); this
does the same for a sub-agent, at the moment it finishes. It detaches the
worktree's HEAD and nothing else -- the worktree, its files and the branch
all stay, so there is nothing to undo, and `git switch <branch>` inside it
takes the branch back.

Only when the work is safe elsewhere: the tree is clean (untracked files
count) and every commit on HEAD is on some remote-tracking ref. A dirty or
unpushed worktree keeps its branch, so its work stays where a human looking
for it will find it. No network: a remote ref that is stale only makes the
check stricter.

Locates the worktree from the sub-agent's own transcript (its cwd), falling
back to <repo>/.claude/worktrees/agent-<agent_id> under the parent's repo --
where the Agent tool puts it. Fails open, silently: a session must never be
unable to end because a branch could not be released.
"""
import os
import re
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402,F401  (puts lib/ on sys.path)
import gitrun  # noqa: E402
import hookio  # noqa: E402


def field(ev, key):
    v = ev.get(key)
    return v if isinstance(v, str) and v else None


def worktree(agent_id, transcript, cwd):
    """The sub-agent's worktree path, or None."""
    if transcript and os.path.isfile(transcript):
        pat = re.compile(r'"cwd":"([^"]*/\.claude/worktrees/agent-' + re.escape(agent_id) + r')"')
        with open(transcript, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.search(line)
                if m:
                    return m.group(1)
    if cwd:
        common = gitrun.out("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
        if common:
            return os.path.join(os.path.dirname(common), ".claude", "worktrees", f"agent-{agent_id}")
    return None


def main():
    ev = hookio.read()
    agent_id = field(ev, "agent_id")
    if not agent_id or not re.fullmatch(r"[A-Za-z0-9_-]+", agent_id):
        return 0
    wt = worktree(agent_id, field(ev, "agent_transcript_path"), field(ev, "cwd"))
    if not wt or not os.path.isdir(wt):
        return 0
    if gitrun.out("rev-parse", "--show-toplevel", cwd=wt) != wt:
        return 0
    if not gitrun.ok("symbolic-ref", "-q", "HEAD", cwd=wt):
        return 0  # already detached
    if gitrun.run("status", "--porcelain", cwd=wt).stdout.strip():
        return 0
    unpushed = gitrun.run("rev-list", "-n1", "HEAD", "--not", "--remotes", cwd=wt)
    if unpushed.returncode or unpushed.stdout.strip():
        return 0
    gitrun.run("switch", "-q", "--detach", cwd=wt)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 -- a session must never be unable to end
        sys.exit(0)
