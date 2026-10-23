#!/usr/bin/env python3
"""statusLine: the always-on readout. Reads the cache `metrics-live.py` wrote;
recomputes only when that cache has gone stale, so the pass over the
transcript happens on the order of once per 15s rather than per render.

Free in context terms: statusline output is never sent to the model.

Prints the model name, then the row from lib-metrics-fmt.jq (the one home of
the layout, rendered by jq), or `⛁ warming up` while the cache is absent or
short of the fields the row needs. No session id in the payload, or no jq:
prints nothing. Fails open: any error exits 0, traced to the state repo's
metrics/hook-errors/ (lib/hooktrace.py).
"""
import json
import os
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path; reads the event)

HOOK_DIR = os.path.dirname(os.path.realpath(__file__))
WARMING = "⛁ warming up"


def say(text):
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def shaped(cache):
    """True when the cache holds the fields the row needs. A cache written
    before they existed, or caught mid-write, must not render as nulls."""
    if not isinstance(cache, dict):
        return False
    dec = cache.get("decisions")
    return isinstance(dec, dict) and dec.get("total") is not None and cache.get("output_tokens") is not None


def main():
    # No jq means no readout rather than a broken statusline row.
    if not shutil.which("jq"):
        return
    ev = lib_state.event()
    sid = ev.get("session_id")
    sid = sid if isinstance(sid, str) else ""
    if not sid:
        return
    model = (ev.get("model") or {}).get("display_name") if isinstance(ev.get("model"), dict) else ""
    model = model if isinstance(model, str) else ""

    # Refresh the cache when stale; its stdout is not part of the row.
    try:
        subprocess.run([sys.executable, os.path.join(HOOK_DIR, "metrics-live.py"), "statusline", "15"],
                       input=json.dumps(ev).encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        lib_state.trace_failure("statusline-metrics", "statusLine", e, stage="refresh", once=True)

    # A custom statusline replaces the default row, so the model name it used
    # to carry has to come back from here.
    if model:
        say(f"{model}  ")

    sd = lib_state.state_dir()
    path = None
    if sd:
        import state
        path = state.state_shard_path(f"{sd}/metrics/live", f"{sid}.json", sid)
    if not path or not os.path.isfile(path):
        say(WARMING)
        return
    try:
        with open(path, encoding="utf-8") as f:
            ok = shaped(json.load(f))
    except (OSError, ValueError):
        ok = False
    if not ok:
        say(WARMING)
        return

    # Two rows: the readout, then the time row on its own line. `time` yields
    # empty rather than zeros on a stale cache, so the row disappears.
    p = subprocess.run(["jq", "-r", "-L", HOOK_DIR, 'include "lib-metrics-fmt"; row', path], capture_output=True)
    say(p.stdout.decode("utf-8") if p.returncode == 0 else "⛁ —")


if __name__ == "__main__":
    lib_state.run_hook("statusline-metrics", "statusLine", main)
