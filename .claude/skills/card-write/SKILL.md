---
name: card-write
description: Route an open loop to its one home — work it around, a GitHub issue, or a card on the global kanban.md board in the house format: one line, imperative, link mandatory. Use whenever a loop is found that must be captured ("card that", "add a card", "put it on the board", "file that", a unilateral call, a finding that doesn't belong in this session). Not for walking a card or issue with the user — that is /card-helper; not for pruning the board — that is /sweep.
---

# Writing a card

A card is capture, not activation: the work still waits for a pull. Write
it the moment the loop is found, while the comment link, timestamp and
exact wording still exist.

**The default owner is you.** An item exists because an agent found work: do
the work, or prove there is none and close it with the proof. Handing an item
to Solace needs a written reason, on the card.

**A migration is a triage, never a copy.** A bulk move between trackers applies
the destination's bar to every item and records the counts kept and dropped;
what cannot be restated from scratch closes rather than moves.

## Where the loop lives

One home per fact. GitHub owns work state; the board holds what has no
GitHub home. Take the first line that fits:

- **Work state** — open, merged, closed, CI, threads — lives on the PR or
  issue and nowhere else. Never write it down; `worklist` reads it live.
- **A question** → **the one-way-door test.** *Name the default and its
  undo; if there is a default, and the undo is a revert in a repo you
  control before anyone else has seen or built on the choice, take the
  default.* Record the assumption where the work lands — the PR body or the
  commit message — and carry on. The test fails two ways: no defensible
  default exists, or the undo is not a revert — published, posted to a
  public repo, pushed into others' clones, sent to a person, rotated,
  flashed, adopted by a user, or inherited by later decisions. Only then →
  a card under `## Needs ruling`. There is no `needs-ruling` label and no
  ruling issue.
- **A check** — "verify X", "confirm Y still works" — is not a loop and never
  reaches Solace. Run it now. A check that needs a future event and has a
  stated expected output goes on `## Claude's` as your own queue, unmentioned;
  one costly enough to plan is a research issue under the issue bar; one with
  no expected output is dropped.
- **The issue bar** — file an issue only when a fresh session could start
  from the body alone: a link to the evidence **and** a next action an agent
  can execute without asking. Status mirrors, vague loops, "review/merge X"
  and hand-chores are never issues. Below the bar it is a log line or nothing.
- **Public or private repo?** An issue on a public repo is a publish, and the
  undo is a support ticket. It goes public only when its text passes the
  private-terms check — `state/global/private-terms.txt` in the state repo,
  read by path, never copied — **and** a stranger could read it without
  learning a plan, a finding or a draft you would not hand them. Otherwise
  `mark-brannan/claude_prompts_scratch`; the public-issue guard refuses the
  first half anyway, the second half is yours to judge.
- **Agent-startable work** → an issue labelled `ready`. Unlabelled is
  untriaged, and only ever a count.
- **Blocked** → label `blocked`, plus a body line `Blocked by owner/repo#N`.
  For a third-party wait with no issue to point at,
  `Blocked by <party> until <YYYY-MM-DD>` — reconcile flips it to `ready` on
  that date unprompted, so write the date the wait is expected to end, not a
  hope.
- **Deferred to after 1.0** → the `1.0` milestone.
- **A launchable session** — prompt written, model and effort sized → the
  epic file's session list; a `ready` issue when no epic owns it.
- **Half-done agent work** → the log and the hand-off prompt, as bare links
  with no state adjectives. A pushed branch has a PR or is a finding.
- **Click work only Solace can do** → a card under `## Solace's`, and only
  when both proofs below are on the line. "Needs a credential" is not a
  reason unless the credential cannot be given to an agent.
- **An agent rabbit-trail** not worth an issue, or too private for one →
  a card under `## Claude's`.

## The board

There is one board: `~/claude_prompts_scratch/state/global/kanban.md`. It is
private, so boats, hosts and services may appear on it; nothing else may
carry a board. "Project" means the `project-<name>` GitHub topic that
`worklist` resolves — it spans repos, it is not a repo.

Three sections, in this order:

- `## Needs ruling` — decisions that failed the one-way-door test. Cards
  are grouped under `### <project>` subheadings, `### global` when no
  project owns it; `###` headings appear nowhere else on the board.
- `## Solace's` — click work an agent cannot do, or that Solace has chosen
  to do by hand to learn it.
- `## Claude's` — agent rabbit-trails and future checks. One flat list,
  never surfaced to Solace.

## The line

Every card: one line, a link, the action in the imperative, a short name
distinctive enough for a later session to find. **The link is never
optional** — a card nobody but its author can resolve is not a card; neither
is an action that cannot be stated without private paths, hosts or ports.
Add `blocked: <dependency>` only when it is actually blocked. Sections and
checkboxes, not a table. **Order is priority:** the top card in a section is
the next to pull; place a new card where it belongs.

```markdown
- [ ] **Short name** — action in the imperative ([link](https://...))
```

A ruling card carries your evaluation, so that the ruling is one word:

```markdown
- [ ] **Short name** — the question ([link](https://...)) default: <what you would do> undo: <the reversal and its cost> until: <event or date it can wait for> risk: <consequence if the default is wrong>
```

A click-work card carries two proofs:

```markdown
- [ ] **Short name** — action in the imperative ([link](https://...)) why you: <the mechanism an agent lacks, named — no API, a consent screen, a USB bus — or `learn`> why this: <evidence this is the confirmed fix, with the alternatives tried and ruled out>
```

`why this:` is what stops "update the secret in GitHub" when the workflow
was failing for a different reason, and "update the key on the boat" when
sops already held it. A `learn` card has no `why this:`; it drops only when
Solace says she has it.

## The lint

`kanban-lint.sh` checks every edit to a `kanban.md`, and checks the state
repo's uncommitted board diff again at Stop. It rejects:

1. a ticked box — `- [x]`;
2. a bullet above the first `## ` heading;
3. a heading other than the three sections, or a `###` group heading outside
   `## Needs ruling`;
4. a card whose verb is review, merge, land, bump, close, approve, ship,
   ratify, rule on, decide, confirm, answer or watch, pointing at a
   `/pull/N` or `/issues/N` — that loop's home is the PR or issue. Not
   applied under `## Needs ruling`, where "decide X on PR N" is the point;
5. a state word: merged, awaiting, not merged, CI green, open as;
6. a card with no link;
7. a ruling card with no `### <project>` group above it;
8. a ruling card missing any of `default:`, `undo:`, `until:`, `risk:`;
9. a `## Solace's` card missing `why you:`, or missing `why this:` when
   `why you:` is not `learn`.

## Lifecycle

- **Cards die when done.** Delete the line, never tick it — this is a
  work-in-progress list, not a log; `git log` and the session logs keep
  the history.
- **An answered ruling moves, it is not deleted.** `/sweep` appends one dated
  line with the answer to `docs/decisions.md` in the project's primary repo
  (a pointer line when the ruling landed as an ADR or a Q-nn), then removes
  the card. That file is where "I decided X on the 24th" is found later.
- No cap and no expiry: `/sweep` prunes what was ruled elsewhere or went
  stale, and reranks the rest. A card that blocks nothing and has no
  consequence is never shown; take its default and record it.
- A sweep — "reconcile", "what's outstanding", "what's stale" — is
  `worklist` for work state, which never edits, and `/sweep` for the board.
- Commit the board in its own repo. The Stop hook commits the state repo.
