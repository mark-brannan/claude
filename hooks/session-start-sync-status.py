#!/usr/bin/env python3
"""SessionStart: report the dotfiles sync's last result when the ~/.claude
clone is behind origin/main or the sync skipped it.

Why (claude#166): the */5 cron `dotfiles-sync.sh` fast-forwards ~/.claude,
but skips a dirty or diverged clone, and a skip reached only syslog. Over
seven days it skipped 181 of 204 runs that found the clone behind, so
sessions ran stale hooks and skills with nobody told. This puts the sync's
own one-line status in front of the session and the user when it matters,
and stays silent when the clone is current.

Three tiers, thresholds in config.json's live_clone block:
  - silent: level, or behind by less than warn_behind_minutes
  - warn, one line: behind longer than warn_behind_minutes, or the
    `claude:` part of `dotfiles-sync.sh --status` starts with "skipped"
  - repair: wedged, or behind longer than repair_behind_minutes, or by
    repair_behind_commits or more. The session is told to hand the repair
    to a sub-agent before any other work and to tell the user so: stale
    hooks and skills in every session are a blocker, not a nag. One session
    per repair_every_minutes sends it; the rest are told one is on its way,
    so sessions opened together do not race each other at the same locks.
"Behind" is read from the clone as last fetched (no network call here: the
cron fetches); how long is the age of the oldest origin/main commit the
clone lacks, so a clone a sync will catch in minutes stays silent.
"Wedged" is a git lock file, or a merge, rebase, cherry-pick or revert in
progress, older than wedged_after_minutes. Nothing in ~/.claude legitimately
holds one that long, and no sync can move the clone until it is cleared, so
the warning names the file, its age and the commands that clear it, rather
than relay the sync's guess at the cause (on 2026-11-17 a pull killed
mid-update left HEAD.lock and refs/heads/main.lock for 16 hours; the sync
called it "diverged").

A setting that cannot be read turns off only what it governs (no block:
any lag warns, no wedge check, no repair tier), and the line names it, so a
check never goes quiet unseen.
No clone, or no sync script: silent; there is nothing to report on.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to
the state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import os
import shlex
import subprocess
import sys
import time

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py
try:
    import gitrun  # noqa: E402
except ImportError:  # a seed without lib/: how far behind is unknown
    gitrun = None

sys.dont_write_bytecode = True

TIMEOUT = 5


def run(args):
    """stdout of args, stripped, or None when it fails or hangs."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def behind(clone, now):
    """(commits on origin/main the clone's HEAD lacks, seconds since the
    oldest of them was committed); (0, 0) when level or unknown."""
    if gitrun is None:
        return 0, 0
    p = gitrun.run("-C", clone, "log", "--format=%ct", "HEAD..origin/main", timeout=TIMEOUT)
    times = [int(t) for t in p.stdout.split() if t.isdigit()] if p.returncode == 0 else []
    return (len(times), max(0, now - min(times))) if times else (0, 0)


def limits():
    """config.json's live_clone block, and why it is unusable ("" when it is)."""
    import config  # lib/, on sys.path above
    try:
        v = config.get("live_clone")
    except config.ConfigError as e:
        return {}, str(e)
    return (v, "") if isinstance(v, dict) else ({}, "config.json's live_clone is not an object")


def number(lim, key, unread, scale=1):
    """lim[key] times scale, or None when absent or not a number; a key the
    block lacks or holds badly is added to unread."""
    try:
        return float(lim[key]) * scale
    except (KeyError, TypeError, ValueError):
        if lim:
            unread.append(key)
        return None


def first_repair(home, now, every):
    """True when no session sent a repair in the last `every` seconds, and
    stamp this one; always True when `every` is unknown."""
    stamp = os.path.join(home, ".local", "state", "session-start-sync-status", "repair")
    try:
        if every is not None and now - os.stat(stamp).st_mtime < every:
            return False
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(stamp), exist_ok=True)
        with open(stamp, "w"):
            pass
    except OSError:
        pass
    return True


def wedge(clone, now, stale_after):
    """Stale git locks and operations in progress in the clone, oldest
    first, as (path under .git, age, verb): verb is the git command whose
    --abort clears the path, or None for a lock, which is removed."""
    if stale_after is None:
        return []
    gitdir = os.path.join(clone, ".git")
    markers = dict(gitrun.IN_PROGRESS) if gitrun else {}
    found = []
    for root, dirs, files in os.walk(gitdir):
        if root == gitdir:
            dirs[:] = [d for d in dirs if d != "objects" and d not in markers]
        found += [(os.path.join(root, f), None) for f in files if f.endswith(".lock")]
    found += [(os.path.join(gitdir, m), verb) for m, verb in markers.items()
              if os.path.exists(os.path.join(gitdir, m))]
    stale = []
    for path, verb in found:
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            continue
        if now - mtime > stale_after:
            stale.append((mtime, os.path.relpath(path, gitdir), verb))
    import when  # lib/, on sys.path above
    return [(rel, when.age(now - m), verb) for m, rel, verb in sorted(stale)]


def unwedge(stuck):
    """The shell line that clears a wedge and fast-forwards: locks off
    first, since an --abort takes the index lock, then each abort once, in
    gitrun.IN_PROGRESS order. A rebase killed before its first step refuses
    --abort; --quit clears that one."""
    locks = [f"~/.claude/.git/{shlex.quote(rel)}" for rel, _, verb in stuck if not verb]
    steps = [f"rm {' '.join(locks)}"] if locks else []
    verbs = {v for _, _, v in stuck if v}
    for v in dict.fromkeys(v for _, v in gitrun.IN_PROGRESS if v in verbs):
        abort = f"git -C ~/.claude {v} --abort"
        steps.append(f"({abort} || git -C ~/.claude rebase --quit)" if v == "rebase" else abort)
    return " && ".join(steps + ["git -C ~/.claude merge --ff-only origin/main"])


def claude_part(status):
    """The `claude: ...` phrase of a status line, or ""."""
    for part in status.split("; "):
        if part.startswith("claude: "):
            return part[len("claude: "):]
    return ""


REPAIR = ("PRIORITY, first: ~/.claude is not live with origin/main, so this and every "
          "session runs stale hooks and skills. Say so to the user in your first line, then hand the repair "
          "to a sub-agent at once (Agent tool): it runs ~/.claude/bin/self-check, clears any wedge named "
          "below, fast-forwards ~/.claude to origin/main, and reports what it found and did; a code fix it "
          "needs goes in a worktree of ~/claude, never in ~/.claude. Carry on with the user's task while it "
          "runs. ")


def main():
    home = os.path.expanduser("~")
    clone = os.path.join(home, ".claude")
    sync = os.path.join(home, ".local", "bin", "dotfiles-sync.sh")
    if not os.path.isdir(os.path.join(clone, ".git")) or not os.path.isfile(sync):
        return
    now = time.time()
    lim, why = limits()
    unread = []
    status = run(["sh", sync, "--status"]) or ""
    n, lag_secs = behind(clone, now)
    skipped = claude_part(status).startswith("skipped")
    stuck = wedge(clone, now, number(lim, "wedged_after_minutes", unread, 60))
    warn_after = number(lim, "warn_behind_minutes", unread, 60) or 0
    repair_after = number(lim, "repair_behind_minutes", unread, 60)
    repair_commits = number(lim, "repair_behind_commits", unread)
    every = number(lim, "repair_every_minutes", unread, 60)
    late = n and lag_secs >= warn_after
    repair = bool(stuck) or bool(n and repair_after is not None and lag_secs >= repair_after) \
        or bool(n and repair_commits is not None and n >= repair_commits)
    off = (f"config.json's live_clone is unreadable ({why}), so any lag warns and there is no wedge check "
           f"or repair tier. " if why else
           f"config.json's live_clone has no usable {', '.join(unread)}; what it sets is off. " if unread else "")
    if not late and not skipped and not repair and not off:
        return
    import when  # lib/, on sys.path above
    lag = (f"~/.claude is {n} commit(s) behind origin/main, the oldest {when.age(lag_secs)} old" if n
           else "~/.claude was skipped by the last sync" if skipped else "")
    text = f"{lag}, so this session may run stale hooks and skills. " if lag else ""
    text = off + text + f"Last sync (`dotfiles-sync.sh --status`): {status or 'no output'}"
    if stuck:
        named = ", ".join(f".git/{rel} ({old} old)" for rel, old, _ in stuck)
        text = (f"~/.claude is wedged: {named}. No sync can move it until that is cleared; with no git "
                f"process running in ~/.claude, run `{unwedge(stuck)}`. {text}")
    if repair and not first_repair(home, now, every):
        repair, text = False, f"~/.claude needs repair; another session sent a sub-agent for it. {text}"
    context = (REPAIR + text) if repair else text
    shown = (f"⚠ ~/.claude needs repair; a sub-agent is being sent. {text}") if repair else text
    import hookio  # lib/, on sys.path above
    hookio.emit(hookio.context("SessionStart", context, system=shown), ascii=False)


if __name__ == "__main__":
    import lib_state  # beside this file
    lib_state.run_hook("session-start-sync-status", "SessionStart", main)
