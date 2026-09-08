---
name: npm-first-publish
description: Walk a new npm package through its first release, which trusted-publisher CI cannot do on its own. Use when a new package is ready for its first release, on "publish", "first publish", "release a new package", or when CI hits an npm publish E404.
---

# First publish of a new npm package

## Diagnose first

An E404 on the `PUT` during `npm publish` means no trusted publisher is
registered for that name yet, or no auth at all — not a missing package
and not a bad build. Check `npm view <name> version` against the registry
before touching anything. Do not edit the release workflow to fix this; a
workflow that is correct for every later release still fails on the first
one, by design.

## Preconditions before asking

All of these must already be green. Fix whichever is red; don't ask Solace
until they are:

- the release tag's CI is green;
- `npm run build` succeeds;
- the tests pass;
- `npm publish --dry-run` produced the tarball and its file list has been
  checked. `--dry-run` needs no auth, so there's no excuse for skipping it.

## Ask inline, not a card

Ask Solace in chat, with exactly these four commands, named in full:

    cd ~/<repo>
    git pull --rebase
    npm login
    npm publish            # scoped name: add --access public

`npm login` is named explicitly rather than left implicit — a past ask that
omitted it left her unsure what it would do.  It opens (or prints) a
browser auth URL; she approves with her passkey. Never pass `--otp`.
A scoped package (`@scope/name`) publishes as private unless
`--access public` or `publishConfig.access: public` says otherwise, and a
free account fails on private. Provenance stays opt-in; leave it to CI.

## After success

Register the trusted publisher for the package on npmjs.com (GitHub
Actions publisher: repo plus workflow filename). Every later release is
then CI's job, not hers.

## Assumption

Releases use npm trusted publishing (OIDC), not a stored automation token.
Don't "fix" a first-publish failure by adding a token secret: granular
write tokens expire within 90 days, and npm is removing publish from
bypass-2FA tokens (scheduled January 2027). Trusted publishing can't
create a name that doesn't exist yet ([npm/cli#8544](https://github.com/npm/cli/issues/8544)),
so the hand-off is by design, not a gap to engineer around.
