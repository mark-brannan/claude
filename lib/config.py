#!/usr/bin/env python3
"""The one home for this layer's settings: config.json at the repo root.

What lives there is a fact more than one tool needs and the user may change:
where the state repo is (its GitHub name, and the directories a clone is
looked for in) and the plan figures (what a week of the subscription buys,
priced at API rates). A tool reads it here, never from its own copy; shell
reads it with `python3 lib/config.py get <dotted.key>`, jq by `--arg` from
its caller.

config.json is found beside lib/ (a checkout, or the seed ~/.claude links
to), else at ~/.claude/config.json. There are no built-in defaults: a second
copy of a value here would be the drift this file exists to end. A missing or
unreadable file is ConfigError, and each caller fails the safe way (a guard
that only allows stops allowing; a write root is left out).

Stdlib only.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
PLACES = (os.path.join(HERE, "..", "config.json"), os.path.expanduser("~/.claude/config.json"))


class ConfigError(Exception):
    pass


_cache = {}


def load(places=PLACES):
    """config.json as a dict; ConfigError when none is readable."""
    key = tuple(places)
    if key in _cache:
        return _cache[key]
    errors = []
    for p in places:
        try:
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            errors.append(f"{p}: {e}")
            continue
        if isinstance(cfg, dict):
            _cache[key] = cfg
            return cfg
        errors.append(f"{p}: not a JSON object")
    raise ConfigError("; ".join(errors) or "no config.json beside lib/ or in ~/.claude")


def get(key, places=PLACES):
    """The value at a dotted key, e.g. "plan.week_usd"; ConfigError when absent."""
    v = load(places)
    for part in key.split("."):
        if not isinstance(v, dict) or part not in v:
            raise ConfigError(f"config.json has no {key}")
        v = v[part]
    return v


def state_repo_github(places=PLACES):
    """The state repo as owner/name on GitHub."""
    v = get("state_repo.github", places)
    parts = v.split("/") if isinstance(v, str) else []
    if len(parts) != 2 or not all(re.fullmatch(r"[A-Za-z0-9_.-]+", p) and p not in (".", "..")
                                  for p in parts):
        raise ConfigError(f"state_repo.github is not owner/name: {v!r}")
    return v


def state_repo_name(places=PLACES):
    """The state repo's name, which is also its clone's directory name."""
    return state_repo_github(places).split("/")[1]


def state_repo_dirs(home, places=PLACES):
    """Where a clone of the state repo is looked for, in order; ~ is home."""
    name = state_repo_name(places)
    out = []
    for d in get("state_repo.search", places):
        if d == "~" or d.startswith("~/"):
            d = home + d[1:]
        out.append(os.path.join(d, name))
    return out


def main(argv):
    if len(argv) == 2 and argv[0] == "get":
        try:
            v = get(argv[1])
        except ConfigError as e:
            print(f"config.py: {e}", file=sys.stderr)
            return 1
        print(v if isinstance(v, str) else json.dumps(v))
        return 0
    if argv == ["state_repo_name"]:
        try:
            print(state_repo_name())
        except ConfigError as e:
            print(f"config.py: {e}", file=sys.stderr)
            return 1
        return 0
    print("usage: config.py get <dotted.key> | state_repo_name", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
