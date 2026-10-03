# Cost practices: what the outside world knows, checked against ours

Companion to `token-budget.md`. That file is *measured on this config* and
stays that way. This one is **sourced from elsewhere** — vendor docs and
third-party benchmarks — and every claim carries its provenance, because
none of it was measured here. Where the two disagree, `token-budget.md`
wins: it measured this setup, these numbers measured someone else's.

Provenance tags: **[V]** vendor doc · **[M]** third-party measured
benchmark · **[A]** anecdotal.

## The gap this fills

`token-budget.md` answers two questions well — what the floor is made of,
and why growth (not config) is the bill. It does not cover a third:
**cache churn**. The floor is cheap *because* 83% of it came back as
`cache_read` at 10% of list price. Anything that invalidates the prefix
re-charges that at full rate, and nothing in this repo currently warns
about it.

### What dumps the cache mid-session

- **switching model — measured**, see `token-budget.md`: 73.5-75.7%
  recompute on the next turn at ~50k context, ~65-70k tokens, two runs.
- **changing effort (`/effort`) — measured**, see `token-budget.md`: 100%
  recompute, `cache_read_input_tokens: 0`, worse than a model switch.
- the first fast-mode turn [V]
- connecting or disconnecting a non-deferred MCP server [V]
- denying a whole tool [V]
- `/compact` [V]
- upgrading the CLI, or resuming a session across an upgrade [V]

### What is cache-safe [V]

- editing files, including `CLAUDE.md` (no effect until reload)
- output style, permission mode, skills, slash commands
- `/recap`

### Still unverified: `/rewind`

The claim that `/rewind` re-enters a cached prefix (vs `/compact`, which
doesn't) could not be tested headlessly — `-p --resume` refuses it outright
("`/rewind isn't available in this environment`"), no request sent, zero
usage. It's bound to the interactive REPL. **[V]** only, not measured here;
don't rely on the "beats `/compact`" framing below until someone probes it
interactively.

Two consequences worth acting on:

- **Pick model and effort at session start, not mid-flight — measured, not
  just vendor advice.** Both are cache keys. A switch at ~50k tokens
  reprocesses most of it uncached; effort change reprocesses all of it. See
  `token-budget.md` for the numbers.
- **`/rewind` is claimed to beat `/compact` for abandoning a bad path** — it
  would truncate to an already-cached prefix, where `/compact` is itself a
  full-context request that then rebuilds the prefix from scratch. **[V],
  unverified here** — see above. `/clear` remains free, and remains the main
  event — see `token-budget.md`.

## Counterweight to "search via subagents"

`token-budget.md` ranks subagents third, correctly: a subagent burns its own
window and returns a paragraph. Two costs it does not mention **[V]**:

- a subagent does **not** read the parent's cache
- it gets the 5-minute cache TTL even on a subscription that otherwise has
  an hour

So a short throwaway subagent can be net-negative. The rule holds for what
it was written for — genuinely verbose retrieval — and inverts for anything
small enough to have been two `grep`s.

## Output-filtering hooks: real, but narrowly

A `PreToolUse` hook that rewrites a verbose command into a filtered one —
`npm test` to a grep for failures — turns tens of thousands of tokens into
hundreds. Anthropic ships an example. **[V]** This is real *when it targets
output you were always going to discard*.

The generalised version is not real. Wrappers advertising 60–90% savings on
all Bash output (the `rtk` family) were run by JetBrains over 425 billed
trials on SkillsBench: **median 7.6% cost increase** at low effort, no change
at high effort. **[M]** The advertised figure came from counting raw output
as the counterfactual — output Claude Code would have truncated anyway — and
pricing cached re-reads at full rate. Same shape for "caveman" terse-prompt
skills: advertised −65%, measured **−8.5%** over 86 tasks. **[M]**

The distinction that matters: a hook that knows *this specific command's*
output is noise is a win. A hook that compresses everything is a tax on the
cases where the detail mattered, plus a rewrite bug surface, and it does not
pay for itself.

## Small context is a quality argument, not only a cost one [M]

Chroma's context-rot study across 18 models found degradation that is not
uniform with length: 30+ point accuracy drops for facts sitting mid-context,
and a 7.9% floor loss from length alone. This is the strongest available
argument for `token-budget.md`'s one-task-per-session habit, and it has
nothing to do with money.

## Deliberately not adopted

- **Trimming `CLAUDE.md` to a line count.** The common advice is "under 200
  lines." Measured here, all own-config is 9% of the floor and `CLAUDE.md`
  is 4,123 tokens of it. Halving it buys 2k against a 47.8k floor. Prune it
  when a rule stops earning its keep — the existing maintenance rule — not
  to hit someone else's number.
- **A generic Bash-output compressor.** See above.

## Sources

- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/prompt-caching
- https://code.claude.com/docs/en/hooks
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering/advanced-tool-use
- https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/
- https://blog.jetbrains.com/ai/2026/07/speak-to-ai-agents-like-cavemen-tosave-tokens/
- https://www.trychroma.com/research/context-rot
