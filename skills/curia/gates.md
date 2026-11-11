# Opening a new curia: gates 2 to 6

2. **The question petitioned the agora first.** An agent that finds a
   question too hard for the one-way-door test writes a `## Needs ruling`
   card in the house format — default, undo, until, risk, evidence,
   judgment — per
   `/card-write`. That card is the petition, and it must carry enough
   pre-work to fit the format; the agora is cheap, not free.
   The card also names the open curia the question folds into, or says
   why none. The user's direct order to open a curia with them skips this
   gate and the next; nothing else does.
3. **The user answered "confer", and the confer ran.** In an agora sitting
   the user answers the card with the one word; that opens a one-off confer
   session on the card's question, not a folder. Most confers end there —
   a ruling, a spawned issue, a sharper card — and the card's home stays
   the board. Only when the user, in that session, says to open a curia does
   the next gate apply.
4. **The open list and the fold check.** Before any folder exists, list
   the open curiae exactly as bare `/curia` does — count, id, question,
   last touched. For each, say in one line whether the new question is a
   sub-question of it. If it is one, it becomes a line under that curia's
   `## Open questions` with its provenance, never a folder; folding a
   small question into an existing curia is always on the table. Show the
   list and the fold verdict, then wait for the user's word.
5. **The WIP limit.** Soft, **5 open in total, 1–2 per repo**. Gate 4's
   list says where the count stands against it. Soft means the user may
   pass it, by their own word in the same turn after seeing that list; an
   agent never does. The reason: a forcing function so that an errant but
   well-meaning agent cannot start a parallel curia while the big one is
   ongoing. **Suspended until 2026-12-08** on the user's order (card
   179136412936a787ac, extended on 2026-11-07 with the word cap in [facet-table.md](facet-table.md)):
   the count still shows, and no session warns about the limit or raises
   its review before that day; on it, the count and `status`'s numbers go
   to the user, who rules whether the limit returns.
6. **The user confirms the id.** The id is a kebab-case slug of the
   question's own words — `widget-retirement`, not a coined name — so
   confirming one names nothing. The user renames at will; a rename moves
   the folder and adds `formerly: <old-id>` to the digest's header, the
   only trace of the old id; nothing stays at the old path.

Only then: create the folder, copy [template.md](template.md) to
`digest.md`, fill in the question, the origin link, the date, who ordered
it and a reference to the words, and `related:` — the ids of open curiae from
gate 4 that touch it, ids only; lint keeps it derived from then on — and
commit. That placeholder is the
whole opening; the first sitting does the rest. Say the id in the opening
session's record.
Then file the curia's epic, 1:1: a private issue in
the state repo (`state_repo.github` in config.json), titled `[Epic] <the question>`,
labelled `epic`, body the whole `digest.md`
(`gh issue create -R "$(python3 ~/.claude/lib/config.py get state_repo.github)" --label epic --title ... --body-file digest.md`),
and write it as `issue:` in the header. A trial (2026-10-06): for now the
issue is a replica of the digest, for reading back; what it becomes is
open indefinitely, and not an agent's to close.
Also create `decided.md` and `agent-notes.md` from the headers in
[forms/decided.md](forms/decided.md) and
[forms/agent-notes.md](forms/agent-notes.md).

