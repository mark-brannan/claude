# claude

The Claude Code layer of a personal setup: hooks, skills, settings and the
conventions around them. "Claude" here means Claude Code, the CLI, not the
model.

This is a reference implementation. It is public so that the way these
pieces fit together can be read and borrowed. This repo is the source of
truth for the layer; it began as a copy from
[mark-brannan/dotfiles](https://github.com/mark-brannan/dotfiles), which
stopped tracking it at f09f0d2. Nothing is installed from this repo yet.

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
