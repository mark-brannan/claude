# stop-continuity.sh: requirements

What the Stop hook does: its thirteen jobs as `stop-continuity.sh` does
them, and the session's item, which the one-entry-point curia's questions
14 to 16 set. The acceptance cases at the end are the test list: the Python
rewrite (question 17) is generated from this file and tested against them.
Where the doc runs ahead of the code, the case says so.

## The whole hook

- Runs on every Stop and needs nothing from the conversation: a session
  that ends any way at all is recorded.
- Always exits 0. A failure in one job never fails the Stop.
- `stop-sequence.py` runs it first, then `metrics-live.sh`'s readout, which
  reads this hook's verdict back. It gets 290 s and is killed as a process
  group (`SIGKILL`) past that: no trap runs, and the next Stop reclaims any
  lock the dead hook held, its pid gone.
- Every file it writes under the state dir is the session's own, except
  `metrics-rollup.sh`'s untracked rollup (job 3), a curia digest (job 10)
  and the state commit (jobs 12, 13). The metrics and the checkpoint are
  sharded by `state_shard_path` (`lib-state.sh`). Two parallel sessions
  never write the same session file.

## 1. Read the Stop

Reads `transcript_path`, `session_id` and `cwd` from the event; `cwd`
defaults to the working directory. With no `jq`, no transcript, no session
id or no `session-metrics.jq`, it writes nothing. The metrics come from one
`jq -s` over the transcript; a failed parse never fails the Stop.

## 2. Write the metrics

Four files per session under `metrics/`, each rewritten whole on every Stop:
`sessions/<id>.json` (the session object plus `commits`), and
`decisions/`, `friction/`, `blocked/` as `<id>.jsonl`, one event per line.
`commits` comes from `git rev-list` since the session's start, never from
the transcript.

## 3. Drop the live snapshot

Deletes `metrics/live/<id>.json` under the session's lock, the one
`metrics-live.sh` takes. A lock it cannot take still gets the delete. Then
runs `metrics-rollup.sh`; a failure there is ignored.

## 4. Rewrite the checkpoint

`log/auto/<date>-<repo>-<id8>.md`, rewritten whole on every Stop under the
same lock. In order: the heading, the verdict line (written first as
`not archivable: the Stop hook did not finish`, replaced by job 6), the
session's facts and decision rate, the `## Resume` block, the commits since
the start (20 at most), the uncommitted files (40 at most), the unpushed
count, the branch-home gate's lines and the decisions pushed to the user.

The `## Resume` block, from its heading to the next `## `, is carried
verbatim across the rewrite, its `- consumed:` marker included. The
session's item replaces that carry (question 16); the rest of the file stays.

## 5. Take the push lock

Waits up to 90 s for the state-push lock, one pusher per clone. Not taken,
the hook exits: jobs 6 to 13 do not run and the checkpoint keeps its
placeholder verdict. The exit releases every lock the hook holds.

## 6. The archive verdict

One verdict per Stop, computed after the salvage (job 7) so it describes the
tree the salvage leaves. `archivable` only when every condition holds;
otherwise `not archivable: ` and the reasons, comma-joined, in this order:

1. worktree dirty
2. commits unpushed: counted as `HEAD --not --remotes=origin`, `origin/wip/*`
   excluded; no upstream reads as never pushed
3. no home: no open PR and no pointer card or issue, by
   `branch-home-gate.sh --check`
4. session live: another session's fresh claim stamp on the branch's card;
   the session's own never counts. The store's claim replaces the stamp
   (question 16)
5. the caller's own: `not a git repo`; `state repo not committed (git
   filter <f> unconfigured)`; `state-repo commit failed`; and in the cloud
   only, `state-repo push failed`

Reason 3 is asked only when 1 and 2 are clear, reason 4 only when 1 to 3
are. Could not verify is never a pass: a count git cannot make, or a home
check that cannot reach GitHub, is a reason. The home check runs at most
once per Stop, job 9 reusing its answer. The verdict replaces the
checkpoint's verdict line, never adds a second, and goes into the session
record as `verdict` and `verdict_at` (epoch seconds).

## 7. Salvage the work repo

A dirty work repo is committed to this session's own `wip/<session-id>` ref
and that ref is pushed; the session's branch never keeps or pushes the commit.

Silent, with nothing done, when: not in a git repo; the work repo is the
state repo; `CLAUDE_STOP_COMMIT=off`; nothing uncommitted. Otherwise the
branch is re-read, then the salvage is refused, the reason under
`## Stop-commit` in the checkpoint and the files left on disk, when:

- the checkout is `$HOME`
- the branch is `main`, `master`, a detached `HEAD` or unnamed
- neither the path is under `.claude/worktrees/` nor the branch starts
  `claude/`
- there is no `origin` remote
- `GITHUB_ACTIONS` or `CI` is set; checked before any fetch
- after a fetch, the branch is behind `origin/<branch>`
- a tracked file the branch changed now matches base (`origin/HEAD`, else
  `origin/main`, else `origin/master`) byte for byte: a revert; files named
- the repo is shallow and cannot be unshallowed
- an untracked path was tracked in `HEAD`'s history, is absent from base,
  and matches its last tracked content: a stale leftover; paths named

The commit: `git add -A`; signing forced on,
key or not; 30 s; message `wip: session <id8> at Stop (<date>)`. A failed
commit resets the index and is a refusal. The commit is written to
`refs/heads/wip/<session-id>`, the branch is reset (mixed) to where it was
whatever else happened, and only that ref is force-pushed, 120 s. The
checkpoint says salvaged and pushed, or salvaged with the push failed.

## 8. Refresh or release the claim stamp

With a work repo: archivable releases the session's stamp on the branch's
card; anything else refreshes it. Failures are ignored, and a session that
never claimed pays no network call. The store's claim replaces the stamp
(question 16).

## 9. Write the pickup item

`pickup/<start-minute>-<id8>.md`, one per session, found again by every
Stop. A header (`status`, `updated`, `session`, `model`, `branch`, `pr`,
`where`, `until` when present, `prompt`), `---`, then a body.

- The body becomes the last prompt only when empty or still the hook's last
  write; a body a model wrote survives every rewrite.
- `status` is `open` on the first Stop and whenever the prompt changes;
  otherwise carried.
- `until` is carried, never written.
- `pr` is looked up only while `none` and once nothing is ahead of origin;
  it reuses the verdict's home check, and a miss is not asked again for
  10 minutes.

The session's item replaces this file (questions 14, 16).

## 10. Stamp the curia floor

For each curia the user named in a prompt (a `state/global/curia/<id>`
path, `curia <id>` with or without the slash, or `confer <id>`), never one a
tool call only read: a floor block between its markers (last touched,
session, model, branch, PR) closes `## Where this stands` in `digest.md`,
else `thread.md`, else nothing. With no heading after that section, or no
such section, the block ends the file. The old block is dropped; text
above it and `roll.md` are never touched. The session's item replaces the
floor (question 16).

## 11. Refuse an unconfigured filter

When `.gitattributes` names a `filter=` with no `filter.<f>.clean` in this
clone, the state repo is not committed: the checkpoint says why and the
verdict gets the reason.

## 12. Commit the state repo

Not a git repo: nothing committed. Otherwise `git add state/`, the board's
`items/` included; nothing staged, the hook exits with no commit and no
push. The commit: author `Claude <noreply@anthropic.com>` unless the
environment sets one, signed when the clone has `user.signingkey`, 30 s,
message `State: <repo> session <id8> (<date>)`. A failed commit is never
retried unsigned: the state stays staged for the next Stop and the verdict
says why.

## 13. Push the state repo

### Push rate

The state-repo push to the remote must not fire on every Stop hook.
Throttle, batch, or debounce in some form. The local commit is not
affected since it stays per-Stop, so nothing is lost.

The window and the force-through conditions are tuning and can change
freely. Removing the throttle entirely cannot.

Note that the GitHub recommended limit (6 pushes per minute per repo) must
account for all of our pushes combined and we should strive to stay far
below this limit.
https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits

### As built

A 300 s window per clone, stamped in the clone's git dir, never the tracked
tree. The stamp records the attempt, not the success. A cloud session
(`CLAUDE_CODE_REMOTE=true`) whose verdict is archivable skips the window.
Two attempts, each a `pull --rebase --autostash` (a conflict is aborted,
never left) then a push, 120 s each. In the cloud a failed push becomes a
verdict reason; locally the commit is the promise.

## 14. The session's item

The session's record is one work item in `state/global/items/`, written
through `work-item`. It replaces the pickup item, the claim stamp, the
checkpoint's `## Resume` carry and the curia floor (question 16); once the
hook writes items, `pickup/` is retired (question 14).

- At its first Stop, a session that holds no claimed item mints one
  (question 15, pen). A session holding a claimed item writes onto that
  item and mints none (one id per life, pen).
- A later Stop of the session that writes writes onto the same item,
  never a new one; how often it writes is open (below). The hook's
  hand-off is the item's log entry (question 14, pen).
- The item is created `open`, never `ready` (pen); the hook writes no
  `ready` line on it (pencil, scoping item 3).
- Its brief is today's first hand-off, the last prompt's first line
  (job 9's default body); its home is the session's PR,
  `home=<owner/repo#n>`, once there is one (pencil, question 13).
- A second mint of the same id is refused by the store and never retried
  under a fresh id (pen).
- The write lands before job 12, so the same Stop commits it.
- A refused or failed item write never stops the later jobs.

### Open, unruled

Neither the code nor a ruling settles these; the spec holds no requirement
on them.

- What a failed transcript parse (job 1) should still do. Today it skips
  every later job, the state commit included.
- Which link a minted item carries. `work-item create` refuses a brief with
  no link, and a session with no PR at its first Stop has none, so row 14.1
  cannot pass as the store stands.
- How often the hook writes onto the item. Stop fires every turn.
- Which item a session writes after it mints one and then claims another.
- The owner of a minted item.
- Whether a session that crosses midnight UTC should keep one checkpoint.
  Its name carries the date, so today it writes two.
- Whether a lock-wait failure (job 5) should say more than the placeholder
  verdict.
- What a kill at 290 s should leave. The per-job timeouts (90 s lock, 60 s
  fetches, 30 s commits, 120 s pushes and pulls) add up past it.

## Acceptance cases

Met: **tested** (in `stop-continuity.test.sh`), **untested** (the code does
it, no test), **no** (the code does not; the scoping item that meets it, or
the card that tracks the bug).

| # | Given | When | Then | Met |
|---|---|---|---|---|
| 0.1 | any input, including none | Stop | exit 0 | untested |
| 0.2 | a Stop killed past 290 s after the checkpoint write, before job 6 | the next Stop | that checkpoint read `the Stop hook did not finish`; the next Stop takes any push lock the dead hook held | untested |
| 1.1 | an event with no `transcript_path`, or one that does not exist | Stop | nothing written under the state dir | untested |
| 1.2 | an event with no `session_id` | Stop | nothing written | untested |
| 1.3 | a transcript `jq -s` cannot parse | Stop | exit 0 | untested |
| 2.1 | a session with commits since its start | Stop | `sessions/<id>.json` has `commits` = `git rev-list --count --since=<start> HEAD` | untested |
| 2.2 | a transcript whose text contains `git commit` but no commit was made | Stop | `commits` is 0 | untested |
| 2.3 | an earlier Stop wrote `decisions/<id>.jsonl` | Stop again | the file holds this transcript's events only, not the earlier ones appended | untested |
| 3.1 | `metrics/live/<id>.json` exists | Stop | it is gone | untested |
| 3.2 | `metrics-live.sh` holds the session's lock | Stop | the Stop completes inside 10 s and writes the checkpoint | tested |
| 4.1 | a fresh session | Stop | the checkpoint's `**Verdict:**` line is the verdict | tested |
| 4.2 | a checkpoint with a `## Resume` block and a `- consumed:` line | Stop | both survive verbatim, and the section after the block is still there | tested |
| 5.1 | the state-push lock held past 90 s | Stop | exit 0; no salvage, no state commit; verdict line reads `the Stop hook did not finish` | untested |
| 5.2 | `flock` missing | Stop | the state repo is still committed and pushed | tested |
| 6.1 | clean, pushed, an open PR, no foreign stamp | Stop | `archivable`, in the checkpoint and in `sessions/<id>.json` with `verdict_at` | tested |
| 6.2 | a dirty tree with unpushed commits | Stop | reasons name dirty, then unpushed, in that order | tested |
| 6.3 | no PR and no pointer | Stop | `no PR and no pointer for <branch>` | tested |
| 6.4 | a branch never pushed, commits ahead | Stop | never pushed is a reason | tested |
| 6.5 | a branch with no upstream and no commits ahead of main | Stop | not a reason | tested |
| 6.6 | a detached `HEAD` whose commit lives on no remote branch | Stop | a reason; the same `HEAD` on a remote branch is not | tested |
| 6.7 | `@{u}` is `main` and the commits are on a pushed `stack/` branch | Stop | not unpushed | tested |
| 6.8 | the home check cannot reach GitHub | Stop | not archivable, `branch home unverified` | tested |
| 6.9 | `cwd` outside any repo | Stop | `not archivable: not a git repo` | tested |
| 6.10 | a clean, pushed branch | Stop | `branch-home-gate.sh --check` runs once | tested |
| 6.11 | another session's fresh claim stamp on the branch's card | Stop | not archivable; the session's own stamp alone is not a reason | untested |
| 7.1 | a dirty Claude-made worktree, level with origin | Stop | a signed commit on `wip/<id>`, pushed; branch `HEAD` and `@{u}` unchanged; files still dirty | tested |
| 7.2 | 7.1 after a first salvage | Stop again | `wip/<id>` moves; the branch is untouched | tested |
| 7.3 | no signing key | Stop | `refused: commit failed`; files left as they were | tested |
| 7.4 | `GITHUB_ACTIONS` or `CI` set | Stop | `refused: running under CI` | tested |
| 7.5 | a branch-changed file put back to base's bytes, with or without another real edit | Stop | refused as a revert, the file named | tested |
| 7.6 | a branch-changed file edited to neither version | Stop | salvaged | tested |
| 7.7 | an untracked stale leftover (7 in the job) | Stop | refused, the path named | tested |
| 7.8 | a new untracked file, or a path the branch deleted and recreated with new bytes | Stop | salvaged | tested |
| 7.9 | the branch behind `origin/<branch>` | Stop | refused, behind count named | tested |
| 7.10 | the checkout is `$HOME` | Stop | refused, `yadm gate` | untested |
| 7.11 | on `main` or `master`, or detached | Stop | refused, uncommitted work left in place | untested |
| 7.12 | not under `.claude/worktrees/` and not a `claude/` branch | Stop | refused, `does not look Claude-made` | untested |
| 7.13 | no `origin` remote | Stop | refused, `no origin remote` | untested |
| 7.14 | a shallow clone that cannot unshallow | Stop | refused, `repo is shallow` | untested |
| 7.15 | `CLAUDE_STOP_COMMIT=off`, a dirty tree | Stop | no commit, no `## Stop-commit` note | untested |
| 8.1 | archivable, the session holds a stamp | Stop | `claim-stamp.sh release` for this session | untested |
| 8.2 | not archivable, the session holds a stamp | Stop | `claim-stamp.sh refresh` for this session | untested |
| 9.1 | a fresh session | Stop | one `pickup/<start-minute>-<id8>.md`, `status: open`, body the last prompt | tested |
| 9.2 | a body a model wrote | Stop again | the body survives | tested |
| 9.3 | an `until:` header; or none | Stop again | carried; or no `until:` line | tested |
| 9.4 | `status: done`, the prompt unchanged | Stop again | still `done` | tested |
| 9.5 | the hook's own body, a new prompt | Stop again | body is the new prompt, `status: open` | tested |
| 9.6 | `pr: none`, nothing ahead, a lookup missed under 10 minutes ago | Stop | no `gh` call | untested |
| 10.1 | a prompt naming `confer <id>`, its digest exists | Stop | one floor block closing `## Where this stands`; text above unchanged | tested |
| 10.2 | 10.1 | Stop again | one block, never two | tested |
| 10.3 | 10.1 | Stop again | the digest is byte-identical to after the first Stop | no (blank line grows; card 1790975613f676e0a7, item 5 retires the floor) |
| 10.4 | a tool call only read the digest | Stop | digest untouched | tested |
| 10.5 | only `thread.md` exists; or neither | Stop | floor on `thread.md`; or no write | tested |
| 11.1 | `.gitattributes` declares `filter=x`, `filter.x.clean` unset | Stop | no state commit; checkpoint says `NOT COMMITTED`; verdict names the filter | untested |
| 12.1 | the clone has `user.signingkey`; or none | Stop | the state commit is signed; or unsigned | tested |
| 12.2 | a new file under `state/global/items/` | Stop | it is in the state commit | tested |
| 12.3 | nothing changed under `state/` | Stop | no commit, no push | untested |
| 12.4 | signing fails | Stop | no unsigned commit; state staged; verdict `state-repo commit failed` | untested |
| 13.1 | a push under 300 s ago from this clone | Stop | committed, not pushed | tested |
| 13.2 | 13.1, the push stamp brought in by a pull | Stop | the window still holds | tested |
| 13.3 | cloud, archivable, a push under 300 s ago | Stop | pushed | untested |
| 13.4 | a pull that conflicts | Stop | rebase aborted, no rebase left in progress | tested |
| 13.5 | cloud, the push fails | Stop | `not archivable: state-repo push failed` | tested |
| 13.6 | local, the push fails | Stop | verdict unchanged; the next Stop in the window does not retry | tested |
| 14.1 | a session with no item | first Stop | one new item; its first log line `status=open` from this session | no (item 3) |
| 14.2 | 14.1 | a later Stop that writes | it writes the same item; no second item is minted | no (item 3) |
| 14.3 | a session that claimed an item with `work-item claim` | Stop | that item gets this session's line; nothing minted | no (item 3) |
| 14.4 | a minted item | any Stop | no `status=ready` line from the hook | no (item 3) |
| 14.5 | the session's branch has an open PR | Stop | the item carries `home=<owner/repo#n>` | no (item 3) |
| 14.6 | a fresh session | first Stop | the minted item's brief is the last prompt's first line | no (item 3) |
| 14.7 | the store refuses the write, or `work-item` crashes | Stop | jobs 12 and 13 still run; exit 0 | no (item 3) |
| 14.8 | a fresh session | first Stop | the item is in that Stop's state commit | no (item 3) |
| 14.9 | the hook writes items and the duplicates are retired | Stop | no `pickup/` file, no claim-stamp call, no floor block, no `## Resume` carry | no (item 5) |
