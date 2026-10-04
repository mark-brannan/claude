---
paths:
  - "**/README*"
  - "**/CHANGELOG*"
  - "**/*.md"
---

# Writing (README, CHANGELOG, docs)

Personal conventions for user-facing prose. Loads when touching README,
CHANGELOG, or markdown docs.

Long for the agent so the human's prose can be short. Examples and anchors,
not adjectives. A rule here is cut by its cost only when a counted result
shows it dead weight, never for being long.

## Default to less

- Bias toward no README, or a one-paragraph README, when unsure what
  belongs in it. "The more the words, the less the meaning." A gap is
  better than padding that only looks complete.
- Cut what's obvious from context. Don't explain the default path (e.g.
  installing from an app store) — say what's non-default, nothing else.
- When asked to cut, cut hard. Prefer deleting a paragraph to hedging it
  down by 20%. One unexplained sentence beats three mediocre ones.

## The shape of a new entry

- **Copy the shortest neighbour, never the longest.** A new bullet or row
  takes the length and shape of the shortest one already in that list. That
  is what "match the surrounding style" means; matching the longest is how a
  list ratchets.
- **One rendered line.** A list item or table cell says what the thing does
  for the reader, as a sentence or a fragment, in under 110 characters once
  link syntax is stripped: that is where GitHub wraps on a laptop screen.
  Count it; source wrapped at 80 columns hides the length.
- **The README says what a person decides or sets. The code header says
  how.** Flags, fields, env vars, edge cases, scar stories: header. Missing
  there? Add it there.
- **"Too long" means delete.** Never answer a length comment with a clause
  that explains, and never hedge with more detail. A detail that cannot be
  cut gets one question: where does it live?
- **Slop, by shape:** a table whose columns repeat each other, a parenthetical
  that restates its bullet, a setting only an agent would touch. Delete on
  sight.
- **Show the render.** Before a human reads a doc change, look at it as they
  will, rendered at their width, and run the one-line check on it.
- **The bar is a number in the repo.** `docs/budgets.json` caps README lines
  and words per change; `prose-budget` runs in CI and the gate needs it.
  Raising a cap lands alone, with its reason.

## Don't touch a human-written doc without being asked

- Don't edit, restructure, or "clean up" README/CHANGELOG prose as a side
  effect of unrelated work. Wait to be asked, explicitly, for that file.
- If a claim in the doc is now false, fix only the false claim, in the
  voice already there. Don't rewrite the sentence around it, don't
  restructure the section, don't improve the tone while you're in there.
  Someone spent effort on that voice; a correction isn't a rewrite.
- Once I've signed off on a doc, treat it as frozen. Don't re-polish it on
  a later pass just because the repo is open.
- If I park a doc rewrite, drop it. I'll bring it back up.

## Sound like a person, not a model

This section governs what I draft, not existing prose I didn't write. It
is a phrase/pattern match, not an authorship detector — it can't tell "AI
wrote this" from "a verbose human wrote this," and the user has told me they're
the second kind by nature. Never use this checklist as grounds to flag or
edit prose you didn't just draft, including anything predating this repo's
Claude commits — check `git blame` before treating old text as a tell
rather than assuming. That's what "don't touch a human-written doc"
already covers; this section doesn't override it.

- Self-check before showing a draft: would a reader guess this was
  AI-written? If yes, revise before I see it.
- Words that read as AI by default — avoid or replace with something
  plainer: delve, leverage, seamless, cutting-edge, robust, comprehensive,
  vibrant, testament, tapestry, landscape (as metaphor), pivotal, foster,
  align, elevate, unlock, game-changer, revolutionary.
- Phrases that read as AI by default: "it's worth noting," "not just X,
  but Y," "whether you're X or Y," "in today's ___," any sentence opening
  with "Moreover," "Additionally," or "Certainly."
- Structural tells, not just word choice: rule-of-three lists, one em
  dash per sentence, uniform sentence length, a throat-clearing preamble
  before the actual point, hedges stacked on hedges. Vary rhythm, use
  contractions, get to the point in sentence one.
- Write for the actual reader. For a SignalK plugin that's often a boat
  owner who isn't a programmer — plain and concrete beats technically
  precise but generic.
- When the brief is unclear, ask. A flagged gap beats a paragraph that
  reads like nobody wrote it.
