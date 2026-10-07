---
name: card-write
description: Route an open loop to its one home — work it around, a GitHub issue, or a card, which is one work item in the state repo written through `work-item`: a one-line imperative brief, link mandatory. Use whenever a loop is found that must be captured ("card that", "add a card", "put it on the board", "file that", a unilateral call, a finding that doesn't belong in this session). Not for walking a card or issue with the user — that is /card-helper; not for pruning cards — that is /sweep.
---

# Writing a card

A card is capture, not activation: the work still waits for a pull. Write
it the moment the loop is found, while the comment link, timestamp and
exact wording still exist.

**The default owner is you.** An item exists because an agent found work: do
the work, or prove there is none and retire it with the proof (`done`, below). Handing an item
to the user needs a written reason, on the card.

**A migration is a triage, never a copy.** A bulk move between trackers applies
the destination's bar to every item and records the counts kept and dropped;
what cannot be restated from scratch closes rather than moves.

## Where the loop lives

One home per fact. GitHub owns work state; the state repo's items hold what has
no GitHub home. Take the first line that fits:

- **Work state** — open, merged, closed, CI, threads — lives on the PR or
  issue and nowhere else. Never write it down; `worklist` reads it live.
- **A tentative design decision for the colregs family** (colregs,
  colregs-engine, searoom; nav-wright if it ever has one) → a
  `kind: tentative ADR` card (owner `human-ruling`), never a draft ADR in
  the public repo. Before a ruling session writes it up, the decision is
  something the codebase is living with, not settled; the card is its only
  home.
- **A question** → **the one-way-door test.** *Name the default and its
  undo; if there is a default, and the undo is a revert in a repo you
  control before anyone else has seen or built on the choice, take the
  default.* Record the assumption where the work lands — the PR body or the
  commit message — and carry on. The test fails two ways: no defensible
  default exists, or the undo is not a revert — published, posted to a
  public repo, pushed into others' clones, sent to a person, rotated,
  flashed, adopted by a user, or inherited by later decisions. Only then →
  a `human-ruling` card. There is no `needs-ruling` label and no
  ruling issue.
- **A question that wants a curia** — deep, multi-turn, a governing idea in
  doubt — is still only a `human-ruling` card: the petition. Never a
  folder under `state/global/curia/`; only the user opens one, through the
  gates in the curia skill, after the agora and a confer. The card names
  the open curia the question folds into, or why none (`folds: <id>` or
  `folds: none — <why>`).
- **A check** — "verify X", "confirm Y still works" — is not a loop and never
  reaches the user. Run it now. A check that needs a future event and has a
  stated expected output is an `agent` card, your own queue, unmentioned;
  one costly enough to plan is a research issue under the issue bar; one with
  no expected output is dropped.
- **A `churn-ok` request** — the label is the user's alone, given on the PR.
  Never a card, ruling or agora item. A working session may ask about the
  churn guard inline; otherwise it says nothing.
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
- **An epic** is one of three things, and said bare means the first: a
  GitHub issue titled `[Epic] <aim>` and labelled `epic`, both; a curia (a
  design epic, which also has its own such issue 1:1, private, in the
  state repo, see the curia skill); a parent card with many children. The issue associates
  sub-issues (`gh issue edit <n> --add-sub-issue <m>`), the logical work,
  where PRs attach; a PR goes on the epic itself only with the user's yes
  for that PR. Its body carries the aim and a `- [ ] #m` sequence, ticked
  as each lands, for public progress; that list replaces neither the
  sub-issues nor the cards that hold the granular work. Name one by
  `owner/repo#n`. Create or split one through `/scoping`.
- **A launchable session** — prompt written, model and effort sized → a
  sub-issue of its epic, or the private epic's file under
  `state/global/epics/`; a `ready` issue when no epic owns it.
- **Half-done agent work** → the log and the hand-off prompt, as bare links
  with no state adjectives. A pushed branch has a PR or is a finding.
- **Click work only the user can do** → a `human-click` card, and only
  when both proofs below are on the line. "Needs a credential" is not a
  reason unless the credential cannot be given to an agent.
- **An agent rabbit-trail** not worth an issue, or too private for one →
  an `agent` card.

## Where the card lands

One item per card, in `~/claude_prompts_scratch/state/global/items/`, written
only through `~/.claude/bin/work-item`. Never hand-write an item file, and
never put a card anywhere else, `kanban.md` included. The store is private, so boats, hosts and services may appear in it; nothing else
may carry cards. "Project" means the `project-<name>` GitHub topic that
`worklist` resolves — it spans repos, it is not a repo.

`--owner` takes exactly one of these three words, and nothing else:

| Owner | For | Surfaced to the user |
|---|---|---|
| `human-ruling` | decisions that failed the one-way-door test | yes |
| `human-click` | click work an agent cannot do, or that the user has chosen to do by hand to learn it | yes |
| `agent` | agent rabbit-trails and future checks | never |

There is no `### <project>` group: pass `--repo <owner/name>` when the
card's link names one.

## The line

Every card: a title, and a brief that is one line — a link, the action in the
imperative, distinctive enough for a later session to find. **The link is
never optional** — a card nobody but its author can resolve is not a card;
neither is an action that cannot be stated without private paths, hosts or
ports. Its id is minted by `create` (epoch seconds then this session's eight
hex, no separator) and printed; never type, edit or reuse one, and the
brief carries none. Nor does it carry the title: `work-item list` draws the
card line as `**title**: brief`, the facts, then `id:`, so a new card reads like
a migrated one, whose brief holds the whole line. Name a card by it in a hand-off — "card 1790836842077c62eb"
is enough for the next session. Add `blocked: <dependency>` to the brief only
when it is actually blocked. There is no list to place a card in and `work-item list` reads
oldest first, so state urgency in the brief's own words; nothing ranks it.

Three calls, and the item exists and is pickable. The caller makes the id
(`card-id new`, the store never picks one); `create` writes the item `open`,
and a replay of the same create is a no-op that succeeds; a writer has to log
`status=ready` or no reader picks it:

```sh
id=$(~/.claude/bin/card-id new)
~/.claude/bin/work-item create --id "$id" --owner agent --repo owner/name \
  --model sonnet --effort medium \
  --brief 'action in the imperative ([link](https://...))' 'Short name'
~/.claude/bin/work-item log "$id" status=ready
```

`create` needs `CLAUDE_CODE_SESSION_ID`, which a session has. Title is the
short name (one line); the brief is everything else, `-` to read it from stdin
when it holds quotes. A brief line may not start with `## `. `--repo`,
`--model` (sonnet/opus/fable) and `--effort` (low/medium/high, as a hand-off
names them) are facts on the item, so leave them out of the brief; readers
append them to the card line. All are optional on an `agent` card. A dated
`until` is one word, logged after create, on any card:

```sh
~/.claude/bin/work-item log "$id" until=2026-11-01
```

An `until:` that is an event, with spaces, cannot be one word; write it
inside the brief. A link is one word and can be logged.

A ruling card carries your evaluation, so that the ruling is one word. Owner
`human-ruling`; the brief:

```markdown
the question ([link](https://...)) default: <what you would do> undo: <the reversal and its cost> until: <event or date it can wait for> risk: <consequence if the default is wrong> judgment: <values | risk | direction | legal | people>
```

`judgment:` is the gate. A call you cannot file under one of those five
kinds is toil however unsure you feel: take the default, record it where
the work lands, and write no card.

A tentative-ADR card is a ruling card whose decision is already tentatively
taken, living with the codebase until a ruling session writes it up as a
colregs-family ADR (the next number in `docs/adr/`, a budget entry in
`docs/budgets.json`) — never a direct edit to a public repo's docs. It
carries `kind: tentative ADR` and `until:`/`settle:`/`repos:` in place of
`default:`/`undo:`/`risk:`; `until:` holds the date, event and link as on any
ruling card; the decision itself is the card's own
sentence, and `judgment:` gates it as it gates any ruling card:

```markdown
the decision, one sentence ([link](https://...)) kind: tentative ADR until: <date, event and link> settle: <what would settle it> repos: <repo(s) it touches> judgment: <values | risk | direction | legal | people>
```

A click-work card, owner `human-click`, carries two proofs:

```markdown
action in the imperative ([link](https://...)) why you: <the mechanism an agent lacks, named — no API, a consent screen, a USB bus — or `learn`> why this: <evidence this is the confirmed fix, with the alternatives tried and ruled out>
```

`why this:` is what stops "update the secret in GitHub" when the workflow
was failing for a different reason, and "update the key on the boat" when
sops already held it. A `learn` card has no `why this:`; it drops only when
the user says they have it.

An `agent` card whose link is evidence in another repo — the PR where the
bug surfaced, not the repo that fixes it — takes `--repo <owner/name>` for
the repo that fixes it: grind works a card in the repo it names, and falls
back to the link's repo without it.

## Check it before you write it

Nothing lints a card at write time; these are yours to hold. A card:

1. has no verb of review, merge, land, bump, close, approve, ship, ratify,
   rule on, decide, confirm, answer or watch pointing at a `/pull/N` or
   `/issues/N` — that loop's home is the PR or issue. Not applied to a
   `human-ruling` card, where "decide X on PR N" is the point;
2. has no state word: merged, awaiting, not merged, CI green, open as;
3. has a link;
4. if `human-ruling`, has all of `default:`, `undo:`, `until` (in the brief, or logged as a date), `risk:`,
   `judgment:`, and a `judgment:` that is one of the five kinds (a
   `kind: tentative ADR` card has `until:`, `settle:`, `repos:`, `judgment:`
   instead, and the same `judgment:` rule);
5. if `human-click`, has `why you:`, and `why this:` unless `why you:` is
   `learn`.

After writing, `~/.claude/bin/work-item show <id>` prints the file, and
`~/.claude/bin/work-item list | grep <id>` shows the card line a reader sees.

## Lifecycle

- **Cards die when done, never by an edit to the brief.** Per
  [the lifecycle](../../docs/work-item-lifecycle.md), an `open` item gets
  `work-item log <id> status=ready` first (the second call above), then
  `work-item claim <id>`, then `work-item log <id> status=done
  'evidence=<link>'` — the PR, commit or decisions line that shows it. Stop
  there: no skill writes `closed`; that waits on the user's acceptance and a
  sweep of the whole tree. `work-item` refuses `done` without a claim. The
  endings below are the lifecycle doc's reading, still pencil.
- **An answered ruling moves, it is not deleted.** `/agora` records the answer
  at once and retires the card as above; where `/sweep` finds one answered
  elsewhere it records the answer where
  [Where a ruling lands](../agora/SKILL.md#where-a-ruling-lands) says
  (private by default; a pointer line when the ruling landed as an ADR or a
  Q-nn) and retires it the same way.
- No cap and no expiry: `/sweep` prunes what was ruled elsewhere or went
  stale. A card that blocks nothing and has no
  consequence is never shown; take its default and record it.
- A sweep — "reconcile", "what's outstanding", "what's stale" — is
  `worklist` for work state, which never edits, and `/sweep` for the cards.
- Writes are plain files in the state repo; the Stop hook commits and pushes.
