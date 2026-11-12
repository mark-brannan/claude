"""Price Claude Code work at API list prices: the price table, a transcript's
usage, a session's spend with its sub-agents, and spend as a share of the plan
week.

Self-contained by design, so it can leave this repo whole: stdlib only, no
import from the rest of lib/, and settings (the plan figures) come in as
arguments, never read here. hooks/session-metrics.jq reads the same table,
prices.json, as jq data.

The table is generated (sync.py, never imported here) and held to Claude
Code's own stored totals by claude_costing.test.py and `check`.

Usage folds into a dict of messages keyed by message id: a message's content
blocks each arrive as a transcript event carrying the same usage, so each
field keeps its largest value rather than summing.
"""
import datetime
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.realpath(__file__))
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens", "cache_5m", "cache_1h")

with open(os.path.join(HERE, "prices.json"), encoding="utf-8") as _f:
    TABLE = json.load(_f)


RATES = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
_RULES = [(re.compile(r["match"]), r) for r in TABLE["rules"]]
_SEEN = {}  # model name -> its rule: a transcript repeats a handful of names


def _rule(name):
    if name not in _SEEN:
        _SEEN[name] = next((r for rx, r in _RULES if rx.search(name)), TABLE["fallback"])
    return _SEEN[name]


def rates(model, prompt_tokens=0):
    """{input, output, cache_read, cache_write_5m, cache_write_1h} in USD per
    1M tokens for a model name, at the tier a request with that prompt pays."""
    rule = _rule(model or "")
    above = rule.get("above")
    tier = above if above and prompt_tokens > above["prompt_tokens"] else rule
    return {k: tier[k] for k in RATES}


def add_usage(e, msgs):
    """Fold one transcript event's assistant usage into msgs."""
    if not isinstance(e, dict) or e.get("type") != "assistant":
        return
    m = e.get("message") or {}
    u = m.get("usage") or {}
    mid = m.get("id") or e.get("uuid")
    cur = msgs.get(mid)
    if cur is None:
        cur = msgs[mid] = dict.fromkeys(FIELDS, 0)
        cur["model"] = m.get("model") or ""
    split = u.get("cache_creation") or {}
    vals = {
        "input_tokens": u.get("input_tokens"),
        "output_tokens": u.get("output_tokens"),
        "cache_read_input_tokens": u.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": u.get("cache_creation_input_tokens"),
        "cache_5m": split.get("ephemeral_5m_input_tokens"),
        "cache_1h": split.get("ephemeral_1h_input_tokens"),
    }
    for k, v in vals.items():
        if isinstance(v, (int, float)) and v > cur[k]:
            cur[k] = v


def read_usage(path, msgs):
    """Fold one transcript's assistant usage into msgs; OSError if unreadable."""
    with open(path, "rb") as f:
        for line in f:
            # Cheap prefilter: most lines are tool results and user turns.
            if b'"assistant"' not in line or b'"usage"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            add_usage(e, msgs)


def price(msgs):
    """USD for folded messages, each at its own model's rates and prompt size."""
    spend = 0.0
    for u in msgs.values():
        write = u["cache_creation_input_tokens"]
        r = rates(u["model"], u["input_tokens"] + u["cache_read_input_tokens"] + write)
        w1h = min(u["cache_1h"], write)
        w5m = write - w1h  # unsplit writes price as the 5-minute cache
        spend += (u["input_tokens"] * r["input"] + u["output_tokens"] * r["output"]
                  + u["cache_read_input_tokens"] * r["cache_read"]
                  + w5m * r["cache_write_5m"] + w1h * r["cache_write_1h"])
    return spend / 1e6


def session_transcript(path):
    """<session>/subagents/agent-<id>.jsonl, a sub-agent's own transcript, names
    the session's <session>.jsonl when that exists; any other path is itself."""
    head, sep, _ = path.partition(os.sep + "subagents" + os.sep)
    if sep and head and os.path.exists(head + ".jsonl"):
        return head + ".jsonl"
    return path


def session_spend(path):
    """(USD, context tokens of the last call) for the session a transcript belongs to.

    Spend counts the sub-agents too: Claude Code writes each one's transcript
    to <session>/subagents/agent-<id>.jsonl beside <session>.jsonl. Context is
    the main transcript's last call only. OSError if the main transcript cannot
    be read; an unreadable sub-agent one is skipped."""
    path = session_transcript(path)
    msgs = {}
    read_usage(path, msgs)
    ctx = 0
    if msgs:
        u = next(reversed(msgs.values()))  # insertion order: the last is newest
        ctx = u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
    base = path[:-len(".jsonl")] if path.endswith(".jsonl") else path
    for sub in glob.glob(os.path.join(glob.escape(base), "subagents", "**", "*.jsonl"),
                         recursive=True):
        try:
            read_usage(sub, msgs)
        except OSError:
            continue
    return price(msgs), ctx


def recorded_state(path):
    """The cost-state line Claude Code writes when a session exits, or None
    when it cannot stand for the whole session: none written; usage follows
    it; the process that wrote it started after the transcript's first call
    (a resume starts the count again); the session was continued in another,
    which takes its running sub-agents' spend; or it holds a model Claude
    Code could not price. OSError if the transcript cannot be read."""
    state, first, stale = None, None, False
    with open(path, "rb") as f:
        for line in f:
            costs = b'"cost-state"' in line or b'"continued-in"' in line
            if not costs and (b'"assistant"' not in line or b'"usage"' not in line):
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict):
                continue
            if e.get("type") == "continued-in":
                return None
            if e.get("type") == "cost-state":
                state, stale = e, False
            elif e.get("type") == "assistant" and (e.get("message") or {}).get("usage"):
                stale = True
                if first is None:
                    first = e.get("timestamp") or ""
    if state is None or stale or state.get("hasUnknownModelCost"):
        return None
    total, start = state.get("totalCostUSD"), state.get("startTime")
    if isinstance(total, bool) or not isinstance(total, (int, float)) or total < 0:
        return None
    if first is not None:
        try:
            began = datetime.datetime.fromisoformat(str(first).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
        if isinstance(start, bool) or not isinstance(start, (int, float)) or start / 1000 > began:
            return None
    return state


def recorded_spend(path):
    """USD Claude Code itself recorded for the session, sub-agents included,
    or None when recorded_state trusts no record. Absent mid-session."""
    state = recorded_state(path)
    return state["totalCostUSD"] if state else None


def share_of_week(usd, week_usd):
    """Spend as a percentage of a plan week priced at week_usd."""
    return 100.0 * usd / week_usd
