## Survey first

A curia is in part a quest to learn whether the solution already has a
known shape: a design pattern, a reference implementation, a known
solution, a known design or modelling technique. Invent novel things;
never re-solve solved ones. Reuse, adapt or partly derive, licence
permitting, before a build. Here, unlike a coding session or a review,
the design and the choice of dependencies are questioned fundamentally.
Ancestors: prior-art search before a patent claim, the literature review
before a study.

**Before any build is costed** — an effort or price on building
something, a build-our-own row, a fork-or-invest table — the sitting
surveys what exists, and the cost cites the survey. One read-only
sub-agent (Sonnet, no worktree, no sub-agents of its own) runs it, beside
the sitting as at step 2 of the opening, and its brief names the axes:

- this curia's own `inputs/`, first: the cheapest axis, and the answer is
  sometimes already in the folder;
- registries for the language and host;
- code search, and a few well-thought-out web searches past GitHub
  keyword search;
- the problem's or format's known consumers: who already reads, writes
  or solves it;
- every packaging of the reference implementation for the target host
  (native binding, WebAssembly, prebuilt binary, shell-out, container);
- known patterns and modelling techniques for the problem's shape.

The survey lands as `inputs/<date>-survey-<topic>.md`, committed at once.
It names each axis searched and what it found, and lists any axis not
searched under *could not determine*, never silently absent. "The only"
appears only beside the axis it was measured on, and one result is not a
sweep: the survey widens by an axis before a build is weighed against
it. A candidate's cost is a measured row — install size, run time, host
fit — never an adjective ("heavy", "weeks") without a number beside it.

**A values rejection reopens the search.** When a candidate is refused on
values, the search reopens at once as a reopened question: a reason to
revisit the breadth and depth of every path discarded earlier, never a
weighing of the refused candidate's replacements alone. The new survey
cites the one it reopens.

<!-- pen (the user, 2026-11-04): survey first is the rule that was
     missing; look deeply and broadly at existing software before any
     build is costed, with web searches past GitHub keyword search;
     question design and dependencies fundamentally in a curia, slowly in
     a coding session or review. pencil (the user, same day): a values
     rejection reopens the search over every discarded path; the rule's
     homes, a standing-orders line in the user's hand and the mechanism
     here and in lint. pencil (the agent): the axes list, the input's
     file name and the measured-row form, from the retrospective's
     scenarios. The curia's ledger holds the stamps. -->

