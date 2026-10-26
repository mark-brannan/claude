#!/usr/bin/env python3
"""Stops unsigned commits from leaving a checkout unnoticed. Repos with a
signed-commits ruleset grey out the merge button when any commit on the
PR is unsigned, and nobody finds out until merge time -- days later, in a
session with no context, which then improvises (2026-09-01: a session
re-signed the wrong commit and pushed it to a stray branch). The commits
come from paths that skip commit.gpgsign: cloud VMs with no key, plumbing
like `git commit-tree`, `-c commit.gpgsign=false`.

On a `git push` from the Bash tool, look at the commits that push would
send and ask whether each carries a signature header at all. Validity is
GitHub's job; a cloud VM has no allowed-signers file, so %G? would report
every signed commit as unsigned there.
  - unsigned + this machine has a signing key -> DENY, with the exact
    rebase command that re-signs them
  - unsigned + no key here (cloud)          -> ALLOW, and tell the session
    the PR will be blocked until they are re-signed on a machine with the
    signing key, so it can say so in the handoff

The current branch of the *pushed* repo is inspected -- which is the
payload's cwd unless the command itself names a different one, via a
leading `cd DIR &&`/`cd DIR;` or a `git -C DIR push`. Without following
those, a push run against one repo from a session sitting in another gets
checked against the wrong repo: a false deny (the real target is clean but
the session's cwd has unsigned commits) or a false allow (the reverse).
A push that names another ref, or a `cd` reached through a pipe or a
multi-hop chain, is still not caught; that is accepted imprecision, not a
bypass anyone would reach for.

GATE where a key exists: an unreadable payload -> deny. Anything else
uncertain (not a repo, no upstream and no origin/HEAD) -> allow.
"""
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402,F401  (puts lib/ on sys.path)
import hookio  # noqa: E402

# Regexes are matched per line (re.M, and \s never crosses a newline here),
# as the grep this replaced did.
SP = r"[^\S\n]"
PUSH = re.compile(
    rf"(?:^|[^A-Za-z0-9_./-])git(?:{SP}+(?:-[cC]{SP}+\S+|--\S+))*{SP}+push(?:{SP}|$)", re.M)
LEADING_CD = [re.compile(rf"{SP}*cd{SP}+[^;&|]*"), re.compile(rf"{SP}*cd{SP}*(?:$|[;&|])")]


def deny(reason):
    hookio.emit(hookio.deny(reason), ascii=False, compact=True, errors="surrogateescape")


def git(cwd, *args):
    """(returncode, stdout without trailing newlines) of a git call in cwd."""
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       encoding="utf-8", errors="surrogateescape")
    return p.returncode, p.stdout.rstrip("\n")


def expand_leading(s):
    """The text of a cd/-C operand with a leading ~ or $HOME expanded. A bare
    `cd` goes to $HOME, as in the shell. `cd -` needs OLDPWD, which this hook
    doesn't have, so it is left unresolved rather than guessed; so is ~ or
    $HOME with HOME unset: expanding it to "" would turn `cd ~/tmp` into a
    check of /tmp."""
    home = os.environ.get("HOME", "")
    if s in ("~", "$HOME") or s.startswith(("~/", "$HOME/")):
        if not home:
            return ""
        return home if s in ("~", "$HOME") else home + "/" + s.split("/", 1)[1]
    return "" if s == "-" else s


def leading_cd(cmd):
    """The directory of a leading `cd`, or None. Only a `cd` opening the
    command counts as the push's directory; one reached after it, as in
    `git push && cd ..`, does not, and neither does one on a later line (it
    runs after the push). `|` stops the operand too, so `cd /a || git push`
    captures `/a`."""
    first = cmd.split("\n", 1)[0]
    raws = [m.group(0) for m in (r.match(first) for r in LEADING_CD) if m]
    if not raws:
        return None
    raw = max(raws, key=len)
    s = re.sub(r"^\s*cd\s*", "", raw)
    s = re.sub(r"\s*$", "", s)
    s = re.sub(r"[;&|]$", "", s)
    s = re.sub(r"\s*$", "", s)
    s = re.sub(r"""^["']""", "", s)
    s = re.sub(r"""["']$""", "", s)
    return s or "~"


def apply_target(target, operand):
    if not operand:
        return target
    return operand if operand.startswith("/") else target + "/" + operand


def target_dir(cmd, cwd):
    """The directory the push runs in. A named target that isn't a real
    directory (bad expansion, a typo, a `cd` into a directory the command
    creates later) falls back to the session cwd, the same
    uncertain-case-allows default as everywhere else here."""
    target = cwd
    cd = leading_cd(cmd)
    if cd is not None:
        target = apply_target(target, expand_leading(cd))
    # -C is only the push's own, from the matched `git ... push` invocation
    # itself -- not from an unrelated `git commit -C HEAD` earlier in the
    # command, nor from a second `git -C other ...` after it. Several -C
    # flags chain, as git does: `git -C a -C b push` runs in a/b.
    segs = [m.group(0) for m in PUSH.finditer(cmd)]
    for flag in re.findall(r"-C\s+(\S+)", segs[-1] if segs else ""):
        flag = re.sub(r"""["']$""", "", re.sub(r"""^["']""", "", flag))
        target = apply_target(target, expand_leading(flag))
    return target if os.path.isdir(target) else cwd


def main():
    raw = sys.stdin.read()
    if not raw.strip():
        return 0
    try:
        ev = json.loads(raw)
        ti = None if ev is None else ev.get("tool_input")
        cmd = None if ti is None else ti.get("command")
        cwd = None if ev is None else ev.get("cwd")
    except (ValueError, AttributeError):
        deny("no-unsigned-push: unreadable hook payload.")
        return 0
    if not isinstance(cmd, str) or not cmd or not PUSH.search(cmd):
        return 0
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        return 0
    cwd = target_dir(cmd, cwd)

    if git(cwd, "rev-parse", "--git-dir")[0]:
        return 0
    if git(cwd, "symbolic-ref", "-q", "HEAD")[0]:
        return 0  # detached: nothing sensible to check

    # Commits the push would send: upstream..HEAD, else origin/HEAD..HEAD.
    # Anything already on origin/HEAD is excluded either way. A branch that
    # merged main after its first push carries main's history past its own
    # upstream; if main holds unsigned commits (a web edit, a key-less VM),
    # counting them here denies every such branch or goads it into re-signing
    # main into duplicates. The PR doesn't list them; they are not this
    # branch's to fix.
    rc, main = git(cwd, "rev-parse", "-q", "--verify", "origin/HEAD")
    main = main if rc == 0 else ""
    rc, base = git(cwd, "rev-parse", "-q", "--verify", "@{u}")
    base = base if rc == 0 else main
    if not base:
        return 0
    _, shas = git(cwd, "rev-list", "HEAD", "--not", base, *([main] if main else []))
    unsigned = []
    for sha in shas.split():
        _, obj = git(cwd, "cat-file", "-p", sha)
        if not any(line.startswith("gpgsig") for line in obj.split("\n")):
            unsigned.append(git(cwd, "log", "-1", "--pretty=%h %s", sha)[1])
    if not unsigned:
        return 0

    # The subject lines are untrusted input: anyone who can get a commit into
    # this branch's history writes that text. Kept verbatim on purpose -- a
    # mangled subject is not identifiable, and identifying the commit is the
    # point of the note.
    listing = "\n".join(unsigned)
    n = len(unsigned)
    branch = git(cwd, "symbolic-ref", "--short", "HEAD")[1]
    rc, mb = git(cwd, "merge-base", base, "HEAD")
    if rc:
        mb = base
    # Past a merged main, a rebase from the upstream replays main's commits as
    # new ones (--rebase-merges too), so rebase from the merged main tip; that
    # rewrites pushed commits, hence the lease.
    how = (f"Re-sign everything since the base and push again:\n  git rebase -S --force-rebase {mb}\n"
           "If the branch is already on the remote, push the result with `git push --force-with-lease`.")
    if main:
        rc, mbm = git(cwd, "merge-base", main, "HEAD")
        if rc == 0 and git(cwd, "merge-base", "--is-ancestor", mbm, mb)[0]:
            how = ("This branch merged main after it was pushed, so re-sign from the merged main tip "
                   "(a rebase from the upstream would replay main's commits as new ones), then push "
                   "with --force-with-lease — the rebase rewrites the pushed commits too:\n"
                   f"  git rebase -S --force-rebase {mbm}")

    if git(cwd, "config", "user.signingkey")[0] == 0:
        deny(f"no-unsigned-push: {n} unsigned commit(s) on {branch} would be pushed, and this machine "
             f"has a signing key, so sign them first:\n\n{listing}\n\n{how}\n"
             "Never make commits with plumbing (`git commit-tree`) or `-c commit.gpgsign=false` "
             "in a repo that requires signatures.")
        return 0

    hookio.emit(hookio.allow(
        f"no-unsigned-push: {n} unsigned commit(s) on {branch} are being pushed from a machine with "
        f"no signing key:\n\n{listing}\n\nA repo that requires signed commits will block the PR until "
        "someone re-signs from a machine with the signing key: `git rebase -S --force-rebase "
        "origin/<base>` then `git push --force-with-lease`. Say so in the PR body and the handoff; "
        "do not try to sign here."),
        ascii=False, compact=True, errors="surrogateescape")
    return 0


if __name__ == "__main__":
    sys.exit(main())
