# Trust anchor for #17: signed tag vs SHA-in-form

What stops a prompt-injected session that runs as Mark and pushes a hook to
`main`:

- **unpinned `main`** — nothing stops it. Propagates in minutes.
- **file-based signing key** — nothing stops it either. The key lives in
  `$HOME`, and the session *is* Mark. All the ceremony, none of the
  protection. This is the option to refuse.
- **SHA-in-form** — stops it. The bad commit sits inert until Mark pastes a
  new SHA into the environment form.
- **touch-required hardware key** — stops it *and* keeps auto-propagation:
  every consumer picks up a new release without a form edit, because minting
  a valid tag needs a physical key touch no session can forge.

The hardware key buys exactly one property over the SHA: **safe automatic
propagation.** Refuse it and the honest design is SHA-in-form with manual,
infrequent bumps and no auto-refresh hook — same safety, loses "it just
syncs." Both stop the attack. That's the whole decision.
