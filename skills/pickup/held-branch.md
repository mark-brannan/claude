# A branch another worktree holds

If git refuses because the branch is checked out in another worktree, that
worktree holds it — but a holder is not always alive. A finished sub-agent
keeps its worktree and branch; a desktop tab left open holds its branch for
hours doing nothing. Check without entering the worktree (`<name>` is the last
part of the path named). A running sub-agent has no registry file, so scan
for a process first: any pid found means **live**, whatever the verdict says,
and `~/.claude/sessions/<pid>.json` carries the session `name`:

```
for p in /proc/[0-9]*; do case $(readlink "$p/cwd" 2>/dev/null) in */<name> | */<name>/*) echo "live: pid ${p#/proc/}" ;; esac; done
```

Only when the scan finds nothing, read the verdict (grace 0 for an
interactive pickup; `branch_brief`'s `worktrees:` line gives the same) and the
stamp, read off the card by its link, since `read -C .` reads your own fork's branch:

```
python3 ~/.claude/lib/state.py liveness <holder worktree path>   # dead | live | parked | waiting
~/.claude/hooks/claim-stamp.py read <the PR or issue link the item names>
```

A stamp from another session means another machine holds it: **live**.

**Dead** or **parked** — the holder is free. Leave its worktree alone and work
on a local branch off the remote, pushing with
`git push --force-with-lease origin HEAD:<the branch>` (a plain `git push`
would create a remote branch named for the local one):

```
git checkout -B <short-name> origin/<the branch>
```

Check what the holder has not pushed, from outside its checkout:
`git -C <holder worktree> log origin/<the branch>..HEAD --oneline`. Absorb
it: cherry-pick those commits onto your own signed branch before you push,
and report it in the line below. A refused lease means someone
else pushed, possibly the holder waking up: §6's stop rule applies. A
cherry-pick that conflicts is a stop: abort it, push nothing, report.

**Live** — it is working, which narrows the work; it does not end it. Do
every step that needs no push, from the same local branch. Reply to and
resolve the threads that need no change, read the failing checks, merge the
base in locally if it conflicts and report it. Do not push. Re-check
before stopping: a holder gone idle meanwhile is parked,
and the push proceeds as above.

**Waiting** — the holder is at a permission prompt, not idle. Tell
the user at once, naming the session, and push nothing until it is answered.

The report names what was checked, never "another session":

```
Branch <branch> is held by your session "<name>" (worktree <path>).
Verdict <dead | live | parked | waiting> (<pid, or none>). Absorbed <n> unpushed commits.
```

