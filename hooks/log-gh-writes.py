#!/usr/bin/env python3
"""PostToolUse, Bash: append one JSON line per GitHub write an agent makes.

Why: an agent running locally acts through the human's own `gh` login, so
GitHub attributes its merges and labels to the human. To count the human's
own touches, the agent's writes have to be known from this side, so a later
script can subtract them from what GitHub says the human did (dotfiles#553).

A write is `gh pr create|merge|close|reopen|edit|review|comment|ready`,
`gh issue create|close|reopen|edit|comment|delete`, `gh label create|edit|
delete`, `gh api` with a non-GET method (or fields, which make it a POST),
and `git push`. Everything else returns at once.

One line per write, in the state dir's metrics/gh-writes/<session>.jsonl:
    {"ts": "2026-01-01T00:00:00Z", "session_id": "...", "repo": "o/r",
     "verb": "pr merge", "target": "42"}
target is the PR/issue number or URL as typed, the API path, or the pushed
refspec; for a create it is read from the URL gh prints. PostToolUse fires
only for a call that succeeded, so a failed write is not logged.

Not covered: commands the human runs outside Claude; a write made by a
script the command only names (`bash release.sh`). Fails open: any error
exits 0 and the call is untouched.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

VERBS = {
    "pr": {"create", "merge", "close", "reopen", "edit", "review", "comment", "ready"},
    "issue": {"create", "close", "reopen", "edit", "comment", "delete"},
    "label": {"create", "edit", "delete"},
}
SPLIT = re.compile(r"&&|\|\||[;|\n]")
FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
# Flags that take a value, so the value is not mistaken for the target.
VALUE_FLAGS = {"-R", "--repo", "-b", "--body", "-t", "--title", "-F", "--body-file",
               "-m", "--merge-method", "-l", "--label", "-a", "--assignee", "-B",
               "--base", "-H", "--head", "-X", "--method", "-f", "--field", "-q",
               "--jq", "-t", "--template", "--add-label", "--remove-label",
               "-r", "--reviewer", "--subject", "--match-head-commit", "-d",
               "--description", "-c", "--color", "--add-assignee", "-M",
               "--milestone", "--repo-url", "-H", "--header", "--hostname",
               "--input", "--raw-field", "--cache", "-p", "--preview"}


def words(segment):
    try:
        toks = shlex.split(segment, comments=False)
    except ValueError:
        return []
    while toks and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in ("env", "command", "time")):
        toks.pop(0)
    return toks


def flag_value(args, names):
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if n.startswith("--") and a.startswith(n + "="):
                return a.split("=", 1)[1]
    return ""


def positionals(args):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in VALUE_FLAGS
        else:
            out.append(a)
    return out


def classify(toks):
    """(verb, target, explicit_repo) for one command, or None if not a write."""
    if not toks:
        return None
    if toks[0] == "git":
        i = 1
        while i < len(toks) and toks[i].startswith("-"):  # git -C dir push: skip option and its value
            i += 2 if toks[i] in ("-C", "-c") else 1
        if i < len(toks) and toks[i] == "push":
            pos = positionals(toks[i + 1:])
            return "git push", " ".join(pos), ""
        return None
    if toks[0] != "gh" or len(toks) < 2:
        return None
    args = toks[1:]
    repo = flag_value(args, ["-R", "--repo"])
    pos = positionals(args)
    if not pos:
        return None
    if pos[0] == "api":
        method = flag_value(args, ["-X", "--method"]).upper()
        has_fields = any(a in FIELD_FLAGS or a.startswith(("--field=", "--raw-field=", "--input=")) for a in args)
        if method in ("", "GET") and not has_fields:
            return None
        if method == "GET":
            return None
        path = pos[1] if len(pos) > 1 else ""
        m = re.match(r"^/?repos/([^/]+/[^/]+)", path)
        return f"api {method or 'POST'}", path, repo or (m.group(1) if m else "")
    if len(pos) >= 2 and pos[0] in VERBS and pos[1] in VERBS[pos[0]]:
        return f"{pos[0]} {pos[1]}", (pos[2] if len(pos) > 2 else ""), repo
    return None


def repo_of(cwd):
    try:
        url = subprocess.run(["git", "-C", cwd, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1) if m else ""


def pushed_ref(cwd):
    try:
        return subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def printed_url_target(resp):
    text = ""
    if isinstance(resp, dict):
        text = str(resp.get("stdout") or "")
    elif isinstance(resp, str):
        text = resp
    m = re.search(r"https://github\.com/\S+?/(?:pull|issues)/\d+", text)
    return m.group(0) if m else ""


def writes(cmd, cwd, resp):
    out = []
    for seg in SPLIT.split(cmd):
        hit = classify(words(seg))
        if not hit:
            continue
        verb, target, repo = hit
        if verb.endswith(" create") and not target:
            target = printed_url_target(resp)
        if verb == "git push" and not target:
            target = pushed_ref(cwd)
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/", target)
        out.append({"verb": verb, "target": target, "repo": repo or (m.group(1) if m else "") or repo_of(cwd)})
    return out


def main():
    import lib_state
    from state import state_shard_path
    ev = lib_state.event()
    if ev.get("tool_name") != "Bash":
        return
    cmd = str((ev.get("tool_input") or {}).get("command") or "")
    if not re.search(r"\b(gh|git)\b", cmd):
        return
    found = writes(cmd, ev.get("cwd") or os.getcwd(), ev.get("tool_response"))
    if not found:
        return
    sid = str(ev.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown")
    path = state_shard_path(os.path.join(lib_state.state_dir(), "metrics", "gh-writes"),
                                      f"{sid}.jsonl", sid)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "a") as f:
        for w in found:
            f.write(json.dumps({"ts": ts, "session_id": sid, **w}) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a logger never blocks a call
        print(f"log-gh-writes: {e}", file=sys.stderr)
    sys.exit(0)
