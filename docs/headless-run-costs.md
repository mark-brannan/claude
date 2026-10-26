# Headless run costs

Every Claude run that leaves no session transcript still has its cost on
record next to the sessions', so `spend` shows what the bots cost. Sessions
with transcripts are priced by the session metrics hooks; this document covers
the rest, wherever its code lives, including outside this repo.

## The record

One JSON line per run, the `headless-run` row. The shape is stable: a field is
added, never renamed or dropped. Run-specific fields ride beside the common
ones.

```json
{"ts": "2026-10-24T14:03:51Z", "what": "claude-review", "repo": "mark-brannan/searoom",
 "pr": 412, "model": "claude-sonnet-5-5", "total_cost_usd": 0.1873,
 "usage": {"input_tokens": 41210, "output_tokens": 2894,
           "cache_read_input_tokens": 118400, "cache_creation_input_tokens": 9120},
 "outcome": "success", "head_sha": "4b45f6d", "tier": "default"}
```

Rows land in the state repo's `metrics/headless-runs`, `metrics-db` loads them
into `headless_runs`, and `spend --by bot` rolls them up by `what`. The cost
lands on the PR a row names; a row from a fork, or from an uploader `spend` does not trust, is costed with no PR.

## The inventory

| Kind of run | Where its code lives | What records it |
|---|---|---|
| Agent-decision judge | this repo, `bin/agent-decision` | the tool writes the row locally |
| Grind workers and other local `claude -p` | this repo | not this mechanism: transcripts exist and the session hooks price them |
| PR review, maxims and arete checks | the shared claude-review workflow in mark-brannan/.github, called by every repo | the shared cost action |
| Searoom issue trial | mark-brannan/searoom | the shared cost action |
| Symphony boat-down triage | mark-brannan/symphony | the shared cost action |
| Cloud routines and cloud sessions | Anthropic's cloud | open, below |

## How a CI run is priced

After its Claude step, the workflow calls the shared cost action in
mark-brannan/.github (`headless-run-cost`, not yet written: mark-brannan/claude#219) and uploads the `headless-run`
artifact. `metrics-db --github` collects every repo's artifacts into the state
repo. Actions expires artifacts after 90 days, so collection runs inside that
window.

## A new one cannot go unpriced

`metrics-db --github` reports any workflow in any repo that runs Claude and
records no cost. A new bot shows up in that report until it is priced.

## Open

Cloud routines and cloud sessions are not priced. Our hooks run there, but the
numbers stay in the sandbox. A decision is pending: mark-brannan/claude#219.
