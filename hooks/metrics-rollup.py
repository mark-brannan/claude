#!/usr/bin/env python3
"""Regenerate metrics/metrics.json from the per-session files.

Generated, never edited, and *never committed*: the state repo gitignores
metrics.json. Per-session inputs are conflict-free by construction, but a
committed rollup of them is not -- every Stop rewrote the one shared file,
so any two sessions ending near each other collided on it and a human had
to resolve a conflict in generated JSON. Untracked, the file is still here
to read; each machine regenerates its own from whatever sessions it has.
Reads that must not depend on a local rollup use the `jq -s` one-liners in
metrics/README.md over sessions/*.json (and sessions/*/*.json) directly.
(2026-08-20, after one such conflict; see the metrics README.)

CONVENIENCE: always exits 0. An unreadable input leaves the previous
metrics.json in place rather than writing a partial one.
"""
import glob
import json
import math
import os
import sys
import time

sys.dont_write_bytecode = True

sys.path[:0] = [os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "lib"),
                os.path.expanduser("~/.claude/lib")]  # lib/libpath.py

import atomic  # noqa: E402
import lib_state  # noqa: E402
import state  # noqa: E402


def prune(root, pattern_suffix, min_age_days, infix=False):
    """find "$root" -name <pattern> -mtime +N -delete: files whose whole-day
    age exceeds N. pattern_suffix '.json' is '*.json'; infix is '*.json.*'."""
    now = time.time()
    for dirpath, _dirs, names in os.walk(root):
        for n in names:
            hit = (".json." in n) if infix else n.endswith(pattern_suffix)
            if not hit:
                continue
            p = os.path.join(dirpath, n)
            try:
                if int((now - os.stat(p).st_mtime) // 86400) > min_age_days:
                    os.unlink(p)
            except OSError:
                pass


def jq_round(x):
    """jq's round: half away from zero."""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def jq_rank(v):
    """jq's ordering across types: null < false < true < numbers < strings
    < arrays < objects; within a type, by value."""
    if v is None:
        return (0,)
    if v is False:
        return (1,)
    if v is True:
        return (2,)
    if isinstance(v, (int, float)):
        return (3, v)
    if isinstance(v, str):
        return (4, v)
    return (5, json.dumps(v, sort_keys=True))


def alt(*vals):
    """jq's a // b // c: the first value that is neither null nor false."""
    for v in vals:
        if v is not None and v is not False:
            return v
    return vals[-1]


def get(obj, key):
    """obj.key as jq has it: null from null, error (TypeError) from a non-object."""
    if obj is None:
        return None
    if not isinstance(obj, dict):
        raise TypeError(f"cannot index {type(obj).__name__} with {key!r}")
    return obj.get(key)


def add(nums):
    return sum(nums) if nums else None


def load(paths):
    """Every JSON value in every file, as jq -s slurps them; ValueError on any
    file jq would reject."""
    dec = json.JSONDecoder()
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            text = fh.read()
        i, n = 0, len(text)
        while True:
            while i < n and text[i] in " \t\r\n":
                i += 1
            if i >= n:
                break
            v, i = dec.raw_decode(text, i)
            out.append(v)
    return out


def rollup(values):
    recs = [v for v in values if get(v, "session_id") is not None]
    keyed = sorted(recs, key=lambda r: jq_rank(r["session_id"]))  # stable, like group_by
    groups = []
    for r in keyed:
        if groups and groups[-1][0] == r["session_id"]:
            groups[-1][1].append(r)
        else:
            groups.append((r["session_id"], [r]))

    def stamp(r):
        return jq_rank(alt(get(r, "updated_at"), get(r, "ts"), ""))

    sessions = []
    for _sid, g in groups:
        done = [r for r in g if get(r, "ended_at") is not None and get(r, "last_event") is None]
        sessions.append(done[-1] if done else sorted(g, key=stamp)[-1])
    sessions.sort(key=lambda r: jq_rank(alt(get(r, "started_at"), "")))

    best = None
    for r in sessions:  # max_by: the last of equal maxima
        if best is None or stamp(r) >= stamp(best):
            best = r
    generated_at = alt(get(best, "updated_at"), "")

    def num(r, *path):
        v = r
        for k in path:
            v = get(v, k)
        return alt(v, 0)

    n = add([num(r, "decisions", "total") for r in sessions])
    junk = add([num(r, "decisions", "junk") for r in sessions])
    by_day = []
    dated = [r for r in sessions if get(r, "started_at") is not None]
    for r in sorted(dated, key=lambda r: jq_rank(r["started_at"][0:10])):
        day = r["started_at"][0:10]
        if by_day and by_day[-1]["day"] == day:
            by_day[-1]["decisions"] += num(r, "decisions", "total")
            by_day[-1]["junk"] += num(r, "decisions", "junk")
        else:
            by_day.append({"day": day, "decisions": num(r, "decisions", "total"),
                           "junk": num(r, "decisions", "junk")})
    for d in by_day:
        d["junk_rate"] = jq_round(d["junk"] / d["decisions"] * 100) if d["decisions"] > 0 else None
    churn = [v for v in (get(r, "cache_churn_pct") for r in sessions) if v is not None]

    return {
        "generated_at": generated_at,
        "sessions": sessions,
        "totals": {
            "sessions": len(sessions),
            "output_tokens": add([num(r, "output_tokens") for r in sessions]),
            "tool_calls": add([num(r, "tool_calls") for r in sessions]),
            "decisions": n,
            "gates": add([num(r, "decisions", "gate") for r in sessions]),
            "junk": junk,
            "junk_rate": jq_round(junk / n * 100) if n is not None and n > 0 else None,
            "junk_by_day": by_day,
            "cache_churn_pct_avg": jq_round(sum(churn) / len(churn)) if churn else None,
        },
    }


def main():
    d = state.state_dir()
    m = f"{d}/metrics"
    if not os.path.isdir(m):
        return
    live = f"{m}/live"
    # Prune live snapshots that Stop never came back for. A container reclaimed
    # mid-session leaves its live file behind forever, and without this the
    # rollup keeps counting that half-session's tokens in every future total.
    # 14 days is well past any session that is still going to finish.
    prune(live, ".json", 14)
    # Interrupted writers leave `<id>.json.<pid>` temp files behind. The globs
    # below never pick them up, so they are harmless to the rollup -- but they
    # sat in the state repo as untracked clutter until someone noticed them.
    prune(live, "", 1, infix=True)
    # stop-continuity.py deletes this session's live file immediately before
    # calling here, so live/ is usually empty; the sessions/ glob alone must
    # still regenerate metrics.json.
    files = []
    for pat in ("sessions/*.json", "sessions/*/*.json", "live/*.json", "live/*/*.json"):
        files += sorted(glob.glob(f"{m}/{pat}"))
    if not files:
        return
    try:
        out = json.dumps(rollup(load(files)), indent=2, ensure_ascii=False)
        atomic.write(f"{m}/metrics.json", out + "\n")
    except (OSError, ValueError, TypeError, KeyError) as e:
        # The previous metrics.json stands; say why the new one did not land.
        lib_state.trace_failure("metrics-rollup", "", e, stage="rollup")


if __name__ == "__main__":
    main()
    sys.exit(0)
