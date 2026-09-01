# Trust anchor for #17: signed tag vs SHA-in-form

Both options answer the same question: *what does an ephemeral consumer trust
before it executes a single repo-supplied line?* The strategy doc (§6.1, §6.3)
designs around the signed tag and names the SHA as a conscious fallback (§11).
This is the comparison, not a recommendation.

## The two shapes

**Signed tag.** The environment form holds a fixed bootstrap whose only
embedded secret-equivalent is a public signing key. It clones, resolves the
highest `claude-config/v*` tag, verifies the SSH signature against that
embedded key, checks out the verified revision, then execs the installer from
it. Releases are minted by a promotion script that shows the diff since the
last release and signs with a touch-required hardware key.

**SHA-in-form.** The form holds a full commit SHA. The bootstrap clones,
checks that SHA out, and runs. Git's own object naming is the integrity check;
there is no signature and no channel.

## Where they differ

**Who can promote.** The signed tag's boundary is physical: a prompt-injected
local session running as Mark, with push credentials and file-based keys
reachable, still cannot mint a valid tag without a key touch. That is the
answer to T1 — the threat the doc calls its central design driver. The SHA has
no promotion event at all; whoever can edit the environment form can point every
consumer at any commit, and a session that can edit files can propose a commit
the form later points at. The gate is entirely in Mark's hands at edit time,
with no artifact recording that a diff was reviewed.

**Cost of a bump.** Signed tag: run the release script once, and every consumer
picks it up — cloud via the refresh hook, CI via the tag. No form edits ever,
except on key rotation. SHA: N manual edits, one per environment form and
workflow, each an opportunity to skip one. Drift between consumers becomes
invisible because there is no shared name for "current".

**The snapshot problem.** Cloud environments cache the filesystem after setup
runs, ~7 days, invalidated only by editing the setup script. The signed tag
routes around this: the SessionStart refresh stage re-resolves and re-verifies
every session, so a stale snapshot self-corrects. A SHA pin only takes effect
when the form edit invalidates the cache — the pin and the invalidation are the
same act, which is tidy, but it means between bumps every session runs the
snapshot and there is no mechanism that notices.

**Revocation and floors.** The signed tag has both: rotate the key line to
invalidate every prior signature at the next seed, or publish a
`claude-config-floor/*` tag to fence off a bad-but-validly-signed release
without rotating. The SHA has neither — remediation is editing every form again
and hoping no consumer's cache is warm.

**Downgrade and monotonicity.** The tag channel enforces "never accept a tag at
or below the installed one" (M3) and the refresh stage can be ceilinged with
`--max-tag`. A SHA is unordered; nothing distinguishes a rollback from a bump,
so an attacker with form access can silently pin a consumer to an old revision
with a known-bad hook.

**Provenance after the fact.** "Which config was this session running" is
answerable from `.sync-status.json` in both cases. Only the tag path makes
"was that revision deliberately promoted, and by a human present at a
keyboard" answerable at all.

## What the tag costs

- **A hardware dependency on the human.** Promotion requires the touch-required
  `sk-ssh-ed25519` or Secure Enclave key to hand. Key lost or unavailable means
  no releases until rotation — and rotation is a form edit on every environment,
  the exact operation the design otherwise avoids.
- **Ceremony friction.** One script run per config release. The doc is explicit
  that the friction *is* the review gate, which is another way of saying the
  gate fails the moment the friction stops being paid. A tag channel where the
  releases stop is strictly worse than a SHA that is at least current.
- **More moving parts to build and keep working.** Release script, GitHub
  ruleset on `claude-config/*`, PreToolUse guard, signers-file persistence and
  its root-ownership requirement (M5), the in-repo fingerprint cross-check (M6),
  floor-tag handling. Each is a place the mechanism can break in a way that
  fails a cloud session's setup window.
- **Verification order is load-bearing and easy to get wrong.** The check must
  live in the form, upstream of any repo-supplied code; an earlier draft had the
  cloned installer verify itself, which authorizes nothing. The SHA path has no
  equivalent subtlety — git either checks out that object or it doesn't.

## What the SHA costs

- No promotion artifact, so R3 ("pinned *and reviewed*") is met only by
  discipline. §8 already rejects this shape once, under "status-quo plus
  pinning bolted on": *a pin to an arbitrary `main` commit gates nothing*.
- N-way manual bumps, invisible drift, no revocation, no monotonicity.
- T1 — the agent-writes-a-hook-on-`main` path — remains open in substance:
  the only barrier is that a human types the SHA, with no diff in front of them
  unless they go looking.

## What is the same either way

Everything in §6.2 and §6.3 that isn't the anchor: atomic stage-and-flip,
complete-hook-set-or-none (T8), `.sync-status.json` written last, degraded
sessions announcing themselves, secret exclusion, and the requirement that the
verification happen before repo-supplied code runs. Both designs need P1's
installer surgery first; the anchor choice is P2 and does not block it.

## The question the choice actually turns on

Whether the threat being defended against is *an attacker who reaches the
config path*, or *a Claude session that reaches it while running as Mark*. The
SHA is adequate against the first and structurally silent against the second.
The signed tag addresses the second, and charges a recurring human act for it —
one that has to keep being paid indefinitely, by someone who has already
deferred this decision once.
