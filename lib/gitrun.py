"""Run git from the Python tools and hooks. Imported, never run directly;
stdlib only.

The one home for this helper (dotfiles#517); bin/scoping-lock,
bin/github-limits, bin/prose-budget and bin/agent-decision use it.
Output is captured as text and never reaches the caller's terminal.
"""
import subprocess

TIMEOUT = 124  # returncode when git ran past its timeout, as timeout(1) reports
MISSING = 127  # returncode when git could not be started, as a shell reports


def run(*args, cwd=None, timeout=None, check=False):
    """git with args, as a CompletedProcess. A timeout or a missing git comes
    back as returncode 124 or 127 rather than an exception. With check, any
    non-zero exit raises CalledProcessError instead."""
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        p = subprocess.CompletedProcess(e.cmd, TIMEOUT, "", f"git timed out after {timeout}s")
    except OSError as e:
        p = subprocess.CompletedProcess(["git", *args], MISSING, "", str(e))
    if check and p.returncode:
        raise subprocess.CalledProcessError(p.returncode, p.args, p.stdout, p.stderr)
    return p


def ok(*args, **kw):
    """True when git exits 0."""
    return run(*args, **kw).returncode == 0


def out(*args, **kw):
    """git's stdout, stripped; whatever it printed, even on failure."""
    return run(*args, **kw).stdout.strip()
