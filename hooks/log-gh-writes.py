#!/usr/bin/env python3
"""PostToolUse, Bash: append one JSON line per GitHub write an agent makes.

Why: an agent running locally acts through the human's own `gh` login, so
GitHub attributes its merges and labels to the human. To count the human's
own touches, the agent's writes have to be known from this side, so a later
script can subtract them from what GitHub says the human did (dotfiles#553).

A write is a verb in GH_WRITES (pr, issue, label, release, workflow, run and
repo), `gh api` with a non-GET method (or fields, which make it a POST), and
a `git push` that is not --dry-run, -n or --help. Everything else returns at
once.

One line per write, in the state dir's metrics/gh-writes/<session>.jsonl:
    {"ts": "2026-01-01T00:00:00Z", "session_id": "...", "repo": "o/r",
     "verb": "pr merge", "target": "42"}
target is the PR/issue number or URL as typed, the API path, or the pushed
refspec; for a create it is read from the URL gh prints. PostToolUse fires
only for a Bash call that succeeded, so the log is per call, not per command:
`gh pr merge 1 || true` logs a merge that failed, and in `a && b` where b
fails the successful `a` is dropped.

A repo comes from -R, a URL target or the git remote of the directory the
command runs in (`git -C dir`, `cd dir &&`; a `cd` inside a subshell is
taken to last past it).

Not covered: commands the human runs outside Claude; a write made by a
script the command only names (`bash release.sh`); a `gh` group outside
GH_WRITES (gist, secret, variable, project, codespace, ssh-key, gpg-key,
cache); a command inside a quoted string or an argument (`echo "$(gh ...)"`).
Fails open: any error exits 0 and the call is untouched.
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

# Each write verb with the flags that take a value, so that value is not
# mistaken for the target. From `gh <group> <verb> --help` (gh 2.100). One
# shared set cannot serve: -r is --reviewer on `pr create` but a boolean
# (--rebase) on `pr merge`; -c is --comment on `pr close`, a boolean on `pr
# review`. -R/--repo takes a value on every verb and is added below.
_GH = {
    "pr": {
        "create": "-a --assignee --attach -B --base -b --body -F --body-file -H --head -l --label"
                  " -m --milestone -p --project --recover -r --reviewer -T --template -t --title",
        "merge": "-A --author-email -b --body -F --body-file --match-head-commit -t --subject",
        "close": "-c --comment",
        "reopen": "-c --comment",
        "edit": "--add-assignee --add-label --add-project --add-reviewer --attach -B --base -b --body"
                " -F --body-file -m --milestone --remove-assignee --remove-label --remove-project"
                " --remove-reviewer -t --title",
        "review": "-b --body -F --body-file",
        "comment": "--attach -b --body -F --body-file",
        "ready": "", "update-branch": "", "unlock": "",
        "lock": "-r --reason",
        "revert": "-b --body -F --body-file -t --title",
    },
    "issue": {
        "create": "-a --assignee --attach --blocked-by --blocking -b --body -F --body-file -l --label"
                  " -m --milestone --parent -p --project --recover -T --template -t --title --type",
        "close": "-c --comment --duplicate-of -r --reason",
        "reopen": "-c --comment",
        "edit": "--add-assignee --add-blocked-by --add-blocking --add-label --add-project"
                " --add-sub-issue --attach -b --body -F --body-file -m --milestone --parent"
                " --remove-assignee --remove-blocked-by --remove-blocking --remove-label"
                " --remove-project --remove-sub-issue -t --title --type",
        "comment": "--attach -b --body -F --body-file",
        "delete": "", "unlock": "", "pin": "", "unpin": "", "transfer": "",
        "lock": "-r --reason",
        "develop": "-b --base --branch-repo -n --name --worktree",
    },
    "label": {
        "create": "-c --color -d --description",
        "edit": "-c --color -d --description -n --name",
        "delete": "", "clone": "",
    },
    "release": {
        "create": "--discussion-category -n --notes -F --notes-file --notes-start-tag --target -t --title",
        "edit": "--discussion-category -n --notes -F --notes-file --tag --target -t --title",
        "delete": "", "upload": "", "delete-asset": "",
    },
    "workflow": {"run": "-F --field -f --raw-field -r --ref", "enable": "", "disable": ""},
    "run": {"rerun": "-j --job", "cancel": "", "delete": ""},
    "repo": {
        "create": "-d --description -g --gitignore -h --homepage -l --license -r --remote -s --source"
                  " -t --team -p --template",
        "edit": "--add-topic --default-branch -d --description -h --homepage --remove-topic"
                " --squash-merge-commit-message --visibility",
        "fork": "--fork-name --org --remote-name",
        "delete": "", "rename": "", "archive": "", "unarchive": "",
    },
}
GH_WRITES = {(g, v): set(f.split()) | {"-R", "--repo"} for g, vs in _GH.items() for v, f in vs.items()}
API_VALUE_FLAGS = set("--cache -F --field -H --header --hostname --input -q --jq -X --method"
                      " -p --preview -f --raw-field -t --template -R --repo".split())
# git push has few value flags; gh's -f and -d would swallow the remote.
GIT_PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
GIT_PUSH_NOOP = {"--dry-run", "--help"}

OPERATORS = set(";&|\n")
# A heredoc: opener, rest of the opener line, body, closing delimiter. Only the
# body and the delimiter are dropped; the rest of the opener line is kept,
# since it can hold the command (`cat <<EOF | gh issue comment 5 -F -`).
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n(?:.*?\n)?[ \t]*\2[ \t]*(?=\n|$)", re.S)
CRED = re.compile(r"(?<=://)[^/@\s]+@")
FIELD_FLAGS = {"-f", "-F", "--field", "--raw-field", "--input"}
# Words that run the next command without being it.
WRAPPERS = {"env", "command", "time", "sudo", "nohup", "exec", "!", "{",
            "if", "then", "do", "else", "elif", "while", "until"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
OPENER = re.compile(r"^(?:[A-Za-z_][A-Za-z0-9_]*=)?(?:\$\(|`|\()+")


def strip_comments(cmd):
    """Drop each shell comment: an unquoted `#` that starts a word, to the end
    of its line. A `#` inside a word (`build#12`, `.../5#issuecomment-1`) or a
    quote is text, as in a real shell."""
    out, quote, i = [], "", 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == "\\" and quote == '"':
                out.append(cmd[i:i + 2])
                i += 2
                continue
            quote = "" if c == quote else quote
        elif c == "\\":
            out.append(cmd[i:i + 2])
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif c == "#" and (not out or out[-1] in " \t\r\n;&|(){"):
            i = cmd.find("\n", i)
            if i < 0:
                break
            continue
        out.append(c)
        i += 1
    return "".join(out)


def split_ops(cmd):
    """Cut the command at each unquoted, unescaped operator character. Done on
    the raw text, since a token shlex returns no longer says whether it was
    quoted: `--body ""` and `-b ";"` are arguments, not operators."""
    out, cur, quote, i = [], [], "", 0
    while i < len(cmd):
        c = cmd[i]
        if quote:
            if c == "\\" and quote == '"':
                cur.append(cmd[i:i + 2])
                i += 2
                continue
            quote = "" if c == quote else quote
        elif c == "\\":
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        elif c in "'\"":
            quote = c
        elif c in OPERATORS:
            out.append("".join(cur))
            cur = []
            i += 1
            continue
        cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def segments(cmd):
    """Split on operators, then tokenise each part quote-aware."""
    cmd = strip_comments(HEREDOC.sub(r" \3", cmd))
    out = []
    for part in split_ops(cmd):
        lex = shlex.shlex(part, posix=True)
        lex.commenters = ""  # comments are gone; shlex's would cut a `#` inside a word
        lex.whitespace_split = True
        try:
            out.append(list(lex))
        except ValueError:
            return []
    depth, segs = 0, []
    for c in out:
        c, depth = strip_prefix(c, depth)
        if c:
            segs.append(c)
    return segs


def strip_prefix(toks, depth=0):
    """Drop what starts a command without being it: VAR=x, env, sudo, `if`,
    `!`, xargs and its flags, an opening `(` or `$(`. A `)` that ends the
    segment closes one of the `depth` open ones and goes too. -> (toks, depth)"""
    while toks:
        m = OPENER.match(toks[0])
        if m:
            depth += m.group(0).count("(")
            toks = ([toks[0][m.end():]] if toks[0][m.end():] else []) + toks[1:]
        elif toks[0] in WRAPPERS or ASSIGN.match(toks[0]):
            toks = toks[1:]
        else:
            break
    if toks and toks[0] == "xargs":
        toks = next((toks[i:] for i, t in enumerate(toks) if t in ("gh", "git")), toks)
    if toks and depth:
        closes = len(toks[-1]) - len(toks[-1].rstrip(")"))
        closes = min(closes, depth)
        if closes:
            toks = toks[:-1] + ([toks[-1][:-closes]] if toks[-1][:-closes] else [])
            depth -= closes
    return toks, depth


def flag_value(args, names):
    for i, a in enumerate(args):
        for n in names:
            if a == n and i + 1 < len(args):
                return args[i + 1]
            if n.startswith("--") and a.startswith(n + "="):
                return a.split("=", 1)[1]
    return ""


def positionals(args, value_flags):
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = a in value_flags
        else:
            out.append(a)
    return out


def push_is_noop(args):
    """True for a push that writes nothing: --dry-run, -n (alone or bundled,
    `-fn`), --help."""
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in GIT_PUSH_NOOP:
            return True
        elif a in GIT_PUSH_VALUE_FLAGS:
            skip = True
        elif a.startswith("-") and not a.startswith("--") and "n" in a[1:].split("o")[0]:
            return True
    return False


def classify(toks):
    """(verb, target, explicit_repo, git_dirs) for one command, or None if not
    a write. git_dirs are the `git -C` directories, in order."""
    if not toks:
        return None
    if toks[0] == "git":
        i, dirs = 1, []
        while i < len(toks) and toks[i].startswith("-"):  # git -C dir push: skip option and its value
            if toks[i] == "-C" and i + 1 < len(toks):
                dirs.append(toks[i + 1])
            i += 2 if toks[i] in ("-C", "-c") else 1
        if i < len(toks) and toks[i] == "push" and not push_is_noop(toks[i + 1:]):
            return "git push", " ".join(positionals(toks[i + 1:], GIT_PUSH_VALUE_FLAGS)), "", dirs
        return None
    if toks[0] != "gh" or len(toks) < 2:
        return None
    args = toks[1:]
    repo = flag_value(args, ["-R", "--repo"])
    head = positionals(args, {"-R", "--repo"})  # group and verb; only -R can precede them
    if not head:
        return None
    if head[0] == "api":
        pos = positionals(args, API_VALUE_FLAGS)
        method = flag_value(args, ["-X", "--method"]).upper()
        if not method:
            method = next((a[2:].upper() for a in args if a.startswith("-X") and len(a) > 2), "")
        has_fields = any(a in FIELD_FLAGS or re.match(r"-[fF].", a) or a.startswith(("--field=", "--raw-field=", "--input=")) for a in args)
        if method == "GET" or (not method and not has_fields):
            return None
        path = pos[1] if len(pos) > 1 else ""
        if path == "graphql" and not method and not any(is_mutation(a) for a in args):
            return None
        m = re.match(r"^/?repos/([^/]+/[^/]+)", path)
        return f"api {method or 'POST'}", path, repo or (m.group(1) if m else ""), []
    if tuple(head[:2]) in GH_WRITES:
        pos = positionals(args, GH_WRITES[tuple(head[:2])])
        return f"{pos[0]} {pos[1]}", (pos[2] if len(pos) > 2 else ""), repo, []
    return None


QUERY_FIELD = re.compile(r"^(?:-[fF]|--(?:raw-)?field=)?query=(.*)$", re.S)


def is_mutation(arg):
    """A graphql `query=` field, in any spelling, that is a mutation. A value
    read from a file (`query=@f.graphql`) cannot be seen, so it counts as one."""
    m = QUERY_FIELD.match(arg)
    return bool(m) and bool(re.match(r"\s*(?:mutation\b|@)", m.group(1)))


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


def chdir(here, args):
    """Where `cd <args>` leaves a shell that was in `here`; unchanged if unknown."""
    args = [a for a in args if a not in ("-P", "-L", "--")]
    if not args:
        return os.path.expanduser("~")
    if args[0] == "-":
        return here
    return os.path.normpath(os.path.join(here, os.path.expanduser(args[0])))


def workdir(here, git_dirs):
    """The directory a command runs in: `here` moved by each `git -C`; the
    session's own if that path does not exist (an unexpanded $VAR, say)."""
    for d in git_dirs:
        here = chdir(here, [d])
    return here if os.path.isdir(here) else ""


def writes(cmd, cwd, resp):
    out, here = [], cwd
    for toks in segments(cmd):
        if toks[0] == "cd":
            here = chdir(here, toks[1:])
            continue
        hit = classify(toks)
        if not hit:
            continue
        verb, target, repo, git_dirs = hit
        wd = workdir(here, git_dirs) or cwd
        if verb.endswith(" create") and not target:
            target = printed_url_target(resp)
        if verb == "git push" and not target:
            target = pushed_ref(wd)
        target = CRED.sub("", target)
        m = re.match(r"https://github\.com/([^/]+/[^/]+)/", target)
        out.append({"verb": verb, "target": target, "repo": repo or (m.group(1) if m else "") or repo_of(wd)})
    return out


def main():
    import lib_state
    ev = lib_state.event()
    if ev.get("tool_name") != "Bash":
        return
    cmd = str((ev.get("tool_input") or {}).get("command") or "")
    if not re.search(r"\b(gh|git)\b", cmd):
        return
    found = writes(cmd, ev.get("cwd") or os.getcwd(), ev.get("tool_response"))
    if not found:
        return
    sd = lib_state.state_dir()
    if not sd:  # no state lib here (lib_state said why on stderr): nowhere to log
        return
    from state import state_shard_path
    sid = str(ev.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown")
    path = state_shard_path(os.path.join(sd, "metrics", "gh-writes"), f"{sid}.jsonl", sid)
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
