"""The machine's memory headroom, read before a session starts: available RAM
plus free swap, against the floor in config.json (memory.floor_gb). A launch
that would push the box into swap-thrash is refused with the numbers, never
queued; driver-start and worker-start ask refusal(), self-check prints row().

GB here is GiB: /proc/meminfo counts in kB of 1024 bytes. $CLAUDE_PROC names
a directory laid out like /proc (meminfo, pressure/memory), for tests and
fixtures; it defaults to /proc.

What cannot be read refuses nothing: no /proc/meminfo (not Linux), or no
floor in config.json, and refusal() is None; no /proc/meminfo, and row()
is None. Stdlib only.
"""
import os
import re

import config

KB_PER_GB = 1024 * 1024


def proc_dir():
    return os.environ.get("CLAUDE_PROC") or "/proc"


def meminfo(proc=None):
    """/proc/meminfo as {field: kB}, or None when unreadable."""
    try:
        with open(os.path.join(proc or proc_dir(), "meminfo"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    out = {}
    for m in re.finditer(r"^(\w+):\s+(\d+)", text, re.M):
        out[m.group(1)] = int(m.group(2))
    return out if "MemAvailable" in out else None


def pressure_avg10(proc=None):
    """The `some avg10` share from /proc/pressure/memory, in percent, or None."""
    try:
        with open(os.path.join(proc or proc_dir(), "pressure", "memory"), encoding="utf-8") as f:
            m = re.search(r"^some\b.*\bavg10=([\d.]+)", f.read(), re.M)
    except OSError:
        return None
    return float(m.group(1)) if m else None


def floor_gb():
    """memory.floor_gb from config.json, or None when absent or not a number."""
    try:
        v = config.get("memory.floor_gb")
    except config.ConfigError:
        return None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def gb(kb):
    return kb / KB_PER_GB


def refusal():
    """'<n> GB available + <n> GB swap, under the <n> GB floor; not starting',
    or None when there is room or nothing could be read."""
    info, floor = meminfo(), floor_gb()
    if info is None or floor is None:
        return None
    avail, swap = info["MemAvailable"], info.get("SwapFree", 0)
    if gb(avail + swap) >= floor:
        return None
    return "%.1f GB available + %.1f GB swap, under the %.1f GB floor; not starting" % (
        gb(avail), gb(swap), floor)


def row(proc=None, floor=None):
    """self-check's memory row: (status, value), or None when /proc/meminfo
    is unreadable (not Linux), so the row is left out rather than warned."""
    info = meminfo(proc)
    if info is None:
        return None
    free = info["MemAvailable"] + info.get("SwapFree", 0)
    total = info.get("MemTotal", 0) + info.get("SwapTotal", 0)
    p = pressure_avg10(proc)
    value = "%.1f GB free of %.0f GB (RAM+swap) · pressure %s" % (
        gb(free), gb(total), "%.0f%% avg10" % p if p is not None else "unread")
    floor = floor_gb() if floor is None else floor
    return ("warn" if floor is not None and gb(free) < floor else "ok", value)
