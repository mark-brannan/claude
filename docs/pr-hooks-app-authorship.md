# The PR hooks once agents post as a bot account: a proposal

Status: proposal, 2026-11-17. Homes: #339, #244, dotfiles#553. Nothing here is
built. A new guard, or a new surface on one, waits until its use case and name
have been reviewed.

Agents' `gh` calls and MCP calls now post on GitHub as a bot account,
`mark-brannan-agent[bot]` (a GitHub App), not as the human; RUNBOOK "Act on
GitHub as the agent App" has the split. Three questions follow from it:
who guards a raw thread resolve, what the PR hooks keep, and whether touches
still need matching.

## The numbers

Measured 2026-11-17 over the last 28 days. Transcript counts are tool calls
matched by regex and deduplicated by call id; no transcript text was read out.

Raw `resolveReviewThread` calls, 4,872 transcripts:

| Path | Calls | How they ended |
|---|---|---|
| Bash `gh api graphql` carrying the mutation | 344 | 193 ran, 68 classifier, 59 a languette message, 23 other errors, 1 permission rule |
| MCP `pull_request_review_write`, method `resolve_thread` | 2 | 2 classifier |
| `gh-resolve-thread`, the sanctioned script | not counted | allowlisted; refused 10 times (8 permission rule, 2 classifier) |

The blocked-call log for the same window has 24 classifier refusals of the raw
mutation across 12 sessions; it records fewer than the transcripts do. The 59
languette messages are not from `guard-review-threads`: it is off in
`settings.json`.

Agent GitHub writes logged by `hooks/log-gh-writes.py`, 28 days: 7,298 writes in
987 sessions. The two verbs that run under the human's login by design:
`git push` 2,921, `gh pr merge` 28.

The human account's last 100 public events (2026-11-12 to 11-17): 83 pushes and
branch creates or deletes, 17 PR, review and issue events, 0 comments signed as
an agent's.

## 1. Which layer guards the raw resolve (#339)

193 raw resolves ran in 28 days, mode unknown (the count is not split by
permission mode), so the classifier's reach is unmeasured; its 68 refusals are
the only evidence about it. A hook does not depend on mode: it runs in every
permission mode (from Claude Code's docs).

Authorship changes one thing. `guard-review-threads` accepts a reply from the
login its own `gh` call sees, or from a login in `review_thread_logins`. In a
session that login is `mark-brannan-agent[bot]` (checked with a `viewer` query),
and the guard already reads the bot account's replies as that login. When a
call runs as the human instead (`AGENT_BOT_OFF`, a fallback) the guard sees the
human, and the bot account's replies count only if the setting lists it.

| Layer | Reaches | Leaves open | Cost |
|---|---|---|---|
| Classifier rule only (today) | gh, MCP, curl, in auto mode | 193 ran, mode unknown | none |
| `guard_review_threads` on, bot login listed | gh, in every mode | MCP, curl, a script | two settings |
| That guard extended to MCP `resolve_thread` | adds MCP | curl | new guard surface: review first |
| A hook in this repo | whatever it names | duplicates languette | one more custom hook |

No layer collides with `gh-resolve-thread`: a hook sees the outer command,
never the mutation the script sends.

Recommended: the second row now. The MCP path had 2 calls, both refused, so it
stays with the classifier.

## 2. What pr-ownership-context and pr-threads-gate keep (#244)

The bot account cannot replace the ownership record: every agent's PR has the
same author, so the author says nothing about which agent holds it.

An agent here is one session, or one sub-agent inside it; ownership lasts as
long as it runs. A session that is killed or handed off leaves no record and
no check; its PR goes back to the pickup list (`/pickup`), and the next session
to hold or push the branch owns it.

| Part | Proposal |
|---|---|
| Rules text, once per session | Keep; inject on the first work call, once per agent, so a sub-agent gets it too |
| The record of PRs touched | Change: an agent owns a PR whose branch it holds or pushed; comments and reads don't count |
| Open threads at Stop | Keep; also at a sub-agent's finish, on its own record. Each check blocks once and then lets the agent go, as the Stop check does today: one nudge, then an honest report of what stays open, never a loop. A parent never gates on a sub-agent's PR |
| Conflicting with its base | Keep |
| Defer a PR whose branch a live sub-agent holds | Drop: a gate never judges liveness ("A gate reads only"); the per-agent record removes the case |

When an author stops working a PR at all is not this gate's call: it follows
whatever bound the pr-chain workflow sets on rounds of fixing, and that bound
may change.

To verify before building: that the hook run at a sub-agent's finish carries
the agent's id, and that agents a Workflow starts carry one too. The second
decides whether the per-agent record covers a batch driver.

## 3. Does the bot account retire the touch matching (dotfiles#553)

Mostly. What still lands under the human's login when an agent acts:

| Write | Why it is the human's | 28 days | A touch? |
|---|---|---|---|
| `git push` | by design | 2,921 | no: pushes are not touches |
| `gh pr merge` | by design: merging stays the human's | 28 | yes |
| Mergify commands from `prt`, `pr-label-audit` | `AGENT_BOT_OFF=1` | not split in the log | no: signed comments |
| Any `gh` call with no bot-account secret, or `GH_TOKEN` set | silent fallback | unknown: the log records no identity | yes, any verb |

Proposed:

- Retire the time-window matching script that dotfiles#553 specifies (a repo
  and a window in, human touches out; the issue gives it no name, and it is not
  yet built).
- Make a fallback say so: one stderr line from the `gh` shim, and the write log
  records which identity each call ran as.
- Touches are the human account's merge, label, review and comment events,
  minus log rows that ran as the human with the same verb and target. The
  join is exact and small, with no time window; signed comments drop out by
  their signature. Log rows from before the identity field lands carry none,
  so events in the first 28 days after it are hand-checked once; after that
  the window holds only rows with an identity.

This changes dotfiles#553's done-when: the hand check of every unmatched event shrinks
to the rows that ran as the human.
