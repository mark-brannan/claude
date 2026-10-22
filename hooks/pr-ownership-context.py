#!/usr/bin/env python3
"""PreToolUse: put the "PR ownership" section of ~/.claude/rules/code.md in
front of the session the first time it touches a pull request.

Why: code.md is a path-globbed rule. It loads when a session reads or edits
a source file, and not otherwise -- so a session that opens with `gh pr
view`, reads the review comments and starts answering them has never seen
the section that says answer *and resolve* the threads and never hand over
red. The one-line pointer in ~/.claude/CLAUDE.md was the stopgap; it relies
on the model noticing it, which is the failure it was meant to fix. This
hook is the mechanical version: the text arrives because a PR-shaped tool
call happened, not because anyone remembered.

Also, on every matching call, records the PR touched (see below) so
pr-threads-gate.sh can block the Stop while review threads are still open.

Fires once per session, on the first matching call:
  - Bash: `gh pr ...`, or `gh api ...` naming pulls / graphql / reviewThreads
  - Bash: `mergify stack push/checkout/sync`, `mergify queue ...`, or
    `mergify merge ...` -- the mergify CLI plugin creates and merges PRs
    without ever calling gh, so a session working a PR only through it used
    to leave the record empty and the Stop gate silently found nothing.
    2026-09-08.
  - Bash: `git push` or `yadm push` -- a session that only pushes a PR
    branch never reads a source file, so code.md never loaded for it.
  - MCP:  any GitHub tool whose name mentions a pull request or a review
The section is read live from code.md, so there is one source of truth and
nothing here to keep in sync. If the file or the heading is missing, say so
in the injected note rather than exit quietly -- a convenience hook that
does nothing looks identical to one that never ran.

CONVENIENCE: never denies, always exits 0. A crash or an odd payload must
not stop a `gh` command; it is reported on stderr.

Which commands count: only what runs. languette's scanner (the plugin's, at
its user-scope install in installed_plugins.json -- a settings.json hook gets
no CLAUDE_PLUGIN_ROOT) keeps one line per segment whose command word is gh,
gh-resolve-thread, mergify, git or yadm, from that word on; git and yadm
only when they push. A heredoc, a quoted message or `echo gh pr` names the
command without running it, and used to arm the Stop gate. No plugin, a
plugin too old to have `scan`, or a command the scanner refuses: fall back
to the raw command (over-match, never silence).

The record: one line per matching call in $TMPDIR/claude-pr-threads.<session>,
"repo<TAB>owner/name<TAB>number<TAB>kind" when the call names a PR, else
"cwd<TAB>path" and the gate asks gh which PR the branch there belongs to.
The repo/number extraction works clause-by-clause on a compound Bash call
(split on ; & |), not on the command as one string. 2026-09-08: pairing the
first repo match and the first number match found *anywhere* in the string
let a call that named an issue and a PR in one line (or two PRs) fabricate a
repo#number neither clause actually queried -- the Stop gate then blocked on
a PR that never existed. Repo and number lock in on the first clause that
supplies both; every later clause naming that same pair can still raise
kind, read to work, never lower it (`gh pr diff 42 -R o/r; gh pr comment 42
-R o/r` records work).

dotfiles#224: kind is read or work. A bare `gh pr view/checks/diff/list`, or
a `gh api` call that isn't a mutating HTTP method (-X/--method
POST|PUT|PATCH|DELETE), a graphql `mutation`, or a field/body flag (-f, -F,
--field, --raw-field, --input: gh switches to POST) not overridden by
-X GET, is a read -- it goes in the
record (so the reminder text still fires, and the call is not invisible) but
pr-threads-gate.sh does not gate the Stop on it. Everything else naming `gh
pr` (create, edit, comment, merge, ready, review, close, reopen, ... -- an
unrecognized subcommand defaults to work, the same fail-closed instinct as
the gate itself) is work, and so is `gh-resolve-thread`. Reading someone
else's PR for evidence must not put its threads on this session's Stop. A
`cwd` line is unaffected: it resolves to the PR of the branch this session's
worktree holds, which is gate-worthy on identity alone, whatever call
produced it. A sub-agent's call (the payload carries agent_id) writes no
`cwd` line: its cwd is the sub-agent's checkout, not the parent's.
"""
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True

SP = r"[ \t\r\f\v]"  # [[:space:]] in a line: the old grep saw one line at a time
NOT_WORD = r"[^A-Za-z0-9_./-]"
SCAN_WORDS = r"(^|/)(gh|gh-resolve-thread|mergify|git|yadm)$"
SCAN_TIMEOUT = 10

# What makes a Bash call PR-shaped. MULTILINE and no DOTALL: each line alone.
BASH_MATCH = re.compile(
    rf"(^|{NOT_WORD})gh{SP}+(pr({SP}|$)|api{SP}.*(pulls|graphql|reviewThreads))"
    rf"|(^|{NOT_WORD})gh-resolve-thread({SP}|$)"
    rf"|(^|[;&|(`]){SP}*mergify{SP}+(stack{SP}+(push|checkout|sync)({SP}|$)|(queue|merge)({SP}|$))"
    rf"|(^|[;&|(`]){SP}*(git|yadm){SP}+push({SP}|$)", re.M)
MERGIFY = re.compile(rf"(^|[;&|(`]){SP}*mergify{SP}", re.M)
MCP_TOOL = re.compile(r"^mcp__.*github.*__", re.S)
MCP_PR = re.compile(r"pull_request|review", re.I)
MCP_READ = re.compile(r"(^|_)(read|get|list|search)($|_)", re.I)

REPO_FLAG = re.compile(rf"(?:^|{SP})(?:-R|--repo)[ \t\r\f\v=]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
PR_NUM = (re.compile(rf"gh{SP}+pr{SP}+[a-z-]+{SP}+([0-9]+)"),
          re.compile(r"pulls/([0-9]+)"),
          re.compile(r"pull/([0-9]+)"))
URL_REPO = re.compile(r"(?:repos|github\.com)/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pulls?/")
GH_READ = re.compile(rf"(^|{NOT_WORD})gh{SP}+pr{SP}+(view|checks|diff|list)({SP}|$)")
GH_PR = re.compile(rf"(^|{NOT_WORD})gh{SP}+pr({SP}|$)")
MUTATING_METHOD = re.compile(rf"(^|{SP})(-X|--method)[ \t=]+(POST|PUT|PATCH|DELETE)", re.I)
MUTATION = re.compile(rf"mutation{SP}*\(", re.I)
# gh api turns a POST on its own once it gets a field or body flag.
# -f/-F may carry the value attached (-fbody=x).
FIELD_FLAG = re.compile(rf"(^|{SP})(-[fF]|--field|--raw-field|--input)")
# graphql always POSTs its -f query; only a mutation writes.
GRAPHQL = re.compile(rf"(^|{SP})api{SP}+graphql({SP}|$)")
GET_METHOD = re.compile(rf"(^|{SP})(-X|--method)[ \t=]+GET\b", re.I)


def jq_str(v):
    """A value as `jq -r` prints it, "" for null or false (`// empty`)."""
    if v is None or v is False:
        return ""
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def note(text):
    """Allow the call and attach text for the session."""
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                  "additionalContext": text}}
    sys.stdout.buffer.write((json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def scanned(cmd):
    """The command reduced to what runs, one line per segment, or None when
    there is no scanner to ask (the caller then over-matches on the raw
    command)."""
    import lib_state
    root = lib_state.languette_root()
    main = os.path.join(root, "languette", "__main__.py") if root else ""
    if not main or not os.path.isfile(main):
        return None
    try:
        p = subprocess.run([sys.executable, "-I", main, "scan", "--command", SCAN_WORDS],
                           input=cmd, capture_output=True, text=True, timeout=SCAN_TIMEOUT)
        if p.returncode:
            return None
        lines = []
        for seg in json.loads(p.stdout)["segments"]:
            words = seg["words"]
            c = re.sub(r".*/", "", words[0]["text"], count=1)
            if c in ("git", "yadm"):  # only a push counts
                w = words[1] if len(words) > 1 else None
                if not (w and not w.get("quoted") and w.get("text") == "push"):
                    continue
            lines.append(re.sub(r"\n", " ", " ".join([c] + [w["text"] for w in words[1:]])))
        return "\n".join(lines)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        return None


def clause_kind(clause):
    if GH_READ.search(clause):
        return "read"
    if GH_PR.search(clause):
        return "work"
    # Only a `gh api` call is left to supply a repo and number.
    if MUTATING_METHOD.search(clause) or MUTATION.search(clause):
        return "work"
    if GRAPHQL.search(clause):
        return "read"
    if FIELD_FLAG.search(clause) and not GET_METHOD.search(clause):
        return "work"
    return "read"


def first(patterns, clause):
    for p in patterns:
        m = p.search(clause)
        if m:
            return m.group(1)
    return ""


def pr_of(cmd):
    """(repo, number, kind) for the PR a Bash call names, or None."""
    repo = num = kind = ""
    for clause in (c for c in re.split(r"[;&|\n]", cmd) if c):
        m = REPO_FLAG.search(clause)
        c_repo = m.group(1) if m else ""
        c_num = first(PR_NUM, clause)
        if not c_repo:
            c_repo = first([URL_REPO], clause)
        if c_repo and c_num and (not repo or (c_repo == repo and c_num == num)):
            c_kind = clause_kind(clause)
            if not repo:
                repo, num, kind = c_repo, c_num, c_kind
            elif c_kind == "work":
                kind = "work"
    return (repo, num, kind) if repo and num else None


def append(record, line):
    """Best-effort: a full disk or a race on the tmp file must not fail the
    command that triggered this."""
    try:
        with open(record, "a", encoding="utf-8", errors="replace") as f:
            f.write(line + "\n")
    except OSError:
        pass


def record_bash(cmd, ev, record):
    # A sub-agent's tool call carries agent_id and the PARENT's session_id,
    # so its cwd -- often a worktree of its own -- would land in the
    # parent's record, and the parent's Stop would gate on a branch only the
    # sub-agent holds. Seen 2026-10-20, mark-brannan/claude#188: every
    # orchestrator turn blocked on its reviewers' PRs. The sub-agent's cwd
    # stays out; a call naming repo and number is still recorded.
    cwd = "" if jq_str(ev.get("agent_id")) else jq_str(ev.get("cwd"))
    if MERGIFY.search(cmd):
        # mergify never names owner/repo/number on the command line -- it
        # infers the PR from the current branch, so cwd is the only handle.
        if cwd:
            append(record, f"cwd\t{cwd}")
        return
    pr = pr_of(cmd)
    if pr:
        append(record, "repo\t%s\t%s\t%s" % pr)
    elif cwd:
        append(record, f"cwd\t{cwd}")


def record_mcp(tool, ev, record):
    kind = "read" if MCP_READ.search(tool) else "work"
    ti = ev.get("tool_input")
    if not isinstance(ti, dict):
        return
    owner, repo = ti.get("owner"), ti.get("repo")
    num = next((ti[k] for k in ("pullNumber", "pull_number", "number") if jq_str(ti.get(k))), None)
    if jq_str(owner) and jq_str(repo) and num is not None:
        append(record, f"repo\t{owner}/{repo}\t{jq_str(num)}\t{kind}")


def rules_section(rules):
    """The PR ownership section: from its heading to the next `## ` heading.
    Split on \\n only, so a stray \\r or form feed stays in the text."""
    with open(rules, "rb") as f:
        lines = f.read().decode("utf-8", "replace").split("\n")
    out, inside = [], False
    for line in lines:
        if line.startswith("## PR ownership"):
            inside = True
        elif inside and line.startswith("## "):
            break
        if inside:
            out.append(line)
    return "\n".join(out).rstrip("\n")


def main():
    import lib_state  # beside this file; it puts lib/ on sys.path
    ev = lib_state.event()
    tool = jq_str(ev.get("tool_name"))
    if not tool:
        return
    if tool == "Bash":
        ti = ev.get("tool_input")
        raw = jq_str(ti.get("command")) if isinstance(ti, dict) else ""
        seen = scanned(raw)
        cmd = raw if seen is None else seen
        if not BASH_MATCH.search(cmd):
            return
    elif MCP_TOOL.match(tool):
        if not MCP_PR.search(tool):
            return
    else:
        return

    # The record is what the Stop gate runs on; the text below fires once.
    sid = jq_str(ev.get("session_id"))
    tag = ""
    if sid:
        tag = re.sub(rb"[^A-Za-z0-9_-]", b"_", sid.encode("utf-8")).decode()
        tmp = os.environ.get("TMPDIR") or "/tmp"
        record = os.path.join(tmp, f"claude-pr-threads.{tag}")
        if tool == "Bash":
            record_bash(cmd, ev, record)
        else:
            record_mcp(tool, ev, record)
        # The marker lives in tmp on purpose: it dies with the machine (cloud
        # VM) or the reboot, and must never land in a state repo.
        marker = os.path.join(tmp, f"claude-pr-ownership-context.{tag}")
        if os.path.exists(marker):
            return
        try:
            open(marker, "w").close()
        except OSError:
            pass

    rules = os.path.join(os.path.expanduser("~"), ".claude", "rules", "code.md")
    if not os.path.isfile(rules):
        return note(f"pr-ownership-context: {rules} is missing, so the PR ownership rules could not be injected. "
                    "Run dotsync (or cloud-session-setup.sh); until then, treat review threads as yours to reply to "
                    "AND resolve, and never hand over red.")
    section = rules_section(rules)
    if not section:
        return note(f"pr-ownership-context: no '## PR ownership' heading in {rules}, so the rules could not be injected. "
                    "Until that is fixed: review threads are yours to reply to AND resolve, and never hand over red.")
    note(f"PR work detected. These are the PR ownership rules from {rules}, injected once per session by "
         "pr-ownership-context.py because path-globbed rules do not load on a gh call. They apply to this PR from "
         f"here on.\n\n{section}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a convenience hook never stops a call
        print(f"pr-ownership-context: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(0)
