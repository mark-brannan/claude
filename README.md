# claude

The Claude Code layer of a personal setup: hooks, skills, settings and the
conventions around them. "Claude" here means Claude Code, the CLI, not the
model.

This is a reference implementation, and for now a copy. It is public so that
the way these pieces fit together can be read and borrowed. The source of
truth stays [mark-brannan/dotfiles](https://github.com/mark-brannan/dotfiles)
until delivery is ruled; nothing is installed from this repo yet. The layer
is copied in, and CI's `dotfiles-drift` job goes red when a copy stops
matching dotfiles `main`.

## Layout

The repo root is `~/.claude`: delivery clones this repo there. So
`hooks/`, `skills/`, `rules/`, `settings.json` and `CLAUDE.md` sit at the
root, and dotfiles' `.claude/X` is `X` here. Two more directories hold what
dotfiles keeps elsewhere: `bin/` (dotfiles' `.local/bin/`, so it lands at
`~/.claude/bin`) and `systemd/` (dotfiles' `.config/systemd/user/`; the
units are not installed from here yet). `docs/` holds the layer's docs and
the two repo docs copied from dotfiles' own `docs/`. The rest of the root,
this README, `.github/` and the editor and merge config, is repo
scaffolding; in `~/.claude` Claude Code ignores it.

Pull requests here meet the same bar as dotfiles: one required check
(`ci-gate / gate`), both secret scanners, a signed-commit, squash-only `main`,
and an advisory Claude review.

## Status

Main is protected: changes land by pull request, never by direct push.
