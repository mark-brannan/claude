---
name: lastword
disable-model-invocation: true
description: DRAFT, not yet wired. The user's own, typed by the user only — close a curia sitting so the user's words come last and the sitting reads as closed until the next one. Carries over from /wrapup the parts that give closure; will replace /wrapup for curia sessions. Not for a plain hand-off (that is /handoff).
---

# Last word

Draft. Design: the hand-off design session (`handoff-workflow-design`).
The user wants, from a curia, one thing no other skill gives: the sense of
getting their words in last, and that the sitting is closed until they are
ready to discuss again.

The curia is not redesigned here. The curia skill's Closing section already
owns the mechanics (land edits, rewrite the two sections the next opening
reads, spawn the runner in the background, print the paste-again prompt,
write `CLOSED`). This skill adds the closure around them and does not copy
them: run that Closing, then the steps below.

## Carried over from /wrapup

- **Say what is still open, by concept, and nothing new.** The closing
  message opens no question, doubt, hint or "one more thing". Anything
  uncaptured goes first into the sitting's `## For next time` list (one line
  each: threads and questions opened and not closed); a closing message may
  say "next time we discuss X" only for an X already on that list.
- **The closing message holds exactly two things:** the paste-again prompt
  (`/curia <id>`, model and effort from the document's header) and links to
  any decision or click-work cards the sitting wrote.
- **Never ask the user to review or merge.** The PR is where that lives.
- **The user speaks last.** Whatever they reply after the closing message is
  recorded verbatim, dated, under `## Final words (verbatim)`; answer with
  one line naming where it landed. If the words change the next action,
  update the hand-off's first line and say so inside that same line. Then
  stop, and stay stopped: a Stop-hook block after this point is answered
  with the block it asks for and the same one line.
- **Release the branch:**
  `~/.claude/hooks/claim-stamp.py release -C . --scan <session id>`, unless
  the sitting is pausing mid-work and keeping its worktree.

## Open (not carried over yet)

- Whether a narrative log earns its keep for a curia, given what `roll.md`
  and the Trace already hold. `/wrapup` wrote one; until decided, the
  Final-words section goes where the curia keeps the user's words.
- Whether `confer` sessions and the agora want the same closure.
- `/wrapup` retires only once this and `/handoff` cover its uses and the
  flag shows it unused.
