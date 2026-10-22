#!/usr/bin/env python3
"""Stop: block the end of a turn while a PR this session touched still has an
unresolved review thread, or cannot merge without a rebase.

Why: the PR ownership rules say review threads are mine to reply to AND
resolve, and pr-ownership-context.py puts that text in front of the session.
Text is not a gate. 2026-09-07, colregs-engine#25: a session twice reported
"all comments resolved" while a thread stayed open, with the rules in
context both times. So the check moves from the model's memory to here:
when the session tries to end its turn, re-fetch every touched PR's threads
over GraphQL and refuse the stop if any is open or the fetch failed. The
reason names each thread by id so the session can read it and resolve it,
one at a time, or say plainly in its final message which ones stay open and
why.

Reads the record pr-ownership-context.py appends to on each PR-shaped call
(repo + number, or the cwd whose branch gh resolves to a PR). No record ->
nothing to do, exit 0 -- most turns never touch a PR.

Blocks at most once per turn: the harness sets stop_hook_active on the
retry, and a second block would just loop against a thread only the user
can close. One forced re-check is the whole point; the honest report after
it is the model's job.

GATE: no gh, gh failing, PR not found -> block once, saying the state could
not be verified. A gate that goes quiet when it can't look is
indistinguishable from one that looked and found nothing. A crash here is
traced (lib/hooktrace.py) and exits 1, so the settings.json wrapper prints
its own fail-closed block; this hook never exits 0 on its own bug.

EXCEPTION, dotfiles#263/#309: NOT_FOUND on `repository` over GraphQL is
ambiguous by GitHub's own anti-enumeration design -- identical whether the
repo is gone or the token merely lacks access to it right now (private,
transferred, unattached in a cloud session). So an entry drops only once a
second, independent `gh repo view` confirms a 404; every other outcome,
repo-view failures included, falls through to the failed-closed case. That
confirming call runs inside the concurrent fetch job that saw the NOT_FOUND,
so N missing repos still cost one timeout window between them, not one each.

EXCEPTION, dotfiles#224: a "repo" record line carries a third field, read or
work, written by pr-ownership-context.py (kind is empty on an older or
hand-written record, which this gate treats as work). A read -- `gh pr
view/checks/diff/list`, or a non-mutating `gh api` call -- is never fetched
and never gates the Stop; a session working four PRs must not inherit a
fifth PR's open threads because it ran `gh pr view` on it for evidence.
"cwd" lines are unaffected: the PR they resolve to is the one whose head
branch this session's worktree holds, which gates on identity alone.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HOOK = "pr-threads-gate"
UNVERIFIED_TAIL = ("so review threads on the PR you worked could not be re-checked. State in your final "
                   "message, per thread id, which are resolved and which are open, then end the turn again.")
PR_URL = re.compile(r"^https://github\.com/([^/]*/[^/]*)/pull/([0-9]*)$")
TIMED_OUT = 124  # what timeout(1) exits with; a fetch past the bound reads the same
THREADS_QUERY = """
    query($owner:String!,$name:String!,$number:Int!){
      repository(owner:$owner,name:$name){ pullRequest(number:$number){
        state mergeable mergeStateStatus
        reviewThreads(first:100){ nodes{ id isResolved path
          comments(first:1){ nodes{ author{login} body } } } } } } }"""
MERGE_QUERY = """
      query($owner:String!,$name:String!,$number:Int!){
        repository(owner:$owner,name:$name){ pullRequest(number:$number){
          mergeable mergeStateStatus } } }"""
FIX_STEPS = (
    "For each open thread, in this order: read it (gh api graphql on the thread id, or the PR's review comments), "
    "fix or answer it, reply on the thread with the evidence, then resolve it by id --\n"
    "  gh-resolve-thread <threadId>\n"
    "(a wrapper around the resolveReviewThread mutation; it is allowlisted, a raw gh api graphql call is not). "
    "One thread at a time, never a loop over all unresolved ids. A thread only the user can close (a decision, "
    "a question to them) stays open: say so in your final message, by id, with what they need to decide. Never "
    "report 'all threads resolved' unless this check passes. Any PR listed as conflicting or behind is rebased, "
    "not reported as green: git fetch origin <base> && git rebase origin/<base>, resolve, then force-push your "
    "own branch. Never say a PR is ready while this check names it. Then end the turn again; this gate does not "
    "fire twice in one turn.")


class Blocked(Exception):
    """The gate's answer is a block with this reason; raised to unwind."""


def jq_str(v):
    """A value as `jq -r` prints it, "" for null or false (`// empty`)."""
    if v is None or v is False:
        return ""
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def interp(v):
    """A value as jq's string interpolation shows it: null prints "null"."""
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def dig(obj, *keys):
    """obj[k1][k2]..., None where a step is missing or not an object."""
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def first_json(text):
    """The leading JSON value of text, as jq reads it before the text gh
    appends after an `errors` reply; {} when there is none."""
    try:
        return json.JSONDecoder().raw_decode(text.lstrip())[0]
    except ValueError:
        return {}


def seconds(raw, default=60.0):
    """A timeout(1) duration (60, 1.5, 2m) in seconds."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([smhd]?)\s*", raw or "")
    if not m:
        return default
    return float(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def tmpdir():
    return os.environ.get("TMPDIR") or "/tmp"


def bounded(argv, out_path, limit, stderr=subprocess.STDOUT):
    """Run argv with stdout (and stderr, unless told otherwise) into out_path, killed (with anything it
    started) past limit seconds. The exit code, TIMED_OUT when killed. A file,
    not a pipe, so a grandchild still holding the pipe cannot hang the wait."""
    with open(out_path, "wb") as out:
        try:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=stderr,
                                 start_new_session=True)
        except OSError as e:
            out.write(f"{argv[0]}: {e}\n".encode())
            return 127
        try:
            return p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(p.pid, sig)
                except OSError:
                    pass
                try:
                    p.wait(timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    continue
            return TIMED_OUT


def read_text(path):
    """A file's text as `$(cat file)` gives it: "" when absent, trailing
    newlines dropped."""
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace").rstrip("\n")
    except OSError:
        return ""


def graphql(repo, num, query):
    owner, _, name = repo.partition("/")
    return ["gh", "api", "graphql", "-f", f"owner={owner}", "-f", f"name={name or owner}",
            "-F", f"number={num}", "-f", f"query={query}"]


def touched_prs(record):
    """Every distinct PR the record names, as sorted (owner/name, number)
    pairs. A cwd line resolves through gh to whatever PR its branch has; no
    PR there is fine. A read never gates the Stop (dotfiles#224)."""
    with open(record, "rb") as f:
        lines = sorted(set(f.read().decode("utf-8", "replace").splitlines()))
    prs = set()
    for line in lines:
        fields = re.split(r"\t+", line.strip("\t"), maxsplit=3)
        kind, a, b, c = (fields + ["", "", "", ""])[:4]
        if kind == "repo":
            if c == "read":
                continue
            prs.add((a, b))
        elif kind == "cwd" and os.path.isdir(a):
            for url in branch_pr_urls(a):
                m = PR_URL.match(url)
                if m:
                    prs.add((m.group(1), m.group(2)))
    return sorted((r, n) for r, n in prs if r and n)


def branch_pr_urls(cwd):
    """The PR urls gh finds for the branch checked out at cwd. The url names
    the base repo, where the threads live; the head repo would be wrong for a
    fork. A local branch named apart from the PR's head (pickup's `checkout
    -B <short-name>`) has no PR by name; after its push, its HEAD does."""
    def run(argv):
        try:
            p = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
        except OSError:
            return None
        return p.stdout.decode("utf-8", "replace").rstrip("\n") if p.returncode == 0 else None

    u = run(["gh", "pr", "view", "--json", "url", "-q", ".url"])
    if not u:
        sha = run(["git", "rev-parse", "HEAD"])
        if not sha:
            return []
        u = run(["gh", "pr", "list", "--state", "open", "--limit", "100", "--json", "url,headRefOid",
                 "-q", f'.[] | select(.headRefOid=="{sha}") | .url'])
    return u.split("\n") if u else []


def not_found_on_repository(reply):
    errors = reply.get("errors") if isinstance(reply, dict) else None
    for e in errors if isinstance(errors, list) else []:
        path = dig(e, "path")
        if dig(e, "type") == "NOT_FOUND" and isinstance(path, list) and path and path[0] == "repository":
            return True
    return False


def fetch(work, i, repo, num, limit):
    """One PR's threads into work/i.out and its exit code into i.rc; on
    NOT_FOUND for the repository, the confirming `gh repo view` too (i.view.*)."""
    base = os.path.join(work, str(i))
    rc = bounded(graphql(repo, num, THREADS_QUERY), base + ".out", limit)
    with open(base + ".rc", "w") as f:
        f.write(str(rc))
    if not_found_on_repository(first_json(read_text(base + ".out"))):
        vrc = bounded(["gh", "repo", "view", repo], base + ".view.out", limit)
        with open(base + ".view.rc", "w") as f:
            f.write(str(vrc))


def first_lines(text, n):
    """`printf '%s' "$text" | head -n | tr '\\n' ' '`."""
    parts = text.split("\n")
    return " ".join(parts[:n]) + (" " if len(parts) > n else "")


def merge_state(pr):
    return (jq_str(dig(pr, "mergeable")) or "UNKNOWN", jq_str(dig(pr, "mergeStateStatus")) or "UNKNOWN")


def open_threads(pr):
    nodes = dig(pr, "reviewThreads", "nodes")
    lines = []
    for t in nodes if isinstance(nodes, list) else []:
        if not isinstance(t, dict) or t.get("isResolved") not in (None, False):
            continue
        cs = dig(t, "comments", "nodes")
        c = cs[0] if isinstance(cs, list) and cs else None
        login = jq_str(dig(c, "author", "login")) or "?"
        body = jq_str(dig(c, "body"))
        first = body.split("\n")[0][:100] if body else None  # jq: "" | split("\n")[0] is null
        lines.append(f"  - {interp(t.get('id'))}  {jq_str(t.get('path')) or '(no file)'}  @{login}: {interp(first)}")
    return lines


def check(prs):
    """The open, stale, failed and dropped findings for the touched PRs."""
    open_, stale, failed, dropped = "", "", "", ""
    limit = seconds(os.environ.get("PR_THREADS_GATE_TIMEOUT"))
    try:
        scratch = tempfile.TemporaryDirectory(prefix="pr-threads-gate.", dir=tmpdir())
    except OSError:
        raise Blocked(f"{HOOK}: cannot create a scratch directory, {UNVERIFIED_TAIL}")
    with scratch as work:
        # One fetch per PR, all at once, each bounded by wall clock rather
        # than the list by count: a fan-out over eight PRs still gets every
        # one checked, and a fetch that hangs is reported as unverified.
        with ThreadPoolExecutor(max_workers=len(prs)) as pool:
            for f in [pool.submit(fetch, work, i, r, n, limit) for i, (r, n) in enumerate(prs, 1)]:
                f.result()
        for i, (repo, num) in enumerate(prs, 1):
            base = os.path.join(work, str(i))
            out = read_text(base + ".out")
            rc = read_text(base + ".rc")
            if rc == str(TIMED_OUT):
                failed += f"\n- {repo}#{num}: fetch timed out"
                continue
            # `gh api graphql` exits non-zero whenever the reply carries an
            # `errors` array, though the body is still valid JSON up to it.
            # A view.rc means the fetch saw NOT_FOUND on `repository` and went
            # looking; any other error is the failed-closed case below.
            if os.path.exists(base + ".view.rc"):
                view_out = read_text(base + ".view.out")
                if read_text(base + ".view.rc") == "0":
                    failed += (f"\n- {repo}#{num}: GraphQL reported repository NOT_FOUND but `gh repo view` can see "
                               "it -- an access problem, not a missing repo; not dropped")
                elif re.search(r"HTTP 404|Could not resolve to a Repository", view_out, re.I):
                    dropped += (f"\n- {repo}#{num}: repository not found over GraphQL (NOT_FOUND), confirmed 404 by "
                                "`gh repo view` -- dropped; this record was never a PR this session worked")
                else:
                    # Unconfirmed failure proves nothing -- failed-closed, not dropped.
                    failed += (f"\n- {repo}#{num}: repository NOT_FOUND over GraphQL, and `gh repo view` failed "
                               f"without confirming it is gone ({view_out.split(chr(10))[0]}) -- unverified, not dropped")
                continue
            if rc != "0":
                failed += f"\n- {repo}#{num}: {first_lines(out, 3)}"
                continue
            pr = dig(first_json(out), "data", "repository", "pullRequest")
            state = jq_str(dig(pr, "state"))
            if not state:
                failed += f"\n- {repo}#{num}: not found (no pullRequest in the GraphQL reply)"
                continue
            if state != "OPEN":
                continue
            threads = open_threads(pr)
            # Merge state, from the same fetch. `gh pr checks` is green on a
            # branch that conflicts with main. CONFLICTING and BEHIND are both
            # a rebase. GitHub computes mergeability lazily, so UNKNOWN means
            # "ask again": one re-ask, then reported as unverified.
            mergeable, mstate = merge_state(pr)
            if "UNKNOWN" in (mergeable, mstate):
                time.sleep(seconds(os.environ.get("PR_THREADS_GATE_RECHECK_SLEEP"), 2.0))
                again = os.path.join(work, f"{i}.again")
                if bounded(graphql(repo, num, MERGE_QUERY), again, limit, subprocess.DEVNULL) == 0:
                    text = read_text(again)
                    if text:
                        mergeable, mstate = merge_state(dig(first_json(text), "data", "repository", "pullRequest"))
            # Checked independently, never concatenated: the two fields are
            # computed apart and don't resolve in lockstep.
            if mergeable == "CONFLICTING":
                stale += f"\n- {repo}#{num} conflicts with its base branch (mergeable=CONFLICTING)"
            elif mstate == "BEHIND":
                stale += f"\n- {repo}#{num} is behind its base branch (mergeStateStatus=BEHIND)"
            elif "UNKNOWN" in (mergeable, mstate):
                failed += f"\n- {repo}#{num}: merge state still UNKNOWN (GitHub had not finished computing it)"
            if threads:
                open_ += f"\n- {repo}#{num} has {len(threads)} unresolved review thread(s):\n" + "\n".join(threads)
    return open_, stale, failed, dropped


def verdict(ev):
    """The gate's answer for this Stop: a dict to emit, or None for silence."""
    sid = jq_str(ev.get("session_id"))
    if not sid:
        return None
    tag = re.sub(rb"[^A-Za-z0-9_-]", b"_", sid.encode("utf-8")).decode()
    record = os.path.join(tmpdir(), f"claude-pr-threads.{tag}")
    try:
        if os.path.getsize(record) == 0:
            return None
    except OSError:
        return None
    import hookio
    if hookio.stop_hook_active(ev):
        return None
    try:
        if not shutil.which("gh"):
            raise Blocked(f"{HOOK}: gh is not installed here, {UNVERIFIED_TAIL}")
        prs = touched_prs(record)
        if not prs:
            return None
        open_, stale, failed, dropped = check(prs)
    except Blocked as b:
        return hookio.block(str(b))
    if not (open_ or stale or failed):
        if dropped:
            return {"systemMessage": f"{HOOK}: dropped from this session's PR record (repository not found over "
                                     f"GraphQL; never a PR this session worked):{dropped}"}
        return None
    msg = f"{HOOK}: this turn cannot end yet. Live GraphQL re-check of the PR(s) this session worked:"
    if open_:
        msg += "\n" + open_
    if stale:
        msg += "\n" + stale
    if failed:
        msg += "\n\nCould not verify:" + failed
    if dropped:
        msg += "\n\nDropped (repository not found over GraphQL; never a PR this session worked):" + dropped
    return hookio.block(msg + "\n\n" + FIX_STEPS)


def main():
    import lib_state  # beside this file; it puts lib/ on sys.path
    import hookio  # a gate cannot read its payload without it: ImportError fails closed
    out = verdict(lib_state.event())
    if out is not None:
        hookio.emit(out, ascii=False, compact=True, errors="replace")


if __name__ == "__main__":
    # A gate fails closed: a crash is traced, then exit 1 so the settings.json
    # wrapper prints its block rather than this Stop passing unchecked.
    try:
        main()
    except Exception as e:  # noqa: BLE001
        try:
            import lib_state
            lib_state.trace_failure(HOOK, "Stop", e)
        except Exception:  # noqa: BLE001
            print(f"{HOOK}: {e}", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
