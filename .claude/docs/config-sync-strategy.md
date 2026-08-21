# Syncing ~/.claude everywhere: strategy for issue #17

Proposal for [#17](https://github.com/mark-brannan/dotfiles/issues/17), researched
2026-08-20. Not auto-loaded into sessions; read when working on config sync.
Revised same day to fold in an independent security review of the draft:
verify-then-run bootstrap (H1), touch-required hardware signing key (H2),
downgrade refusal, namespace-bound signers, fingerprint cross-check,
symlink-flip installs, and authorship provenance on auto-pushes (M1-M6,
L1-L2).

**Recommendation in one sentence:** keep dotfiles as the public source of truth,
publish `~/.claude` config through a signed-tag release channel with one installer
script, consume it pinned everywhere ephemeral (cloud setup script, a composite
action for CI), and close the local loop with a scoped Stop-hook auto-commit and a
SessionStart staleness brief.

---

## 1. The problem, precisely

`~/.claude` config (CLAUDE.md, rules/, hooks/, settings.json) is yadm-managed in
this repo, but nothing guarantees any given session runs current config:

- Cloud sessions start from a fresh VM; only the environment's setup script puts
  config there, and today it floats on `main`.
- CI sessions in other repos fabricate `$HOME/.claude` with a bespoke `curl` —
  unpinned, unbounded, and able to leave a mixed old/new instruction set
  (CodeRabbit findings on signalk-noaa-space-weather#97).
- Local machines drift in both directions: push depends on remembering yadm,
  pull depends on running `dotsync`, and neither direction has a staleness signal.

Upstream, this is a known hole. Six anthropics/claude-code issues ask for config
sync (#20697, #22648, #36693, #38970, #47968, #84611, plus four predecessors);
across all of them there is not one staff comment, assignee, or commitment — only
stale-bot closures. Nobody is coming to fix this.

The requests cluster into three distinct gaps:

1. **Cross-machine sync** of `~/.claude` (#22648, #38970, #36693) — a VS Code
   Settings Sync-shaped ask.
2. **Cross-surface skills** (#20697, #47968, #84611): Cowork, Desktop and cloud
   routines resolve skills from a server-side account store with no programmatic
   write, list, or hash API. No amount of file syncing can reach it. **Out of
   scope here** — it is unfixable client-side. See §10 for what to ask Anthropic.
3. **Ephemeral/CI provisioning**: a fresh container has no `~/.claude` at all.

This proposal covers gaps 1 and 3.

## 2. Entry points

| Entry point | How config arrives today | Gap |
| --- | --- | --- |
| Local interactive (Mac, WSL, Pi) | yadm working tree in `$HOME` | manual push/pull, no drift signal |
| Local headless (`claude -p`, cron) | same working tree | same |
| Cloud sessions (claude.ai/code, mobile) | env setup script → `cloud-session-setup.sh` | floats on `main`; per-file copy; env form unversioned |
| CI in other repos (`claude-review.yml`) | bespoke curl per repo | unpinned, non-atomic, bespoke |
| Sub-sessions spawned from cloud | inherit the spawning environment | covered iff cloud is |
| Desktop / Cowork local | reads local `~/.claude` | covered iff local is |
| Cowork remote, cloud routines, claude.ai skills | server-side account store | unreachable client-side (out of scope) |
| Agent SDK harnesses | nothing auto-loads | out of scope until one exists here |

## 3. What exists and what it's worth

`cloud-session-setup.sh` is better than the usual community answer and most of it
should survive: the yadm-machine refusal, the ephemeral-marker requirement, the
INSTALL allowlist, SKIP_GLOBS tripwires, per-file backups, and prune-with-KEEP.
What it lacks is exactly what #17 names: a pin, atomicity across the set, and a
completion signal a session can read.

The continuity hooks prove the two patterns this proposal reuses: Stop-hook-grade
automation ("commits and pushes every Stop, unprompted") and loud degradation
("absence is reported, not repaired" — the state-repo notice).

The env setup-script web form is itself config that nothing version-controls.
Today it holds clone-and-run logic; anything that stays in it should be a
seldom-changing bootstrap, with the logic and the pin in-repo.

## 4. Threat model

Assets:

- **A1 — instruction integrity.** CLAUDE.md and rules steer every session, and
  sessions hold push credentials. Instruction compromise is code execution by
  proxy: a malicious skill or standing order instructs the agent inside its
  permission envelope. Prompt-level supply chain, same severity class as A2.
- **A2 — executable-config integrity.** Hooks, `settings.json` (including the
  statusLine command), and the seed script run as shell on every machine and VM
  at SessionStart/Stop/PreToolUse.
- **A3 — confidentiality.** The repo is public by choice: standing orders, guard
  logic, deny lists, and the state repo's standing-allow are world-readable.
  Accepted; the mitigations are narrow allows and secret exclusion, not
  obscurity. What must never land here stays governed by the existing rules
  (no boats, hosts, services; no secrets).
- **A4 — consistency.** No mixed old/new sets; stale is fine only when announced.
- **A5 — secret exclusion.** `.credentials.json`, `settings.local.json`, tokens
  never enter the sync path.

Threats, in the order they matter:

- **T1 — config-repo compromise, including by the agent itself.** The local
  rule is "commit straight to main" for dotfiles-scale edits, and Claude
  sessions carry Mark's push credentials. A prompt-injected session that edits
  a hook on `main` becomes code running in every unpinned consumer's next
  session. This is the central design driver: the pin-and-review gate is a
  human checkpoint between an agent-writable branch and agent-executing
  sessions — it is not only about external attackers.
- **T2 — fetch-path substitution.** Unpinned `curl`/clone means whatever the
  network returns becomes standing orders. Pin to a commit SHA and verify with
  git itself. (Do not hash GitHub tarballs: codeload archives are explicitly
  not checksum-stable.)
- **T3 — partial failure.** One of two files fetched → mixed instruction set
  (the CodeRabbit finding). Stage everything, verify completeness, then install;
  write the status marker last.
- **T4 — unversioned environment forms.** Per-environment drift with no audit
  trail. Shrink the form's job to a bootstrap that rarely changes.
- **T5 — settings clobbering, both directions.** `settings.json` merges (the
  jq union in `cloud-setup.sh`) must never overwrite machine-local keys — and
  the file is contested territory upstream: Claude Code rewrites it at runtime
  and has stripped keys it didn't set (statusLine, enabledPlugins, hooks —
  anthropics/claude-code#62486). Any design that treats it as declaratively
  owned will see dirty diffs or silent loss.
- **T6 — auto-commit leaking secrets.** Automation that commits `$HOME` paths
  raises exposure; scope it to the allowlist and keep the yadm `pre_commit`
  secret guard in the path.
- **T7 — silent staleness.** Both directions, both local and ephemeral.
- **T8 — the project-dir hook fallback.** Every hook entry in
  `settings.json` falls back to `$CLAUDE_PROJECT_DIR/.claude/hooks/*` when
  the `$HOME` copy is absent — so in a cloud session on a third-party repo,
  an incomplete seed hands user-scope trust to that repo's own files.
  (Independently flagged on the global board, 2026-08-20.) Seed completeness
  is a security property, not a convenience. PR #20 removes the fallback and
  completes the seeded hook set; this design keeps that invariant.

## 5. Requirements

1. **R1 coverage** — every entry point in §2 that is client-reachable.
2. **R2 atomicity** — a session sees the old set or the new set, never a mix.
3. **R3 pinned + reviewed** — ephemeral consumers run a revision a human
   deliberately promoted; bumping is an explicit act (chosen posture).
4. **R4 local push** — Stop-hook-grade, not memory.
5. **R5 local pull** — automated fetch with a visible behind/ahead signal.
6. **R6 failure visibility** — degraded sessions know and say so.
7. **R7 secret exclusion** — enforced by tripwire, not convention.
8. **R8 cheap** — seconds in the setup window, ~a hundred tokens of brief.
9. **R9 testable** — the installer and its failure modes run under CI.
10. **R10 extractable** — no hardcoded owner/repo/paths in the core, so the
    mechanism can become a community tool without rework.

## 6. Design: a signed release channel

### 6.1 Source and channel

The source of truth stays here, public, yadm-managed. Releases are annotated
tags `claude-config/vN` on reviewed commits.

Promotion is a small script (`claude-config-release`) run by Mark on a real
machine: it shows `git diff <last-release>..HEAD -- .claude/`, asks once, then
creates an SSH-signed tag and pushes it. That diff-then-sign moment **is** the
review gate. SSH signing (verified via `ssh-keygen -Y verify`) avoids a gpg
dependency on consumers — Ubuntu VMs have `ssh-keygen`.

The signing key must be **touch-required hardware-backed** — `sk-ssh-ed25519`
(FIDO2) or a Secure Enclave key. This is load-bearing, not preference: local
Claude runs as Mark with file-based keys reachable, and a pattern guard on
`git tag` is bypassable by anything that shells around it. With a
touch-required key, every signature is a physical human act, so a
prompt-injected session cannot mint a valid tag non-interactively — the gate
survives instruction-level compromise. (H2 in the 2026-08-20 security review
of this doc.)

Two supporting layers behind the ceremony, both ergonomics rather than
boundaries:

- A GitHub ruleset protecting `claude-config/*`: no updates, no deletions,
  creation restricted (keeps the claude.ai app actor from minting tags even
  with push access).
- A PreToolUse guard denying `git tag claude-config/*` / `git push` of such
  refs from Claude sessions, mirroring `guard-add-repo.sh` — it catches the
  accidental path, not a determined bypass; the hardware key is the boundary.

Rotation and revocation: replacing the signer line in the environment form
(and the in-repo fingerprint, §6.3) invalidates every tag the old key signed
at the next seed. For fencing off a bad-but-validly-signed release without
rotating, the installer honors a signed floor: it refuses any tag below the
version named in the newest `claude-config-floor/*` tag.

The gate's job is to make promotion a deliberate, visible, signed act rather
than a side effect of any push to `main` — that converts T1 from "every
consumer executes whatever landed last" into "an attacker needs a physical
key touch and an explicit ceremony."

### 6.2 One installer

`cloud-session-setup.sh` evolves rather than being replaced — its guards are
the part the community versions get wrong (see §7). Changes:

1. Run **from a checkout of the promoted revision**, so script and content are
   the same revision — no version skew between installer logic and file set.
   (How the first execution gets verified is §6.3's job — the installer is
   never the thing that authorizes itself.)
2. Stage the full INSTALL set into a versioned dir and flip a single
   `~/.claude-config/current` symlink — the flip is the install, so a crash
   at any point leaves the previous set fully intact. (Promoted from optional
   to the default: per-file `mv` keeps a stage-to-install window open — L2.)
3. Write `~/.claude/.sync-status.json` **last**:
   `{channel, tag, sha, installed_at, complete, source}`. No status file or
   `complete: false` means degraded, and the brief says so.
4. Signature or pin verification failure: install nothing, keep anything
   already present, report loudly. Never fall back to unpinned `main` — and
   never satisfy a failure by selecting an *older* tag (that's a downgrade
   vector, M3). Version moves are monotonic: refuse any tag at or below the
   currently-installed one.
5. Install the *complete* hook set or none of it: a partial set plus the
   `$CLAUDE_PROJECT_DIR` fallback in `settings.json` is T8 — third-party
   code running with user-scope trust. PR #20 removes that fallback and
   seeds the full hook set; this design keeps that invariant.

### 6.3 Cloud bootstrap — seed, then refresh

A fact that reshapes this entry point: cloud environments **cache the
filesystem snapshot after the setup script runs**, for roughly seven days,
invalidated only by editing the script or network list. A setup script that
"fetches current config" actually serves a week-old copy to most sessions.
So provisioning is two-stage:

**Seed (setup script, runs rarely).** The form holds a self-contained
bootstrap whose only trust anchor is the public signing key, embedded in the
script text (env-panel variables don't reach setup scripts). Order is the
whole point — **verify, then run** (H1): the bootstrap itself clones,
resolves the highest `claude-config/v*` tag, writes the signers file from
its own embedded text, runs `git verify-tag`, and checks out the verified
revision — all before executing a single repo-supplied line. Only then does
it exec the installer *from the checkout it just verified*:

```
set -e
SEED="$HOME/.local/share/dotfiles-seed"
git clone -q https://github.com/mark-brannan/dotfiles "$SEED"
printf '%s\n' 'mark-brannan namespaces="git" sk-ssh-ed25519@openssh.com AAAA…' \
  > "$SEED/../allowed_signers"
TAG=$(git -C "$SEED" tag -l 'claude-config/v*' | sort -t/ -k2 -V | tail -1)
git -C "$SEED" -c gpg.ssh.allowedSignersFile="$SEED/../allowed_signers" \
  verify-tag "$TAG"                     # refuses: exit, install nothing
git -C "$SEED" checkout -q "$TAG"
CLOUD_SESSION=1 sh "$SEED/.local/bin/claude-config-install.sh" --tag "$TAG"
exit 0
```

An earlier draft had the freshly-cloned installer do its own verification —
which authorizes nothing, since a compromised `main` ships an installer that
skips the check. The verification an attacker must beat has to live in the
form, upstream of any code the repo supplies.

The signers line binds a principal and `namespaces="git"` (M4) — a signature
lifted from any other SSH-signing context won't verify. The installer
persists it to `~/.claude-config/allowed_signers` for the refresh stage;
where the file outlives a session (local machines), it should be root-owned
(M5). The repo also carries the key's *fingerprint* — never the trust anchor
itself, but a second channel: bootstrap and refresh warn loudly when form
key and in-repo fingerprint disagree (M6).

**Refresh (SessionStart hook, runs every session).** The seeded config
includes a hook step: bounded `git fetch --tags`, verify the newest tag
against the *persisted* signers file, install if newer — never lower (M3) —
update `.sync-status.json` either way. This is what makes a session current
despite the snapshot, and it's where provenance comes from — without it,
"which config is this session running" is unanswerable after the fact.
Auto-refresh does not reopen the gate it bypasses (M1): with the
touch-required key, every tag it can accept began as a physical human act.
Consumers that want a ceiling anyway can pin `--max-tag` per environment.

**Workspace trust does not gate this (verified 2026-08-21).** P0's V1 found
that a cloud workspace has `hasTrustDialogAccepted: false` in `~/.claude.json`,
that no interactive dialog exists to change it headlessly, and that the harness
refuses to write the flag directly — with the session logging `Ignoring N
permissions.allow entries ... this workspace has not been trusted`. Read as
"synced config is inert in cloud", that would sink this whole section. It isn't:
the gate is **project scope**, not user scope. Direct test — a `SessionStart`
hook declared only in a user-scope `~/.claude/settings.json`, run in a workspace
with no trust record at all — fired normally. V3's skill result is the same
shape: seeded `~/.claude/skills` loaded in the very session where a project
`.claude/` was being ignored.

So the seed and refresh stages install to `~/.claude`, and that is exactly the
scope trust leaves alone. Three consequences the design has to carry:

- **Never rely on a project `.claude/settings.json` in an ephemeral session.**
  Anything that must fire everywhere lives on the installer's INSTALL list and
  lands user-scope. This is already how `cloud-session-setup.sh` works; it is
  now a requirement rather than a convenience.
- **Permissions are the unresolved half.** Hooks and skills are confirmed
  user-scope-honored; whether `permissions.allow` from *user* scope survives an
  untrusted workspace was not isolated — V1 only observed the project-scope
  message. Until measured (V5 below), assume a cloud session may run with
  permissions degraded and design hooks to fail visibly rather than silently.
- **The brief reports it.** `.sync-status.json` and the SessionStart brief
  record the workspace trust flag alongside the installed tag, so a session
  running with a degraded permission set says so rather than being diagnosed a
  week later from behaviour.

Bumping the pin needs **no web-form edits** — the form changes only on key
rotation. (Fallback design, simpler but weaker ops: a full commit SHA in the
form. It inherits the snapshot problem — the pin only takes effect when the
form edit invalidates the cache — so it's a fallback, not a peer.)

This also fixes T4: the form's content becomes a stable, documented bootstrap,
and everything that changes lives in git.

### 6.4 CI in other repos

A composite action in this repo, `.github/actions/claude-config`, replaces the
bespoke curl. Consumers pin it the way actions are pinned:

```yaml
- uses: mark-brannan/dotfiles/.github/actions/claude-config@<full-sha>
```

The action checks out dotfiles at that same SHA and runs the installer from it
into `$HOME/.claude`, before the Claude step. Both CodeRabbit findings on
signalk#97 are fixed structurally: the pin is the action ref (auditable in the
consuming repo's history, bumpable by Dependabot PR — which *is* the
per-consumer review gate), and atomicity is the installer's stage-then-install.

### 6.5 Local push (R4)

A Stop hook, same shape as `stop-continuity.sh`: if yadm-managed paths under
`.claude/` on the INSTALL list have uncommitted changes, commit and push them
(`yadm add <paths> && yadm commit && yadm push`), with the existing `pre_commit`
secret guard in the loop and a flock against parallel sessions. Failure lands
in the checkpoint, not in silence. Auto-push to `main` is consistent with the
chosen posture because the gate sits downstream at promotion, not at push.

One exception: `settings.json`. Claude Code rewrites it at runtime (#62486),
so auto-committing it would push runtime churn — and occasionally runtime
*damage* — into the source of truth. The hook diffs it and reports; a human
commits it. Everything else on the INSTALL list (CLAUDE.md, rules/, hooks/)
is agent-untouched at runtime and safe to auto-commit.

Auto-committed pushes carry distinct authorship (the Claude co-author
trailer), because auto-push otherwise launders agent edits under Mark's name
(L1). The promotion diff is the review surface either way — the release
script shows *what* is being promoted regardless of who committed it — but
authorship in the log keeps provenance readable when reviewing that diff.

### 6.6 Local pull (R5)

SessionStart: `yadm fetch` (bounded timeout, offline-tolerant), then report
"local config N behind origin/main — run `dotsync`" in the brief.
Notify-only at first; an auto-apply flag (fast-forward, clean tree only) can
come later if the nagging gets old. Auto-rebasing `$HOME` from a hook while
other sessions run is not worth the risk on day one.

### 6.7 The brief (R6)

One or two lines merged into the existing SessionStart continuity hook — a new
hook would double the fixed context tax:

- `config: claude-config/v3 (current)` — healthy.
- `config: claude-config/v2, v3 available` / `main is 4 commits ahead of v3`.
- `config: DEGRADED — <reason>` — no status file, incomplete install, fetch or
  signature failure.

Known limit, worth stating in the brief's doc comment: a running session will
not re-read a skill it already loaded (#36693), and hook config is cached for
the session (#22679) — a synced change lands silently at the *next* session.
Sync fixes the next session; don't chase mid-session reload.

## 7. What the ecosystem does (surveyed 2026-08-20)

**Community patterns, ranked by credibility:**

1. Dotfiles repo + symlink/copy setup script — the majority answer for
   cross-machine sync. Breaks on: absolute-path symlinks under cloud drives,
   in-session skill caching, and it never reaches ephemeral surfaces.
2. Session-start HTTPS fetch into a fabricated `$HOME/.claude` — the only
   pattern that works in CI containers; every published example floats on
   `main` and installs per-file. Ours (signalk#97) had exactly those findings.
3. Plugin-archive upload for Desktop/cloud surfaces — manual per release, no
   drift detection (no list/hash API upstream).

**`tkkrixi/claude-docs-sync`** (cited in #20697 as a "full working example") was
security-reviewed file-by-file: code is clean, but it syncs *skills only*, one
way, on two surfaces — no settings, hooks, or CLAUDE.md — and the #20697
citation is the author's own comment draft, checked into the repo. No pinning
model: its CLI route symlinks a working tree (uncommitted edits go live), its
marketplace route floats on a branch head once auto-sync is on. Worth
borrowing: the marketplace operational gotchas (per-entry `version` drives
Desktop update detection; the auto-sync toggle converts a pinned commit into a
floating branch — leave it off for any repo you don't control), and two
validation ideas (frontmatter name must match directory; refuse a dirty tree
without `-f`). Not a foundation.

**Official surface** (docs-verified): user-scope `~/.claude` does not carry
over to cloud or CI — materializing it is on us. Plugins can package skills,
agents, commands, hooks, and MCP servers, but not CLAUDE.md or permission
blocks. Plugin *sources* in a marketplace do support real pinning — `ref`
plus full 40-char commit `sha` (sha wins), a `version` field gating updates,
`sha256` for archive sources — but the marketplace catalog layer itself takes
only `ref`, never `sha`, so the top of that chain floats. `claude-code-action`
accepts `settings`, `claude_args`, `plugin_marketplaces`, and `plugins`
inputs. Enterprise managed settings can inject policy CLAUDE.md server-side —
the right shape, wrong tier. Nothing official syncs user config anywhere.

**Multi-machine sync tools** are a commodity: chezmoi-managed `~/.claude` is
the most-written-up pattern, a plain allowlisted git repo in `~/.claude` with
a pull-before/push-after shell wrapper is the folk version, and a half-dozen
young purpose-built CLIs (jean-claude ~152★, cc-sync, dotclaude, two
"claude-sync"s) reinvent the same triangle — git backend, sync on session
boundary, credential exclusion, merge strategy as the differentiator. All are
local-only. trailofbits/claude-code-config (~2.1k★, the category's most
adopted) is curated-defaults distribution, not sync — drift handling is
"re-run the installer". The consistent exclude list across all of them:
`projects/`, `todos/`, `statsig/`, `cache/`, `history.jsonl`,
`.credentials.json`, `settings.local.json`.

**Documented failure stories** worth designing against: 428 of ~46,500
scanned npm packages contained `.claude/settings.local.json`, 33 with live
credentials (Septim Labs; anthropics/claude-code#13106 — the file isn't
gitignored by default); `~/.claude/.credentials.json` holds OAuth tokens on
Linux, so whole-directory `git init ~/.claude` without an allowlist commits
them; `CLAUDE_CONFIG_DIR` is ignored inside devcontainers (#26623); chezmoi's
bolt-on autoPull (SessionStart `chezmoi update --force`) blocks session start
on rebase conflicts. These justify R7-as-tripwire and the notify-only default
in §6.6.

**Nobody has solved** (recurring across every source): user config into cloud
sessions at all (official answer is "commit it to each repo"); atomic, pinned
provisioning with provenance ("this session ran config version X" is
unrecoverable everywhere); and staleness signaling — every failure above was
discovered by behavior, never by a signal. §6 is aimed squarely at those
three, which is also the community-tool opportunity.

Two doc-vs-measured discrepancies to re-verify before building (cheap, one
throwaway cloud session each — see §12): docs imply user-scope settings are
ignored in cloud sessions, but the seeded `deniedMcpServers` deny list
measurably worked; docs imply setup scripts can clone private repos via the
proxy, but the state repo 403s until attached per-session.

## 8. Alternatives considered

- **Plugin as the backbone.** The only mechanism that spans local, cloud, CI
  and devcontainers today, with genuine SHA pinning at the plugin-source
  level. Three disqualifiers for standing orders: it cannot carry CLAUDE.md
  or permission blocks (the core of what needs syncing), the marketplace
  catalog layer is unpinnable (`ref` only), and cloud consumption requires
  declaring the plugin in *every repo's* project settings — per-repo
  duplication of user config. Serious candidate for the hooks/skills subset
  later (§13 P5); wrong foundation for the whole.
- **Move `~/.claude` to a private repo.** Buys confidentiality (A3) at the
  cost of credentials at every ephemeral entry point (CI secrets per consumer,
  env source attachment quirks). A3 is accepted by choice, and the public repo
  is part of the community story. Not worth it; the state repo stays the
  private half.
- **Status-quo plus pinning bolted on.** A SHA pasted into each environment
  form and each workflow, no channel. Works, but every bump is N manual edits,
  drift between consumers is invisible, and nothing marks a revision as
  *reviewed* — a pin to an arbitrary `main` commit gates nothing.
- **Per-repo bespoke fetch (today's CI answer).** Rejected by the issue itself;
  each copy re-earns the same review findings.

## 9. Testing

- **bats suite** for the installer, run in dotfiles CI (ubuntu + macos matrix):
  fresh install; re-run idempotence; INSTALL-entry missing from checkout;
  simulated truncated stage (kill mid-stage — the `current` symlink must
  still point at the previous set); signature failure (must install nothing,
  report); **verify-then-run** (tamper the installer on a fake `main`; the
  bootstrap must refuse before executing it); downgrade refusal (offer a
  lower signed tag; must be rejected); namespace binding (a signature made
  outside `namespaces="git"` must not verify); fingerprint cross-check
  warning; tag resolution version-sorts (`v10` after `v9`, not lexically);
  user-scope install in an untrusted
  workspace (hooks must still fire); SKIP_GLOBS tripwire; prune with KEEP; yadm-machine refusal; dry-run parity.
- **Composite action smoke test**: a workflow in this repo consumes the action
  at HEAD-SHA, then asserts `$HOME/.claude/CLAUDE.md` matches the checkout and
  `.sync-status.json` says `complete: true`.
- **Release script test**: tag creation refused on dirty tree; produced tag
  verifies against the allowed-signers file.
- **Canary**: the existing environment, one throwaway session after each
  promotion — the brief line is the assertion. No standing infrastructure.

## 10. What to ask Anthropic for

Filing one consolidated issue (referencing the cluster) costs little and the
survey shows the asks are currently scattered and stale-botted:

1. First-class environment provisioning from a dotfiles repo for cloud
   sessions — the Codespaces `dotfiles` feature (which runs your `install.sh`
   in every codespace) is the working precedent, plus a pin-to-ref option.
2. SHA pinning for the marketplace catalog layer (plugin sources already
   take one), and manual invalidation or a version stamp for environment
   snapshots — today a setup-script change is the only lever and sessions
   can't tell what config generation they got.
3. The #84611 skill APIs (publish, **list-with-hash**, delete) so cloud
   surfaces stop being write-only-by-GUI.
4. A docs fix stating precisely which `~/.claude` paths are honored in cloud
   and CI sessions when materialized (the V1 discrepancy), and separating
   declarative config from runtime state in `settings.json` (#62486) so sync
   tools stop fighting the product.

## 11. Costs

- Setup window: one clone + verify + copy, same order as today (~5s measured).
- Context: 1-2 brief lines (~50-100 tokens) per session, replacing nothing.
- Promotion friction: one script run per config release — the friction *is*
  the review gate; if it stalls adoption, drop to the SHA-in-form fallback
  consciously rather than un-pinning.
- Maintenance: allowed-signers rotation documented in the release script;
  Dependabot bumps in consumer repos reviewed like any dependency.
- Build cost: installer surgery + release script + action + hook changes, each
  phase shippable alone (§13).

## 12. Verify before building

1. **V1** — user-scope honored in cloud when materialized. **Answered yes,
   with a caveat** ([results](https://github.com/mark-brannan/dotfiles/issues/17#issuecomment-5373161830)):
   user-scope hooks and skills fire; project-scope `.claude/settings.json` is
   ignored in an untrusted cloud workspace and cannot be trusted headlessly.
   See §6.3. Leaves V5 open.
2. **V2** — private repo as second env source: is it cloned/attached at setup
   time, or only via `add_repo` mid-session? Community reports say git
   credentials are populated for SessionStart hooks but not setup scripts —
   which would mean the refresh stage (§6.3) can reach private sources even
   though the seed stage can't. Determines the README note and nothing else.
3. **V3** — seeded `~/.claude/skills` load in cloud sessions: seed one no-op
   skill, ask for it. Decides whether skills join the INSTALL list.
4. **V5** — user-scope `permissions.allow` in an untrusted workspace: seed a
   permission user-scope in a cloud environment, attempt a call it allows, and
   see whether it is honored or the "not been trusted" message names it.
   Decides whether §6.3's degraded-permissions caveat is real or theoretical.
5. **V4** — snapshot caching bounds: edit a comment in the setup script,
   confirm invalidation; measure how stale an untouched environment's seed
   actually gets. Calibrates how load-bearing the refresh stage is.

## 13. Rollout

- **P0** — V1-V5 experiments; file results on #17. V1/V2/V3 answered
  2026-08-21 and folded into §6.3; V4's staleness half and V5 remain.
- **P1** — installer atomicity + status file + brief line, still tracking
  `main`. Fixes T3/T7 immediately; no ceremony change yet.
- **P2** — release script, first signed tag, ruleset, guard hook, bootstrap
  swap in the environment form. Fixes T1/T2/T4.
- **P3** — composite action; PR to signalk replacing the curl step; close the
  CodeRabbit findings there.
- **P4** — local Stop-hook push + SessionStart fetch/notify. Fixes R4/R5.
- **P5** (optional) — extract: template repo + writeup, the Anthropic issue
  from §10. Decide after P1-P4 have run for a few weeks.

Each phase leaves the system strictly better and none depends on a later one.

## 14. Bar for evaluating any quick fix

A patch for #17 (including the one in flight) should be measured against:
pinned to a reviewed revision, not `main` (R3) · old-or-new, never mixed (R2) ·
degraded is announced (R6) · secrets structurally excluded (R7) · covers cloud
*and* CI *and* local, or says which it skips (R1) · failure paths tested (R9) ·
no second copy of install logic to drift (the composite action and the cloud
bootstrap must share the installer).
