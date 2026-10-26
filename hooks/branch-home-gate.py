#!/usr/bin/env python3
"""Stop gate: blocks the end of a session on a branch that is ahead of the
default branch with neither a PR nor a pointer -- a card on the global board
or an open issue that names it.

Why: twice in one week real design work was lost to a branch that was
pushed, never opened as a PR, and pointed at from nowhere durable. The Stop
hook records *unpushed* commits, so a pushed orphan trips no alarm, and
`worklist` lists stranded branches at the bottom where nobody acts on them.
Detection is not closure (2026-09-09): a PR is not required for every
branch, but until one exists a pointer must -- a board card or an open issue
naming the branch and what it holds.

Runs on Stop, alongside pr-threads-gate.py. The quiet path costs nothing:
HEAD on the default branch, a detached HEAD, no origin, or no commits ahead
and the hook exits before any network call.

Read-only: detects and blocks, never deletes. Abandon lives in its own
script, abandon-branch.py; see dotfiles#115.

Two outcomes:
  pass      a PR, a board card or an open issue names the branch
  block     once per session, with the branch, what was searched, and the
            two ways out

Blocks at most once per session (a marker under TMPDIR, the same convention
pr-ownership-context.py uses for its record -- NOT under the state dir,
which stop-continuity.py commits and pushes, so a per-session marker there
would be repo churn in every session). A gate that can trap a session is
worse than no gate.

GATE: no gh, gh failing or unauthenticated, or this hook crashing -> block
once saying the branch could not be verified. A guard that goes quiet when
it cannot look is indistinguishable from one that looked and found nothing.
A crash is traced to the state repo's metrics/hook-errors/
(lib/hooktrace.py) as well. The settings.json wrapper blocks when python3 or
this file is missing.

  branch-home-gate.py --check [dir]

Second entry point, read-only: answers "does this branch have a home" on
stdout and exits 0, without ever blocking and without touching the
once-per-session marker. stop-continuity.py calls it (through lib/state.py)
for the archive verdict (dotfiles#110) so the verdict and the gate can never
disagree about what a home is -- one implementation, two callers. Prints
exactly one line:
  home: <why>          a PR, a card or an issue names it; or nothing to strand
  none                 ahead of the default branch with no home
  unverified: <why>    could not look (no gh, not authenticated)

  branch-home-gate.py --card [dir]

Third entry point, read-only, same lookup: the machine-readable *card* this
branch belongs to, for claim-stamp.py (dotfiles#287). Exactly one line:
  pr <url>             an open or closed PR has this head
  issue <url>          an open issue names the branch
  none                 no remote card -- including every quiet-path exit
  unverified: <why>    could not look

The local board is deliberately not consulted in --card mode: a card in a
private file on one machine is a home, but it is not something a second
machine can read a claim off. Only a card with a URL counts there.
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HOOK = "branch-home-gate"
# Per gh call. Up to three run in a row and settings.json wraps the gate in a 60 s
# timeout whose fail-closed fallback only runs if the hook exits first, so the
# three must fit inside it.
GH_SECS = 15


class Quiet(Exception):
    """A quiet-path exit: nothing here to strand. args[0] is the why."""


def run(argv, cwd=None, timeout=None):
    """(ok, stdout) of argv; ok False when it could not run, timed out or
    exited non-zero."""
    try:
        p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return p.returncode == 0, p.stdout.decode("utf-8", "surrogateescape")


def git(root, *args):
    ok, out = run(["git", "-C", root, *args])
    return ok, out.strip()


def tr_name(s):
    """tr -c 'A-Za-z0-9_-' '_', byte by byte."""
    return re.sub(rb"[^A-Za-z0-9_-]", b"_", s.encode("utf-8", "surrogateescape")).decode()


def where(cwd):
    """(work_root, branch, base, ahead) for a branch that could strand
    work; raises Quiet with the reason otherwise."""
    ok, work_root = git(cwd, "rev-parse", "--show-toplevel")
    if not ok or not work_root:
        raise Quiet("not a git repo")
    ok, branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if not ok:
        raise Quiet("nothing to strand")
    if branch in ("", "HEAD", "main", "master"):  # default branch or detached
        raise Quiet(f"on `{branch}`")
    # No origin means nothing was published and nothing can be: a purely
    # local repo has no orphan to leave behind.
    if not git(work_root, "remote", "get-url", "origin")[0]:
        raise Quiet("no origin remote")
    # The base to measure "ahead" against: origin's default branch, however
    # it is named here.
    base = ""
    for cand in (git(work_root, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")[1],
                 "origin/main", "origin/master"):
        if cand and git(work_root, "rev-parse", "--verify", "-q", cand)[0]:
            base = cand
            break
    if not base:
        raise Quiet("no default branch to compare against")
    if base == f"origin/{branch}":
        raise Quiet("is the default branch")
    ok, n = git(work_root, "rev-list", "--count", f"{base}..HEAD")
    ahead = int(n) if ok and n.isdigit() else 0
    if ahead <= 0:
        raise Quiet(f"no commits ahead of {base}")
    return work_root, branch, base, ahead


def gh_json(work_root, *args):
    """gh's answer as JSON, or None when gh failed or said nothing usable."""
    ok, out = run(["gh", *args], cwd=work_root, timeout=GH_SECS)
    if not ok:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return []


def stack_head(head, branch):
    """`mergify stack push` opens the PR from a generated head,
    stack/<login>/<local-branch>/<slug>--<change-id>."""
    return head.startswith("stack/") and "/".join(head.split("/")[2:]).startswith(branch + "/")


def find_home(work_root, branch, board):
    """(found, card, unverified): why the branch has a home, its remote
    card as `pr <url>` / `issue <url>`, and why it could not be looked for;
    each "" when not. board: read the local item store first."""
    import state
    if board and state.names_branch(state.board_union(), branch):
        return f"a work item in {state.items_dir()} names it", "", ""
    if not shutil.which("gh"):
        return "", "", "gh is not installed here"
    failed = "gh pr list failed (not authenticated here?)"
    # Any PR with this head is a home: an open one is the point, and a
    # merged or closed one is still a durable record naming the branch.
    prs = gh_json(work_root, "pr", "list", "--head", branch, "--state", "all", "--limit", "5", "--json", "url")
    if prs is None:
        return "", "", failed
    url = prs[0].get("url") if isinstance(prs, list) and prs and isinstance(prs[0], dict) else None
    if url:
        return f"{url} has this head", f"pr {url}", ""
    # The exact --head lookup misses a mergify stack PR; broaden once.
    prs = gh_json(work_root, "pr", "list", "--state", "all", "--limit", "50", "--json", "url,headRefName")
    if prs is None:
        return "", "", failed
    for p in prs if isinstance(prs, list) else []:
        if isinstance(p, dict) and stack_head(str(p.get("headRefName") or ""), branch) and p.get("url"):
            return f"{p['url']} has this head (a mergify stack PR)", f"pr {p['url']}", ""
    iss = gh_json(work_root, "issue", "list", "--state", "open", "--limit", "200",
                  "--json", "number,title,body,url")
    if iss is None:
        return "", "", "gh issue list failed (not authenticated here?)"
    # Whole-token match, same as the board check: a plain substring test
    # gives claude/foobar's issue to claude/foo too.
    for i in iss if isinstance(iss, list) else []:
        if not isinstance(i, dict):
            continue
        text = f"{i.get('title') or ''} {i.get('body') or ''}".replace("\n", " ")
        if state.names_branch(text, branch):
            iurl = i.get("url") or ""
            return f"open issue #{i.get('number')} names it", (f"issue {iurl}" if iurl else ""), ""
    return "", "", ""


def query(mode, cwd):
    """The one line --check or --card prints."""
    try:
        work_root, branch, _, _ = where(cwd)
    except Quiet as q:
        return "none" if mode == "--card" else f"home: {q.args[0]}"
    found, card, unverified = find_home(work_root, branch, board=(mode == "--check"))
    if mode == "--card":
        return card or (f"unverified: {unverified}" if unverified else "none")
    if found:
        return f"home: {found}"
    return f"unverified: {unverified}" if unverified else "none"


def gate(ev):
    """The Stop gate: the block reason, or None to let the Stop through."""
    import hookio
    if hookio.stop_hook_active(ev):
        return None
    sid = ev.get("session_id")
    if not isinstance(sid, str) or not sid:
        return None
    cwd = ev.get("cwd") if isinstance(ev.get("cwd"), str) and ev.get("cwd") else os.getcwd()
    try:
        work_root, branch, base, ahead = where(cwd)
    except Quiet:
        return None
    rec = marker(sid)
    if blocked(rec):
        return None
    found, _, unverified = find_home(work_root, branch, board=True)
    if found:
        return None

    # The remote's name, not the checkout's: a worktree directory is named
    # for the branch, which would make the message say "in stop-hook-refusal".
    url = git(work_root, "remote", "get-url", "origin")[1]
    repo = re.sub(r".*[/:]", "", re.sub(r"\.git$", "", url.rstrip("/"))) or os.path.basename(work_root)
    if unverified:
        note(rec, f"blocked: could not verify a home for `{branch}` ({unverified})")
        return (f"branch-home-gate: this session cannot end yet. Branch `{branch}` in {repo} is {ahead} "
                f"commit(s) ahead of {base}, and whether it has a home could not be verified -- {unverified}. "
                "This is a gate and fails closed, so \"can't check\" is not a pass: open the PR, or file a "
                "pointer card (/card-write) naming the branch and what it holds, then end the turn again. "
                "This gate fires once per session.")
    note(rec, f"blocked: `{branch}` is {ahead} commit(s) ahead of {base} with no PR and no pointer")
    return (f"branch-home-gate: this session cannot end yet. Branch `{branch}` in {repo} is {ahead} commit(s) "
            f"ahead of {base} with no PR and no pointer: no PR has this head, no open issue names the branch, "
            "and no card on the board does either.\n\n"
            "Take one of the two ways out, then end the turn again:\n"
            "  - open the PR, or\n"
            "  - file a pointer card (/card-write) naming the branch and what it holds -- a card on the "
            "global board or an open issue, either counts.\n\n"
            "Detection is not closure -- a pushed branch nobody points at is how two pieces of design work "
            "were lost. This gate fires once per session.")


def marker(sid):
    """One file per session: the once-per-session marker (a line beginning
    "blocked"), which stop-continuity.py copies into the checkpoint."""
    return os.path.join(os.environ.get("TMPDIR") or "/tmp", f"claude-branch-home.{tr_name(sid)}")


def blocked(rec):
    try:
        with open(rec, encoding="utf-8", errors="replace") as f:
            return any(ln.startswith("blocked") for ln in f)
    except OSError:
        return False


def note(rec, line):
    try:
        with open(rec, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main(argv):
    import lib_state  # beside this file; it puts lib/ on sys.path
    import hookio
    if len(argv) > 1 and argv[1] in ("--check", "--card"):
        mode = argv[1]
        cwd = argv[2] if len(argv) > 2 and argv[2] else os.getcwd()
        try:
            print(query(mode, cwd))
        except Exception as e:  # noqa: BLE001 -- say "could not look", never silence
            lib_state.trace_failure(HOOK, "Stop", e, stage=mode.lstrip("-"))
            print(f"unverified: {HOOK} crashed ({type(e).__name__})")
        return
    ev = lib_state.event()
    try:
        reason = gate(ev)
    except Exception as e:  # noqa: BLE001 -- a gate fails closed, once
        lib_state.trace_failure(HOOK, "Stop", e)
        sid = ev.get("session_id")
        if hookio.stop_hook_active(ev) or not isinstance(sid, str) or not sid:
            return
        # The same marker as the gate's own: a crash that repeats every turn
        # still blocks once per session, not once per turn.
        rec = marker(sid)
        if blocked(rec):
            return
        note(rec, f"blocked: crashed ({type(e).__name__})")
        reason = (f"branch-home-gate: crashed ({type(e).__name__}: {e}), so the branch this session worked could "
                  "not be checked for a PR or a pointer card. This is a gate and fails closed: open the PR, or file "
                  "a pointer card (/card-write) naming the branch and what it holds, then end the turn again.")
    if reason:
        hookio.emit(hookio.block(reason))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    main(sys.argv)
