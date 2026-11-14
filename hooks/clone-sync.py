#!/usr/bin/env python3
"""PostToolUse and Stop: bring the user's top-level clone up to its remote's
default branch once an agent's work lands there.

Opt-in per clone: config.json's `clone_sync.clones` maps a clone path to what
to do with the user's uncommitted edits to a file that upstream also changed:

  keep      leave the clone alone and say which files are in the way
  upstream  save the edits under refs/clone-sync/<stamp> and take upstream's

Fires after a Bash call that pushes, merges a PR or waits on one
(`pr-blockers`), after the GitHub MCP merge, and on Stop (an armed auto-merge
lands between turns). Only the clone of the repo in play is touched: the
session's own repo, or one named by owner/repo in the call.

Never leaves a clone mid-operation. A clone off its default branch or with a
merge or rebase already half-done is skipped; local commits are rebased, and
a rebase that conflicts is aborted, so the clone is as it was. Each outcome
other than "already current" is one line to the user and the model.

Fails open: any error is traced and exits 0, and the call is untouched.
"""
import json
import os
import re
import sys
import time

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import config  # noqa: E402
import gitrun  # noqa: E402
import hookio  # noqa: E402

TRIGGER = re.compile(r"\bgit\b[^\n]*\bpush\b|\bgh\b[^\n]*\bpr\b[^\n]*\bmerge\b|\bpr-blockers\b")
MCP_MERGE = re.compile(r"^mcp__.*__merge_pull_request$")
FETCH_TIMEOUT = 20


def clones():
    """[(path, policy)] for configured clones that exist."""
    try:
        seam = os.environ.get("CLONE_SYNC_CONFIG")  # tests point at their own config
        conf = (config.load((seam,)) if seam else config.load()).get("clone_sync", {}).get("clones", {})
    except config.ConfigError:
        return []
    out = []
    for path, policy in conf.items():
        p = os.path.realpath(os.path.expanduser(path))
        if os.path.isdir(os.path.join(p, ".git")) and policy in ("keep", "upstream"):
            out.append((p, policy))
    return out


def common_dir(cwd):
    if not cwd or not os.path.isdir(cwd):
        return None
    d = gitrun.out("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    return os.path.realpath(d) if d else None


def slug(clone):
    """owner/repo from origin's URL, lowercased, or None."""
    url = gitrun.out("config", "--get", "remote.origin.url", cwd=clone)
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else None


def in_play(ev, candidates):
    """The configured clones this event concerns."""
    mine = common_dir(ev.get("cwd"))
    named = json.dumps(ev.get("tool_input") or {}).lower()
    ti = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
    mcp = f"{ti.get('owner', '')}/{ti.get('repo', '')}".lower()
    hits = []
    for clone, policy in candidates:
        s = slug(clone)
        if (mine and common_dir(clone) == mine) or (s and (s == mcp or re.search(
                r"(?<![\w.-])" + re.escape(s) + r"(?![\w.-])", named))):
            hits.append((clone, policy))
    return hits


def short(clone):
    home = os.path.expanduser("~")
    return "~" + clone[len(home):] if clone.startswith(home + os.sep) else clone


def names(text):
    return [n for n in text.splitlines() if n]


def busy(clone):
    """Why the clone is mid-operation, or None."""
    gd = gitrun.out("rev-parse", "--absolute-git-dir", cwd=clone)
    for marker, what in (("rebase-merge", "a rebase"), ("rebase-apply", "a rebase"),
                         ("MERGE_HEAD", "a merge"), ("CHERRY_PICK_HEAD", "a cherry-pick"),
                         ("REVERT_HEAD", "a revert")):
        if os.path.exists(os.path.join(gd, marker)):
            return what
    if names(gitrun.out("diff", "--name-only", "--diff-filter=U", cwd=clone)):
        return "a conflict"
    return None


def sync(clone, policy, quiet=False):
    """One line saying what happened, or None when nothing worth saying.
    quiet (Stop, which the user did not cause) says nothing on a failed fetch."""
    where = short(clone)
    default = gitrun.out("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=clone)
    branch = default.split("/", 1)[1] if default.startswith("origin/") else "main"
    why = busy(clone)
    if why:
        stuck = names(gitrun.out("diff", "--name-only", "--diff-filter=U", cwd=clone))
        files = f" ({', '.join(stuck[:3])} unmerged)" if stuck else ""
        return f"{where} left alone: {why} is half-done there{files}; finish or abort it, then pull"
    if gitrun.out("symbolic-ref", "--short", "-q", "HEAD", cwd=clone) != branch:
        return None  # the user has it on another branch on purpose
    f = gitrun.run("fetch", "-q", "origin", branch, cwd=clone, timeout=FETCH_TIMEOUT,
                   env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if f.returncode:
        return None if quiet else f"{where} not synced: fetch failed ({(f.stderr.strip().splitlines() or ['?'])[-1]})"
    up = f"origin/{branch}"
    before = gitrun.out("rev-parse", "--short", "HEAD", cwd=clone)
    if gitrun.ok("merge-base", "--is-ancestor", up, "HEAD", cwd=clone):
        return None
    incoming = set(names(gitrun.out("diff", "--name-only", "--no-renames", f"HEAD...{up}", cwd=clone)))
    untracked = set(names(gitrun.out("ls-files", "--others", "--exclude-standard", cwd=clone)))
    dirty = set(names(gitrun.out("diff", "--name-only", "HEAD", cwd=clone))) | untracked
    overlap = sorted(incoming & dirty)
    note = ""
    if overlap:
        listed = ", ".join(overlap[:3]) + (f" +{len(overlap) - 3}" if len(overlap) > 3 else "")
        if policy == "keep":
            return f"{where} not synced: your uncommitted edits to {listed} clash with upstream"
        lost = sorted(untracked & incoming)
        if lost:  # stash create cannot back up an untracked file
            return (f"{where} not synced: untracked {', '.join(lost[:3])} would be overwritten "
                    "by upstream; move or add them")
        saved = gitrun.out("stash", "create", f"clone-sync backup of {listed}", cwd=clone)
        if not saved:
            return f"{where} not synced: could not back up your edits to {listed}"
        ref = f"refs/clone-sync/{time.strftime('%Y%m%dT%H%M%S')}"
        gitrun.run("update-ref", ref, saved, cwd=clone, check=True)
        gitrun.run("checkout", "HEAD", "--", *overlap, cwd=clone, check=True)
        note = f"; your edits to {listed} were replaced, back with `git -C {where} checkout {ref} -- {' '.join(overlap)}`"
    local = int(gitrun.out("rev-list", "--count", f"{up}..HEAD", cwd=clone) or 0)
    stash = gitrun.out("rev-parse", "-q", "--verify", "refs/stash", cwd=clone)
    if not local:
        m = gitrun.run("merge", "-q", "--ff-only", "--autostash", up, cwd=clone)
        if m.returncode:
            return f"{where} not synced: fast-forward refused ({(m.stderr.strip().splitlines() or ['?'])[0]}){note}"
        how = "fast-forward"
    else:
        r = gitrun.run("rebase", "-q", "--autostash", up, cwd=clone)
        if r.returncode:
            clash = names(gitrun.out("diff", "--name-only", "--diff-filter=U", cwd=clone))
            gitrun.run("rebase", "--abort", cwd=clone)
            files = ", ".join(clash[:3]) or "?"
            return (f"{where} not synced: rebasing your {local} local commit(s) onto upstream "
                    f"conflicts in {files}; aborted, the clone is as it was{note}")
        how = f"rebased your {local} local commit(s)"
    after = gitrun.out("rev-parse", "--short", "HEAD", cwd=clone)
    if gitrun.out("rev-parse", "-q", "--verify", "refs/stash", cwd=clone) != stash:
        # git exits 0 when the autostash will not reapply and parks it in refs/stash
        note += "; your other edits did not reapply and are in git stash, pop to restore"
    return f"{where} {branch} {before} -> {after} ({how}){note}"


def main():
    ev = hookio.read()
    event = ev.get("hook_event_name") or ""
    tool = ev.get("tool_name") or ""
    if event == "PostToolUse":
        cmd = (ev.get("tool_input") or {}).get("command", "") if tool == "Bash" else ""
        if not (TRIGGER.search(cmd or "") or MCP_MERGE.match(tool)):
            return 0
    elif event != "Stop" or hookio.stop_hook_active(ev):
        return 0
    quiet = event == "Stop"
    lines = [s for s in (sync(c, p, quiet) for c, p in in_play(ev, clones())) if s]
    if not lines:
        return 0
    text = "clone-sync: " + "\nclone-sync: ".join(lines)
    if event == "Stop":
        hookio.emit({"systemMessage": text})
    else:
        hookio.emit(hookio.context("PostToolUse", text, system=text))
    return 0


if __name__ == "__main__":
    lib_state.run_hook("clone-sync", "PostToolUse|Stop", main)
