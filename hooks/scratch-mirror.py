#!/usr/bin/env python3
"""PostToolUse, Edit|Write|MultiEdit: copy state-repo documents to where the
user can open them.

When a readable document (.md, .mmd, .svg, .html) is written in the state
repo from a session rooted in another repo, copy it flat into that repo's
git-ignored .scratch/ and tell the model to link the copy. The app's file
pane opens only files inside the session's own folder and follows no
symlinks, so a link into the state repo shows the user nothing.

A repo that brings its own .scratch (a symlink, or tracked files) is not
ours to write into: a copy there could land outside the repo or be
committed. Silent on the quiet path: every line printed is charged to the
session.
"""
import os
import shutil
import sys

import lib_state  # puts lib/ on sys.path
import gitrun
import hookio

DOCS = (".md", ".mmd", ".svg", ".html")


def git(top, *args):
    return gitrun.run("-C", top, *args)


def main():
    ev = lib_state.event()
    path = (ev.get("tool_input") or {}).get("file_path") or ""
    cwd = ev.get("cwd") or ""
    if not path.endswith(DOCS) or not cwd or not os.path.isfile(path):
        return
    sr = lib_state.state_repo()
    if not sr:
        return
    sr, path = os.path.realpath(sr), os.path.realpath(path)
    if not path.startswith(sr + os.sep):
        return
    r = git(cwd, "rev-parse", "--show-toplevel")
    top = r.stdout.strip()
    if r.returncode or os.path.realpath(top) == sr:
        return

    # Flat, by file name: the state repo's tree means nothing to the reader.
    d = os.path.join(top, ".scratch")
    dest = os.path.join(d, os.path.basename(path))
    if os.path.islink(d) or os.path.islink(dest) or git(top, "ls-files", "--", ".scratch").stdout:
        return
    os.makedirs(d, exist_ok=True)
    common = git(top, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    excl = os.path.join(common, "info", "exclude")
    try:
        with open(excl) as f:
            listed = ".scratch/" in f.read().splitlines()
    except OSError:
        listed = False
    if not listed:
        os.makedirs(os.path.dirname(excl), exist_ok=True)
        with open(excl, "a") as f:
            f.write(".scratch/\n")
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as f:
            f.write("*\n")
    if git(top, "check-ignore", "-q", dest).returncode:
        return
    if os.path.lexists(dest):
        os.remove(dest)
    shutil.copyfile(path, dest)

    rel = os.path.relpath(dest, cwd)
    # Angle brackets keep a space or parenthesis in the name from ending the link.
    name = os.path.basename(path).replace("[", "\\[").replace("]", "\\]")
    hookio.emit(hookio.context(
        "PostToolUse",
        f"Copied for the user to open: {rel}. Link the user to [{name}](<{rel}>), "
        "never to the state-repo path; the copy refreshes on each Write or Edit of the original."))


if __name__ == "__main__":
    lib_state.run_hook("scratch-mirror", "PostToolUse", main)
