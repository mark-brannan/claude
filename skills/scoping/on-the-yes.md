## 6. On the yes

Re-run the `take` line first; a refusal now stops the filing, and a
`read moved:` line means the record moved since the proposal. Then file
the batch exactly as proposed, cards and the issues the proposal showed:

- the parent first, a card owned `agent` whose brief is the driver brief
  below, with links to the target and the proposal, written
  to the item store with
  `~/.claude/bin/work-item create --id "$(~/.claude/bin/card-id new)" --owner agent [--repo <r>] --brief - "$title"`
  (the card text on stdin; it prints the new id; `$title` is read from a
  quoted here-doc, as `/sweep` quotes a value, so a `'` in a title is safe),
  then `~/.claude/bin/work-item log <parent-id> status=ready`; `ready` because `/pickup` finds an agent
  item only when it is ready or claimed (`claude_cards`, lib/state.py);
  and `~/.claude/bin/work-item log <parent-id> lane=autonomous`: the lane
  lives on the parent and its children inherit it (2026-10-22), so `/pickup`
  lets the driver label its PRs; and
  `~/.claude/bin/work-item log <parent-id> driver=<mode>`: `workflow`
  unless the user typed `--subagents` in this run, then `subagents`;
- then one child per yes'd item, worded as `/card-write` words one, its
  estimate in the card text, by the same line with
  `--parent <parent-id> [--model <m>] [--effort <e>]`, plus `--home <owner/repo#n>`
  for a child that plans an issue, so the create refuses a home another open card
  already carries, then
  `~/.claude/bin/work-item log <id> status=ready` so it is claimable;
  a child the plan marks gated gets `~/.claude/bin/work-item log <id> lane=gated`,
  an exception, never the reverse: no gated parent with autonomous children;
- an item proposed as an issue (§4.4) is filed as the shown draft, the
  sub-issue first and then its child card with `home=`; a tick is not a
  yes to issue text the user has not seen (2026-10-10): show the draft
  and ask before filing. The proposal says how many issues it would
  file, and the user's yes covers that number (2026-10-22; before it,
  at most one a session, 2026-10-01); the issue guards hold the line
  beyond that;
- an item vetoed, or held on a new word (§4.5), is not filed, and the
  proposal says so.

The parent is the batch, not a session's work: the driver below claims it
and no child's session marks it done. An item that rests on pencil says which, in
the record's words, on its card. Record what was filed in the proposal file
(the parent and each child by its printed id), then:

```bash
~/.claude/bin/scoping-lock release <lock-folder> ${CLAUDE_SESSION_ID}
```

A run that ends without a yes releases the same way. A dead session's lock
lapses at 25 minutes like any other.

**The driver brief.** The driver is one fresh session that grinds the
batch through workers. Its prompt is the parent's brief, written into the
parent card on filing: the parent's id, the order, the review points, who
merges, the exits (park the child on a card for the agora, or pull the
andon cord), and the walk it hands back. Each child's card carries its
worker model, effort and estimate; the brief repeats none of them. Never a
list of prompts for the user to paste one at a time. The driver only
dispatches, and relays to a successor at about 100k context (`/pickup`, the
batch parent); the brief says so. The brief holds, from
the rulings to date:

- **The plan's order.** Serial or parallel is scoping's call, made in
  the proposal before anything launches (§4: dependencies named, and why
  that order), never the driver's mid-run. Children the plan names no
  dependency between run in parallel, one worker each; a child the plan
  makes wait starts once the PR it waits on has landed on main, and is
  cut from main. No git stacks: each PR lands on main alone.
- **Estimate and actual.** Each child carries its estimate; the parent
  carries the batch's allocation, logged at filing as
  `~/.claude/bin/work-item log <parent-id> allocation=<n>usd` (a trial of
  the spend facts' shape, pencil), and the brief repeats it as dollars and
  share of the plan week, so the driver knows what the batch was set
  against. Through the batch, as each child's worker ends and again at
  the walk, the driver reports actual beside estimate in the cost table's
  form: each child's dollars, the batch's totals in dollars with their
  shares under them, plan figures read from config as in SKILL.md §4. A child
  reads `running` until its worker's Stop writes its cost. Its actual is its
  sessions' priced `cost_usd`, or `~/.claude/bin/spend --by pr` once the
  PR is in the metrics. Running over is reported, never a reason to
  stop. The walk logs the batch's actual on the parent the same way,
  `actual=<n>usd`.
- **Reviews,** after the PR opens, as the human cycle runs (2026-10-23).
  The worker builds, tests, gets the gates green, posts the PR, sees CI
  green and marks it ready. CI runs the critical review (claude[bot]) on
  the PR, and its comments are the round's review; the driver starts no
  reviewer of its own, and a head the bot skipped has had no round. A
  fresh fixer, spawned on `sonnet`, works the comments to `/pickup` §6;
  the review stays on the tier CI picks, whatever the fixer ran on. A
  round is one review and one fixer pass;
  three rounds at most. A PR past the third, or one a fixer labels
  `fixup-hard`, is parked on an agora card and the driver moves on. The
  cap (pencil, 2026-10-23) and the park (pencil, 2026-10-24) are
  short-term: what a PR past the cap should do is open, and it is never
  an andon pull.
- **Arete.** A separate action from the critical review, which is why it
  comes last: the arete check runs once, on the batch as a whole, at the
  end before the walk, as an `Explore` sub-agent that returns the brief,
  with "read every file in the read-set whole" in its prompt. The driver
  writes the brief beside the walk (below). Its findings go to the user
  with the walk, the user's to decide on and act on. It never blocks the autonomous lane's
  work; a finding the driver judges must hold something is escalated to
  the agora, parked on a card, and nothing else holds (2026-10-22). A −
  finding that is `one-way` and seen only `after`, one the item should
  not land with as it stands, always counts as one. On a harm grade at
  this final check the driver takes `merge` off the PRs not yet merged, cards
  the finding for the agora, and the walk says which PRs landed; merged PRs
  stay.
- **Maxims.** `/maxims-check` runs once per child PR (2026-10-24), each as an
  `Explore` sub-agent on `sonnet` with the same read-whole clause, at the end
  before the walk, beside the arete check, on each child PR's final head. The
  driver collects each table into the walk; none goes to a PR thread (pencil,
  2026-10-24). Measured cost, 7 backtest runs: about $0.35 each,
  72–92k peak context. One run over the whole batch is estimated (not
  measured) about 15–25% cheaper, but past ~6 PRs it goes beyond the context
  the backtest runs read whole. Rival maxims pull against each other, so a
  run is expected to find something: a run with no findings is flagged in
  the walk as suspect.
- **Who merges.** In the autonomous lane, where a PR's diff stays inside
  this brief, the driver puts `merge`, `churn-ok` and `mixed-loops-ok` on
  it once its last review round is clean, names the brief in the PR body, and
  the queue lands it on main alone. Where the repo's own instructions forbid
  naming cards, the PR body carries no reference and the brief is named on
  the card's log only. A label attempt that is refused is retried once, with
  the PR's clean review named, then the driver carries on and never hands the
  label to the user. The user's gate is the batch after the fact, with a
  revert as the undo. This replaces "only I merge"
  (2026-10-01) for the autonomous lane. The gated lane keeps the user's
  merge.
- **The walk.** What the driver hands back, kept under the batch parent:
  the driver writes it beside the proposal as `<date>-walk-<parent-id>.md`,
  the arete brief beside it as `<date>-arete-<parent-id>.md`, and logs the
  walk on the parent as `walk=<path>`. It holds each child's PR and actual,
  the batch's actual against its allocation, the arete brief and the
  maxims table, the spend table in the form above, and per batch: hours
  from `/pickup` to the last merge on main, idle hours, sessions used,
  the user's turns, and dollars per merged PR (2026-10-24).
- **The close.** With the walk logged, the driver logs each child whose PR
  merged `status=done evidence=<PR>`, and each that did not
  `~/.claude/bin/work-item log <id> status=ready note=<why>`, where it stays
  a standalone ready item. Then it logs the parent
  `status=done evidence=<walk path>; ready: <child ids>`, naming every child
  it re-readied. A batch whose parent is not done is one its driver never
  finished (2026-11-02).

**The start.** After the yes the driver starts on its own; the user
manages none of it, and pastes nothing (2026-11-06). Run, last:

```bash
~/.claude/bin/driver-start --about "<the target, in a few words>" <parent-id>
```

`--about` names what was planned (the curia, epic or repo, as the user
would say it); it becomes the session's name in every list.
It starts one background session on this box that runs
`/pickup <parent-id>`, with Remote Control on so the user can open it from
the Claude Desktop app, logs `driver_session=<id>` on the parent, and prints
how to attach. `/pickup` already takes a card id, and the parent's brief is
the whole hand-off (pencil on the how: the plan as a card, not a path
`/pickup` learns); long term the same item is what an unattended run
picks up. The run's last lines are what `driver-start` printed: the
session's name in the Desktop session list and its link. Once it has
printed `driver started:` the driver is running, whatever the exit code: a
`driver_session` it could not log is relayed as its warning, never answered
with a second start. A start that is refused, or whose `claude --bg`
failed, ends the run with its message and, in its place, the one line that
starts the driver by hand:

```
/pickup <parent-id>
```
