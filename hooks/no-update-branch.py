#!/usr/bin/env python3
"""Denies GitHub's server-side "Update branch", whichever tool asks for it.

Why: on a repo whose ruleset requires signed commits, `gh pr update-branch
--rebase` silently destroys them. GitHub signs merge commits and commits
authored in its web UI, but it does NOT re-sign commits it rewrites during
a rebase -- so a branch whose commits verified before the call comes back
with every one of them unsigned, and the PR swaps a stale-branch block for
a signature block. That is not a theoretical failure: it happened on
dotfiles#226 (2026-09-16), by a session that had just finished diagnosing a
different silent gate on the same PR.

The merge-commit form (`gh pr update-branch`, no flag) keeps signatures --
GitHub signs the merge commit it creates -- but adds a merge commit, which
`required_linear_history` rejects. This repo's ruleset carries both rules,
so BOTH forms are dead ends here and the hook denies the subcommand
outright rather than trying to distinguish them. On a repo with neither
rule the deny is a false positive; re-signing by hand is correct there too,
so the cost is a redirect, not lost capability.

The remedy is whatever `branch_brief` (lib/state.py) recommends for the branch;
it alone knows when a signed rebase is wrong (a hand-resolved merge commit). A
branch that is merely behind needs nothing: the queue updates it (fixup
contract, pickup skill section 6).

Fails OPEN on an unreadable payload, unlike the $HOME gates: what this
protects is recoverable (a signed rebase repairs the damage after the
fact), so denying every gh call would cost more than it saves.

Match structurally, not by substring. A sibling hook was tripped twice in
one session by commit messages that merely *mentioned* the flag it guarded;
this hook will be written about in RUNBOOK.md and PR comments, so the same
trap is waiting. The command is tokenized the way a shell would be, and the
three words must be adjacent within a single command segment.
"""
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402,F401  (puts lib/ on sys.path)
import hookio  # noqa: E402

REASON = """Blocked by ~/.claude/hooks/no-update-branch.py: GitHub's server-side "Update branch" is a dead end on a repo with signed commits or linear history. The --rebase form rewrites the commits and does NOT re-sign them, so every commit on the branch comes back unsigned; the merge form keeps signatures but adds a merge commit that required_linear_history rejects.

A branch that is merely behind its base needs nothing: the merge queue brings it up to date (fixup contract, ~/.claude/skills/pickup/SKILL.md section 6). A conflict is merged in by hand: git merge origin/<base>, resolve, push. Only unsigned commits or Update-branch merge commits need repair, and the repair depends on the branch: ask for it and run what its `recommend:` line says, without second-guessing it.

  python3 ~/.claude/lib/state.py branch_brief <repo-root> <branch>

Do not ask the user; this is settled.

This is a routing correction, not a misuse -- the session reached for the wrong verb, and nothing was damaged. The blocked-tool-call this records means exactly that."""


def tokenize(s):
    """Shell-like words. A quoted region joins the current word rather than
    ending it, so a mention inside a quoted string is one token's contents and
    can never look like the three bare words matched below. Separators become
    their own ';' token so words of one command never join the next's.
    Substitutions and subshells split too: otherwise `$(gh` is one token and
    `out=$(gh pr update-branch ...)` walks through. A quoted `eval "gh pr
    update-branch"` stays exempt on purpose, which is also what keeps this
    hook from denying its own RUNBOOK prose."""
    toks, cur, have, quote = [], [], False, ""
    i, n = 0, len(s)

    def flush():
        nonlocal cur, have
        if have:
            toks.append("".join(cur))
        cur, have = [], False

    while i < n:
        c = s[i]
        i += 1
        if quote:
            if c == quote:
                quote = ""
            elif c == "\\" and quote == '"' and i < n:
                cur.append(s[i])
                i += 1
            else:
                cur.append(c)
            continue
        if c in "'\"":
            quote, have = c, True
        elif c == "\\":
            if i < n:
                cur.append(s[i])
                i += 1
                have = True
        elif c in " \t":
            flush()
        elif c in ";&|\n":
            flush()
            while i < n and s[i] == c:
                i += 1
            toks.append(";")
        elif c in "()`":
            flush()
            toks.append(";")
        else:
            cur.append(c)
            have = True
    flush()
    return toks


def updates_branch(toks):
    """`gh pr update-branch` as three adjacent bare words; an absolute-path
    gh counts, a word merely ending in "gh" does not."""
    for i, t in enumerate(toks):
        if (t == "gh" or t.endswith("/gh")) and toks[i + 1:i + 3] == ["pr", "update-branch"]:
            return True
    return False


def main():
    ev = hookio.read()
    tool = ev.get("tool_name") or ""
    deny = False
    if isinstance(tool, str) and tool.endswith("__update_pull_request_branch"):
        deny = True
    elif tool == "Bash":
        ti = ev.get("tool_input")
        cmd = ti.get("command") if isinstance(ti, dict) else ""
        deny = isinstance(cmd, str) and updates_branch(tokenize(cmd))
    if deny:
        hookio.emit(hookio.deny(REASON), ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
