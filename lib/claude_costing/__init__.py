"""Price Claude Code work at API list prices: the price table, a transcript's
usage, a session's spend with its sub-agents, and spend as a share of the plan
week.

Self-contained by design, so it can leave this repo whole: stdlib only, no
import from the rest of lib/, and settings (the plan figures) come in as
arguments, never read here. hooks/session-metrics.jq reads the same table,
prices.json, as jq data.

Usage folds into a dict of messages keyed by message id: a message's content
blocks each arrive as a transcript event carrying the same usage, so each
field keeps its largest value rather than summing.
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.realpath(__file__))
FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens",
          "cache_creation_input_tokens", "cache_5m", "cache_1h")

with open(os.path.join(HERE, "prices.json"), encoding="utf-8") as _f:
    TABLE = json.load(_f)


def rates(model):
    """{input, output, cache_read} in USD per 1M tokens for a model name."""
    name = model or ""
    rule = next((r for r in TABLE["rules"] if re.search(r["match"], name)), TABLE["fallback"])
    return {"input": rule["input"], "output": rule["output"],
            "cache_read": rule.get("cache_read", rule["input"] * TABLE["cache_read_ratio"])}


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
    """USD for folded messages, each at its own model's rates."""
    spend = 0.0
    for u in msgs.values():
        r = rates(u["model"])
        write = u["cache_creation_input_tokens"]
        w1h = min(u["cache_1h"], write)
        w5m = write - w1h  # unsplit writes price as the 5-minute cache
        spend += (u["input_tokens"] * r["input"] + u["output_tokens"] * r["output"]
                  + u["cache_read_input_tokens"] * r["cache_read"]
                  + w5m * r["input"] * TABLE["cache_write_5m"]
                  + w1h * r["input"] * TABLE["cache_write_1h"])
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


def share_of_week(usd, week_usd):
    """Spend as a percentage of a plan week priced at week_usd."""
    return 100.0 * usd / week_usd
