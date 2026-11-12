"""Reprice local transcripts against the totals Claude Code stored in them:
python3 lib/claude_costing check [--days N] [--projects DIR]

One row per model, from every session whose record claude_costing trusts
(recorded_state): what this table makes of the transcript's usage, sub-agents
included, beside what Claude Code recorded for that model. Exit 1 when a model
carrying at least MIN_SHARE of the recorded dollars is outside LOW..HIGH.
"""
import argparse
import glob
import os
import sys
import time

import claude_costing as cc

# Measured over 14 days of sessions: we land 0-3% under per model (a
# transcript misses some of what Claude Code bills) and never over.
LOW, HIGH = 0.95, 1.01
# Below this share of the dollars a model's ratio is noise, or (Haiku) mostly
# background calls the transcript never holds.
MIN_SHARE = 0.02


def session_by_model(path):
    """{model: USD} for a session's transcript and its sub-agents'."""
    msgs = {}
    cc.read_usage(path, msgs)
    for sub in glob.glob(os.path.join(glob.escape(path[:-len(".jsonl")]), "subagents", "**", "*.jsonl"),
                         recursive=True):
        try:
            cc.read_usage(sub, msgs)
        except OSError:
            continue
    out = {}
    for mid, u in msgs.items():
        out[u["model"]] = out.get(u["model"], 0.0) + cc.price({mid: u})
    return out


def compare(paths):
    """({model: [sessions, ours, stored]}, sessions trusted, sessions seen)."""
    rows, trusted, seen = {}, 0, 0
    for path in paths:
        try:
            state = cc.recorded_state(path)
            ours = session_by_model(path) if state else {}
        except OSError:
            continue
        seen += 1
        if not state:
            continue
        trusted += 1
        stored = {m: (u or {}).get("costUSD") or 0.0 for m, u in (state.get("modelUsage") or {}).items()}
        for model in set(ours) | set(stored):
            if not ours.get(model) and not stored.get(model):
                continue
            row = rows.setdefault(model, [0, 0.0, 0.0])
            row[0] += 1
            row[1] += ours.get(model, 0.0)
            row[2] += stored.get(model, 0.0)
    return rows, trusted, seen


def failing(rows):
    """The models with enough recorded dollars to judge whose ratio is out of bounds."""
    total = sum(r[2] for r in rows.values())
    return sorted(m for m, (_, ours, stored) in rows.items()
                  if total and stored >= MIN_SHARE * total and not LOW <= ours / stored <= HIGH)


def main(argv):
    ap = argparse.ArgumentParser(prog="claude_costing check", description=__doc__.split("\n\n")[0])
    ap.add_argument("--days", type=float, default=14, help="transcripts modified this recently (default 14)")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    cutoff = time.time() - args.days * 86400
    paths = [p for p in glob.glob(os.path.join(glob.escape(args.projects), "*", "*.jsonl"))
             if os.path.getmtime(p) >= cutoff]
    rows, trusted, seen = compare(sorted(paths))
    print(f"{trusted} of {seen} transcripts carry a trusted stored total")
    print(f"{'model':30} {'sessions':>8} {'ours':>10} {'stored':>10} {'ratio':>6}")
    bad = failing(rows)
    for model in sorted(rows):
        n, ours, stored = rows[model]
        ratio = f"{ours / stored:.3f}" if stored else "-"
        print(f"{model:30} {n:8d} {ours:10.2f} {stored:10.2f} {ratio:>6}{'  OUT' if model in bad else ''}")
    ours, stored = sum(r[1] for r in rows.values()), sum(r[2] for r in rows.values())
    print(f"{'all':30} {trusted:8d} {ours:10.2f} {stored:10.2f} {ours / stored if stored else 0:6.3f}")
    if bad:
        print(f"outside {LOW}..{HIGH}: {', '.join(bad)}", file=sys.stderr)
    return 1 if bad else 0
