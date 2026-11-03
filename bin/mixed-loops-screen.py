#!/usr/bin/env python3
"""mixed-loops-screen: classify a PR's changed paths for the mixed-loops guard,
screening out design files whose change is mechanical.

Usage: mixed-loops-screen.py <base-ref>
       mixed-loops-screen.py --diff -      (a unified diff on stdin)

Design set: every CLAUDE.md, rules/, docs/, hooks/*-requirements.md, *.adr.md,
and the curia and agora skills. Implementation set: .jq, .py, workflows,
hooks/, settings.json, and anything whose first two bytes are a shebang.
Tests and everything else are neutral.

A design file is screened out (neutral) when its change is mechanical:
  image        an image or PDF, by extension
  format       the diff's two sides match once whitespace and markdown
               punctuation are stripped
  typo         at most 3 tokens differ, each within edit distance 2
  rename sync  every token that differs also appears in the implementation
               files' changed lines or paths
Each rule judges the whole file. An added, deleted or renamed design file is
never screened out.

Prints one `neutral: <path> (<rule>)` line per screened-out file, then, when
both sets remain non-empty, the design and implementation files.
Exits 0 when they do not mix, 1 when they do, 2 on usage or a git failure.

In --diff mode a shebang is read from the diff when a hunk shows line 1,
otherwise from HEAD in the current directory if that is a git checkout.
"""
import difflib
import fnmatch
import re
import string
import subprocess
import sys

DESIGN = ("CLAUDE.md", "*/CLAUDE.md", "rules/*", "docs/*", "hooks/*-requirements.md",
          "*.adr.md", "skills/curia/*", "skills/agora/*")
TESTS = ("*.test.*", "*.examples.sh", "tests/*", "*/tests/*", "test_*.py", "*/test_*.py")
IMPL = ("*.jq", "*.py", ".github/workflows/*", "hooks/*", "settings.json")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf")

MAX_TYPOS = 3
MAX_TYPO_DISTANCE = 2

LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
MARKDOWN_PUNCT = str.maketrans("#*_-|>~`", " " * 8)
# Code splits on these as well as whitespace, so `open("hooks/x.py")` yields hooks/x.py.
CODE_SPLIT = re.compile(r"[\s\"'`()\[\]{},;=<>:$]+")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class FileDiff:
    def __init__(self, old, new):
        self.old, self.new = old, new
        self.status = "modified"
        self.binary = False
        self.hunks = []  # each: {"old_start", "new_start", "lines": [(sign, text)]}

    @property
    def path(self):
        """The path `git diff --name-only` prints: the new one, the old for a deletion."""
        return self.old if self.status == "deleted" else self.new

    def first_line(self):
        for hunk in self.hunks:
            want, start = ("-", hunk["old_start"]) if self.status == "deleted" else ("+", hunk["new_start"])
            if start > 1:
                continue
            for sign, text in hunk["lines"]:
                if sign in (" ", want):
                    return text
        return None


def _unquote(p):
    if len(p) >= 2 and p[0] == p[-1] == '"':
        raw = p[1:-1].encode("latin-1", "backslashreplace").decode("unicode_escape")
        p = raw.encode("latin-1", "replace").decode("utf-8", "replace")
    return p


def _strip_prefix(p):
    p = _unquote(p)
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_diff(text):
    files, cur, hunk = [], None, None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r'^diff --git ("?a/.*?"?) ("?b/.*"?)$', line)
            old, new = (m.group(1), m.group(2)) if m else ("", "")
            cur = FileDiff(_strip_prefix(old), _strip_prefix(new))
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        m = HUNK.match(line)
        if m:
            hunk = {"old_start": int(m.group(1)), "new_start": int(m.group(2)), "lines": []}
            cur.hunks.append(hunk)
            continue
        if hunk is None:
            if line.startswith("new file mode"):
                cur.status = "added"
            elif line.startswith("deleted file mode"):
                cur.status = "deleted"
            elif line.startswith("rename from "):
                cur.status, cur.old = "renamed", _unquote(line[len("rename from "):])
            elif line.startswith("rename to "):
                cur.status, cur.new = "renamed", _unquote(line[len("rename to "):])
            elif line.startswith(("copy from ", "copy to ")):
                cur.status = "copied"
            elif line.startswith("Binary files ") or line == "GIT binary patch":
                cur.binary = True
            elif line.startswith("--- ") and line[4:] != "/dev/null":
                cur.old = _strip_prefix(line[4:])
            elif line.startswith("+++ ") and line[4:] != "/dev/null":
                cur.new = _strip_prefix(line[4:])
        elif line[:1] in ("+", "-", " "):
            hunk["lines"].append((line[0], line[1:]))
    return files


def classify(path, shebang):
    """design, impl or None, tested in the guard's order."""
    if any(fnmatch.fnmatchcase(path, p) for p in DESIGN):
        return "design"
    if any(fnmatch.fnmatchcase(path, p) for p in TESTS):
        return None
    if any(fnmatch.fnmatchcase(path, p) for p in IMPL):
        return "impl"
    return "impl" if shebang(path) else None


def format_tokens(line):
    return LIST_MARKER.sub("", line).translate(MARKDOWN_PUNCT).split()


def word_tokens(line):
    return [t for t in (w.strip(string.punctuation) for w in line.split()) if t]


def code_tokens(line):
    toks = set(word_tokens(line))
    toks.update(t for t in (w.strip(string.punctuation) for w in CODE_SPLIT.split(line)) if t)
    return toks


def sides(hunk, tokenize):
    old, new = [], []
    for sign, text in hunk["lines"]:
        if sign == "-":
            old += tokenize(text)
        elif sign == "+":
            new += tokenize(text)
    return old, new


def changed_pairs(old, new):
    """Aligned (old, new) token pairs that differ; a missing side is ''."""
    pairs = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        a, b = old[i1:i2], new[j1:j2]
        pairs += [(a[k] if k < len(a) else "", b[k] if k < len(b) else "") for k in range(max(len(a), len(b)))]
    return pairs


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def screen(fd, impl_tokens):
    """The rule that makes this design file's change mechanical, or None."""
    if fd.path.lower().endswith(IMAGE_EXT):
        return "image"
    if fd.status != "modified" or fd.binary or not fd.hunks:
        return None
    pairs = [p for h in fd.hunks for p in changed_pairs(*sides(h, format_tokens))]
    if not pairs:
        return "format"
    if len(pairs) <= MAX_TYPOS and all(levenshtein(a, b) <= MAX_TYPO_DISTANCE for a, b in pairs):
        return "typo"
    differing = {t for h in fd.hunks for p in changed_pairs(*sides(h, word_tokens)) for t in p if t}
    if differing <= impl_tokens:
        return "rename sync"
    return None


def evaluate(files, shebang):
    """(design paths left, implementation paths, [(screened-out path, rule)])."""
    design, impl = [], []
    for fd in files:
        kind = classify(fd.path, shebang)
        if kind == "design":
            design.append(fd)
        elif kind == "impl":
            impl.append(fd)
    impl_tokens = set()
    for fd in impl:
        for p in (fd.old, fd.new):
            if p:
                impl_tokens.update((p, p.rsplit("/", 1)[-1]))
        for h in fd.hunks:
            for sign, text in h["lines"]:
                if sign in "+-":
                    impl_tokens |= code_tokens(text)
    remaining, neutral = [], []
    for fd in design:
        rule = screen(fd, impl_tokens)
        if rule:
            neutral.append((fd.path, rule))
        else:
            remaining.append(fd.path)
    return remaining, [fd.path for fd in impl], neutral


def _git(*args):
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], capture_output=True)


def git_shebang(*revs):
    def shebang(path):
        for rev in revs:
            out = _git("show", f"{rev}:{path}")
            if out.returncode == 0 and out.stdout:
                return out.stdout[:2] == b"#!"
        return False
    return shebang


def diff_shebang(files):
    first = {fd.path: fd.first_line() for fd in files}
    fallback = git_shebang("HEAD")

    def shebang(path):
        line = first.get(path)
        return line.startswith("#!") if line is not None else fallback(path)
    return shebang


def main(argv):
    if argv == ["--diff", "-"]:
        files = parse_diff(sys.stdin.read())
        shebang = diff_shebang(files)
    elif len(argv) == 1 and not argv[0].startswith("-"):
        base = argv[0]
        out = _git("diff", "--no-color", "--no-ext-diff", f"{base}...HEAD")
        if out.returncode != 0:
            sys.stderr.write(out.stderr.decode("utf-8", "replace"))
            return 2
        files = parse_diff(out.stdout.decode("utf-8", "replace"))
        shebang = git_shebang("HEAD", base)
    else:
        sys.stderr.write(__doc__)
        return 2
    design, impl, neutral = evaluate(files, shebang)
    for path, rule in neutral:
        print(f"neutral: {path} ({rule})")
    if not design or not impl:
        return 0
    print("design files touched:")
    for p in design:
        print(f"  {p}")
    print("implementation files touched:")
    for p in impl:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
