#!/usr/bin/env python3
"""Stop hook step: write the session's work item (stop-continuity-requirements.md, 14).

Called by stop-continuity.sh after the pickup item is written and before the
state commit, so the same Stop commits what this writes. Every write goes
through bin/work-item; this step only decides which item and what changed.

Which item, in order:
  1. one this session holds a live claim on (`work-item list`, holder column);
     the newest if several. A session that mints and then claims another
     writes onto the claimed one (pencil).
  2. the one this session minted: its id is the session's start second plus
     its eight hex, so every Stop names the same id without a lookup file.
  3. one this session's Stop already wrote onto (a `stop` line from it): a
     claim since released, so the session still has one id per life.
  4. none: mint it, `open`, owner `agent`. Never `ready`, no status line ever.

What it writes (pencil):
  - a minted item's brief is written once, at the mint: the first prompt's
    first line, with one link line: the PR when there is one, else the
    session's checkpoint log in the state repo. Never rewritten; the hook
    decides nothing about the hand-off. Later Stops log only `stop`, with
    `home=` when the PR changed.
  - a claimed item keeps its brief; it gets one `stop` line on its first
    Stop, and `home=` the PR only while it has no home of its own.

Fails open: prints one outcome line for the checkpoint and exits 0, whatever
happens. A refused mint is never retried under another id. Stdlib only.
"""
import argparse
import calendar
import os
import re
import subprocess
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_ITEM = os.path.join(os.path.dirname(HOOK_DIR), "bin", "work-item")
CALL_SECS = 20  # work-item waits up to 10 s for an item's lock


class Failed(Exception):
    pass


def work_item(env, *args, stdin=None):
    """Run one work-item command; its stdout, or Failed with its complaint."""
    try:
        p = subprocess.run([sys.executable, WORK_ITEM, *args], input=stdin, env=env,
                           capture_output=True, text=True, timeout=CALL_SECS)
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed(f"work-item {args[0]}: {e}")
    if p.returncode != 0:
        why = (p.stderr.strip().splitlines() or [f"exit {p.returncode}"])[-1]
        raise Failed(f"work-item {args[0]} refused: {why}")
    return p.stdout


def git(path, *args):
    try:
        p = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def github_repo(path):
    """owner/repo of the clone at path when its origin is on GitHub, else ''."""
    url = git(path, "remote", "get-url", "origin") if path else ""
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(\.git)?/?$", url)
    return f"{m[1]}/{m[2]}" if m else ""


def pr_home(url):
    """https://github.com/o/r/pull/7 -> o/r#7; anything else -> ''."""
    m = re.fullmatch(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)/?", url or "")
    return f"{m[1]}/{m[2]}#{m[3]}" if m else ""


def handoff(prompt):
    """The hand-off a pickup body starts as: the last prompt's first line."""
    return next((l.strip() for l in (prompt or "").splitlines() if l.strip()), "")


def checkpoint_link(ckpt, items):
    """The checkpoint's URL in the state repo on GitHub, else a link relative
    to the item, which the store's link check accepts all the same."""
    top = git(os.path.dirname(ckpt), "rev-parse", "--show-toplevel")
    repo = github_repo(top) if top else ""
    if repo:
        rel = os.path.relpath(ckpt, top)
        return f"https://github.com/{repo}/blob/HEAD/{rel}"
    return f"[checkpoint]({os.path.relpath(ckpt, items)})"


def brief_for(text, pr, ckpt_link):
    """The minted item's brief: the hand-off, then one link line. A line the
    store would read as a section or a points line gets one leading space."""
    lines = [" " + l if l.startswith(("## ", "points:")) else l for l in text.splitlines()]
    body = "\n".join(lines).strip("\n")
    link = f"PR: {pr}" if pr else f"Checkpoint: {ckpt_link}"
    return f"{body}\n\n{link}" if body else link


def stop_lines(path, sid8):
    """Whether this session's Stop already wrote a line onto the item."""
    pat = re.compile(r"^\S+ " + sid8 + r" stop(\s|$)", re.M)
    try:
        return bool(pat.search(open(path).read()))
    except OSError:
        return False


def epoch(iso):
    try:
        return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return None


def short_model(m):
    m = (m or "").lower()
    return next((w for w in ("opus", "sonnet", "haiku", "fable") if w in m), "-")


def find_item(env, items, sid8, started):
    """(id, how): how is claimed, minted or touched; (minted id, None) when none."""
    held = []
    for row in work_item(env, "list", "--all").splitlines():
        f = row.split("\t")
        if len(f) >= 5 and f[3] == sid8:
            held.append((f[4], f[0]))
    if held:
        return max(held)[1], "claimed"
    start = epoch(started)
    mint = f"{start}{sid8}" if start is not None else None
    if mint and os.path.isfile(os.path.join(items, f"{mint}.md")):
        return mint, "minted"
    touched = []
    if os.path.isdir(items):
        for name in sorted(os.listdir(items)):
            if name.endswith(".md") and stop_lines(os.path.join(items, name), sid8):
                touched.append(name[:-3])
    if touched:
        return touched[-1], "touched"
    return mint, None


def step(a):
    sid8 = a.session.replace("-", "")[:8].lower()
    if not re.fullmatch(r"[0-9a-f]{8}", sid8):
        return f"skipped: session id {a.session} does not start with eight hex"
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=a.session, WORK_ITEM_DIR=a.items)
    pr = a.pr if pr_home(a.pr) else ""
    home = pr_home(pr)
    item, how = find_item(env, a.items, sid8, a.started)

    if how is None:
        if not item:
            raise Failed("no session start time, so no id to mint under")
        text = handoff(a.prompt)
        brief = brief_for(text, pr, checkpoint_link(a.checkpoint, a.items))
        first = next((l.strip() for l in text.splitlines() if l.strip()), "")
        if len(first) > 72:
            first = first[:71].rstrip() + "…"
        title = f"{a.repo or 'session'}: {first}" if first else f"{a.repo or 'session'} session {sid8}"
        work_item(env, "create", "--id", item, "--owner", "agent",
                  "--repo", github_repo(a.work_root) or "-", "--model", short_model(a.model),
                  "--brief", "-", title, stdin=brief)
        if home:
            work_item(env, "log", item, "stop", f"home={home}")
        return f"{item}: minted" + (f", home={home}" if home else "")

    path = os.path.join(a.items, f"{item}.md")
    facts = dict(l.split("=", 1) for l in work_item(env, "fold", item).splitlines() if "=" in l)
    had = facts.get("home", "")
    done, first = [], False
    if how == "minted":
        words = [f"home={home}"] if home and home != had else []
    else:
        words = [f"home={home}"] if home and had in ("", "-") else []
        # One `stop` line per session on a claimed item, not one per Stop
        # (pencil): a claim that only converses goes stale after
        # WORK_ITEM_STALE_SECS. How often to write is open in the spec, 14.
        first = how == "claimed" and not stop_lines(path, sid8)
    if words or first:
        work_item(env, "log", item, "stop", *words)
        done += words or ["stop"]
    return f"{item} ({how}): " + (", ".join(done) if done else "unchanged")


def main(argv):
    p = argparse.ArgumentParser(description="Write the session's work item.")
    for name in ("session", "items", "prompt", "pr", "checkpoint", "work-root",
                 "repo", "model", "started"):
        p.add_argument(f"--{name}", default="")
    try:
        a = p.parse_args(argv)
        print(step(a))
    except SystemExit:
        print("failed: bad arguments")
    except Failed as e:
        print(f"failed: {e}")
    except Exception as e:  # noqa: BLE001 -- a crash here never fails the Stop
        print(f"failed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
