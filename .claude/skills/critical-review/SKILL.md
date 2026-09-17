---
name: critical-review
description: Fire the critical-review prompt at one pull request — review, fix, hand over ready. Use on "/critical-review <PR>" or "critical review of #N". Not for merging; that is Solace's.
---

Do a critical review of $ARGUMENTS.

You may ask questions or comment directly on the individual PRs.
Then, without waiting for answers, switch gears: fix any open issues and
get the PR ready for my review.
Then summarize anything you fixed or that I should look at or decide,
under three headings: **Fixed** (with the commit), **Look at** (needs a
human read; say why a machine couldn't decide it), **Decide** (one line
each: question, default, undo, risk). Show an empty heading as empty.
End with the PR link.
