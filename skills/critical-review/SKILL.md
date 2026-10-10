---
name: critical-review
description: Fire the critical-review prompt at one pull request — review, fix, hand over ready. Use on "/critical-review <PR>" or "critical review of #N". Not for merging; that is the user's.
---

Do a critical review of $ARGUMENTS.

You may ask questions or comment directly on the PR; every comment you
post is signed as an agent's, the way the code rules say. Then, without
waiting for answers, switch gears: fix any open issues and get the PR
ready for my review.

Before the summary may call the PR ready to merge, run
`~/.claude/bin/pr-blockers <PR>`. Any line it prints is fixed (an unsigned
commit by `~/.claude/bin/resign-branch.sh`) or reported, never assumed:
"awaiting approval" is a guess until it has said nothing else blocks.

Then summarize. Open with one line, before any heading: what the PR does
in your words and whether it is ready to merge. That sentence stands in
for my reading the diff. Then five headings, each shown even when empty.
One line per item. Reading is my toil; deciding is dearer still.

**Fixed** — what you changed, with the commit.

**Look at** — a diff a human must read: where (file and lines), and why a
machine couldn't settle it. Never a question; a question belongs under
Pencil or Decide.

**Reversed** — every thread, a bot's or a reviewer's, that asked to undo
an instruction: a governing document (a design doc, a decisions file, an
ADR, a curia, a rules file, CLAUDE.md), the linked issue's words, a
thread I wrote. The bot read the text; it never read the sitting that
wrote it, so its ask is a reversal of a ruling in plain clothes. **A
reversal is never Pencil** (ruled 2026-10-09, claude#127): you do not
make the change, however cheap the revert, and the thread stays open.
**A bot finding against a governing document's substance is never an
edit** (ruled 2026-10-09; languette#112 shipped one, d6227e9 reverted
it): you do not change the design doc, decisions file, ADR, curia, rules
file, CLAUDE.md or standing orders on a bot's word. It becomes a Decide
line and the thread stays open. Typos and broken links in one are yours.
Find what the record says (the decisions file, the issue, the PR body,
the curia) before you reply, and write the line in those words:

```
- <file or issue> · the record said: <the rule> · the bot wanted: <the change, and why> · you did: kept, thread open · [thread](link)
```

A reversal already on the branch when you arrive — an earlier commit, a
reply that says "that is the intent", a Pencil line that contradicts the
issue — is the same line with `you did: restored in <sha>`; if the PR
cannot be right without the reversal, it is a Decide line and the thread
is its home. Plain words, no shorthand: I read this cold to see whether
we undid a decision on a bot's say-so.

**Pencil** — the defaults you took that were judgment-shaped, mirrored
from the PR body's `## Pencil:` list, kind first — values, risk,
direction, legal, people — so I can scan:
`**direction** · what you did · undo: <the reversal> · [thread](link)`. A bot
thread you answered with a default is one of these, so I see it without
deciding it. My silence keeps them. Toil — names, structure, order,
tooling, wording — is yours and goes nowhere. So is the churn guard: a red
churn check means a smaller change, never a line to me.

**Decide** — a question only I can answer, that this PR cannot merge
without. Kind first, then the ruling card's own line:

```
- **direction** · the question? default: <what you did> · undo: <the reversal and its cost> · risk: <if the default is wrong> · [thread](link)
```

Before a line goes under Decide, walk the exits in order and stop at the
first that fits:

1. **Reversed.** The default would contradict an instruction: the linked
   issue, a design doc, the decisions file, a ruling, a thread I wrote.
   The revert being cheap changes nothing; I have already seen this
   choice, so it is not yours to take. Keep the instruction, write the
   Reversed line, leave the thread open.
2. **Omit.** A default exists and its undo is a revert of your own branch
   before anyone builds on it. Take it; it is a Pencil line, not a
   question. "Default: yes, risk: none" is this exit asking for a line it
   doesn't deserve.
3. **Omit.** It is already ruled or carded — check the board, the repo's
   decisions file and the PR's threads before you write. The card is its
   home and the board brings it up; restating it adds a decision to my day
   for nothing. The one exception: a card whose `until:` is this PR's
   merge, named by link alone.
4. **Card.** It fails the one-way-door test but this PR is right whichever
   way it goes: a `human-ruling` card through card-write, named nowhere in
   the summary; its `until:` lies past this merge, so exit 3's exception
   never applies to it. A follow-up — "should a later PR…" — is this exit too, or an
   issue under its bar.
5. **Decide.** Nothing above fit, and you can name which of the five
   kinds of judgment it is. Post
   it as a PR thread first; the thread is its home and stays open until I
   answer. A bot thread that lands here stays open the same way: it is
   the thread, and you do not resolve it.

Empty is the usual Decide. A question whose answer would be obvious to me
is the dearest thing a review can produce.

**Waffling.** A review thread is not a new order. When a comment argues
against a default you took, change it at most once, on evidence, and
write the Pencil line; when it argues against what the issue, the design
or I said, the instruction wins and the thread stays open (exit 1).
Changing a thing, then changing it back on the next comment, then again
on the one after, is waffling: each flip lands as a commit, the last
comment wins instead of the right one, and the code ends worse than
either side. Scar: claude#82 on 2026-10-07, where a header's figures
moved on bot comments until I asked what the doc said; then languette#110,
#112 and #116 on 2026-10-08, my instruction undone on a thread three
times in one night. Before you change anything a second time: find the
record, write the Reversed or Decide line, stop.

End with the PR link.
