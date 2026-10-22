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
Set up and emergency instructions are here: [RUNBOOK.md](RUNBOOK.md)

The repo root is `~/.claude`: delivery clones this repo there. So
`hooks/`, `skills/`, `rules/`, `settings.json` and `CLAUDE.md` sit at the
root, and dotfiles' `.claude/X` is `X` here. Two more directories hold what
dotfiles keeps elsewhere: `bin/` (dotfiles' `.local/bin/`, so it lands at
`~/.claude/bin`) and `systemd/` (dotfiles' `.config/systemd/user/`; the
units are not installed from here yet). `docs/` holds the layer's docs and
the two repo docs copied from dotfiles' own `docs/`. The rest of the root,
this README, `.github/` and the editor and merge config, is repo
scaffolding; in `~/.claude` Claude Code ignores it.

`~/.claude` is mastered here: change it in a worktree of `~/claude` and let
it go live from `main`, never by editing the live clone in place.

| In the repo | Live | Loads |
|---|---|---|
| `CLAUDE.md` | `~/.claude/CLAUDE.md` | the standing orders, in every session |
| `.claude/CLAUDE.md` | `~/.claude/.claude/CLAUDE.md` | the repo map, only in this repo, its worktrees and `~/.claude` |
| `settings.json`, `hooks/` | `~/.claude/settings.json`, `~/.claude/hooks/` | every session; hooks always run from the live clone |
| `rules/`, `skills/` | `~/.claude/rules/`, `~/.claude/skills/` | every session, by path or by name |
| `bin/` | `~/.claude/bin/` | when a hook, skill or person calls a tool |

Pull requests here meet the same bar as dotfiles: one required check
(`ci-gate / gate`), both secret scanners, a signed-commit, squash-only `main`,
and an advisory Claude review.

## Status

Main is protected: changes land by pull request, never by direct push.

## License

Markdown files (skills, rules, docs) are [CC BY-SA 4.0](LICENSE-CC-BY-SA); everything else is
[AGPL-3.0-or-later](LICENSE). Copyright 2026 Solace (Mark) Brannan.
Credit "Solace Brannan" and link this repository.
