---
name: scoping
description: Loop-one sync, scoping only — what has a governing source settled that code hasn't caught up with? Read one curia, fully formed ADR or large GitHub issue, propose session-sized work items, stop for the user's yes. Use on "/scoping <target>" or bare "/scoping" (the most recently touched curia). Builds nothing; files nothing before the yes. Not for running a sitting (/curia), ruling (/agora), or doing the work (grind, /orchestrate).
---

# Scoping

The touch point where a governing source's rulings become claimable work
items: the seam between judgment and toil (Solace, 2026-10-01). The id
`scoping` is pencil ("maybe /scoping"). Source: the one-entry-point curia,
§1t, §1u and §5's entries of 2026-10-01; its first run is
`curia/one-entry-point/inputs/2026-10-01-scoping-proposal.md`, the shape
kept below.

**Words.** Use the record's words. A word or idea the record does not
hold is a new one, and step 5 counts it. Agent-drafted words are avoided.

## 1. The target, said aloud

`$ARGUMENTS` is any governing source: a curia id, an ADR path, or an
`owner/repo#n` issue. Empty means the most recently touched open curia:
list the open curiae as bare `/curia` does and take the newest. Say which
target, and why, in the first line.

| Target | Decided record and open questions | Lock folder |
|---|---|---|
| curia `<id>` | `digest.md`'s Decided and Open questions; a redirect's own loop section says where (one-entry-point: §5 and §6 of its `digest.md`) | `state/global/curia/<id>` |
| ADR | its Decision and its open or deferred items | `state/global/scoping/<repo>-<adr-slug>` |
| issue | body and comments; sub-issues as in flight | `state/global/scoping/<owner>-<repo>-<n>` |

## 2. The lock: one writer per target, 25 minutes

```bash
scoping-lock take <lock-folder> ${CLAUDE_SESSION_ID} <record-file>   # an issue: its updatedAt
```

`<record-file>` is the file step 1's table names. For a curia that is
`digest.md`, never `roll.md`: the hook appends to the roll on every
prompt, so the record would always read as moved.

Exit 1 is a held scoping: show its `held:` line and stop. Exit 2 is a lock
that could not be taken: show the reason and stop. Never work around
either. The lock is `LOCK`, beside a curia's `LIVE`; `LIVE` is the soft
sitting marker and this run never touches it.

**The clock is toil, and it is yours** (Solace, 2026-10-01). A scoping runs
10 to 25 minutes. The lock lapses 25 minutes after it was taken; the lapse
is the release, whether or not this session is still talking, because
nothing of yours runs between turns. Re-taking your own live lock never
extends it. At the top of every turn and before every write:

```bash
scoping-lock check <lock-folder> ${CLAUDE_SESSION_ID}   # 0 ours, 1 held, 3 lapsed or free
```

- **15m, not close to the yes:** say so in one line, with what is still open.
- **22m:** write and commit the proposal as it stands, unasked.
- **Exit 3:** re-run the `take` line silently and say only "lock retaken".
  Write nothing before it succeeds. Then record any decision made, and
  propose releasing at once; if Solace carries on, the retake is a fresh
  25 minutes.
- **Exit 1, or a retake refused:** another session holds the target. Write
  nothing into it. Put any decision not yet recorded in this session's
  pickup item, name the holder, and stop.

## 3. Read, never edit

Read only the decided record and open questions; never edit them, and
never anything else in the target. State today comes from the files the
rulings name (read them), and in flight from open PRs and issues (`gh`)
and other sessions' pickup items (`pickup-list find <word>`). A wide state
sweep goes to a read-only sub-agent (no worktree, no sub-agents of its
own) that returns the rows; a curia's worth of greps does not need one.
Build nothing.

When the decided record visibly lags (a ruling cited but not recorded),
name the gap in the proposal; never fill it from elsewhere.

## 4. The proposal

Write it to the target's `inputs/` (a curia) or its lock folder (otherwise)
as `$(date -u +%F)-scoping-proposal.md`, adding `-<session-id8>` when the name is
taken; never overwrite an earlier one. Commit it. Shape:

1. **Header,** a brief: read [brief.md](../agora/brief.md), which
   `/agora` shares, and write to it. It adds: target and why; what was
   read, a `read_at` stamp and its links; what Solace decides, the yes below; "Nothing edited,
   nothing filed. Nothing here is claimable until Solace says yes"; the
   homes the items touch.
2. **Ambiguity named, not guessed.** A ruling that reads two ways: both
   readings, the default if it is a standing ruling, held out of the items.
3. **Rulings.** One row per ruling:

   | Ruling | § | Pen or pencil | Files | State today | In flight | Verdict |
   |---|---|---|---|---|---|---|

   Pen or pencil is as the record marks it; unmarked is said so. Verdict is
   done, in flight #n, out, or in scope. Out is pencil, held, imagined, not
   ordered, or touched by an open question; a ruling with nothing to build
   is out, not ordered. A ruling already true in the code is done, and
   work already started is in flight, pencil or not. Out rows collapse
   into groups, each with its count and one reason.
4. **Work items,** one session each, in order, dependencies named. Each
   item: its rulings, its files, its home, and every default the doer will
   pick that carries medium risk or more, as a table of default, undo,
   risk. Home by target (§5, 2026-10-01): a curia, cards, or issues when an
   item stands on its own without the curia or a future ADR; an ADR,
   issues or cards in a mix; an issue, sub-issues.
5. **Pencil and new words.** How many items rest on pencil, and which
   pencil; whether any item needs a new word or idea. If one does, name
   it and its two exits, a veto here or back to the curia or agora; that
   item is not filed on the yes.
6. **The yes.** The form it takes, from the size (below).

## 5. Stop and show

Show the proposal and stop. Nothing is claimable before Solace's yes.

The yes scales with size. Pencil thresholds, the agent's default until
ruled: up to 3 work items and 400 words in the work-items section, one
word for the whole; above that, a tick per item, and an item over 150
words is split before it is shown. Measure with `wc -w` from the
work-items heading to the next heading, counted as
[brief.md](../agora/brief.md) counts, and say the count.

## 6. On the yes

Re-run the `take` line first; a refusal now stops the filing, and a
`read moved:` line means the record moved since the proposal. Then file
each yes'd item exactly as proposed:

- a card under `## Claude's` through `/card-write`, linking the target;
- at most one GitHub issue this session, never a batch (Solace,
  2026-10-01, pen); further issue-homed items stay in the proposal, marked
  unfiled, and the hand-off names them.

An item that rests on pencil says which, in the record's words, on its
card or issue. Record what was filed in the proposal file, then:

```bash
scoping-lock release <lock-folder> ${CLAUDE_SESSION_ID}
```

A run that ends without a yes releases the same way. A dead session's lock
lapses at 25 minutes like any other.
