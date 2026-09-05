---
name: wrapup
description: Close a session — write the narrative log to the right state repo, bring the session's cards for batch accept/edit/delete, and end with a paste-ready hand-off prompt. Use when Mark says "wrap up", "log it", "hand off", "hand-off prompt", "call it there", or when a session is ending with work still open.
---

# Wrapping up

The Stop hook (`stop-continuity.sh`) already writes the session record, the
typed decision log and an auto-checkpoint, then commits and pushes the state
repo — every Stop, unprompted. Don't redo any of that by hand and don't wait
to be asked. This skill covers what only you can write: what the session
meant, what is still open, and how the next one starts.

## 1. Where state lands

Settled 2026-08-19. A project's session state stays in that project's own
repo. Never stage one project's work under another's.

| Work | State goes to |
|---|---|
| Symphony | `~/symphony/intermediate_files/claude_slop/` (`kanban.md` + `log.md`). Its human-facing `maintenance/log.md` and `priorities.md` get only finished, high-level results. |
| Global and cross-cutting — standing orders, rules, hooks, Claude tooling, anything spanning projects | The private repo `~/claude_prompts_scratch`, under `state/global/kanban.md` and `state/global/log/`. Work on `main` there; `git pull --rebase` before pushing. |
| Any project with no private repo of its own | The same global paths. |
| Dotfiles | **Never** — it is public, and session notes name boats, hosts and services. Dotfiles has no board of its own: its cards sit on the global board, and anything with a question in it becomes a dotfiles issue the card links to. |
| Any other project with its own board | That repo, at the path its CLAUDE.md names. |

## 2. Narrative log

Write `log/YYYY-MM-DD-<slug>.md` under the state directory above. The
auto-checkpoint records what happened; only you can record what it meant
and what should happen next. The machine one is evidence, not a substitute.
Put in it:

- what was decided, and why — including calls that reversed or narrowed an
  earlier one;
- what was tried and abandoned, so the next session doesn't retry it;
- what comes next: the hand-off prompt from step 4, verbatim;
- observations worth keeping. They go here, silently — never as an aside in
  chat.

## 3. Cards

Bring every card written during the session for batch accept / edit /
delete: one list, one line per card, each with its link. Apply Mark's
decisions to the board before the session ends. Anything only Mark can do
personally is a card, referenced by link and by a short name; either the
link or the short name must be distinctive enough for a future session to
find it.
Board selection and card format: `/card-write`.

## 4. Hand-off prompt

When the session ends with work still to do, write the prompt that starts
the next one. It must:

- be **ready to paste** — no "as discussed", no context the reader has to
  supply;
- name the **branch, PR, file, card, etc.** it acts on;
- name a **recommended model and difficulty (effort) setting**;
- be written so somebody who was not in this session can act on it.

Put it in the narrative log as well as the chat. The log survives; the chat
does not.

## 5. The closing message

End with a prompt, not a status bullet or observation. A closing that reads
"the vague thing is borked, your call" costs a read and returns nothing
actionable. The closing message holds exactly two things: the hand-off
prompt, and the cards only Mark can act on, by link and short name. Nothing
else goes in it.
