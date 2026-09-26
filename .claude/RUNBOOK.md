# Claude Code runbook

Procedures for the Claude Code layer of these dotfiles: the hooks, the cloud
environments, the PR workflows, and what to do when one of them misbehaves.

The machine itself — setup, sync, secrets — is [RUNBOOK.md](../RUNBOOK.md),
and nothing about Claude Code goes there. This file is where a hook, a cloud
seed entry or a workflow gets its procedure.

Procedures only. The hook designs and the scars behind them are in
[README.md § Conventions](../README.md).

## Where things are

**Cloud environments**
- [Create a cloud environment](#create-a-cloud-environment)
- [Attach the state repo to a running session](#attach-the-state-repo-to-a-running-session)
- [Add a file to the cloud seed](#add-a-file-to-the-cloud-seed)
- [Refresh the MCP connector deny list](#refresh-the-mcp-connector-deny-list)

**A real machine**
- [Wire the hooks on a real machine](#wire-the-hooks-on-a-real-machine)
- [Change what the metrics readouts show](#change-what-the-metrics-readouts-show)
- [Check a repo's prose budgets](#check-a-repos-prose-budgets)
- [Prune stale Stop-hook salvage refs](#prune-stale-stop-hook-salvage-refs)

**GitHub repository**
- [Cut and promote a prose-budget engine version](#cut-and-promote-a-prose-budget-engine-version)
- [Set the auth token for the PR review workflows](#set-the-auth-token-for-the-pr-review-workflows)
- [Re-sign a branch whose commits are unsigned](#re-sign-a-branch-whose-commits-are-unsigned)

**PRs**
- [Find all PRs awaiting human review](#find-all-prs-awaiting-human-review)
- [Audit the `awaiting-human` label](#audit-the-awaiting-human-label)
- [Find out which session holds a branch](#find-out-which-session-holds-a-branch)
- [Waive the churn gate on a PR](#waive-the-churn-gate-on-a-pr)
- [Run the PR fixer on a timer](#run-the-pr-fixer-on-a-timer)

**Troubleshooting**
- [Session state went to `~/.claude/state/global`](#session-state-went-to-claudestateglobal)
- [A hook didn't fire in a cloud session](#a-hook-didnt-fire-in-a-cloud-session)
- [A cloud session is running an old rule](#a-cloud-session-is-running-an-old-rule)
- [A deleted hook keeps running](#a-deleted-hook-keeps-running)
- [A grind session keeps printing after it should be done](#a-grind-session-keeps-printing-after-it-should-be-done)
- [PR checks fail immediately with an empty credential](#pr-checks-fail-immediately-with-an-empty-credential)

---

## Create a cloud environment

A Claude Code cloud environment configures exactly four things: **name, network
access, environment variables, and a setup script.** Repositories are *not*
part of the environment — they attach per session, as sources.

**1 — Setup script.** The field only takes pasted text, so every environment's
script is version-controlled here as the source of truth and pasted in by
hand — the field itself is never the record.

`Trusted` and `Full network access` take
[`cloud-session-setup.sh`](../.local/bin/cloud-session-setup.sh)'s caller
verbatim. It only clones and delegates, so the logic stays in the repo rather
than going stale in a web form:

```sh
git clone -q https://github.com/mark-brannan/dotfiles \
  "$HOME/.local/share/dotfiles-seed" 2>/dev/null
CLOUD_SESSION=1 sh "$HOME/.local/share/dotfiles-seed/.local/bin/cloud-session-setup.sh"
exit 0
```

`Default (with tailscale)` needs tailscale installed before the seed exists to
delegate to, so it can't be a bare clone-and-delegate — paste
[`cloud-session-setup-tailscale.sh`](../.local/bin/cloud-session-setup-tailscale.sh)
verbatim instead; it ends with the same clone-and-delegate. Neither variant is
executed by the platform — both files exist only so the pasted text has an
authoritative copy in git. Keep them in sync by hand if either changes.

Measured cost on a cold VM: about 5s, against a ~5 minute window.

Paste the matching variant into **every** environment, not just the one in
front of you. An environment created before this existed has no seed at all,
and a session started in it is indistinguishable from one that has it until
something is missing — which was the whole failure. As of 2026-08-21 that
means `Default (with tailscale)`, `Trusted` and `Full network access`.

**The setup script runs once, when the container is created**, and the
container is then checkpointed and reused. So the blob's `git clone` is the
seed's only chance to be fresh, and it is a no-op forever after. Two things
close that gap and both are in this repo, not in the web form:
`cloud-session-setup.sh` pulls the seed before installing from it, and
`session-start-seed-refresh.sh` re-runs the whole installer on every
SessionStart. A rule edited here therefore reaches the next session with no
re-provision — deliberately live rather than pinned, because these are
interactive sessions and a stale standing order is worse than a changed one.

Only `CLAUDE.md` cannot be refreshed in place: it is loaded before any hook
runs. When the refresh rewrites it, the hook emits the new copy as
`additionalContext` so the current session gets it too.

**2 — Sources.** Add **both**:

- `mark-brannan/dotfiles` — carries `.claude/settings.json`, so any session
  started on this repo gets the hooks even with no user-scope settings at all.
- `mark-brannan/claude_prompts_scratch` — the private state repo. The
  continuity hooks read the board from it and write their state back to it.
  **The setup script cannot clone this**: a VM has no credentials for a private
  repo at setup time, and the GitHub proxy 403s any repo not attached. Without
  it the hooks still run but write to `~/.claude/state/global`, which dies with
  the container.

**3 — Network access.** Outbound HTTPS goes through the environment's proxy.
Leave it at whatever policy the other environments use unless a session
actually needs a host that is being blocked; widening it is a deliberate
decision, not a default.

**4 — Environment variables.** Nothing in this repo requires one. The two the
seed script reads are set inline by the paste blob (`CLOUD_SESSION=1`) or by the
harness (`CLAUDE_CODE_REMOTE=true`), so the field stays empty.

**Verify** on the next session: `session-start-continuity.sh` prints a
`config: <channel>@<sha> (installed <timestamp>)` line, then the worklist brief. A
`config: DEGRADED` line means the installer never ran or didn't finish —
see [a deleted hook keeps running](#a-deleted-hook-keeps-running) for the
same `~/.claude/.sync-status.json` check. If it instead prints a "state repo
NOT available" notice, step 2 did not take — see [attaching it to a running
session](#attach-the-state-repo-to-a-running-session).

## Attach the state repo to a running session

Needed every cold session where `claude_prompts_scratch` was not attached as a
source. There is no environment setting that does this for you.

1. `mcp__Claude_Code_Remote__add_repo` with owner `mark-brannan`, repo
   `claude_prompts_scratch`, access `push`.
2. Clone it to `/workspace/claude_prompts_scratch` — a path `state_repo()`
   in `.claude/hooks/lib-state.sh` already searches.

The other paths it searches, in order: `$CLAUDE_STATE_REPO`,
`/home/user/claude_prompts_scratch`, `/workspace/claude_prompts_scratch`,
`~/claude_prompts_scratch`, `~/src/…`, `~/Projects/…`, `~/code/…`. Setting
`CLAUDE_STATE_REPO` wins over all of them if the clone landed somewhere else.

## Add a file to the cloud seed

Edit the `INSTALL` allowlist in `.local/bin/cloud-session-setup.sh` — repo-
relative paths, one per line, copied to the same path under `$HOME`. Expand
deliberately: every line lands in every cloud session.

```bash
$EDITOR .local/bin/cloud-session-setup.sh
sh .local/bin/cloud-session-setup.sh --dry-run   # safe on any machine, including yadm-managed
```

Two guards make expansion safe, and both will simply refuse rather than warn:

- `SKIP_GLOBS` hard-blocks `.gitconfig*`, `.gitignore` and anything sops-shaped
  even if added to `INSTALL` by mistake.
- The script refuses to run where `$HOME` is yadm-managed, and skips entirely
  unless `CLOUD_SESSION=1` or `CLAUDE_CODE_REMOTE=true`.

If the new file lives in a directory not already in `OWNED_DIRS`, decide
whether that directory is *wholly owned* by this script. Only wholly-owned leaf
directories go in `OWNED_DIRS` — the script links them into `$HOME` as a
single symlink to the staged release rather than mirroring them file by file;
`OWNED_NEVER` lists the shared ones that must never be linked that way.

**Every hook `.claude/settings.json` references must be in `INSTALL`, and so
must every library a hook loads (`lib-*.awk`).** A convenience hook wired in
settings but missing from the seed is a silent no-op in every cloud session —
its settings entry is `[ -f ]`-guarded and ends in `|| true`, so it looks
identical to a hook that ran and found nothing to do. A gate hook
(`no-git-footguns`, `no-rm-tree`, `no-unsigned-push`) is
the opposite: its entry denies when the file is missing or crashes, so a
seed gap there blocks every Bash call with a message naming the hook. After
editing either file, diff the two lists (CI runs the same check):

```bash
{ grep -o '\.claude/hooks/[a-z-]*\.sh' .claude/settings.json
  grep -ho 'lib-[a-z-]*\.awk' .claude/hooks/*.sh | sed 's|^|.claude/hooks/|'; } | sort -u
sed -n '/^INSTALL=/,/^"$/p' .local/bin/cloud-session-setup.sh | grep hooks/
```

## Refresh the MCP connector deny list

Cloud sessions get claude.ai connectors delivered server-side, and their tool
schemas are the largest fixed cost in the context floor. Deny is **by name**, so
a connector added to the account later is not covered until this list is
refreshed.

1. Run the `ListConnectors` tool in a session to get the live list.
2. Server names are the connector's display name with spaces replaced by
   underscores.
3. Update the `DENY` array in `.claude/cloud-setup.sh`, and mirror any addition
   into `deniedMcpServers` in `.claude/settings.json`.

`cloud-setup.sh` merges rather than clobbers — an existing `settings.json`
keeps its other keys and its existing `deniedMcpServers` entries are unioned
with the new ones — and it degrades to a non-`jq` path when `jq` is absent.

```bash
sh .claude/cloud-setup.sh
jq '.deniedMcpServers | length' ~/.claude/settings.json
```

Note `disableClaudeAiConnectors` in `.claude/settings.json` does **not** do this
job: it governs the CLI's own auto-fetch path, not the server-side delivery
cloud sessions use. `deniedMcpServers` merges across all settings sources and
beats every allowlist.

## Wire the hooks on a real machine

Nothing to do — `yadm clone` puts `.claude/settings.json` and
`.claude/hooks/` in `$HOME`, which is user scope, and every session on the
machine reads them. Hook commands resolve against `$HOME/.claude/hooks/`; the
cloud seed's whole job is to put the same files at the same path on a VM.

To confirm on a machine you have just set up:

```bash
ls ~/.claude/hooks/
bash ~/.claude/hooks/statusline-metrics.sh   # prints the status line, or nothing
```

Then start a session: `session-start-continuity.sh` injecting the worklist brief
is the end-to-end proof.

## Change what the metrics readouts show

Two readouts print session metrics: the **statusline row**, always on, and the
**event block**, shown at a question, a git event and session end. They share
one vocabulary and one set of layouts in `.claude/hooks/lib-metrics-fmt.jq`.
Edit that file, not the scripts.

| File | What it owns |
| --- | --- |
| `session-metrics.jq` | the measurement — tokens, turns, decisions, time |
| `metrics-live.sh` | writes the cache; prints the two-line event block |
| `statusline-metrics.sh` | prints the one-line statusline row |
| `lib-metrics-fmt.jq` | **every field and both layouts** |

Fields are `env`, `cost`, `time`, `dec`, `turns`, `work` (plus `split`, unused).
Layouts are `row` and `block`. Both draw from one `fields` list, so field order
cannot drift between them.

**Hooks load from `$HOME/.claude/hooks/`, not from a clone.** Edit the file
under `$HOME`, or copy it there afterwards — a change made only in another
checkout of this repo will render nothing different and give no error.

Then verify — this is the step that matters, because **every call site ends in
`2>/dev/null`**. That is correct for a hook, since a broken format must never
break a session, but it means a jq syntax error looks exactly like "no metrics
yet":

```bash
metrics-preview.sh --fields
```

It runs the real scripts — not a copy of their jq — against your newest
transcript, and prints: the compile check, the two paths that must stay silent,
the event block for all three event types, the statusline row, each field with
its width, and a column ruler. Exit status is non-zero if any check fails, so
it also works as a pre-commit or CI step:

```bash
metrics-preview.sh --quiet
```

Silent and exit 0 when everything passes; prints only the failures otherwise.

The two silence checks are there because a regression in either is invisible
during a session rather than noisy: a leak on the `prompt` event turns the
block into model context instead of display, and a leak in the git-command
filter runs a transcript-wide jq pass after every `ls`.

Widths worth knowing: the block's header pads to 30 columns, and the desktop
UI prefixes **each line** with `PostToolUse:<tool> says:` — 50 characters on
its own for a long MCP tool name — then wraps around 75. `--fields` shows which
field is eating the budget when a line wraps.

## Check a repo's prose budgets

`prose-budget` reads `docs/budgets.json` (or `.prose-budgets.json`), walking
up from the current directory; a repo with neither is skipped. The commit
hook runs `--staged` and denies the commit on findings. `--base` is not yet
wired into this repository's CI — `hook-tests.yml` only runs the engine's own
test suite — so a finding that a local commit lets through (`--file`,
`--only`, an uncommitted skip) has no CI backstop today.

```bash
prose-budget --tree                     # every tree rule, whole repo
prose-budget --staged                   # what the commit hook sees
prose-budget --base origin/main         # what CI sees for this branch
prose-budget --tree --file docs/x.md    # one file, as the edit hook does
```

Exit 0 is clean, 1 lists findings as `file:line: rule: message`, 2 is a bad
config. Cut the prose first; the config, never the engine, is where a limit
that is genuinely wrong gets changed (the `narration` message prints the hash
to grandfather).

A config change that weakens the guard — a cap raised, an exemption added, a
rule switched off — is itself a finding unless it is the only thing in the
diff. Land it alone, with the reason in the commit or PR body:

```bash
git add docs/budgets.json && git commit          # nothing else staged
prose-budget --staged                            # "config: weakened, landing alone -- ..."
```

Staging anything beside it fails, and names what rode along:

```bash
prose-budget --base origin/main | grep ': config:'   # empty unless a weakening rode along
```

```bash
prose-budget --tree; echo "exit $?"     # 0, and one "OK" line
```

## Prune stale Stop-hook salvage refs

The Stop hook's salvage pushes `refs/heads/wip/<session-id>` to origin, and
nothing else deletes them. Run on a machine with the state repo checked out:
the checkpoint is how a ref is proven landed.

```bash
prune-wip-refs           # preview
prune-wip-refs --delete
```

Verify: exit 0 and a final `deleted N wip ref(s)` line; each deletion line
carries its undo. `prune-wip-refs --help` has the rules.

## Cut and promote a prose-budget engine version

An immutable `prose-budget/vX.Y.Z` tag here names the engine; a moving `v1`
on `mark-brannan/.github` names the workflow that fetches it. Consumers pin
`v1` and nothing else — never add a `dotfiles-ref` to a consumer. No checkout
below, so nothing touches `$HOME`.

```bash
# 1. tag the SHA of the latest green hook-tests run on main, named from its VERSION line
read -r SHA OK < <(gh run list --repo mark-brannan/dotfiles --workflow hook-tests.yml \
  --branch main --limit 1 --json headSha,conclusion --jq '.[0] | "\(.headSha) \(.conclusion)"')
TAG="prose-budget/v$(gh api "repos/mark-brannan/dotfiles/contents/.local/bin/prose-budget?ref=$SHA" \
  --jq .content | base64 -d | awk -F'"' '/^VERSION = / {print $2; exit}')"
echo "$OK $TAG"                                   # success prose-budget/vX.Y.Z
gh api -X POST repos/mark-brannan/dotfiles/git/refs -f ref="refs/tags/$TAG" -f sha="$SHA"

# 2. PR on mark-brannan/.github: set the dotfiles-ref default in
#    .github/workflows/prose-budget.yml to $TAG. Merge it. Then promote:
PREV=$(gh api repos/mark-brannan/.github/git/ref/tags/v1 --jq .object.sha)
gh api -X PATCH repos/mark-brannan/.github/git/refs/tags/v1 \
  -f sha="$(gh api repos/mark-brannan/.github/commits/main --jq .sha)" -F force=true

# 3. verify: the workflow at v1 names $TAG ...
gh api 'repos/mark-brannan/.github/contents/.github/workflows/prose-budget.yml?ref=v1' \
  --jq .content | base64 -d | grep -c "default: $TAG"            # 1
# ... and the next consumer PR's prose-budget job fetched it (its log echoes the input)
gh api repos/mark-brannan/colregs/actions/jobs/<job-id>/logs | grep -c "dotfiles-ref: $TAG"   # 1
```

Roll back with the same `PATCH` and `-f sha="$PREV"`.

## Set the auth token for the PR review workflows

`claude-code-review.yml` runs on every PR via `anthropics/claude-code-action@v1`,
authenticating through the `claude_code_oauth_token` input, which reads the
`CLAUDE_CODE_OAUTH_TOKEN` secret. The OAuth token bills against a Claude
subscription rather than metered API credit.

This is a **GitHub repo secret, not a sops secret.** Nothing about it lives
in this repo: `secrets/`, `.sops.yaml` and the bootstrap are not involved. It
is set once per repository, and no machine setup does it for you.

**1 — Mint the token.** From Claude Code on a machine already logged in:

```bash
claude setup-token
```

It prints a long-lived token tied to your subscription. It is not an API key
and will not work in `ANTHROPIC_API_KEY`.

**2 — Set it.** Never paste a token onto the command line — it lands in shell
history. Let `gh` prompt, or pipe it in:

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo mark-brannan/dotfiles
# reads from the prompt; nothing is echoed, nothing is stored locally
```

Without `gh`: the repo's Settings → Secrets and variables → Actions → New
repository secret. Name it exactly `CLAUDE_CODE_OAUTH_TOKEN`.

**3 — Verify.** `gh` never prints a secret's value, so the only proof is that
the name exists and that a run goes green:

```bash
gh secret list --repo mark-brannan/dotfiles     # the name, with a set date
```

Then re-run the failed checks on any open PR. **Setting a secret does not
retroactively rerun anything** — a PR that failed before it existed stays red
until something kicks it:

```bash
gh run list --repo mark-brannan/dotfiles --limit 5
gh run rerun <run-id> --failed --repo mark-brannan/dotfiles
```

`review` should now complete and comment on the PR.

The token expires. When `review` starts failing on PRs that used to pass and
nothing about the workflow changed, re-run `claude setup-token` and set the
secret again — same procedure, no other cleanup.

This repo is public. Actions secrets are not exposed to workflows triggered by
forked PRs, so this is safe under the current setup — true here because only
the owner pushes.

CodeRabbit is configured by `.coderabbit.yaml` and authenticates as a GitHub
App. It needs no secret, so none of this affects it.

## Re-sign a branch whose commits are unsigned

**When:** a PR says *"All commits must have verified signatures"*, or the
`no-unsigned-push` hook refused a push. Commits come out unsigned from cloud
sessions (no key on the VM), from plumbing such as `git commit-tree`, and
from anything run with `-c commit.gpgsign=false`. The fix is the same for
all three, and it runs from any machine that has the signing key, never from
the cloud session.

**Never reach for GitHub's own "Update branch" instead** — neither the button
nor `gh pr update-branch`, in either form. The `--rebase` form rewrites the
commits and does not re-sign them, so a branch that verified before the call
comes back with every commit unsigned; the merge form keeps signatures but
adds a merge commit that `required_linear_history` rejects. On a repo carrying
both rules there is no form that works, and the damage looks like a different
problem: the PR simply swaps one silent block for another. The
`no-update-branch` hook refuses the subcommand for this reason.

From any checkout of the repo; it works in a throwaway worktree, so the
branch you have checked out and any uncommitted work are untouched:

```bash
resign-branch.sh <branch>
```

It resets local `<branch>` to `origin/<branch>`, rebases onto the tip of the
PR's base branch with `-S` (which re-signs every commit and drops any "Update
branch" merge commits), verifies each one locally, and force-pushes with
lease. The base comes from GitHub, so a stacked PR stays on its parent; with
no open PR it uses the default branch, and `RESIGN_BASE=<branch>` names the
base by hand when `gh` can't answer. It also runs when the branch is merely
behind its base, so it doubles as a signed, linear "Update branch". Running
it on a branch that already verifies and is up to date does nothing. It
refuses if any clone of the repo on this machine — `~/dotfiles` and yadm's
both count — has local commits on the branch that are not on origin, if
the rebase conflicts, or if linearizing would drop content from a
hand-resolved merge commit — in every case the branch is left as it was. Your working tree is
never touched, dirty or not: all the rewriting happens in a throwaway
worktree, so there is nothing to stash first.

Verify on GitHub — every line must say `true`:

```bash
gh api repos/<owner>/<repo>/pulls/<n>/commits --jq '.[]|"\(.sha[0:7]) \(.commit.verification.verified) \(.commit.message|split("\n")[0])"'
```

If the local verify step reports every commit as `U` or `E` instead of
`G`, `~/.ssh/allowed_signers` is missing or in the wrong column order. The
format is `<email> <key-type> <key>` — email first, unlike
`authorized_keys`. The script builds a temporary one when none is
configured, so this only matters for `git log --show-signature` by hand.

## Find all PRs awaiting human review

https://github.com/pulls?q=is%3Apr+state%3Aopen+archived%3Afalse+sort%3Aupdated-desc+label%3Aawaiting-human+user%3Amark-brannan

Across your own repos that use the `awaiting-human` label. Not all repos do.
Without `user:mark-brannan`, the search spans every public repo on GitHub,
not just yours.

## Audit the `awaiting-human` label

The search above only finds pull requests the label *reached*. Two silent
failures keep it away: a repository that never defined the label (Mergify's
label action is then a no-op and reports nothing), and a repository with no
`ci-gate / gate` check (the rule never matches). Both look exactly like "no
work waiting". Run the audit to tell them apart.

```bash
~/dotfiles/.local/bin/pr-label-audit
```

Read-only by default — it reports, it never labels, pushes or merges. Override
the account with `PR_LABEL_AUDIT_OWNER=<owner>`. Three flags, combinable:

| Flag | What it does |
| --- | --- |
| `--json` | One JSON object per open PR (mergeable, labels, head sha, unresolved threads, failing checks, and the `section` it fell in), then one `repos_missing_fixup_hard` object. With `--pr` that fleet-wide object is omitted |
| `--pr owner/repo#n` | The same report for one pull request, text or `--json`. Drafts print a note on stderr and nothing else |
| `--refresh` | The one write: posts `@mergifyio refresh` on every PR in the two "label disagrees with reality" sections below. Skips a PR whose last comment is already that, from this account, within 24h |

It prints up to seven diagnostic sections, each with its own fix, and then
`## Your turn` with the pull requests that really are yours:

| Section | What to do |
| --- | --- |
| Repositories whose labels could not be read | The lookup failed — neither confirmed missing nor present. Re-run; if it persists, `gh auth status`, or the repo was renamed/archived. Do **not** create the label on the strength of this |
| Repositories that do not define the label | `gh label create awaiting-human -R mark-brannan/<repo> -d "Green and thread-free: it is your turn"` — the command is in the output |
| Repositories that do not define `fixup-hard` | Same failure, different rule: a fixer session that gives up has nowhere to say so. The `gh label create` command is in the output |
| No `ci-gate / gate` check | Adopt the reusable ci-gate workflow, or accept that those PRs are manual |
| Gated, unlabelled | Hand each to a session to finish; nothing updates them meanwhile |
| Green and thread-free but NOT labelled | Re-run with `--refresh` first. If it stays, the Mergify rule itself is broken — read `mark-brannan/.github`'s `.mergify.yml` |
| Labelled but no longer green | The toggle hasn't caught up: re-run with `--refresh`, and re-check before treating it as your turn |

Verify:

```bash
~/dotfiles/.local/bin/pr-label-audit | grep '^## '
```

Every run ends with a `## Your turn (N)` line, so that line alone means the
audit completed and found nothing wrong — not that it failed. A run that
prints nothing, or exits non-zero with `the GitHub query failed`, is a
credential or rate-limit problem: check `gh auth status`. An empty section is
omitted rather than printed empty, so the heading count varies by day.

The audit refuses rather than under-reports: it follows the search cursor, and
if the account ever exceeds GitHub search's 1000-result ceiling it exits
non-zero with `more than 1000 open pull requests` instead of printing a
truncated report that looks complete.

## Find out which session holds a branch

Every session that opens on a branch with a PR or a pointer issue stamps that
card with a claim — session id, branch, an opaque machine token and a UTC
timestamp — and its Stop hook refreshes the timestamp while it is alive.
`git worktree list` only sees this machine; the stamp is what a second machine
can read.

From a checkout of the branch:

```bash
~/.claude/hooks/claim-stamp.sh read -C .
```

One line per claim: `live` or `stale`, the session, the machine, the age, the
card. `live` means assume the other session is still working — don't push to
the branch. `stale` means the session died without releasing it; the next
`claim` on that card deletes it, so there is nothing to clean up by hand.
`no card` means the branch has no PR and no pointer issue, so there is nowhere
to stamp: `branch-home-gate.sh` will say the same thing at the end of the
session.

Fleet-wide, the `claimed` label is the cheap filter — `pr-label-audit --json`
reports it per PR. The first claim on a repo creates the label (the issues
endpoint creates a label it is asked for), so a repo where it never appears
is one where no session has ever claimed a card, not one missing setup.

Verify the whole loop by hand: open a second session on the same branch and it
prints a warning naming the first at start-up; `/wrapup` the first and
`claim-stamp.sh read -C .` no longer lists it.

## Waive the churn gate on a PR

`churn-ok` is a human-applied label — `public-issue-guard.sh` blocks a
session from adding it, so this is a step you run yourself, not Claude.

```bash
~/dotfiles/.local/bin/mark-as-churn-ok.sh <PR#>
```

Verify: `gh pr view <PR#> --json labels -q '.labels[].name'` lists
`churn-ok`.

If it fails with `'churn-ok' not found`, the label doesn't exist on the
repo yet — create it once:

```bash
gh label create churn-ok --repo mark-brannan/dotfiles --color FBCA04 --description "Waives the churn-diff gate (human-applied only)"
```

## Run the PR fixer on a timer

`grind --prs` every four hours, on one repository checkout. Do this **only on
the machine that holds the signing key** — elsewhere grind refuses the run and
the wakeup is wasted.

The unit is templated on the path below `$HOME`, with `/` written as `-`:

```bash
systemd-escape "src/colregs"          # prints src-colregs; a repo at ~/dotfiles is just `dotfiles`
```

Enable it, then run it once by hand rather than waiting four hours for the
first answer:

```bash
systemctl --user daemon-reload
```

```bash
systemctl --user enable --now grind-prs@dotfiles.timer
```

```bash
systemctl --user start grind-prs@dotfiles.service
```

**Verify**, and read the log rather than the timer — three of the four ways
this fails leave the timer looking perfectly healthy:

```bash
systemctl --user list-timers grind-prs@dotfiles.timer
```

```bash
tail -30 ~/.local/state/grind/timer-dotfiles.log
```

The log ends in a tally — `done: PR queue exhausted. Running total $N / $5.00. N skipped.`
— or `grind: no unfinished PRs on <repo>`, with a timestamp inside the window.
Anything else is one of these, and each says so on its own line:

- `needs a signing key` — the key is not on this machine, or the user manager
  cannot see the agent that holds it. Wrong machine, or enable lingering.
- `current directory is not a checkout of` — the instance name does not match
  a repo under `$HOME`. Re-run `systemd-escape`.
- every item `FAILED` with no result text — `claude` is not on the unit's
  PATH. Put the real one in `~/.config/grind-prs.env`:

  ```bash
  printf 'PATH=%s\n' "$PATH" > ~/.config/grind-prs.env
  ```

Stop it:

```bash
systemctl --user disable --now grind-prs@dotfiles.timer
```

---

## Session state went to `~/.claude/state/global`

`claude_prompts_scratch` is not checked out where `state_repo()` looks, so the
hooks degraded to a local, unpushed directory. On a cloud session it dies with
the container.

```bash
ls -d /workspace/claude_prompts_scratch/.git ~/claude_prompts_scratch/.git 2>/dev/null
```

Cloud session: [attach it](#attach-the-state-repo-to-a-running-session). Real
machine: clone it to one of the searched paths, or export
`CLAUDE_STATE_REPO=/path/to/it`. Anything already written to
`~/.claude/state/global` can be copied across by hand; nothing does that for you.

## A hook didn't fire in a cloud session

Check in this order:

```bash
ls ~/.claude/hooks/                              # did the seed run at all?
grep -n 'the-hook-name' ~/.claude/settings.json  # is it wired?
```

- Nothing in `~/.claude/hooks/` → the setup script did not run. The seed skips
  entirely unless `CLOUD_SESSION=1` or `CLAUDE_CODE_REMOTE=true`, so a paste
  blob missing the `CLOUD_SESSION=1` prefix is a silent no-op.
- Wired in settings but absent from `~/.claude/hooks/` → it is not in
  `INSTALL`. See [adding a file to the seed](#add-a-file-to-the-cloud-seed).
  This is the common one, and it is silent by design.
- Present and wired → run it by hand (`bash ~/.claude/hooks/<name>.sh`). A
  convenience hook's settings entry ends in `|| true` and most redirect
  stderr, so one that errors every time looks identical to one that is not
  wired. A gate hook that errors denies every Bash call instead and says so.

The seed is not the only path that works: a repo carrying its own
`.claude/settings.json` gets its project settings loaded in a cloud session even
with no user-scope settings at all. What the seed buys is the *other* repos.

## A cloud session is running an old rule

The seed checkout at `~/.local/share/dotfiles-seed` is a real clone, so ask it:

```bash
git -C ~/.local/share/dotfiles-seed log --oneline -1
```

Behind `origin/main` means the refresh is not running. Either the container
predates it — `ls ~/.claude/hooks/session-start-seed-refresh.sh` — or the pull
failed, which the installer reports rather than swallowing:
`CLOUD_SESSION=1 sh ~/.local/share/dotfiles-seed/.local/bin/cloud-session-setup.sh`
prints the reason. A blocked proxy leaves the last-known-good seed in place on
purpose; that is a stale session, not a broken one.

## A deleted hook keeps running

`$HOME/.claude/hooks` is a symlink to `~/.claude-config/current/.claude/hooks`
(and `.claude/rules` the same), so a file dropped from `INSTALL` simply isn't
in the next staged release — there is no separate prune step to fall out of
sync, unlike the per-file-copy design this replaced. If a stale hook is still
running, check first that its directory is actually in `OWNED_DIRS` in
`.local/bin/cloud-session-setup.sh` — a file outside those two directories is
linked individually and a rename can leave the old name behind:

```bash
ls -la ~/.claude/hooks   # should be a symlink -> ~/.claude-config/current/.claude/hooks
cat ~/.claude/.sync-status.json   # sha/installed_at of what's actually live
```

If the symlink target is stale (points at a release dir other than
`~/.claude-config/current`'s own target, or is missing), re-run the installer:
`CLOUD_SESSION=1 sh ~/.local/share/dotfiles-seed/.local/bin/cloud-session-setup.sh`.
If the hook's directory isn't in `OWNED_DIRS` at all, add it there — that's the
structural fix, not a one-off `rm`.

## A grind session keeps printing after it should be done

A worker's own child process (an MCP server it started, most often) can
outlive it and hold grind's output pipe open, so the heartbeat keeps saying
"still working" long after the actual work is finished. Find and stop it:

```bash
ps -ef | grep '[.]local/bin/grind'                    # the grind pid
ps --ppid <grind pid>                                 # its live children, if any
kill -TERM <grind pid>                                # graceful: releases the lock too
```

`kill -TERM` is enough on a current checkout: the lock's cleanup trap fires
on TERM as well as on normal exit. If the process ignores it, `kill -KILL`
and then remove the lock by hand:

```bash
rmdir "${XDG_STATE_HOME:-$HOME/.local/state}/grind/locks/$(printf '%s' owner/repo | tr '/' '_').lock"
```

Verify: `ps -p <grind pid>` reports no such process, and
`ls ~/.local/state/grind/locks/` no longer lists that repo's lock — a
`grind --resume <session-id>` on the same repo should then start rather
than refuse with "another grind is already running."

## PR checks fail immediately with an empty credential

A check goes red about 30 seconds in, on every PR, including ones that change
nothing relevant. The tell is in the job log's env group:

```bash
gh run view <run-id> --repo mark-brannan/dotfiles --log \
  | grep -i 'CLAUDE_CODE_OAUTH_TOKEN'
```

A name with nothing after it means that repository secret is unset or empty —
the workflow is fine, the credential is missing. Then
[set it](#set-the-auth-token-for-the-pr-review-workflows) and rerun the failed
jobs; a secret does not apply retroactively.

Not this if the failure comes minutes in rather than seconds — that is a real
finding, a rate limit, or an expired token, not a missing one.
