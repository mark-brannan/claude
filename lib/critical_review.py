"""One metrics row per critical review: what it cost and what it produced.

Two writers, one row shape, one home:
  - the Stop hook (stop-continuity.py) finds every `/critical-review` the
    user typed in the session's transcript; the review runs from that
    command to the next human prompt, sub-agents spawned inside it included;
  - `prt spent` writes one for each review prt dispatched to a sub-agent,
    priced from that agent's transcript.

Rows land in <state>/metrics/critical-review/<session_id>.jsonl. The Stop
hook recomputes its rows (by=user) from the transcript every time it fires;
prt's rows are keyed by agent id. Either rewrite replaces its own rows and
keeps the other's, under a lock on the file. Imported, never run directly;
stdlib only.
"""
import collections
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import lock  # noqa: E402
import state  # noqa: E402

MARK = b"<command-name>/critical-review</command-name>"
COMMAND = re.compile(r"^\s*(?:<command-message>[^<]*</command-message>\s*)?"
                     r"<command-name>/critical-review</command-name>\s*"
                     r"(?:<command-args>(.*?)</command-args>)?", re.S)
# Not the user speaking: hand-backs and injected content the harness queues.
QUEUED = re.compile(r"^\s*<(task-notification|agent-message|system-reminder|local-command)")
HEADINGS = (("fixed", "Fixed"), ("look_at", "Look at"), ("pencil", "Pencil"), ("decide", "Decide"))
# `**Fixed**`, `**Fixed** (commit abc)`, `## Fixed`, `Fixed:` -- not `**Fixed now**`.
_NAMES = "Fixed|Look at|Pencil|Decide"
HEADING = re.compile(rf"^\s{{0,3}}(?:#{{1,6}}\s*)?(?:\*\*\s*({_NAMES})\s*:?\s*\*\*(?:[\s:(—-].*)?"
                     rf"|({_NAMES})\s*:?\s*)$|^\s{{0,3}}#{{1,6}}\s+({_NAMES})\b.*$", re.I)
ITEM = re.compile(r"^\s?(?:[-*+]|\d+[.)])\s+(.*\S)")
NONE = re.compile(r"^[\W_]*(none|nothing|n/a)\b[\W_]*$", re.I)
USAGE = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def spend_gate():
    """hooks/spend-gate.py, the one home of the price table and the usage reader."""
    path = os.path.join(os.path.dirname(HERE), "hooks", "spend-gate.py")
    spec = importlib.util.spec_from_file_location("spend_gate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def events(path):
    out = []
    with open(path, "rb") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


def command_args(e):
    """The /critical-review command's args, or None when e is not that command."""
    if e.get("type") != "user" or e.get("isMeta"):
        return None
    m = COMMAND.match(text_of((e.get("message") or {}).get("content")))
    return None if m is None else (m.group(1) or "").strip()


def human_prompt(e):
    """A prompt the user typed, which ends the review before it."""
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    origin = (e.get("origin") or {}).get("kind")
    if origin is not None:
        return origin == "human"
    content = (e.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                         for b in content):
        return False
    text = text_of(content)
    return bool(text.strip()) and not QUEUED.match(text)


def stamp(ts):
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def summary_counts(text):
    """Item counts under the four summary headings; a heading not found is None."""
    counts = dict.fromkeys(k for k, _ in HEADINGS)
    cur = None
    for ln in text.splitlines():
        h = HEADING.match(ln)
        if h:
            word = next(g for g in h.groups() if g).lower()
            cur = next(k for k, name in HEADINGS if name.lower() == word)
            counts[cur] = 0
            continue
        item = ITEM.match(ln)
        if cur and item and not NONE.match(item.group(1)):
            counts[cur] += 1
    return counts


def last_summary(evs):
    """Counts from the last assistant message that carries a summary heading."""
    texts = collections.OrderedDict()
    for e in evs:
        if e.get("type") != "assistant":
            continue
        m = e.get("message") or {}
        mid = m.get("id") or e.get("uuid")
        texts[mid] = texts.get(mid, "") + text_of(m.get("content")) + "\n"
    for text in reversed(list(texts.values())):
        c = summary_counts(text)
        if any(v is not None for v in c.values()):
            return c
    return dict.fromkeys(k for k, _ in HEADINGS)


def most_common(values):
    values = [v for v in values if v and v != "<synthetic>"]
    return collections.Counter(values).most_common(1)[0][0] if values else None


def tool_ids(evs):
    return {b.get("id") for e in evs if e.get("type") == "assistant"
            for b in ((e.get("message") or {}).get("content") or [])
            if isinstance(b, dict) and b.get("type") == "tool_use"}


def subagents(transcript, spawned):
    """[(path, events)] of every sub-agent transcript a tool call in `spawned`
    started, and the ones those started in turn. A meta file names the call."""
    base = transcript[:-len(".jsonl")] if transcript.endswith(".jsonl") else transcript
    root = os.path.join(base, "subagents")
    metas = {}
    for d, _, files in os.walk(root):
        for f in files:
            if f.endswith(".meta.json"):
                try:
                    with open(os.path.join(d, f)) as fh:
                        tid = json.load(fh).get("toolUseId")
                except (OSError, ValueError, AttributeError):
                    continue
                metas.setdefault(tid, []).append(os.path.join(d, f[:-len(".meta.json")] + ".jsonl"))
    found, todo = [], list(spawned)
    while todo:
        for p in metas.pop(todo.pop(), []):
            try:
                evs = events(p)
            except OSError:
                continue
            found.append((p, evs))
            todo.extend(tool_ids(evs))
    return found


def measure(main, subs):
    """The row's cost and shape fields, from the review's own events and its sub-agents'."""
    sg = spend_gate()
    msgs, calls = {}, set()
    for evs in [main] + [s for _, s in subs]:
        for e in evs:
            sg.add_usage(e, msgs)
        calls |= tool_ids(evs)
    times = [t for t in (stamp(e.get("timestamp")) for e in main) if t]
    asst = [e for e in main if e.get("type") == "assistant"]
    row = {"model": most_common((e.get("message") or {}).get("model") for e in asst),
           # Claude Code stamps each assistant event with the session's effort level.
           "effort": most_common(e.get("effort") for e in asst)}
    for k in USAGE:
        row[k] = sum(u[k] for u in msgs.values())
    row.update({"usd": round(sg.price(msgs), 4), "turns": len(msgs), "tool_calls": len(calls),
                "subagents": len(subs),
                "wall_s": round((max(times) - min(times)).total_seconds()) if times else None})
    return row


def origin_repo(cwd):
    try:
        p = subprocess.run(["git", "-C", cwd or ".", "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", p.stdout.strip())
    return f"{m[1]}/{m[2]}" if p.returncode == 0 and m else None


def pr_of(args, cwd):
    """(owner/repo#n, guessed). A bare number is resolved against cwd's origin,
    which is a guess; anything unreadable is (None, False)."""
    m = re.search(r"github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)", args or "")
    if m:
        return f"{m[1]}/{m[2]}#{m[3]}", False
    m = re.match(r"([\w.-]+)/([\w.-]+)#(\d+)\b", args or "")
    if m:
        return f"{m[1]}/{m[2]}#{m[3]}", False
    m = re.match(r"#?(\d+)\b", args or "")
    if m:
        repo = origin_repo(cwd)
        return (f"{repo}#{m[1]}", True) if repo else (None, True)
    return None, False


def session_rows(sid, transcript, cwd):
    """One row per /critical-review the user typed in this transcript."""
    evs = events(transcript)
    rows = []
    starts = [i for i, e in enumerate(evs) if command_args(e) is not None]
    for i in starts:
        cmd = evs[i]
        end = next((j for j in range(i + 1, len(evs)) if human_prompt(evs[j])), len(evs))
        window = evs[i:end]
        pr, guessed = pr_of(command_args(cmd), cmd.get("cwd") or cwd)
        meta = {"ts": cmd.get("timestamp"), "session_id": sid, "review_id": cmd.get("uuid"),
                "pr": pr, "pr_guessed": guessed, "by": "user", "run": None}
        subs = subagents(transcript, tool_ids(window))
        rows.append({**meta, **measure(window, subs), **last_summary(window)})
    return rows


def agent_row(transcript, pr, run, sid=""):
    """The row for one review prt dispatched: the agent's whole transcript."""
    evs = events(transcript)
    name = os.path.basename(transcript)[:-len(".jsonl")]
    parent = transcript.split(os.sep + "subagents" + os.sep)[0]
    sid = sid or next((e.get("sessionId") for e in evs if e.get("sessionId")), "") \
        or (os.path.basename(parent) if parent != transcript else "")
    meta = {"ts": next((e.get("timestamp") for e in evs if e.get("timestamp")), None),
            "session_id": sid, "review_id": name, "pr": pr, "pr_guessed": False,
            "by": "prt", "run": run}
    subs = subagents(parent + ".jsonl", tool_ids(evs)) if parent != transcript else []
    return {**meta, **measure(evs, subs), **last_summary(evs)}


def path_for(sid):
    sid = sid or "_"
    return state.state_shard_path(f"{state.state_dir()}/metrics/critical-review", f"{sid}.jsonl", sid)


def merge(path, rows, drop):
    """Rewrite path under its lock: existing rows drop() matches go, rows are added."""
    if not rows and not os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with lock.locked(path) as fd:
        old = b""
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            old += chunk
        keep = []
        for ln in old.decode("utf-8", "surrogateescape").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                r = None
            if ln.strip() and not (isinstance(r, dict) and drop(r)):
                keep.append(ln)
        data = "".join(x + "\n" for x in keep + [json.dumps(r, separators=(",", ":")) for r in rows])
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        buf = memoryview(data.encode("utf-8", "surrogateescape"))
        while buf:
            buf = buf[os.write(fd, buf):]


def record_session(sid, transcript, cwd):
    """The Stop hook's half: recompute this session's by=user rows."""
    with open(transcript, "rb") as f:
        if MARK not in f.read():
            return
    merge(path_for(sid), session_rows(sid, transcript, cwd), lambda r: r.get("by") == "user")


def save_agent(row):
    """prt's half: write (or replace) the row agent_row built for one review."""
    merge(path_for(row["session_id"]), [row],
          lambda r: r.get("by") == "prt" and r.get("review_id") == row["review_id"])
