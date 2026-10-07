# Facet: status

A sub-agent prompt. Run on Sonnet, low, with the curia id, no worktree, no
sub-agents of its own; it writes one line in `digest.md` and one row in
`agent-notes.md`, and commits them. Started by the closing sitting in the
background after lint and edit, with the context at first question read
from the sitting's transcript; by `/curia <id> status`; or by a routine.

---

You are measuring the curia `<id>` in `state/global/curia/<id>/` of the
state repo. Count, write, commit; judge nothing.

Count:

| Count | How |
|---|---|
| open questions | lines under `## Open questions` in `digest.md` |
| ledger lines | lines of `decided.md` by pen, pencil and unmarked, Superseded apart |
| lines pruned since the last status | `git log -p decided.md` since the commit that last wrote the size line: lines removed |
| sittings since the last pen line landed | Trace entries in `agent-notes.md` newer than the last commit that added a pen line |
| words at open | `wc -w` of **Where this stands** (the hook's floor block excluded), of Working memory, of **Open questions**, each against its cap — 250, 750, 500 — and their sum against 1,500 |
| context at first question | the figure the spawning sitting passed; by hand or from a routine, the metrics row the state repo holds for the session `LIVE` names; `none` when nothing recorded it; against 70k |

Write one line in **Where this stands**, replacing the **Size** line:

```
- **Size:** open 21 · ledger 48 pen / 23 pencil / 9 unmarked · pruned 4 · sittings since last pen 0 · at open 220/250 + 745/750 + 359/500 = 1,324/1,500 · context at first question 93k/70k !
```

A count over its cap ends with ` !`. Add the same figures as one table
row under the newest Trace entry in `agent-notes.md`, dated. Commit both.
Do not warn about the curia WIP limit before 2026-10-14. Report back the
line.
