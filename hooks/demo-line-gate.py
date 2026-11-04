#!/usr/bin/env python3
"""Stop: block a turn that hands the user a demo line for a PR in any form but
the repo's one exact Try it line. The line is the one the shared show-dont-tell
check asks for in the PR body (mark-brannan/.github, tryItLine in
.github/scripts/show-dont-tell.mjs): fetch the PR head onto refs/pr/N, add or
move a detached worktree, install, serve on 10000 + N, all on one line.

Why: the check sees the PR body, never the chat. Agents handed the user
`gh pr checkout N && ... --port <wrong>` (the main clone switched, the port
guessed) and `npm run try-it -- N` (a command that only prints the line, from
inside the repo), and the user had to correct each one.

Fires only where the session's repo opts in: its .github/show-dont-tell.yml
sets `serve:`. A candidate is a line of code (a fence, or an inline span) in
the turn's last message that names a PR number in a demo shape: pull/N/head,
`gh pr checkout N`, `npm run try-it -- N`, `try-pr <repo> N`. A candidate that
is not the exact line for its N blocks once, and the reason carries the exact
line. stop_hook_active on the retry exits 0, so a quoted bad example costs one
extra stop, never a trap. Any error exits 0, traced (lib/hooktrace.py).
"""
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path; reads the event)

CONFIG = ".github/show-dont-tell.yml"
SHAPES = [
    re.compile(r"pull/(\d+)/head"),
    re.compile(r"\bgh pr checkout\s+(\d+)\b"),
    re.compile(r"\bnpm run try-it\s+(?:--\s+)?(\d+)\b"),
    re.compile(r"\btry-pr\s+\S+\s+(\d+)\b"),
]
REASON = (
    "demo-line-gate: this turn hands over a demo line that is not the repo's Try it line:\n"
    "  %s\n"
    "Give the user exactly this, on one line, in a ```bash fence:\n"
    "  %s\n"
    "It works from any directory: fetch the PR head, detached worktree, install, serve on "
    "port 10000 + N. Never a gh pr checkout, a command that prints the line, or a guessed port. "
    "If you quoted the other line as an example, not as one to run, end the turn again; "
    "this gate does not fire twice."
)


def parse_config(text):
    """checkout:, install:, serve: as show-dont-tell.mjs's parseConfig reads them."""
    out = {}
    for raw in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).rstrip()
        m = re.match(r"^(checkout|install|serve):\s*(.*)$", line)
        if m:
            out[m.group(1)] = re.sub(r"^([\"'])(.*)\1$", r"\2", m.group(2).strip())
    return out


def try_it_line(pr, checkout, install, serve):
    """A copy of tryItLine in show-dont-tell.mjs; the tests pin both to the
    same string, so a change to one shows red until the other follows."""
    port = 10000 + int(pr)
    wt = f"{checkout}/.claude/worktrees/pr-{pr}"
    parts = [
        f"git -C {checkout} fetch origin +pull/{pr}/head:refs/pr/{pr}",
        f"{{ [ -d {wt} ] || git -C {checkout} worktree add --detach {wt} refs/pr/{pr}; }}",
        f"git -C {wt} checkout -q --detach refs/pr/{pr}",
        f"cd {wt}",
        install,
        serve.replace("{port}", str(port)),
    ]
    return " && ".join(p for p in parts if p)


def code_lines(msg):
    """Lines inside ``` fences, plus inline `spans`; a backslash continuation
    is joined so a wrapped line is judged whole."""
    out, fence, buf = [], False, ""
    for line in msg.splitlines():
        if line.lstrip().startswith("```"):
            if buf:
                out.append(buf.strip())
                buf = ""
            fence = not fence
            continue
        if fence:
            if line.rstrip().endswith("\\"):
                buf += line.rstrip()[:-1] + " "
                continue
            out.append((buf + line).strip())
            buf = ""
        else:
            out.extend(s.strip() for s in re.findall(r"`([^`\n]+)`", line))
    return [x for x in out if x]


def misfits(msg, cfg, cwd):
    """(bad line, the exact line) for the first candidate that misses."""
    checkout = cfg.get("checkout") or f"~/{origin_name(cwd)}"
    for line in code_lines(msg):
        for shape in SHAPES:
            m = shape.search(line)
            if m:
                want = try_it_line(m.group(1), checkout, cfg.get("install", ""), cfg["serve"])
                if line != want:
                    return line, want
                break
    return None


def git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def origin_name(cwd):
    """The GitHub repository's name, as the CI check reads it from REPO; the
    clone's directory name can differ (~/.claude is mark-brannan/claude)."""
    url = git(cwd, "remote", "get-url", "origin").rstrip("/")
    name = re.sub(r"\.git$", "", re.split(r"[/:]", url)[-1]) if url else ""
    return name or Path(git(cwd, "rev-parse", "--show-toplevel") or cwd).name


def repo_config(cwd):
    """The config dict when cwd's repo opts in with serve:, else None."""
    top = git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return None
    path = Path(top) / CONFIG
    if not path.is_file():
        return None
    cfg = parse_config(path.read_text(encoding="utf-8", errors="replace"))
    return cfg if cfg.get("serve") else None


def main():
    ev = lib_state.event()
    if not ev:
        return
    hookio = lib_state.hookio
    if hookio.stop_hook_active(ev):
        return
    msg = ev.get("last_assistant_message")
    cwd = ev.get("cwd")
    if not isinstance(msg, str) or not msg or not isinstance(cwd, str):
        return
    cfg = repo_config(cwd)
    if not cfg:
        return
    bad = misfits(msg, cfg, cwd)
    if bad:
        hookio.emit(hookio.block(REASON % bad))


if __name__ == "__main__":
    lib_state.run_hook("demo-line-gate", "Stop", main)
