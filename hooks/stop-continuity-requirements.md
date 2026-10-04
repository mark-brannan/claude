# stop-continuity.sh: requirements

What the Stop hook does: its thirteen jobs as `stop-continuity.sh` does
them, and the session's item, which the one-entry-point curia's questions
14 to 16 set. The acceptance cases at the end are the test list: the Python
rewrite (question 17) is generated from this file and tested against them.
Where the doc runs ahead of the code, the case says so.

Two sources. Sections 1 to 13 describe the bash as it runs today and are
checkable against it and its tests; a line there is a fact, not a rule,
until the Python replaces the bash. Section 14 is prescriptive and cites
the curia; a line there holds only while its ruling does, and a
disagreement goes back to the curia, never to this file. Where the two
disagree, the table records a `no` row naming the item that closes the
gap, and neither side is edited to match the other here. Once the Python
lands and the bash is retired, this file is the source and the code
derives from it. Job numbers are the audit's, not the run order; the order
is under Interfaces.

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

## Interfaces

- Run order: 1, 2, 3, 4, 5, 7, 6, 8, 9, 10, 11, 12, 13 (the verdict is
  taken after the salvage).
- Environment read: `CLAUDE_STOP_COMMIT` (`off` skips the salvage),
  `CLAUDE_CODE_REMOTE` (`true` is the cloud), `CLAUDE_STATE_REPO`, `CI` and
  `GITHUB_ACTIONS` (refuse the salvage), `GIT_AUTHOR_NAME` and
  `GIT_AUTHOR_EMAIL` (the state commit's author), `TMPDIR`,
  `STATE_LOCK_DIR`, `STATE_LOCK_STALE_SECS`, `WORK_ITEM_DIR`,
  `WORK_ITEM_BIN`.
- Files under `${TMPDIR:-/tmp}`: `claude-state-push.lock.d` (job 5),
  `claude-stop-home.<pid>` (the home line, job 6 to job 9),
  `claude-branch-home.*` (the gate's own), `claude-pickup-pr-miss.*`
  (job 9's 10-minute miss).
- Scripts called: `branch-home-gate.sh --check` prints `home:<…>` or
  `unverified:<…>`, else nothing; `claim-stamp.sh refresh|release`;
  `metrics-rollup.sh`. The transcript's fields are whatever
  `session-metrics.jq` emits, which is the contract for job 2.
- The push stamp is the literal `$SR/.git/claude-last-state-push` in the
  state repo, on purpose: a worktree's git dir would not do.
- Writes: the checkpoint and the metrics files are truncated and rewritten
  in place; the pickup item and the verdict line go through a temp file and
  a rename.

## 1. Read the Stop

Reads `transcript_path`, `session_id` and `cwd` from the event; `cwd`
defaults to the working directory. With no `jq`, no transcript, no session
id or no `session-metrics.jq`, it writes nothing. The metrics come from one
`jq -s` over the transcript; a failed parse never fails the Stop. As built,
a failed parse, empty metrics or a failed `mkdir` exits before every later
job, the state commit included; whether that should hold is open
(section 14).

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

Waits up to 90 s for the state-push lock, one pusher per `TMPDIR`
(`claude-state-push.lock.d`). The 90 s is fixed in the code. Not taken,
the hook exits: jobs 6 to 13 do not run and the checkpoint keeps its
placeholder verdict. The exit releases every lock the hook holds.

## 6. The archive verdict

One verdict per Stop, computed after the salvage (job 7) so it describes the
tree the salvage leaves. `archivable` only when every condition holds;
otherwise `not archivable: ` and the reasons, comma-joined, in this order:

1. `worktree dirty`
2. `<n> commit(s) unpushed`: counted as `HEAD --not --remotes=origin`,
   `origin/wip/*` excluded. With no upstream and commits ahead:
   `` `<branch>` has no upstream (never pushed) ``, or `detached HEAD, no
   upstream to compare against`. A count that fails: `could not count
   unpushed commits`. No origin refs at all, or nothing ahead of any origin
   branch, is clear.
3. `` no PR and no pointer for `<branch>` ``, by `branch-home-gate.sh
   --check`; `branch home unverified (<detail>)` when the gate cannot say
4. `session live`: another session's fresh claim stamp on the branch's card;
   the session's own never counts
5. the caller's own: `not a git repo`; `state repo not committed (git
   filter <f> unconfigured)`; `state-repo commit failed`; and in the cloud
   only, `state-repo push failed`

The strings are the interface: `verdict_explain` in `lib-state.sh` matches
them to explain the verdict, so a rewrite emits them byte for byte.

Reason 3 is asked only when 1 and 2 are clear, reason 4 only when 1 to 3
are. Could not verify is never a pass: a count git cannot make, or a home
check that cannot reach GitHub, is a reason. The home check runs once per
Stop; job 9 reuses its answer and asks again only when it printed nothing.
The verdict replaces the
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

- The commit message carries a `Co-Authored-By: Claude
  <noreply@anthropic.com>` trailer.
- A reset that fails after the commit leaves the commit on the branch; the
  checkpoint says so and names the commit.
- A fetch that fails skips the behind check.
- With no resolvable base (`origin/HEAD`, `origin/main`, `origin/master` all
  missing) the revert, shallow and stale checks are skipped.

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

A 300 s window per clone, stamped at the literal
`$SR/.git/claude-last-state-push` in the state repo, never the tracked
tree. The stamp records the attempt, not the success. A cloud session
(`CLAUDE_CODE_REMOTE=true`) whose verdict is archivable skips the window.
Two attempts, each a `pull --rebase --autostash` (a conflict is aborted,
never left) then a push, 120 s each. In the cloud a failed push becomes a
verdict reason; locally the commit is the promise.

## 14. The session's item

The session's record is one work item in `state/global/items/`, written
through `work-item`. It replaces the pickup item, the claim stamp, the
checkpoint's `## Resume` carry and the curia floor (question 16); once the
hook writes items, `pickup/` is retired (question 14). Until item 5
retires them, the hook writes the pickup file, the stamp and the floor as
well (scoping item 3).

- At its first Stop, a session that holds no claimed item mints one
  (question 15, pen). A session holding a claimed item writes onto that
  item and mints none (one id for the item's whole life, the sessions that
  touch it listed on it in order, pen, roll `20261001t064716z`; the
  claimed-item case is scoping item 3's reading, accepted at the yes).
- A later Stop of the session that writes writes onto the same item,
  never a new one; how often it writes is open (below). The hook's
  hand-off is the item's log entry (question 14, pen).
- The item is created `open`, never `ready` (pen); the hook writes no
  `ready` line on it (pencil, scoping item 3).
- The hook never claims the item. A session that takes it up logs `ready`,
  then `claimed` (`docs/work-item-lifecycle.md`): `open` never goes
  straight to `claimed`.
- Its brief is written once, at the mint, from the prompt's first line
  (job 9's default body), and never rewritten: the hook decides nothing
  about the hand-off; its home is the session's PR,
  `home=<owner/repo#n>`, once there is one (pencil, question 13).
- The brief carries one link; the store refuses a brief without one. Which
  link, when the session has no PR yet, is open (below).
- A second mint of the same id is refused by the store and never retried
  under a fresh id (pen).
- The write lands before job 12, so the same Stop commits it.
- A refused or failed item write never stops the later jobs.
- Orphaned minted items are the sweep's to retire, on the same path as old
  cards (question 15).

### Open, unruled

Neither the code nor a ruling settles these; the spec holds no requirement
on them.

- What a failed transcript parse (job 1) should still do. Today it skips
  every later job, the state commit included.
- Which link a minted item carries before the session has a PR. The store
  accepts an http link, `owner/repo#n`, or a markdown link into `log/`, so
  the session's checkpoint is available at the first Stop; item 3 takes a
  default and names it in its PR.
- How often the hook writes onto the item. Stop fires every turn.
- Which item a session writes after it mints one and then claims another.
- The owner of a minted item.
- Whether a session that crosses midnight UTC should keep one checkpoint.
  Its name carries the date, so today it writes two.
- Whether a lock-wait failure (job 5) should say more than the placeholder
  verdict.
- What a kill at 290 s should leave. The per-job timeouts (90 s lock, 60 s
  fetches, 30 s commits, 120 s pushes and pulls) add up past it.
- What replaces job 8's release and refresh once the store's claim holds:
  `work-item release` writes `status=ready`, which puts the item in grind's
  queue, and a claim goes stale two hours after its holder's last line,
  which ties this to how often the hook writes.
- What the hook needs from the environment to call `work-item`: the session
  id reaches `work-item` from the environment, the hook has it only in the
  event.

## Acceptance cases

Evidence: **test**, an assertion in `stop-continuity.test.sh`; **code**, the
code does it and no test asserts it; **item N** or a card id, not built, and
what builds it. Ids are the job's number and a counter, appended, never
renumbered or reused; a retired row is struck through with a pointer. When
the Python lands the column goes: every id must then appear in a test name,
checked by a lint.

A Then may hold several assertions of one scenario, separated by `;`; a
test asserts each. A Given with `or` is two fixtures sharing the Then.

| # | Given | When | Then | Evidence |
|---|---|---|---|---|
| 0.1 | any input, including none | Stop | exit 0 | code |
| 0.2 | a Stop killed past 290 s after the checkpoint write, before job 6 | the checkpoint is read before the next Stop | its verdict line reads `the Stop hook did not finish` | code |
| 0.3 | a push lock left by a hook killed past 290 s | the next Stop | it takes the lock | code |
| 1.1 | an event with no `transcript_path`, or one that does not exist | Stop | nothing written under the state dir | code |
| 1.2 | an event with no `session_id` | Stop | nothing written | code |
| 1.3 | a transcript `jq -s` cannot parse | Stop | exit 0 | code |
| 2.1 | a session with commits since its start | Stop | `sessions/<id>.json` has `commits` = `git rev-list --count --since=<start> HEAD` | code |
| 2.2 | a transcript whose text contains `git commit` but no commit was made | Stop | `commits` is 0 | code |
| 2.3 | an earlier Stop wrote `decisions/<id>.jsonl` | Stop again | the file holds this transcript's events only, not the earlier ones appended | code |
| 3.1 | `metrics/live/<id>.json` exists | Stop | it is gone | code |
| 3.2 | `metrics-live.sh` holds the session's lock | Stop | the Stop completes inside 10 s and writes the checkpoint | test |
| 4.1 | a fresh session | Stop | the checkpoint's `**Verdict:**` line is the verdict | test |
| 4.2 | a checkpoint with a `## Resume` block and a `- consumed:` line | Stop | both survive verbatim, and the section after the block is still there | test |
| 5.1 | the state-push lock held past 90 s | Stop | exit 0; no salvage, no state commit; verdict line reads `the Stop hook did not finish` | code |
| 5.2 | `flock` missing | Stop | the state repo is still committed and pushed | test |
| 6.1 | clean, pushed, an open PR, no foreign stamp | Stop | `archivable`, in the checkpoint and in `sessions/<id>.json` with `verdict_at` | test |
| 6.2 | a dirty tree with unpushed commits | Stop | reasons name dirty, then unpushed, in that order | test |
| 6.3 | no PR and no pointer | Stop | `no PR and no pointer for <branch>` | test |
| 6.4 | a branch never pushed, commits ahead | Stop | never pushed is a reason | test |
| 6.5 | a branch with no upstream and no commits ahead of any origin branch | Stop | not a reason | test |
| 6.6 | a detached `HEAD` whose commit lives on no remote branch | Stop | a reason; the same `HEAD` on a remote branch is not | test |
| 6.7 | `@{u}` is `main` and the commits are on a pushed `stack/` branch | Stop | not unpushed | test |
| 6.8 | the home check cannot reach GitHub | Stop | not archivable, `branch home unverified` | test |
| 6.9 | `cwd` outside any repo | Stop | `not archivable: not a git repo` | test |
| 6.10 | a clean, pushed branch | Stop | `branch-home-gate.sh --check` runs once | test |
| 6.11 | another session's fresh claim stamp on the branch's card | Stop | not archivable; the session's own stamp alone is not a reason | code |
| 7.1 | a dirty Claude-made worktree, level with origin | Stop | a signed commit on `wip/<id>`, pushed; branch `HEAD` and `@{u}` unchanged; files still dirty | test |
| 7.2 | 7.1 after a first salvage | Stop again | `wip/<id>` moves; the branch is untouched | test |
| 7.3 | no signing key | Stop | `refused: commit failed`; files left as they were | test |
| 7.4 | `GITHUB_ACTIONS` or `CI` set | Stop | `refused: running under CI` | test |
| 7.5 | a branch-changed file put back to base's bytes, with or without another real edit | Stop | refused as a revert, the file named | test |
| 7.6 | a branch-changed file edited to neither version | Stop | salvaged | test |
| 7.7 | an untracked stale leftover (7 in the job) | Stop | refused, the path named | test |
| 7.8 | a new untracked file, or a path the branch deleted and recreated with new bytes | Stop | salvaged | test |
| 7.9 | the branch behind `origin/<branch>` | Stop | refused, behind count named | test |
| 7.10 | the checkout is `$HOME` | Stop | refused, `yadm gate` | code |
| 7.11 | on `main` or `master`, or detached | Stop | refused, uncommitted work left in place | code |
| 7.12 | not under `.claude/worktrees/` and not a `claude/` branch | Stop | refused, `does not look Claude-made` | code |
| 7.13 | no `origin` remote | Stop | refused, `no origin remote` | code |
| 7.14 | a shallow clone that cannot unshallow | Stop | refused, `repo is shallow` | code |
| 7.15 | `CLAUDE_STOP_COMMIT=off`, a dirty tree | Stop | no commit, no `## Stop-commit` note | code |
| 8.1 | archivable, the session holds a stamp | Stop | `claim-stamp.sh release` for this session | code |
| 8.2 | not archivable, the session holds a stamp | Stop | `claim-stamp.sh refresh` for this session | code |
| 9.1 | a fresh session | Stop | one `pickup/<start-minute>-<id8>.md`, `status: open`, body the last prompt | test |
| 9.2 | a body a model wrote | Stop again | the body survives | test |
| 9.3 | an `until:` header; or none | Stop again | carried; or no `until:` line | test |
| 9.4 | `status: done`, the prompt unchanged | Stop again | still `done` | test |
| 9.5 | the hook's own body, a new prompt | Stop again | body is the new prompt, `status: open` | test |
| 9.6 | `pr: none`, nothing ahead, a lookup missed under 10 minutes ago | Stop | no `gh` call | code |
| 10.1 | a prompt naming `confer <id>`, its digest exists | Stop | one floor block closing `## Where this stands`; text above unchanged | test |
| 10.2 | 10.1 | Stop again | one block, never two | test |
| 10.3 | 10.1 | Stop again | the digest is byte-identical to after the first Stop | card 1790975613f676e0a7 |
| 10.4 | a tool call only read the digest | Stop | digest untouched | test |
| 10.5 | only `thread.md` exists; or neither | Stop | floor on `thread.md`; or no write | test |
| 11.1 | `.gitattributes` declares `filter=x`, `filter.x.clean` unset | Stop | no state commit; checkpoint says `NOT COMMITTED`; verdict names the filter | code |
| 12.1 | the clone has `user.signingkey`; or none | Stop | the state commit is signed; or unsigned | test |
| 12.2 | a new file under `state/global/items/` | Stop | it is in the state commit | test |
| 12.3 | nothing changed under `state/` | Stop | no commit, no push | code |
| 12.4 | signing fails | Stop | no unsigned commit; state staged; verdict `state-repo commit failed` | code |
| 13.1 | a push under 300 s ago from this clone | Stop | committed, not pushed | test |
| 13.2 | 13.1, the push stamp brought in by a pull | Stop | the window still holds | test |
| 13.3 | cloud, archivable, a push under 300 s ago | Stop | pushed | code |
| 13.4 | a pull that conflicts | Stop | rebase aborted, no rebase left in progress | test |
| 13.5 | cloud, the push fails | Stop | `not archivable: state-repo push failed` | test |
| 13.6 | local, the push fails | Stop | verdict unchanged; the next Stop in the window does not retry | test |
| 14.1 | a session with no item | first Stop | one new item; its first log line `status=open` from this session | test |
| 14.2 | 14.1 | a later Stop that writes | it writes the same item; no second item is minted | test |
| 14.3 | a session that claimed an item with `work-item claim` | Stop | that item gets this session's line; nothing minted | test |
| 14.4 | a minted item | any Stop | no `status=ready` line from the hook | test |
| 14.5 | the session's branch has an open PR | Stop | the item carries `home=<owner/repo#n>` | test |
| 14.6 | a fresh session | first Stop | the minted item's brief is the prompt's first line; later Stops leave it unchanged | test |
| 14.7 | the store refuses the write, or `work-item` crashes | Stop | the state commit is made; exit 0 | test |
| 14.8 | a fresh session | first Stop | the item is in that Stop's state commit | test |
| 14.9 | the hook writes items and the duplicates are retired | Stop | no `pickup/` file, no claim-stamp call, no floor block, no `## Resume` carry | item 5 |
