---
name: wrapup
description: Close a session — write the narrative log to the state repo, list the issues the session opened or labelled, dry-run the board sweep, and end with a paste-ready hand-off prompt. Use when Solace says "wrap up", "log it", "hand off", "hand-off prompt", "call it there", or when a session is ending with work still open.
---

# Wrapping up

The Stop hook (`stop-continuity.sh`) already writes the session record, the
typed decision log and an auto-checkpoint, then commits and pushes the state
repo — every Stop, unprompted. Don't redo any of that by hand and don't wait
to be asked. This skill covers what only you can write: what the session
meant, what is still open, and how the next one starts.

## 1. Where state lands

Session state lives in the private repo `~/claude_prompts_scratch`, under
`state/global/kanban.md` and `state/global/log/`, for every project. Work on
`main` there; `git pull --rebase` before pushing. No project repo carries a
board or a session log; a public repo never carries session notes, because
they name boats, hosts and services. Symphony's human-facing
`maintenance/log.md` and `priorities.md` get only finished, high-level
results.

## 2. Narrative log

Write `log/YYYY-MM-DD-<slug>.md` under the state directory above. The
auto-checkpoint records what happened; only you can record what it meant
and what should happen next. The machine one is evidence, not a substitute.
Put in it:

- what was decided, and why — as a link to where each decision landed (the
  Q-nn footnote, the ADR, the `docs/decisions.md` line, the closed issue,
  the PR), including calls that reversed or narrowed an earlier one. The log
  holds the link, not a copy;
- what was tried and abandoned, so the next session doesn't retry it;
- what comes next: the hand-off prompt from step 4, verbatim;
- stamp the memos that argued a question when it's ruled — a dated
  one-line annotation under the memo's H1 naming what settled it, per
  `/reconcile`'s convention. Bodies stay as evidence, never reworded;
- the `/sweep --dry-run` output from step 3;
- observations worth keeping. They go here, silently — never as an aside in
  chat.

## 3. Issues and the board

List the issues this session opened or labelled: one line each, with its
link. Then run `/sweep --dry-run` and put its output in the log. Nothing
else — no board edits, no checking what merged. State lives on GitHub and
`worklist` reads it; a wrap-up that edits it is a second copy. Routing and
format: `/card-write`.

## 4. Hand-off prompt

When the session ends with work still to do, write the prompt that starts
the next one. It must:

- be **ready to paste** — no "as discussed", no context the reader has to
  supply;
- name the **branch, PR, file, card, etc.** it acts on;
- carry **links, not state adjectives** — `#42`, not "PR #42 (merged, CI
  green)". State is read live at the other end; written down it is stale by
  the time it's read;
- **never ask Solace to review or merge.** The PR is where that lives, and
  `worklist` shows him when it is his turn;
- rate every item it puts in front of Solace **twice** — difficulty for
  Solace, and difficulty for an agent with full permissions and high stakes —
  and answer `could an agent do it: yes/no`. Low for an agent means do it, not
  ask;
- name a **recommended model and difficulty (effort) setting** — both,
  every time, e.g. `Model: opus · Effort: high`. A hand-off prompt missing
  either is not finished;
- be written so somebody who was not in this session can act on it.

Put it in the narrative log as well as the chat. The log survives; the chat
does not.

## 5. The closing message

End with a prompt, not a status bullet or observation. A closing that reads
"the vague thing is borked, your call" costs a read and returns nothing
actionable. The closing message holds exactly two things: the hand-off
prompt, and links to the `## Needs ruling` and `## Solace's` cards this
session wrote. Nothing else goes in it. If nothing hit a one-way door, that
half is simply absent — a question you worked around is reported in the PR
body, not here.
