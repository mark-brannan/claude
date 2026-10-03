# claude

The Claude Code layer of a personal setup: hooks, skills, settings and the
conventions around them. "Claude" here means Claude Code, the CLI, not the
model.

This is a reference implementation, and for now a copy. It is public so that
the way these pieces fit together can be read and borrowed. The source of
truth stays [mark-brannan/dotfiles](https://github.com/mark-brannan/dotfiles)
until delivery is ruled; nothing is installed from this repo yet. The layer
is copied in at the same paths, and CI's `dotfiles-drift` job goes red when
a copy stops matching dotfiles `main`.

Pull requests here meet the same bar as dotfiles: one required check
(`ci-gate / gate`), both secret scanners, a signed-commit, squash-only `main`,
and an advisory Claude review.
