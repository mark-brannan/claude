#!/usr/bin/env python3
"""Keep this repo's copy of the Claude layer equal to mark-brannan/dotfiles main.

Dotfiles stays the source until delivery is ruled; every file here that came
from it sits at the same path and must match it byte for byte. manifest.txt
beside this script lists them. The check is red when:

  - a copied file differs between the two repos (edited on either side);
  - a copied file is missing from either repo;
  - a file under one of the manifest's roots, in either repo, is not listed:
    dotfiles grew a file the copy lacks, or this repo grew one dotfiles lacks.

  drift.py check --source DIR    DIR is a git checkout of dotfiles main

CI checks dotfiles main out beside this repo and passes its path. Nothing is
written anywhere. Port a change across, or list the file, to make it green.
"""
import difflib, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
KINDS = ("root", "copy", "skip", "own")


def read_manifest():
    m = {k: [] for k in KINDS}
    for n, line in enumerate(open(os.path.join(HERE, "manifest.txt"), encoding="utf-8"), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        kind, _, path = line.partition(" ")
        path = path.strip()
        if kind not in KINDS or not path or " " in path:
            sys.exit("manifest.txt:%d: want '<%s> <path>', got %r" % (n, "|".join(KINDS), line))
        m[kind].append(path)
    return m


def tracked(repo, roots):
    out = subprocess.run(["git", "-C", repo, "ls-files", "-z", "--"] + roots,
                         check=True, capture_output=True).stdout
    return {p.decode() for p in out.split(b"\0") if p}


def read(repo, path):
    try:
        return open(os.path.join(repo, path), "rb").read()
    except FileNotFoundError:
        return None


def check(source):
    m = read_manifest()
    copy, skip, own = set(m["copy"]), set(m["skip"]), set(m["own"])
    bad = []

    for path in sorted(copy):
        ours, theirs = read(ROOT, path), read(source, path)
        if ours is None or theirs is None:
            bad.append("MISSING: %s is listed as copied but absent from %s"
                       % (path, "this repo" if ours is None else "dotfiles main"))
        elif ours != theirs:
            diff = difflib.unified_diff(theirs.decode("utf-8", "replace").splitlines(True),
                                        ours.decode("utf-8", "replace").splitlines(True),
                                        "dotfiles/" + path, "claude/" + path)
            bad.append("DRIFT: %s differs from dotfiles main (dotfiles -> this repo):\n%s"
                       % (path, "".join(diff)))

    for path in sorted(tracked(ROOT, m["root"]) - copy - own):
        bad.append("UNLISTED here: %s is under a root but not in manifest.txt "
                   "(copy it from dotfiles, or list it as own)" % path)
    for path in sorted(tracked(source, m["root"]) - copy - skip):
        bad.append("UNLISTED in dotfiles: %s is new on dotfiles main "
                   "(copy it here, or list it as skip)" % path)

    if bad:
        print("\n".join(bad))
        print("\n%d problem(s). Dotfiles is the source: port the change into whichever repo "
              "lacks it, so the two match, and update manifest.txt if a file came or went."
              % len(bad))
        sys.exit(1)
    print("ok: %d copied files equal dotfiles main; %d skipped there, %d this repo's own"
          % (len(copy), len(skip), len(own)))


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 3 or args[0] != "check" or args[1] != "--source":
        sys.exit(__doc__)
    check(os.path.abspath(args[2]))
