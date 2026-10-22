"""Replace a file's contents in one step. Imported, never run directly;
stdlib only.

The one home for this helper (dotfiles#517). The text goes to a hidden
sibling, then os.replace moves it over the target, so a reader sees the old
file or the new one, never a half-written one; a write that fails leaves no
sibling behind and raises its OSError to the caller.
"""
import os


def write(path, text):
    """Write text to path atomically; the directory must exist."""
    path = os.fspath(path)
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.tmp.{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
