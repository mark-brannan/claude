---
name: card-write
description: Route an open loop to its one home — work it around, a GitHub issue, or a card on a kanban.md board in the house format: one line, imperative, link mandatory. Use whenever a loop is found that must be captured ("card that", "add a card", "put it on the board", "file that", a unilateral call, a finding that doesn't belong in this session). Not for walking a card or issue with the user — that is /card-helper.
---

# Writing a card

A card is capture, not activation: the work still waits for a pull. Write
it the moment the loop is found, while the comment link, timestamp and
exact wording still exist.

**The default owner is you.** An item exists because an agent found work: do
the work, or prove there is none and close it with the proof. Handing an item
to Solace needs a written reason.

**A migration is a triage, never a copy.** A bulk move between trackers applies
the destination's bar to every item and records the counts kept and dropped;
what cannot be restated from scratch closes rather than moves.

## Where the loop lives

One home per fact. GitHub owns work state; the board holds what has no
GitHub home. Take the first line that fits:

- **Work state** — open, merged, closed, CI, threads — lives on the PR or
  issue and nowhere else. Never write it down; `worklist` reads it live.
- **A question only Solace can answer** → **work around it.** Decide it
  yourself, record the assumption where the work lands — the PR body or the
  commit message — and carry on. A parked question is usually one that never
  gets answered; a recorded assumption is reversible work.
- **A one-way door** — a choice that would cost more than a session to
  reverse — → a card under `## Needs ruling`. One line, imperative
  question, with a link to where the argument lives (a `requirements.md`
  Q-nn, an ADR draft, a PR). That is the only kind of question that earns a
  card. There is no `needs-ruling` label and no ruling issue.
- **The issue bar** — file an issue only when a fresh session could start
  from the body alone: a link to the evidence **and** a next action an agent
  can execute without asking. Verify/confirm notes, status mirrors, vague
  loops, "review/merge X" and hand-chores only Solace can do are never
  issues; a question with a defensible default is answered by taking the
  default and recording it, not filed. Below that bar it is a log line or
  nothing.
- **Public or private repo?** An issue goes on the public repo when its text
  passes the private-terms check — `state/global/private-terms.txt` in the
  state repo, read by path, never copied. When it would fail it goes on
  `mark-brannan/claude_prompts_scratch`; the public-issue guard refuses it
  anyway.
- **Agent-startable work** → an issue labelled `ready`. Unlabelled is
  untriaged, and only ever a count.
- **Blocked** → label `blocked`, plus a body line `Blocked by owner/repo#N`.
- **Deferred to after 1.0** → the `1.0` milestone.
- **A launchable session** — prompt written, model and effort sized → the
  epic file's session list; a `ready` issue when no epic owns it.
- **Half-done agent work** → the log and the hand-off prompt, as bare links
  with no state adjectives. A pushed branch has a PR or is a finding.
- **An agent rabbit-trail** not worth an issue, or too private for one →
  a card under `## Claude's`.

## The board

Every project keeps one board: `kanban.md` at the repo root, or the path
its own CLAUDE.md names. A loop that belongs to no project, or a repo with no
board, goes to `~/claude_prompts_scratch/state/global/kanban.md`; don't create
a board unilaterally. A public repo's board never carries boats, hosts or
services — those cards go global. Dotfiles has no board: its cards go global.

A board has two sections, in this order:

- `## Needs ruling` — one-way doors waiting on Solace. Normally empty.
  Its cards are grouped under `### <project>` subheadings — the
  `project-<name>` GitHub topic `worklist` resolves, `### global` when no
  project owns it. Put the card under its group, creating the group if it is
  missing; `###` headings appear nowhere else on the board.
- `## Claude's` — agent rabbit-trails with no GitHub home. One flat list.

`## Solace's` (older boards: `## Yours`) is retired.

## The line

```markdown
- [ ] **Short name** — action in the imperative ([link](https://...)) blocked: <dependency>
```

- One line per card: a link, and the action in the imperative.
- **The link is never optional** — a card nobody but its author can
  resolve is not a card. Neither is the action: a card that cannot state it
  without private paths, hosts or ports is not ready to be one.
- The short name or the link must be distinctive enough for a future
  session to find the card.
- Add `blocked:` and the dependency only when the card is actually blocked.
- Sections and checkboxes, not a table.
- **Order is priority.** The top card in a section is the next one to pull.
  Place a new card where it belongs, not at the bottom by default.

## The lint

`kanban-lint.sh` checks every edit to a `kanban.md`, and checks the state
repo's uncommitted board diff again at Stop. It rejects:

1. a ticked box — `- [x]`;
2. a bullet above the first `## ` heading;
3. a heading other than `## Needs ruling` or `## Claude's`, or a `###`
   group heading outside `## Needs ruling`;
4. a card whose verb is review, merge, land, bump, close, approve, ship,
   ratify, rule on, decide, confirm, answer or watch, pointing at a
   `/pull/N` or `/issues/N` — that loop's home is the PR or issue. Not
   applied under `## Needs ruling`, where "decide X on PR N" is the point;
5. a state word: merged, awaiting, not merged, CI green, open as;
6. a card with no link;
7. a ruling card with no `### <project>` group above it.

## Lifecycle

- **Cards die when done.** Delete the line, never tick it — this is a
  work-in-progress list, not a log; `git log` and the session logs keep
  the history.
- Keep the board short: 15 cards or fewer. A list nobody can hold in their
  head is a second place to lose things; finish or delete before adding.
- A sweep — "reconcile", "what's outstanding", "what's stale" — is
  `worklist` and a report. It never edits a board, epic or log.
- Commit the board in its own repo, never one project's work under
  another's. The Stop hook commits the global state repo.
