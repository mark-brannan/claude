"""Run git from the Python tools and hooks. Imported, never run directly;
stdlib only.

The one home for this helper (dotfiles#517); bin/scoping-lock,
bin/github-limits, bin/prose-budget, bin/agent-decision and
bin/prune-worktrees use it. Output is captured as UTF-8 text and never
reaches the caller's terminal; a byte that is not UTF-8 is replaced by
default, or kept losslessly with errors="surrogateescape" (for paths).
"""
import subprocess

TIMEOUT = 124  # returncode when git ran past its timeout, as timeout(1) reports
MISSING = 127  # returncode when git could not be started, as a shell reports


def run(*args, cwd=None, timeout=None, check=False, env=None, input=None, errors="replace"):
    """git with args, as a CompletedProcess. A timeout or a missing git comes
    back as returncode 124 or 127 rather than an exception. With check, any
    non-zero exit raises CalledProcessError instead. env replaces the child's
    environment, input is fed to its stdin, errors is how undecodable bytes
    are handled ("replace" or "surrogateescape")."""
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           encoding="utf-8", errors=errors, timeout=timeout,
                           env=env, input=input)
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
