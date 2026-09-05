---
name: card-write
description: Write or edit an open-loop card on a kanban.md board in the house format — one line, imperative, link mandatory, right section, right board. Use whenever a loop is found that must be captured ("card that", "add a card", "put it on the board", a unilateral call, a finding that doesn't belong in this session). Not for walking a card with the user — that is /card-helper.
---

# Writing a card

A card is capture, not activation: the work still waits for a pull. Write
it the moment the loop is found, while the comment link, timestamp and
exact wording still exist.

## Which board

- Every project keeps one board: `kanban.md` at the repo root, or the path
  its own CLAUDE.md names.
- A loop that belongs to no project, or the first card of a repo with no
  board, goes to `~/claude_prompts_scratch/state/global/kanban.md`. Don't
  create a board unilaterally — a card landing global is the signal to
  decide whether that repo earns one.
- A **question** goes to an issue; an **action** goes on a board.
- A **public repo's board never carries boats, hosts or services.** Those
  cards go global, with a link back.
- Dotfiles has no board: its cards go global, and anything with a question
  in it becomes a dotfiles issue the card links to.

## Which section

One file, two sections: `## Solace's` for loops only Mark can close, and
`## Claude's` for loops an agent can. One file, not two, because the useful
edges cross — an agent's card is routinely blocked on one of Mark's, and two
files would show each list clear while the work sits deadlocked. Older
boards still head the first section `## Yours`; treat it as the same section
and don't rename it as a side effect of adding a card.

## The line

```markdown
- [ ] **Short name** — action in the imperative ([link](https://...)) blocked: <dependency>
```

- One line per card: a link, and the action in the imperative.
- **The link is never optional** — a card nobody but its author can
  resolve is not a card.
- The short name or the link must be distinctive enough for a future
  session to find the card.
- Add `blocked:` and the dependency only when the card is actually blocked.
- Sections and checkboxes, not a table.
- **Order is priority.** The top card in a section is the next one to pull.
  Place a new card where it belongs, not at the bottom by default.

## Lifecycle

- **Cards die when done.** Delete the line — this is a work-in-progress
  list, not a log; `git log` and the session logs keep the history. A ticked
  box is at most a placeholder until the next tidy.
- Keep each section short. A list nobody can hold in their head is a second
  place to lose things; finish or delete before adding.
- If a loop is not worth a card, it is not worth telling Mark about either.
- Commit the board in its own repo, and never stage one project's work
  under another's. The Stop hook commits the global state repo; a project
  board is committed with that project's work.
