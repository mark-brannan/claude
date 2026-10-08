"""Run git from the Python tools and hooks. Imported, never run directly;
stdlib only.

The one home for this helper (dotfiles#517); bin/scoping-lock,
bin/github-limits, bin/prose-budget, bin/agent-decision,
bin/prune-worktrees, lib/state.py and hooks/stop-continuity.py use it.
Output is captured as UTF-8 text and never reaches the caller's terminal; a
byte that is not UTF-8 is replaced by default, or kept losslessly with
errors="surrogateescape" (for paths). Text mode also turns \\r\\n and a lone
\\r into \\n; exact() keeps every byte, for a caller that writes git's output
back out verbatim.
"""
import subprocess

TIMEOUT = 124  # returncode when git ran past its timeout, as timeout(1) reports
MISSING = 127  # returncode when git could not be started, as a shell reports


def run(*args, cwd=None, timeout=None, check=False, env=None, input=None, errors="replace",
        binary=False):
    """git with args, as a CompletedProcess. A timeout or a missing git comes
    back as returncode 124 or 127 rather than an exception. With check, any
    non-zero exit raises CalledProcessError instead. env replaces the child's
    environment, input is fed to its stdin, errors is how undecodable bytes
    are handled ("replace" or "surrogateescape"). binary hands stdout and
    stderr back as bytes, untouched, and takes input as bytes."""
    text = {} if binary else {"encoding": "utf-8", "errors": errors}

    def said(msg):
        return msg.encode() if binary else msg
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           timeout=timeout, env=env, input=input, **text)
    except subprocess.TimeoutExpired as e:
        p = subprocess.CompletedProcess(e.cmd, TIMEOUT, said(""), said(f"git timed out after {timeout}s"))
    except OSError as e:
        p = subprocess.CompletedProcess(["git", *args], MISSING, said(""), said(str(e)))
    if check and p.returncode:
        raise subprocess.CalledProcessError(p.returncode, p.args, p.stdout, p.stderr)
    return p


def ok(*args, **kw):
    """True when git exits 0."""
    return run(*args, **kw).returncode == 0


def out(*args, **kw):
    """git's stdout, stripped; whatever it printed, even on failure."""
    return run(*args, **kw).stdout.strip()


def exact(*args, **kw):
    """run, with stdout and stderr decoded byte for byte: UTF-8 with
    surrogateescape and no newline translation, so text written back out
    with errors="surrogateescape" is exactly what git printed."""
    p = run(*args, binary=True, **kw)
    p.stdout = p.stdout.decode("utf-8", "surrogateescape")
    p.stderr = p.stderr.decode("utf-8", "surrogateescape")
    return p
