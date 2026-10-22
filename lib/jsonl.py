"""JSON Lines files: read them a row at a time, skipping what is not JSON,
and append one row. Imported, never run directly; stdlib only.

The one home for this helper (dotfiles#517). A row is written compact and
as UTF-8 (ensure_ascii off), one per line; a reader takes whatever value a
line holds and decides for itself whether a non-object counts.
"""
import json
import os


def rows(lines):
    """Each line of lines (a file, a list) as the value it parses to; a line
    that is not JSON is skipped. Blank lines are not JSON either."""
    for ln in lines:
        try:
            yield json.loads(ln)
        except ValueError:
            continue


def read(path, errors="replace"):
    """rows() over the file at path, decoded as UTF-8. OSError when it cannot
    be opened: whether that is an empty answer is the caller's call."""
    with open(path, encoding="utf-8", errors=errors) as fh:
        yield from rows(fh)


def dumps(row):
    """One row as its line, without the newline."""
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def append(path, row):
    """One row on the end of path; the directory is made first."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(dumps(row) + "\n")
