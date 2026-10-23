#!/usr/bin/env python3
"""PostToolUse Edit|Write|MultiEdit: after a markdown or JSON file is written
inside a repo that has a prose-budget config, run the tree rules on that
one file and hand any findings back as additionalContext. Advisory only:
it never blocks, and CI is the gate.

Silent on the quiet path (no engine, no config, other file types, clean file
under 2/3 of its cap): every line printed here is charged to the session.
PROSE_BUDGET names another engine; the default is prose-budget on PATH, then
bin/prose-budget beside this hook.
"""
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
# The engine reports a budgeted file's count as "lines: <file> 398/400".
COUNT = re.compile(r"^prose-budget: lines: .* (\d+)/(\d+)$", re.M)
BUDGET_LINE = re.compile(r"^prose-budget: [a-z_]*: ")


def engine():
    return os.environ.get("PROSE_BUDGET") or shutil.which("prose-budget") \
        or os.path.join(HERE, "..", "bin", "prose-budget")


def main():
    eng = engine()
    if not (os.path.isfile(eng) and os.access(eng, os.X_OK)):
        return
    ti = hookio.read().get("tool_input")
    file = ti.get("file_path") if isinstance(ti, dict) else None
    if not isinstance(file, str) or not file.endswith((".md", ".json")) or not os.path.isfile(file):
        return

    p = subprocess.run([eng, "--tree", "--file", file], cwd=os.path.dirname(file) or ".",
                       stdin=subprocess.DEVNULL, capture_output=True)
    out = p.stdout.decode("utf-8", "replace").rstrip("\n")
    err = p.stderr.decode("utf-8", "replace")
    m = COUNT.search(err)
    count = f"{m.group(1)}/{m.group(2)}" if m else ""

    if p.returncode in (1, 2):
        rest = "\n".join(l for l in err.split("\n") if not BUDGET_LINE.match(l)).rstrip("\n")
        head = f"prose-budget on {file}" + (f" ({count} lines):" if count else ":")
        msg = "\n".join([head, out, rest, "Fix these before the push; CI fails on them."])
    elif p.returncode == 0:
        # A clean budgeted file speaks only past 2/3 of its cap.
        if not m or int(m.group(1)) * 3 <= int(m.group(2)) * 2:
            return
        msg = f"prose-budget: {file} {count} lines."
    else:
        return
    text = "".join(l + "\n" for l in msg.split("\n") if l)
    hookio.emit(hookio.context("PostToolUse", text), ascii=False)


if __name__ == "__main__":
    lib_state.run_hook("prose-budget-edit", "PostToolUse", main)
