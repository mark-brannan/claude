---
name: npm-first-publish
description: Walk a new npm package through its first release, which trusted-publisher CI cannot do on its own. Use when a new package is ready for its first release, on "publish", "first publish", "release a new package", or when CI hits an npm publish E404.
---

# First publish of a new npm package

## The rule

A new package's first release is **0.0.1, published by CI**. The hand step
only claims the name: **0.0.0, published by hand**, before any release. Then
the trusted publisher is registered, and release-please's 0.0.1 is the first
release CI publishes. A new package never borrows the repo's version or
another package's.

Trusted publishing can't create a name that doesn't exist yet
([npm/cli#8544](https://github.com/npm/cli/issues/8544)), so the 0.0.0
placeholder exists to make every real release, 0.0.1 included, a CI
release.

## Version setup, before the hand publish

In `release-please-config.json`, on the new package:

    "initial-version": "0.0.1"

and seed `.release-please-manifest.json` with `0.0.0`, with the package's
`package.json` (and its lockfile entry) at `0.0.0`.

A seed alone does not work: a package with no earlier release ignores its
manifest entry and takes `initial-version`, or 1.0.0 when that is unset
(release-please's `buildNewVersion`). `release-as` is not the remedy:
left in place it pins every later release, so it needs a second PR to
remove (languette#160, #165). `initial-version` applies only while no
release exists and needs no cleanup.

A package that is not the repo's root is its own release-please component,
with component tags (`<name>-vX.Y.Z`), and the shared release workflow's
`publish-path` names it.

Prove the version before any merge, against the branch:

    npx release-please@17 release-pr --dry-run \
      --token "$(gh auth token)" --repo-url <owner/repo> \
      --target-branch <branch>

The proposal must read `<name>: 0.0.1`. Anything else, fix the config first.

## Diagnose first

An E404 on the `PUT` during `npm publish` means no trusted publisher is
registered for that name yet, or no auth at all — not a missing package
and not a bad build. Check `npm view <name> version` against the registry
before touching anything. Do not edit the release workflow to fix this; a
workflow that is correct for every later release still fails on a name
that was never claimed.

## Preconditions before asking

All of these must already be green. Fix whichever is red; don't ask the user
until they are:

- the package is at 0.0.0 on the branch to publish from;
- the dry-run above proposes 0.0.1;
- `npm run build` succeeds;
- the tests pass;
- `npm publish --dry-run` produced the tarball and its file list has been
  checked. `--dry-run` needs no auth, so there's no excuse for skipping it.

## Ask inline, not a card

Ask the user in chat for the 0.0.0 publish, with each command named in
full, starting from a checkout that exists (create the worktree in the
command if it may not):

    cd ~/<repo>          # or the PR's worktree, at 0.0.0
    git pull --rebase
    npm login
    npm publish          # scoped name: add --access public

`npm login` is named explicitly rather than left implicit — a past ask that
omitted it left them unsure what it would do.  It opens (or prints) a
browser auth URL; they approve with their passkey. Never pass `--otp`.
A scoped package (`@scope/name`) publishes as private unless
`--access public` or `publishConfig.access: public` says otherwise, and a
free account fails on private. Provenance stays opt-in; leave it to CI.

## After the 0.0.0 publish

Register the trusted publisher for the package on npmjs.com (GitHub
Actions publisher: repo plus workflow filename). Then merge the release
PR: 0.0.1 publishes from CI, and so does every later release.

## Assumption

Releases use npm trusted publishing (OIDC), not a stored automation token.
Don't "fix" a first-publish failure by adding a token secret: granular
write tokens expire within 90 days, and npm is removing publish from
bypass-2FA tokens (scheduled January 2027).
