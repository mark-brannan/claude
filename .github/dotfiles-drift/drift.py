#!/usr/bin/env python3
"""Keep this repo's copy of the Claude layer equal to mark-brannan/dotfiles main.

Dotfiles stays the source until ~/.claude is switched to a clone of this repo.
This repo's root is ~/.claude itself, so a dotfiles path maps here as:

  dotfiles/.claude/X              <->  X
  dotfiles/.local/bin/X           <->  bin/X
  dotfiles/.config/systemd/user/X <->  systemd/X
  anything else                   <->  the same path

manifest.txt beside this script lists files by their dotfiles path. A copied
file must match dotfiles byte for byte once the layout rewrites below are
applied to the dotfiles side: the moved paths a file names (~/.local/bin/tool
becomes ~/.claude/bin/tool, ../../.local/bin from a hook becomes ../bin, and
so on). The check is red when:

  - a copied file differs between the two repos (edited on either side);
  - a copied file is missing from either repo;
  - a file under one of the manifest's roots, in either repo, is not listed:
    dotfiles grew a file the copy lacks, or this repo grew one dotfiles lacks.

  drift.py check --source DIR    DIR is a git checkout of dotfiles main

CI checks dotfiles main out beside this repo and passes its path. Nothing is
written anywhere. Port a change across, or list the file, to make it green.
"""
import difflib, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
KINDS = ("root", "copy", "skip", "own")

# dotfiles prefix -> this repo's prefix; first match wins.
LAYOUT = ((".claude/", ""), (".local/bin/", "bin/"), (".config/systemd/user/", "systemd/"))

# Applied to every copied file's dotfiles text before comparing.
REWRITES = [(re.compile(a, re.M), b) for a, b in (
    (r"PATH=%h/\.local/bin:", "PATH=%h/.claude/bin:%h/.local/bin:"),
    (r"(\$HOME|(?<![\w/.])~|%h)/\.local/bin(?=[/\"'\s`)]|$)", r"\1/.claude/bin"),
    (r"\.\./\.\./\.local/bin/", "../bin/"),
    (r"\.\./\.\./\.claude/hooks", "../hooks"),
    (r'here\.parent\.parent / "\.claude" / "hooks"', 'here.parent / "hooks"'),
    (r"\.\./\.\./\.\./docs/", "../../docs/"),
    (r"\]\(\.\./\.local/bin/", "](bin/"),
    (r"Run: (bash|sh|python3) \.local/bin/", r"Run: \1 bin/"),
    (r"Run: (bash|sh|python3) \.claude/", r"Run: \1 "),
    (r"shellcheck source=\.claude/", "shellcheck source="),
)]

# Layout edits too particular for a general rule: dotfiles path -> literal pairs.
ADAPT = {
    ".local/bin/grind": [
        ("fixed paths in the dotfiles\n# tree, which is $HOME on a real machine and two levels up from this script in\n"
         "# a worktree. GRIND_ROOT overrides both, for tests and for a machine that keeps\n# the tree elsewhere.",
         "fixed paths in the Claude\n# layer's tree, which is $HOME/.claude on a real machine and one level up from\n"
         "# this script in a worktree. GRIND_ROOT overrides both, for tests and for a\n# machine that keeps the tree elsewhere."),
        ("<path relative to the dotfiles tree>", "<path relative to the Claude layer's tree>"),
        ('"${GRIND_ROOT:-$self_dir/../..}/$1" "$HOME/$1"', '"${GRIND_ROOT:-$self_dir/..}/$1" "$HOME/.claude/$1"'),
        ("find_beside .local/bin/", "find_beside bin/"),
        ("find_beside .claude/", "find_beside "),
        ('pr_unmet=".claude/hooks/', 'pr_unmet="hooks/'),
        ("contract in .claude/skills/", "contract in skills/"),
    ],
    ".local/bin/grind.test.sh": [
        ('"$prroot/.local/bin" "$prroot/.claude/hooks" "$prroot/.claude/skills/pickup"',
         '"$prroot/bin" "$prroot/hooks" "$prroot/skills/pickup"'),
        ('"$(dirname "$GRIND")/../.." && pwd)/.claude/skills', '"$(dirname "$GRIND")/.." && pwd)/skills'),
        ("$prroot/.claude/", "$prroot/"),
        ("$prroot/.local/bin/", "$prroot/bin/"),
    ],
    ".local/bin/languette-step-two.test.py": [
        ("parents[2]", "parents[1]"),
        ('REPO / ".local/bin/languette-step-two"', 'REPO / "bin/languette-step-two"'),
    ],
}


def here(path):
    for a, b in LAYOUT:
        if path.startswith(a):
            return b + path[len(a):]
    return path


def adapt(path, data):
    text = data.decode("utf-8", "replace")
    for rx, to in REWRITES:
        text = rx.sub(to, text)
    for a, b in ADAPT.get(path, ()):
        if a not in text:
            sys.exit("drift.py: ADAPT rule for %s no longer matches dotfiles: %r" % (path, a))
        text = text.replace(a, b)
    return text.encode("utf-8")


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
    copy, skip = set(m["copy"]), set(m["skip"])
    bad = []

    mapped = {}
    for path in copy:
        if here(path) in mapped:
            sys.exit("drift.py: %s and %s both map to %s" % (mapped[here(path)], path, here(path)))
        mapped[here(path)] = path

    for path in sorted(copy):
        ours, theirs = read(ROOT, here(path)), read(source, path)
        if ours is None or theirs is None:
            bad.append("MISSING: %s is listed as copied but absent from %s"
                       % (path, "this repo (as %s)" % here(path) if ours is None else "dotfiles main"))
        elif ours != adapt(path, theirs):
            diff = difflib.unified_diff(adapt(path, theirs).decode("utf-8", "replace").splitlines(True),
                                        ours.decode("utf-8", "replace").splitlines(True),
                                        "dotfiles/" + path, "claude/" + here(path))
            bad.append("DRIFT: %s differs from dotfiles main (dotfiles -> this repo):\n%s"
                       % (path, "".join(diff)))

    # This repo's roots are the dotfiles roots, mapped; "" is the whole repo.
    # An own entry ending in / covers everything under it.
    own_files = {p for p in m["own"] if not p.endswith("/")}
    own_dirs = tuple(p for p in m["own"] if p.endswith("/"))
    roots_here = sorted({here(r) or "." for r in m["root"]})
    for path in sorted(tracked(ROOT, roots_here) - set(mapped) - own_files):
        if path.startswith(own_dirs):
            continue
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
          % (len(copy), len(skip), len(m["own"])))


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 3 or args[0] != "check" or args[1] != "--source":
        sys.exit(__doc__)
    check(os.path.abspath(args[2]))
