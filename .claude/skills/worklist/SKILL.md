---
name: worklist
description: Report a project's status and the next unblocked work, by running the worklist script and reading its output. Use when Solace asks "what's next", "what can we work on", "project status", "what's on the roadmap", "what's outstanding", "what's stale", "what's my turn", asks for a sweep or a reconcile, or says "/worklist".
---

# Worklist

Read-only. Run `~/.local/bin/worklist [project]` — add `--fresh` when Solace
asks for current state rather than what the cache holds — read its output,
add judgment only where a bucket needs it (a dependency the script can't
see, which ready item you'd start first if asked), and stop. Never file,
label, tick or edit anything from here: a sweep, a reconcile and "what's
stale" are all this command plus a report, and they never touch a board,
epic or log.

## Output shape

The script prints it; don't rewrite it into another format. First line
`as of HH:MMZ` (`cached N min` when served from cache), then the repo set
and the account-wide counts, then these buckets. An empty bucket prints
`none` — that is "checked, nothing there", not a failure:

```
Solace's turn             PRs ready for her: not draft, mergeable, checks
                          green, no unresolved threads, no auto-merge
                          (failing check names printed, never a boolean)
Queued (auto-merge)       auto-merge enabled, waiting on checks
Ready                     `ready` issues — agent-startable now
Blocked                   `blocked` issues, with what blocks them
Not ready (agent's turn)  open PRs that are none of the above, with why
Untriaged: N              unlabelled issues, count only
Stranded branches         pushed branches with no PR
Needs ruling              the board's `## Needs ruling` cards, at most 8 —
                          one-way doors only, so normally empty
Board                     the `## Claude's` cards, at most 8
```

Every line carries its repo; the full view carries links too, `--brief`
does not. Failure lines are per cause — `no gh`, `gh unauthenticated`,
`<repo>: 403 — attach the repo`, `network` — and a bucket missing for one
of those reasons is not an empty bucket; say so.

## After reporting

Stop. Don't recommend a single item unless asked — the point is to hand
over the list so Solace can pick what fits the moment (one session, a
subagent, or a stream of several). If asked which one you'd start, give one
sentence naming it before any explanation, per standing orders.
