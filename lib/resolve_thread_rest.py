#!/usr/bin/env python3
"""The REST route of bin/gh-resolve-thread, for where GitHub refuses GraphQL (a
Claude Code cloud session answers HTTP 403).

Run by the wrapper, never directly:
    resolve_thread_rest.py <owner/repo#n:comment id> <resolve|reply|reply-only> [BODY]

The handle is the PR plus the thread's first comment id, because the CCR
thread list (`pulls/<n>/ccr/review_threads`) carries `resolved` and
`comment_ids` and no GraphQL node id, so a PRRT_ id cannot be turned into a
PR without GraphQL. Same refusals as the GraphQL route: a reply is signed, a
bare resolve needs the thread's last comment to be a signed reply of the
caller's, and a reply lands only on the PR this checkout is.
"""
import re
import subprocess
import sys

HANDLE = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+):(\d+)$")
SIG_FIRST = "\U0001f916 "
SIG_LAST = re.compile(r"^\U0001f916 [^ ]+ · [^ ]+ · [0-9a-f]{8}$")


class Refused(Exception):
    pass


def gh(*args):
    p = subprocess.run(["gh", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise Refused((p.stderr or p.stdout).strip() or f"gh {args[0]} failed")
    return p.stdout


def get_json(path):
    import json
    return json.loads(gh("api", path) or "null")


def signed(body):
    lines = (body or "").split("\n")
    nonblank = [x for x in lines if x.strip()]
    return (lines[0].startswith(SIG_FIRST) and bool(nonblank)
            and bool(SIG_LAST.match(nonblank[-1])))


def local_checkout(repo, head):
    def out(*cmd):
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else ""
    origin = out("git", "remote", "get-url", "origin")
    branch = out("git", "symbolic-ref", "--short", "-q", "HEAD")
    return re.search(r"github\.com[:/]" + re.escape(repo) + r"(\.git)?$", origin) is not None and branch == head


def run(handle, mode, body, say):
    m = HANDLE.match(handle)
    if not m:
        raise Refused(f"'{handle}' is not a thread handle (expected owner/repo#n:comment id)")
    repo, num, cid = m.group(1), m.group(2), int(m.group(3))
    base = f"repos/{repo}/pulls/{num}"
    threads = get_json(f"{base}/ccr/review_threads") or []
    thread = next((t for t in threads if t.get("comment_ids") and t["comment_ids"][0] == cid), None)
    if thread is None:
        raise Refused(f"no review thread on {repo}#{num} starting at comment {cid}")

    if mode == "resolve":
        me = (gh("api", "user", "--jq", ".login").strip())
        last = get_json(f"repos/{repo}/pulls/comments/{thread['comment_ids'][-1]}") or {}
        author = (last.get("user") or {}).get("login") or ""
        if not me or author != me or not signed(last.get("body")):
            raise Refused(f"{handle} has no signed reply of yours ({me}) as its last comment; answer it with --reply BODY")
    else:
        head = (get_json(base) or {}).get("head", {}).get("ref", "")
        if not local_checkout(repo, head):
            raise Refused(f"{handle} is on {repo}#{num} (branch {head}), and this checkout is not; only a session working that PR replies there.\n"
                          f"  If this session works it, reply with: gh api -X POST {base}/comments/{cid}/replies -f body=<signed reply>\n"
                          f"  then resolve with: gh-resolve-thread {handle}")
        posted = get_json_post(f"{base}/comments/{cid}/replies", body)
        if not (posted or {}).get("html_url"):
            raise Refused(f"reply on {handle} not posted: {posted}")
        if mode == "reply-only":
            say(f"replied on {handle}")
            return
    try:
        gh("api", "-X", "POST", f"{base}/ccr/comments/{cid}/resolve")
    except Refused as e:
        if mode == "reply":
            raise Refused(f"reply posted on {handle} but not resolved ({e}); do not post it again, finish with: gh-resolve-thread {handle}")
        raise
    after = get_json(f"{base}/ccr/review_threads") or []
    if not any(t.get("comment_ids") and t["comment_ids"][0] == cid and t.get("resolved") for t in after):
        raise Refused(f"{handle} not resolved: the thread list still shows it open")
    say(f"resolved {handle}")


def get_json_post(path, body):
    import json
    return json.loads(gh("api", "-X", "POST", path, "-f", f"body={body}") or "null")


def main(argv):
    if len(argv) not in (2, 3) or argv[1] not in ("resolve", "reply", "reply-only") or (argv[1] != "resolve") != (len(argv) == 3):
        print("usage: resolve_thread_rest.py <handle> <resolve|reply|reply-only> [BODY]", file=sys.stderr)
        return 1
    try:
        run(argv[0], argv[1], argv[2] if len(argv) == 3 else "", print)
    except Refused as e:
        print(f"gh-resolve-thread: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
