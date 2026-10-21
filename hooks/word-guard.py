#!/usr/bin/env python3
"""PreToolUse and PostToolUse: catch listed words in text an agent writes.

Words, scopes and actions live in word-guard.json beside this script,
with a repo's own .claude/word-guard.json added on top. An entry:

  {"pattern": "\\bfoo\\b", "action": "deny",
   "repos": ["owner/*"], "exclude_repos": ["owner/private-notes"],
   "paths": ["*"], "exclude_paths": ["word-guard.json"], "outward": true,
   "message": "Say bar instead."}

What is checked: the text an Edit, Write, MultiEdit or NotebookEdit adds to a
tracked file in a matching repo (paths are globs from the repo root), and,
when "outward" is true, the text of a git commit, a gh pr/issue/release/api
call or a GitHub MCP write. An Edit that keeps an existing hit adds nothing,
so old lines never nag.

"deny" refuses the call before it lands (PreToolUse). "warn" lets it land and
hands the agent the hit as context to fix (PostToolUse). Silent otherwise;
fails open, since a crash here must never block work.
"""
import fnmatch
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_CONFIG = os.environ.get("WORD_GUARD_CONFIG", os.path.join(HERE, "word-guard.json"))

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# git may carry global options (-C dir, -c k=v, --git-dir=...) before the subcommand.
OUTWARD_BASH = re.compile(
    r"(^|[\s;&|(`])(git(\s+(-[Cc]\s+\S+|--[\w-]+(=\S+)?))*\s+(commit|tag|notes)\b"
    r"|gh\s+(pr|issue|release|api|gist)\b)")
# Every -C in the command is a repo it may write to; each one is checked.
GIT_DIR = re.compile(r"(?:^|\s)-C\s+(['\"]?)([^\s'\"]+)\1")
# Message and body files: their text is what goes out, so it is read too.
TEXT_FILE = re.compile(r"(?:^|\s)(?:-F|--file|--body-file)(?:\s+|=)(['\"]?)([^\s'\"]+)\1")
MCP_WRITE = re.compile(
    r"^mcp__.*github.*__(create_|update_|add_|push_|merge_|issue_write|sub_issue_write|pull_request_review_write)")


def git(cwd, *args):
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def slug_of(root):
    url = git(root, "remote", "get-url", "origin") or ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(\.git)?/?$", url)
    return m.group(1) if m else os.path.basename(root)


def load(path):
    try:
        with open(path) as f:
            return json.load(f).get("entries", [])
    except (OSError, ValueError, AttributeError):
        return []


def globs(patterns, value):
    return any(fnmatch.fnmatchcase(value, p) for p in patterns)


def in_scope(entry, slug, rel):
    # GitHub owner and repo names are case-blind; file paths are not.
    repos = [p.lower() for p in entry.get("repos", ["*"])]
    if not globs(repos, slug.lower()) or globs([p.lower() for p in entry.get("exclude_repos", [])], slug.lower()):
        return False
    if rel is None:
        return True
    return globs(entry.get("paths", ["*"]), rel) and not globs(entry.get("exclude_paths", []), rel)


def edit_pairs(name, ti):
    """(old, new) text pairs for what a file edit adds."""
    if name == "Edit":
        return [(ti.get("old_string", ""), ti.get("new_string", ""))]
    if name == "MultiEdit":
        return [(e.get("old_string", ""), e.get("new_string", "")) for e in ti.get("edits", [])]
    if name == "Write":
        return [("", ti.get("content", ""))]
    return [("", ti.get("new_source", ""))]


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def check(payload):
    event = payload.get("hook_event_name", "PreToolUse")
    want = "deny" if event == "PreToolUse" else "warn"
    name = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()

    if name in EDIT_TOOLS:
        path = os.path.abspath(ti.get("file_path") or ti.get("notebook_path") or "/")
        d = os.path.dirname(path)
        while d != "/" and not os.path.isdir(d):
            d = os.path.dirname(d)
        root = git(d, "rev-parse", "--show-toplevel")
        if not root:
            return None
        rel = os.path.relpath(path, root)
        if git(root, "check-ignore", "-q", rel) is not None:
            return None
        targets, pairs, outward, where = [(root, slug_of(root))], edit_pairs(name, ti), False, rel
    elif name == "Bash":
        cmd = ti.get("command", "")
        if not OUTWARD_BASH.search(cmd):
            return None
        dirs = [cwd] + [os.path.join(cwd, os.path.expanduser(m.group(2))) for m in GIT_DIR.finditer(cmd)]
        roots = {r for r in (git(d, "rev-parse", "--show-toplevel") for d in dirs) if r}
        if not roots:
            return None
        targets = [(r, slug_of(r)) for r in sorted(roots)]
        rel, pairs, outward, where = None, [("", cmd)], True, "the command"
        files = {os.path.join(d, os.path.expanduser(m.group(2))) for m in TEXT_FILE.finditer(cmd) for d in dirs}
        for f in sorted(files):
            try:
                if os.path.isfile(f) and os.path.getsize(f) < 1 << 20:
                    with open(f, errors="replace") as fh:
                        pairs.append(("", fh.read()))
            except OSError:
                pass
    elif MCP_WRITE.match(name) and ti.get("owner") and ti.get("repo"):
        targets, rel, outward, where = [(None, f"{ti['owner']}/{ti['repo']}")], None, True, "the GitHub write"
        pairs = [("", s) for s in strings(ti)]
    else:
        return None

    lines = []
    for root, slug in targets:
        lines += scan(root, slug, rel, pairs, outward, where, want)
    lines = list(dict.fromkeys(lines))
    if not lines:
        return None
    text = "\n".join(lines)
    if want == "deny":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": text + "\nRewrite without it and retry."}}
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": text + "\nFix it now, before moving on."}}


def scan(root, slug, rel, pairs, outward, where, want):
    entries = load(GLOBAL_CONFIG) + (load(os.path.join(root, ".claude", "word-guard.json")) if root else [])
    lines = []
    for e in entries:
        if e.get("action", "warn") != want or (outward and not e.get("outward", False)):
            continue
        if not in_scope(e, slug, rel):
            continue
        try:
            rx = re.compile(e["pattern"], 0 if e.get("case", False) else re.IGNORECASE)
        except (KeyError, re.error):
            continue
        hits = set()
        for old, new in pairs:
            if len(rx.findall(new or "")) > len(rx.findall(old or "")):
                hits.update(m.group(0) for m in rx.finditer(new))
        if hits:
            lines.append(f"word-guard: {', '.join(sorted(hits))} in {where} ({slug}). {e.get('message', '')}".rstrip())
    return lines


def main():
    try:
        out = check(json.load(sys.stdin))
    except Exception:
        return 0
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
