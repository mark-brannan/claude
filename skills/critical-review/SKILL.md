---
name: critical-review
description: Fire the critical-review prompt at one pull request — review, fix, hand over ready. Use on "/critical-review <PR>" or "critical review of #N". Not for merging; that is the user's.
---

Do a critical review of $ARGUMENTS.

You may ask questions or comment directly on the PR. Then, without
waiting for answers, switch gears: fix any open issues and get the PR
ready for my review.

Then summarize under four headings, each shown even when empty. One line
per item. Reading is my toil; deciding is dearer still.

**Fixed** — what you changed, with the commit.

**Look at** — a diff a human must read: where (file and lines), and why a
machine couldn't settle it. Never a question; a question belongs under one
of the two headings below.

**Pencil** — the defaults you took that were judgment-shaped, mirrored
from the PR body's `## Pencil:` list, kind first so I can scan:
`**risk** · what you did · undo: <the reversal>`. My silence keeps them.
Toil — names, structure, order, tooling, wording — is yours and goes
nowhere.

**Decide** — a question only I can answer, that this PR cannot merge
without. Kind first, then the ruling card's own line:

```
- **risk** · the question? default: <what you did> · undo: <the reversal and its cost> · risk: <if the default is wrong> · [thread](link)
- **click** · `churn-ok` on this PR: +N prose lines, <what they are>
```

Before a line goes under Decide, walk the exits in order and stop at the
first that fits:

1. **Omit.** A default exists and its undo is a revert of your own branch
   before anyone builds on it. Take it; it is a Pencil line, not a
   question. "Default: yes, risk: none" is this exit asking for a line it
   doesn't deserve.
2. **Omit.** It is already ruled or carded — check the board, the repo's
   decisions file and the PR's threads before you write. The card is its
   home and the board brings it up; restating it adds a decision to my day
   for nothing. The one exception: a card whose `until:` is this PR's
   merge, named by link alone.
3. **Card.** It fails the one-way-door test but this PR is right whichever
   way it goes: a `human-ruling` card through card-write, named nowhere in
   the summary. A follow-up — "should a later PR…" — is this exit too, or an
   issue under its bar.
4. **Decide.** Nothing above fit, and you can name which of the five
   kinds of judgment it is — values, risk, direction, legal, people. Post
   it as a PR thread first; the thread is its home and stays open until I
   answer. A click only I can make (`churn-ok`) is a `click` line, with no
   default, undo or risk.

Empty is the usual Decide. A question whose answer would be obvious to me
is the dearest thing a review can produce.

End with the PR link.
