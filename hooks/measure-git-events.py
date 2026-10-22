#!/usr/bin/env python3
"""PostToolUse: log the git events that carry a cost the user ends up paying.

Three kinds, and only three -- logging every commit would make this a commit
log wearing a metrics label, and the signal is the whole point:

  cherry_pick  shuttling a commit between branches; the original question
               was how much of that is actually happening
  branch       `rules/code.md` says a branch requires the user's explicit ask,
               because a branch demands a PR and a PR is a decision pushed
               to him. Five stranded `claude/*` branches is what prompted
               that rule; this is the counter that would have shown them
  pr           the decision itself, logged as high-cost by definition

One JSON line per event in the state dir's metrics/git-events/<session>.jsonl:
    {"ts": "2026-01-01T00:00:00Z", "session_id": "...", "kind": "branch",
     "repo": "claude", "branch": "main", "created_branch": "feat/x"}

Match the tool NAME in settings.json and filter the command in here: a matcher
written as `Bash(git commit.*)` is permission-rule syntax, which as a regex
needs a tool literally named `Bashgit commit...`, so it never fires.

Fails open: any error exits 0 with one line on stderr, and the call is untouched.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

GIT_OR_PR = re.compile(r"\bgit\b.*\b(commit|cherry-pick|checkout|switch|branch|worktree)\b"
                       r"|\bgh\b.*\bpr\b.*\bcreate\b")
GH_PR_CREATE = re.compile(r"\bgh\b.*\bpr\b.*\bcreate\b")
DRAFT = re.compile(r"(^|\s)--draft(\s|$)", re.M)
# Branch created: all four forms -- `checkout -b`, `switch -c`, `worktree add
# -b`, and bare `git branch <name>` (never -d/-D/-m/--list/-a).
NEW_BRANCH = (
    re.compile(r".*\bgit[^\S\n]+(?:checkout[^\S\n]+-b|switch[^\S\n]+-c|worktree[^\S\n]+add[^\S\n]+-b)"
               r"[^\S\n]+([^\s;&|]+)"),
    re.compile(r".*\bgit[^\S\n]+branch[^\S\n]+([^-\n][^\s;&|]*)"),
)
CHERRY_PICKED = re.compile(r"^\(cherry picked from commit ([a-f0-9]*)", re.M)


def alt(value, default):
    """jq's `value // default`: the default for null and false only."""
    return default if value is None or value is False else value


def text(value):
    return value if isinstance(value, str) else json.dumps(value)


def last_line(path):
    try:
        with open(path, "rb") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""
    return lines[-1].decode("utf-8", "replace") if lines else ""


def already_logged(path, commit):
    """The file's last line is this commit's cherry_pick, so a later git
    command on the same HEAD does not count it again."""
    try:
        row = json.loads(last_line(path))
    except ValueError:
        return False
    return isinstance(row, dict) and row.get("kind") == "cherry_pick" and row.get("commit") == commit


def main():
    import lib_state
    ev = lib_state.event()
    tool = text(alt(ev.get("tool_name"), ""))
    if not (tool == "Bash" or tool.endswith("create_pull_request")):
        return
    sd = lib_state.state_dir()
    if not sd:  # no state lib here (lib_state said why on stderr): nowhere to log
        return
    import gitrun
    from state import state_shard_path

    ti = ev.get("tool_input")
    ti = ti if isinstance(ti, dict) else {}
    cwd = text(alt(ev.get("cwd"), ""))
    sid = text(alt(ev.get("session_id"), "unknown"))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path = state_shard_path(os.path.join(sd, "metrics", "git-events"), f"{sid}.jsonl", sid)

    def emit(kind, repo, branch, detail):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {"ts": ts, "session_id": sid, "kind": kind, "repo": repo, "branch": branch, **detail}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    if tool != "Bash":
        emit("pr", text(alt(ti.get("repo"), "")), text(alt(ti.get("head"), "")),
             {"title": alt(ti.get("title"), ""), "base": alt(ti.get("base"), ""),
              "draft": alt(ti.get("draft"), False)})
        return

    cmd = text(alt(ti.get("command"), ""))
    if not GIT_OR_PR.search(cmd) or not cwd:
        return
    if not gitrun.ok("rev-parse", "--git-dir", cwd=cwd):
        return
    top = gitrun.run("rev-parse", "--show-toplevel", cwd=cwd)
    repo = os.path.basename((top.stdout.strip() if top.returncode == 0 else cwd).rstrip("/"))
    branch = gitrun.out("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd)

    if GH_PR_CREATE.search(cmd):
        emit("pr", repo, branch, {"title": "", "base": "", "draft": bool(DRAFT.search(cmd))})

    m = NEW_BRANCH[0].search(cmd) or NEW_BRANCH[1].search(cmd)
    if m:
        emit("branch", repo, branch, {"created_branch": m.group(1)})

    # Identified from the commit trailer, not from the command, so a
    # `git commit` finishing a conflicted pick still counts.
    head = gitrun.run("rev-parse", "HEAD", cwd=cwd)
    commit = head.stdout.strip() if head.returncode == 0 else ""
    if not commit:
        return
    picked = CHERRY_PICKED.search(gitrun.out("log", "-1", "--format=%B", commit, cwd=cwd))
    if picked and not already_logged(path, commit):
        emit("cherry_pick", repo, branch, {"commit": commit, "original_commit": picked.group(1)})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a logger never blocks a call
        print(f"measure-git-events: {e}", file=sys.stderr)
    sys.exit(0)
