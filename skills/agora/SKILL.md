---
name: agora
description: Run an agora sitting — the quick decisions, in batch, one fresh subagent per item, the user rules. Use on "/agora", "/agora briefs" (the briefs alone, ahead of a sitting), "walk the decision cards", "what needs deciding", or when the user says they have the headspace to rule on a queue of open decisions. Not for toil; that is grind. Not for a hard multi-turn question; "confer" is a closed answer here, and it sends the item to a one-off confer session, never straight to a curia.
disable-model-invocation: true
---

# Agora

The user's analogue of grind: the sitting in which the quick judgment items
are consumed in batch. Each item is quick by construction; a hard one is
answered with the one word **confer**, the sitting moves past it, and it
goes to a one-off confer session of its own — not a curia. A curia opens
only at the gates in the curia skill, on the user's word in that confer.
This skill absorbs the retired `/ruling`: the typed per-item contract below was ruling's.

Ancestor concepts: GTD inbox processing, office hours, a replenishment
cadence; the ruling's default that holds is "act after a veto window".

## The sitting

`/agora briefs` runs **Admission** below and nothing else: no opening
list, no dialog; see [Difficulty and model](#difficulty-and-model).

<!-- Sourcing is settled in design (awake items from the ruling items);
     the awake/asleep mechanism (worklist rung 3) is not built. Until
     then: -->

Pull candidates from the state repo's items with `owner=human-ruling`
(`~/.claude/bin/work-item list | awk -F'\t' '$2 == "human-ruling" && ($3 == "ready" ||
$3 == "open")'`, since a held item cannot be claimed and a blocked one
waits on its `until=`; the card line is the last column, the id the first),
anything `/reconcile` flagged as an implicit "Pending:" tail, and
anything the user names; a candidate with no item skips every
`work-item` step below. That list is the **agora-docket**. Count it
before the first question, show the count on every question, and say once
how many ruling items it left out as blocked or held. <!-- When
worklist awake/asleep lands, filter to awake only. -->

**The opening list.** Before the first question, print the docket as a
numbered list capped at 12, each line the card's own one-line question (the
card line, last column) so the user can think before the first ruling. If
the docket is longer, end with "+N more". It is a preview: no dialog, no
subagent, no brief read.

**Admission** (pencil, the agent's proposal in the one-entry-point
curia's §6, "The agora petition"; not ruled). Each candidate passes one
test: could the user rule on it from the card alone, with no prior
context? If not, a subagent writes a brief and only then admits it. The
brief is a file, `state/global/agora/briefs/<card-id>.md`, and the card
gains its link (`~/.claude/bin/work-item brief <id> -`, fed the text under `## Brief` in
`~/.claude/bin/work-item show <id>`, less its `points:` line, plus the link), so the
card stays one line, the context has one home, and the next sitting
reuses it. A card whose question events have overtaken never reaches the
user: restate the live question under it, or route it
to `/sweep`. "May I delete this?" is never the item. The docket is counted
after admission; a card routed away leaves the count.
A card without its evidence (`evidence:` per `/card-write`: the picture
for a visual call, the inventory for a storage call, the whole scope
behind a scope default) is returned to the filer as work, not put on the
docket: `~/.claude/bin/work-item log <id> owner=agent 'needs evidence: <what>'`
sends it to the agent's queue, and the agent that gathers the evidence
logs `owner=human-ruling` to send it back. It leaves the count.
A visual or taste item (how something looks or reads: a drawing, a crop,
a sprite, a picture, a layout, a colour) carries its visual evidence in
the question itself: goldens, a before/after, or a rendered example. It
is offered as a toggle to try, both options built behind a switch with
the default on, rather than as a ruling; the user tries them and keeps
one when ready.
A question never cites a label by its code alone (R1, D5, Q-nn, §7); it
gives the label's words, in one or two sentences.

**The brief** follows [brief.md](brief.md), which `/scoping` shares;
read it before writing one.

Where the item touches the user depends on its kind:

| Kind | Touches the user at | The brief carries |
|---|---|---|
| Risk appetite | an action they take | the moment, the incident, each answer's cost |
| Technical design | what they live with later | the crux in one line; failures, upkeep, CI, agent reach |
| Values and voice | how it reads | rendered examples |
| Money, law, people | outside the screen | numbers measured or guessed; who sees it; one-way door? |
| A family of items | one context, many rulings | the shared brief once, each item a one-line delta |
| A default in force | it is already happening | "object or let stand", with what it has done |

A fold also carries the curia's question in one line.

## Per item: the contract

Every item this skill touches gets, and keeps:

- **Input** — the exact question, one sentence, answerable yes / no / a
  number / a named choice, plus the five fields `default`, `undo`,
  `until`, `risk`, `evidence`. Not "figure out X"; that is unscoped work, sent back
  to be scoped.
- **Output** — exactly one of:
  - **Ruling** — the user answers; the ruling is written at once where
    [Where a ruling lands](#where-a-ruling-lands) says. The card retires in the same turn, per
    [the lifecycle](../../docs/work-item-lifecycle.md): an `open` item
    gets `~/.claude/bin/work-item log <id> status=ready` first, then `~/.claude/bin/work-item claim
    <id>`, then `~/.claude/bin/work-item log <id> status=done 'evidence=<link>'`, the
    link to where the answer is recorded (the roll or decisions line, the
    spawned work, the curia's open question). Stop there: no skill writes
    `closed`. A refused `claim` leaves the card as it is, and a `done` that
    fails after the claim takes `~/.claude/bin/work-item release <id>`; either goes in
    the output line.
  - **Spawned work item** — the answer was "build X to find out"; open
    the issue or card, link it, this item retires as a ruling does.
  - **Item (partly) unblocked** — the ruling removes one dependency; say
    which, and what still blocks (`~/.claude/bin/work-item log <id> 'unblocked: <which>,
    still blocked by <what>'`; single-quoted, with no `=` or `'` in the
    words, since a `key=value` word moves the item or sets a fact).
  - **Confer** — the user's one word; the item leaves the sitting for a
    one-off confer session (see below). Not a failure of the item; a
    rating of its difficulty and possibly of the question's quality.
    Not a curia: the agora is the second of the curia skill's gates, and
    the sitting never passes the later ones.
    Confer keeps the card open and works it further; never offer it
    paired with closing or deleting.
  - **Folded** — the item is a sub-question of an open curia; a yes writes
    it under that curia's `## Open questions` with its provenance, and
    the card retires as a ruling does. No folder is touched beyond that
    line.

## Where a ruling lands

The decision is as public as the question that drove it.

- **The question was already public** (a public issue or PR argued it):
  the decision is public, a dated line
  `- YYYY-MM-DD — <short name>: <the answer>, because <the reason> ([link])`,
  newest first, in `docs/decisions.md` of the project's primary repo — the
  repo whose name the `project-<name>` topic shares, else the repo the card
  links. The because is brief, one clause, and is the agent's derivation
  of the reason from the question and the evidence, never the user's own
  words quoted; the file's header says so once, so a reader knows its
  source. It exists so the user can later answer "why?" when scoping or
  deciding, so it is never omitted. Lines already in the file are not
  rewritten. The line passes the private-terms check; failing it,
  the ruling is private.
- **The driving force is non-public** (a card, a curia, a private
  session): the decision stays private, in the state repo, with the
  user's words verbatim where there are any: the sitting's log,
  `state/global/log/<date>-agora-<project>.md`; outside a sitting (a
  `/sweep` Answered), `state/global/log/<date>-sweep-<project>.md`. A
  curia's sub-question is **Folded** into that curia instead, and a
  ruling on one lands where [the curia skill](../curia/SKILL.md) keeps
  its rulings; no agent writes its `roll.md`.

Either way, when the answer already landed as an ADR or a Q-nn, the line
points there rather than repeating it.

When in doubt, it stays private, and a private card
(`owner=human-ruling`) asks whether to publish it. A sitting never opens
a PR or comments on an issue just to record a private ruling.

## Per item: the steps

1. A fresh subagent (Haiku, low effort) gathers the item's context, starting from
   `~/.claude/bin/work-item show <id>` (a confer mark or an unblocked note lives in its
   log, not on the docket row), and returns the typed
   question with its five fields and a **direct link** to the stored
   context, readable by the user. It also lists the open curiae exactly as
   the curia skill's bare `/curia` does (`status: open` in the header; a
   header-less digest is open) and says whether the item is likely a
   sub-question of one, naming it. The sitting, not the sub-agent,
   decides whether its pick is "fold into `<id>`" (outcome **Folded**).
   A subagent has no channel
   to the user, so it never asks; it only prepares. <!-- Context budget and
   return format: open (design doc, open question on the agora
   procedure). -->
2. The sitting checks the brief is still true: a link it read that changed
   after its `read_at` (`gh ... --json updatedAt`, `git log -1`) sends it
   back to a subagent for a fresh brief. Then it shows the brief and asks
   the question in one `AskUserQuestion` dialog, `multiSelect` when
   outcomes combine (fold and rule): the agent's pick first and why, then
   the alternatives. Every question carries **X of Y** and the total.
   Nothing else from the subagent enters the sitting's context.
3. The user rules: yes / no / a value / **confer** / other.
4. Apply the output per the contract, immediately; don't batch.
   Then commit and push what the ruling touched in the state repo, by
   path: the card, the brief and the ruling's log line (`work-item`
   writes only edit files). Never `git add state/` or `-A`, and the
   commit takes the same pathspec, or it sweeps up what other sessions
   staged. Under the Stop hook's push lock, in one Bash call:

   ```bash
   python3 ~/.claude/lib/state.py push_locked 'd=$(python3 ~/.claude/lib/state.py state_repo) && cd "$d" \
     && git add -- <paths> && git commit -q -m "State: agora session <sid8> (<date>)" -- <paths> \
     && git pull -q --rebase --autostash && git push -q origin HEAD'
   ```

   A held edit trips every other session's kanban-gate until Stop.
5. Discard the subagent. Next item.

## Confer: handing a hard item to a confer session

On the word *confer*: record it on the card
(<!-- format open; this is its pencil form -->
`~/.claude/bin/work-item log <id> confer=<YYYY-MM-DD>`), leave the card where it is,
and move on. **Create nothing under `state/global/curia/`.** A curia question
petitions the agora first; no lower-level session creates a curia. The
agora is one gate of several; a curia opens only when
the user says so inside the confer session, at the curia skill's gates.

Then start the confer at once, in the background, and keep sitting:

```bash
~/.claude/bin/confer-start --model <m> --effort <e> --title '<short name>' <id>
```

It starts one session on this box with Remote Control on, whose prompt is
the confer hand-off for the card, logs `confer_session=<id>` on it, and
prints how to attach. Model and effort come from the item's agent
rating (see Difficulty and model). The confer reads
the card itself and waits on its first question, so the user can answer
it in parallel or after the sitting; nothing is pasted. Relay its
`confer started:` lines in one line: the session's name and link. Once
that line has printed the confer is running, whatever the exit code; a
`confer_session` it could not log is relayed as its warning, never
answered with a second start. Commit the card with the ruling's other
paths, as in step 4.

A start that is refused, or whose `claude --bg` failed, falls back: at
the end of the sitting, print its confer prompt, ready to paste:

```
Confer on <short name>: <the card's question, one sentence> (<card link>).
A one-off session — a discussion held in chat. Set out the item, give
your recommendation and one question about the item as text, never a
permission ask; the user answers in their own words. Never use the
AskUserQuestion dialog. It ends in a ruling, a spawned issue or a
sharper card; open no curia unless the user says so, and then only
through the gates in the curia skill. Model: fable · Effort: high
```

The sitting never opens the hard discussion itself; that would bloat its
context.

## Difficulty and model

Before the first item, rate each candidate twice from its `default:` /
`risk:` text, as a triage table does: the user's difficulty and a
high-stakes agent's, each low / medium / high. The sitting stays on its
own model (below) whatever the ratings say; it never offers a switch, since
a mid-session switch recomputes the context (`rules/code.md`). The agent
rating has one use: an item that needs more than a brief and one dialog is
a confer, and the confer starts at that rating's model and effort:
high is fable · high, medium is opus · high, low is sonnet · medium.

**The sitting's own model** (pencil, the agent's default on the user's
word, 2026-11-07, curia-loop): **Sonnet · medium**. Per item the sitting
shows a brief, asks one dialog and applies the output contract; the
judgment is the user's, and the many turns cost context × turns, so the
cheapest model that can hold the contract runs it. Fable and Opus enter
only where an item's rating sends a confer. The briefs are Haiku's, and
they may be written **ahead of the sitting**: `/agora briefs` runs
**Admission** whole and alone, on the sitting's model, with the same test
and the same moves (a card without evidence goes back to the agent's
queue, an overtaken card is restated or routed to `/sweep`; none is a
ruling), one Haiku sub-agent per candidate that fails the card-alone
test, writing each brief to its file under `state/global/agora/briefs/`
with its `read_at` and linking it from the card. It ends as step 4 does:
one `push_locked` commit whose pathspec is the briefs and the cards it
touched, then returns with no dialog. The sitting then checks each
brief's freshness and shows it; a stale one goes back for a fresh brief
as step 2 says. A brief may flag the item as a likely sub-question of an
open curia; the sitting judges the fold, never the brief.

## Output

Per item: the question, the outcome, the link. At the end, one line:
how many ruled, spawned, unblocked, folded, deferred to a confer, still
open, out of the docket's total; then each confer started, by name and
link, and any paste prompt a failed start left.

## Open (design doc, open question on the agora procedure)

- Awake/asleep filter: depends on worklist rung 3.
- Subagent context budget and return format.
- How a confer deferral is recorded on the card.
- Where the confer session's own record lands when it rules without a curia.
- Where rulings land when the item has no obvious home repo.
