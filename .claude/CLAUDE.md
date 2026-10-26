# This repo

The Claude Code layer: hooks, skills, rules, settings and the `bin/` tools.
`~/.claude` is a clone of it, so what merges to `main` is what every session
runs, and hooks run from `~/.claude`, never from this checkout. Edit in a
worktree of `~/claude`, never in `~/.claude`. The root `CLAUDE.md` is the
standing orders themselves, live at `~/.claude/CLAUDE.md`, not a copy of
them. This file is live at `~/.claude/.claude/CLAUDE.md` and loads only in
this repo, its worktrees and `~/.claude`. README "Layout" maps every repo
path to its live one.

Where each subsystem's design lives:

- Layout and delivery: README "Layout"; RUNBOOK "Where things are" indexes every operation.
- Metrics readouts: RUNBOOK "Change what the metrics readouts show"; `hooks/metrics-live-requirements.md`.
- Stop hook, checkpoints and pickup items: `hooks/stop-continuity-requirements.md`.
- Config sync across machines: `docs/config-sync-strategy.md`.
- Work items: `docs/work-item-lifecycle.md`.
- Headless run costs: `docs/headless-run-costs.md`.

Two reflexes:

- A display problem (a readout missing, wrong or wrapping): read RUNBOOK
  "Change what the metrics readouts show" before any code.
- A hook problem (silent, stale or misfiring): run the hook by hand on a real
  transcript, then read the live clone's reflog. `~/.claude/bin/self-check`
  runs the hook and sets the live clone against `origin/main` in one table.

Reviewing a PR here: this repo is public and runs unattended inside every
session, so look hard at anything that executes automatically (hooks), widens
permissions, fetches and runs remote content, or puts a credential in the
diff.
