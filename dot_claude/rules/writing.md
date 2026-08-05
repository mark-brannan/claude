---
paths:
  - "**/README*"
  - "**/CHANGELOG*"
  - "**/*.md"
---

# Writing (README, CHANGELOG, docs)

Personal conventions for user-facing prose. Loads when touching README,
CHANGELOG, or markdown docs.

## Default to less

- Bias toward no README, or a one-paragraph README, when unsure what
  belongs in it. "The more the words, the less the meaning." A gap is
  better than padding that only looks complete.
- Cut what's obvious from context. Don't explain the default path (e.g.
  installing from an app store) — say what's non-default, nothing else.
- When asked to cut, cut hard. Prefer deleting a paragraph to hedging it
  down by 20%. One unexplained sentence beats three mediocre ones.

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
