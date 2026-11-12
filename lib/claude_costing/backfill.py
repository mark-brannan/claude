"""Reprice stored session records from the transcripts on this machine:
python3 lib/claude_costing backfill [--dry-run] [--sessions DIR] [--projects DIR]

A record's dollars are a function of its transcript and the price table: the
total Claude Code stored at exit where claude_costing trusts one
(recorded_state), split by model as Claude Code split it; otherwise this
table's price of the transcript's usage, sub-agents included. cost_source says
which. The Stop hook writes a record before the exit total exists, so a record
reaches it only here.

Safe to rerun at any time: a record whose three fields already hold the answer
is not written, and one whose transcript is not on this machine is left as it
is. Exit 1 when no session records are found.
"""
import argparse
import glob
import json
import os
import re
import sys

import claude_costing as cc
from claude_costing import check

FIELDS = ("cost_usd", "cost_usd_by_model", "cost_source")
STORED, PRICED = "claude-code", "price-table"


def default_sessions():
    """The state repo's session records on this machine, or None."""
    import state
    d = state.state_dir_or_none()
    p = d and os.path.join(d, "metrics", "sessions")
    return p if p and os.path.isdir(p) else None


def cents(usd):
    """Four decimals, as the Stop hook writes a record's dollars."""
    return round(usd * 10000) / 10000


def answer(path):
    """{cost_usd, cost_usd_by_model, cost_source} for a session's transcript.
    OSError if it cannot be read."""
    state = cc.recorded_state(path)
    if state and state.get("modelUsage"):
        by_model = {}
        for model, use in state["modelUsage"].items():
            name = re.sub(r"\[[^\]]*\]$", "", model)  # claude-opus-5-5[1m] is claude-opus-5-5
            by_model[name] = by_model.get(name, 0.0) + ((use or {}).get("costUSD") or 0.0)
        total, source = state["totalCostUSD"], STORED
    else:
        by_model = {m or "unknown": c for m, c in check.session_by_model(path).items()}
        total, source = sum(by_model.values()), PRICED
    return {"cost_usd": cents(total),
            "cost_usd_by_model": {m: cents(c) for m, c in sorted(by_model.items())},
            "cost_source": source}


def rewrite(record_path, transcripts, write=True):
    """(outcome, dollars before, dollars after) for one record file; outcome is
    'changed', 'same' or 'skipped' (not a record, or no transcript here)."""
    try:
        with open(record_path, encoding="utf-8") as f:
            raw = f.read()
        rec = json.loads(raw)
    except (OSError, ValueError):
        return "skipped", 0.0, 0.0
    path = transcripts.get(rec.get("session_id")) if isinstance(rec, dict) else None
    if not path:
        return "skipped", 0.0, 0.0
    try:
        new = answer(path)
    except OSError:
        return "skipped", 0.0, 0.0
    before = rec.get("cost_usd") if isinstance(rec.get("cost_usd"), (int, float)) else 0.0
    if all(rec.get(k) == new[k] for k in FIELDS):
        return "same", before, before
    if write:
        try:
            with open(record_path, encoding="utf-8") as f:
                if f.read() != raw:  # the Stop hook wrote it while we parsed
                    return "skipped", before, before
        except OSError:
            return "skipped", before, before
        rec.update(new)
        pretty = raw.startswith("{\n")
        out = json.dumps(rec, ensure_ascii=False, indent=2 if pretty else None,
                         separators=None if pretty else (",", ":"))
        tmp = record_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(out + ("\n" if raw.endswith("\n") else ""))
            os.replace(tmp, record_path)
        except OSError:
            if os.path.exists(tmp):
                os.remove(tmp)
            return "skipped", before, before
    return "changed", before, new["cost_usd"]


def run(sessions, projects, write=True):
    """{outcome: [records, dollars before, dollars after]} over every record."""
    transcripts = {os.path.basename(p)[:-len(".jsonl")]: p
                   for p in glob.glob(os.path.join(glob.escape(projects), "*", "*.jsonl"))}
    root = glob.escape(sessions)
    tally = {k: [0, 0.0, 0.0] for k in ("changed", "same", "skipped")}
    for rec in sorted(glob.glob(os.path.join(root, "*.json")) + glob.glob(os.path.join(root, "*", "*.json"))):
        outcome, before, after = rewrite(rec, transcripts, write)
        row = tally[outcome]
        row[0] += 1
        row[1] += before
        row[2] += after
    return tally


def main(argv):
    ap = argparse.ArgumentParser(prog="claude_costing backfill", description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--sessions", help="the session records (default: the state repo's)")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    sessions = args.sessions or default_sessions()
    if not sessions or not os.path.isdir(sessions):
        print("claude_costing backfill: no session records found; name them with --sessions", file=sys.stderr)
        return 1
    tally = run(sessions, args.projects, write=not args.dry_run)
    n, before, after = tally["changed"]
    print(f"{'would change' if args.dry_run else 'changed'} {n} records: ${before:.2f} -> ${after:.2f}")
    print(f"already right {tally['same'][0]}; left alone {tally['skipped'][0]} (no transcript on this machine, or not a record)")
    return 0
