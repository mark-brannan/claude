#!/usr/bin/env python3
"""SessionStart: shout if too many MCP connectors are enabled.

Connectors are the one line of the token floor that can grow without limit and
without being noticed -- in a local CLI their schemas load in full. Measured
floor breakdown and the reasoning: .claude/docs/token-budget.md

Counts the distinct server names in ~/.claude.json (global, and the ones
under projects[cwd]) and in the cwd's .mcp.json, less any named in
deniedMcpServers of the config dir's settings.json or the cwd's
.claude/settings.json and settings.local.json. CLAUDE_CONNECTOR_MAX (default 5)
is the limit; CLAUDE_CONFIG_DIR moves the first settings file.

Silent at or below the limit. Every line printed here is charged to every
session, so the quiet path must cost exactly zero.

CONVENIENCE: never blocks a session, always exits 0; a crash is traced to the
state repo's metrics/hook-errors/ (lib/hooktrace.py).
"""
import json
import os
import sys

sys.dont_write_bytecode = True

import lib_state  # noqa: E402  (puts lib/ on sys.path)
import hookio  # noqa: E402


def load(path):
    """The JSON object in path, or {} when it is absent, unreadable or not one."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def server_names(obj):
    servers = obj.get("mcpServers")
    return list(servers) if isinstance(servers, dict) else []


def denied_names(obj):
    denied = obj.get("deniedMcpServers")
    if not isinstance(denied, list):
        return []
    return [d["serverName"] for d in denied if isinstance(d, dict) and isinstance(d.get("serverName"), str)]


def main():
    try:
        limit = int(os.environ.get("CLAUDE_CONNECTOR_MAX") or 5)
    except ValueError:
        limit = 5
    home = os.path.expanduser("~")
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
    cwd = os.getcwd()

    cfg = load(os.path.join(home, ".claude.json"))
    names = set(server_names(cfg))
    projects = cfg.get("projects")
    if isinstance(projects, dict) and isinstance(projects.get(cwd), dict):
        names.update(server_names(projects[cwd]))
    names.update(server_names(load(os.path.join(cwd, ".mcp.json"))))

    for s in (os.path.join(conf, "settings.json"),
              os.path.join(cwd, ".claude", "settings.json"),
              os.path.join(cwd, ".claude", "settings.local.json")):
        names.difference_update(denied_names(load(s)))

    enabled = sorted(names)
    if len(enabled) <= limit:
        return
    text = (
        f"## !! CONNECTOR BUDGET EXCEEDED: {len(enabled)} enabled, limit {limit} !!\n"
        "\n"
        f"Enabled: {', '.join(enabled)}\n"
        "\n"
        "Tell the user this in your FIRST reply, before anything he asked for.\n"
        "In a local CLI every one of these loads its full tool schemas into\n"
        "the floor of every session. Offer to disable the ones this task does\n"
        "not need (`deniedMcpServers` in settings.json), then continue.\n"
    )
    hookio.emit(hookio.context("SessionStart", text))


if __name__ == "__main__":
    lib_state.run_hook("connector-budget", "SessionStart", main)
