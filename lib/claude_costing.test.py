#!/usr/bin/env python3
# Tests for lib/claude_costing. Run: python3 lib/claude_costing.test.py
#
# Cost per push: about a second, a step in CI's existing tool-tests job. No
# network: sync is fed local files and its fetch is made to fail.
import contextlib
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.dont_write_bytecode = True
LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))
import claude_costing as cc  # noqa: E402
from claude_costing import backfill, check, sync  # noqa: E402

JQF = LIB.parent / "hooks" / "session-metrics.jq"
FIXTURE = LIB / "claude_costing.fixture.jsonl"

# The official card, USD per 1M tokens: input, 5m write, 1h write, cache read, output.
# https://platform.claude.com/docs/en/about-claude/pricing
OFFICIAL = {
    "fable-5-2": (8, 10, 16, 0.20, 40), "mythos-5-2": (8, 10, 16, 0.20, 40),
    "fable-5-1": (10, 12.5, 20, 0.25, 50), "mythos-5-1": (10, 12.5, 20, 0.25, 50),
    "fable-5": (10, 12.5, 20, 1, 50), "mythos-5": (10, 12.5, 20, 1, 50),
    "opus-5-5": (4, 5, 8, 0.20, 20),
    "opus-5": (5, 6.25, 10, 0.5, 25), "opus-4-8": (5, 6.25, 10, 0.5, 25),
    "opus-4-7": (5, 6.25, 10, 0.5, 25), "opus-4-6": (5, 6.25, 10, 0.5, 25),
    "opus-4-5": (5, 6.25, 10, 0.5, 25),
    "opus-4-1": (15, 18.75, 30, 1.5, 75), "opus-4": (15, 18.75, 30, 1.5, 75),
    "sonnet-5-5": (2, 2.5, 4, 0.10, 10), "sonnet-5": (2, 2.5, 4, 0.2, 10),
    "sonnet-4-6": (3, 3.75, 6, 0.3, 15), "sonnet-4-5": (3, 3.75, 6, 0.3, 15),
    "sonnet-4": (3, 3.75, 6, 0.3, 15),
    "haiku-5-5": (0.10, 0.125, 0.20, 0.01, 0.50), "haiku-4-5": (1, 1.25, 2, 0.1, 5),
}
HAIKU_5_5_ABOVE_100K = (0.50, 0.625, 1, 0.05, 2.50)
# Names no version rule covers: (name, the listed model whose price it takes).
ALIASES = (("opus", "opus-5-5"), ("sonnet", "sonnet-5-5"), ("haiku", "haiku-5-5"),
           ("fable", "fable-5-2"), ("mythos", "mythos-5-2"), ("opus[1m]", "opus-5-5"),
           ("claude-opus", "opus-5-5"),
           # an unlisted version reads as its family's dearest
           ("claude-opus-4-9", "opus-5"), ("claude-opus-6", "opus-5"),
           ("claude-sonnet-6", "sonnet-4-6"), ("claude-haiku-6", "haiku-4-5"),
           ("claude-fable-6", "fable-5"), ("claude-mythos-preview", "mythos-5"),
           ("claude-3-5-sonnet-20241022", "sonnet-4-6"))


def card(r):
    return (r["input"], r["cache_write_5m"], r["cache_write_1h"], r["cache_read"], r["output"])


def event(mid, model, **u):
    return {"type": "assistant", "uuid": mid, "message": {"id": mid, "model": model, "usage": u}}


def jq_costs(events):
    """cost_usd_by_model as hooks/session-metrics.jq prices a transcript."""
    with tempfile.TemporaryDirectory() as d:
        t = Path(d) / "t.jsonl"
        t.write_text("".join(json.dumps(e) + "\n" for e in events))
        p = subprocess.run(["jq", "-s", "--arg", "sid", "x", "--arg", "repo", "r", "--arg", "branch", "b",
                            "--arg", "now", "t", "--arg", "cwd", "/", "-f", str(JQF), str(t)],
                           capture_output=True, text=True, cwd=os.sep)
    if p.returncode:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)["session"]


class RatesTest(unittest.TestCase):
    def test_every_listed_model_prices_at_the_official_card(self):
        for name, want in OFFICIAL.items():
            for model in (f"claude-{name}", f"claude-{name}-20260101", f"claude-{name}[1m]", name):
                self.assertEqual(card(cc.rates(model)), want, model)

    def test_names_without_a_listed_version(self):
        for name, same_as in ALIASES:
            self.assertEqual(card(cc.rates(name)), OFFICIAL[same_as], name)

    def test_a_request_over_the_threshold_pays_the_higher_tier(self):
        for model in ("claude-haiku-5-5", "claude-haiku-5-5-20260101", "haiku"):
            self.assertEqual(card(cc.rates(model, 100_000)), OFFICIAL["haiku-5-5"], model)
            self.assertEqual(card(cc.rates(model, 100_001)), HAIKU_5_5_ABOVE_100K, model)
        self.assertEqual(card(cc.rates("claude-opus-5-5", 900_000)), OFFICIAL["opus-5-5"])

    def test_an_unknown_model_prices_at_the_top_tier(self):
        for model in ("mystery", "", None):
            self.assertEqual(cc.rates(model)["output"], 50)


class PriceTest(unittest.TestCase):
    def test_repeated_blocks_of_one_message_count_once(self):
        msgs = {}
        for _ in range(3):
            cc.add_usage(event("m1", "claude-opus-5-5", output_tokens=1_000_000), msgs)
        self.assertAlmostEqual(cc.price(msgs), 20)

    def test_cache_writes_by_ttl_and_reads(self):
        msgs = {}
        cc.add_usage(event("m", "claude-opus-5-5", cache_creation_input_tokens=3_000_000,
                           cache_read_input_tokens=1_000_000,
                           cache_creation={"ephemeral_1h_input_tokens": 1_000_000}), msgs)
        # 2M unsplit-or-5m at $5, 1M 1h at $8, 1M read at $0.20
        self.assertAlmostEqual(cc.price(msgs), 10 + 8 + 0.2)

    def test_each_message_is_priced_at_its_own_prompt_size(self):
        msgs = {}
        cc.add_usage(event("small", "claude-haiku-5-5", input_tokens=40_000, cache_read_input_tokens=60_000,
                           output_tokens=1_000_000), msgs)
        cc.add_usage(event("big", "claude-haiku-5-5", input_tokens=40_000, cache_read_input_tokens=60_000,
                           cache_creation_input_tokens=1, output_tokens=1_000_000), msgs)
        small = 0.04 * 0.10 + 0.06 * 0.01 + 0.50
        big = 0.04 * 0.50 + 0.06 * 0.05 + 0.625e-6 + 2.50
        self.assertAlmostEqual(cc.price(msgs), small + big, places=9)

    def test_session_spend_counts_subagents_and_context_is_the_last_call(self):
        with tempfile.TemporaryDirectory() as d:
            main = Path(d) / "s.jsonl"
            main.write_text("\n".join(json.dumps(e) for e in (
                event("a", "claude-haiku-4-5", input_tokens=1_000_000),
                event("b", "claude-haiku-4-5", input_tokens=10, cache_read_input_tokens=5))) + "\n")
            sub = Path(d) / "s" / "subagents" / "agent-x.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text(json.dumps(event("c", "claude-opus-5-5", output_tokens=1_000_000)) + "\n")
            for start in (main, sub):  # a sub-agent's path walks up to the session's
                usd, ctx = cc.session_spend(str(start))
                self.assertAlmostEqual(usd, 1 + 20, places=4)
                self.assertEqual(ctx, 15)

    def test_share_of_week(self):
        self.assertAlmostEqual(cc.share_of_week(100, 2000), 5.0)


def transcript(d, *lines):
    p = Path(d) / "s.jsonl"
    p.write_text("".join(json.dumps(e) + "\n" for e in lines))
    return str(p)


def call(at, mid="m", usd_tokens=1_000_000):
    return {**event(mid, "claude-opus-5-5", output_tokens=usd_tokens), "timestamp": at}


def cost_state(total, start_ms, **more):
    return {"type": "cost-state", "totalCostUSD": total, "startTime": start_ms,
            "modelUsage": {"claude-opus-5-5": {"costUSD": total}}, "hasUnknownModelCost": False, **more}


FIRST, LATER = "2026-10-14T10:14:00.000Z", "2026-10-14T11:00:00.000Z"
# The writing process started a minute before the first call, in epoch ms.
T0 = int(datetime.datetime(2026, 10, 14, 10, 13, tzinfo=datetime.timezone.utc).timestamp() * 1000)


class RecordedTest(unittest.TestCase):
    def recorded(self, *lines):
        with tempfile.TemporaryDirectory() as d:
            return cc.recorded_spend(transcript(d, *lines))

    def test_a_record_written_after_the_last_call_by_the_process_that_made_every_call(self):
        self.assertEqual(self.recorded(call(FIRST), cost_state(20.5, T0)), 20.5)
        # Claude Code may write the line twice, and other lines may follow it
        self.assertEqual(self.recorded(call(FIRST), cost_state(20.5, T0), {"type": "last-prompt"},
                                       cost_state(20.5, T0)), 20.5)

    def test_no_record_mid_session(self):
        self.assertIsNone(self.recorded(call(FIRST)))

    def test_usage_after_the_record_is_not_in_it(self):
        self.assertIsNone(self.recorded(call(FIRST), cost_state(20.5, T0), call(LATER, "m2")))

    def test_a_resumed_session_records_only_its_last_sitting(self):
        resumed = T0 + 30 * 60 * 1000  # the writing process started after the first call
        self.assertIsNone(self.recorded(call(FIRST), call(LATER, "m2"), cost_state(20.0, resumed)))

    def test_a_session_continued_elsewhere_leaves_its_subagents_to_the_other(self):
        self.assertIsNone(self.recorded(call(FIRST), cost_state(20.5, T0), {"type": "continued-in"}))

    def test_a_model_claude_code_could_not_price(self):
        self.assertIsNone(self.recorded(call(FIRST), cost_state(20.5, T0, hasUnknownModelCost=True)))

    def test_a_total_that_is_not_a_number(self):
        self.assertIsNone(self.recorded(call(FIRST), cost_state(None, T0)))

    def test_an_unreadable_transcript_raises(self):
        with self.assertRaises(OSError):
            cc.recorded_spend("/nonexistent/s.jsonl")


def fixture_sessions():
    """[(messages, cost-state)] from the fixture: each session's assistant
    usage, sub-agents folded in, ends at the cost-state line it was stored with."""
    out, msgs = [], {}
    for line in FIXTURE.read_text().splitlines():
        e = json.loads(line)
        if e["type"] == "cost-state":
            out.append((msgs, e))
            msgs = {}
        else:
            cc.add_usage(e, msgs)
    return out


class StoredTotalTest(unittest.TestCase):
    """Real usage, stripped to model and token counts, against what Claude
    Code itself recorded for those sessions."""
    # Over 839 local sessions in 14 days each model with volume summed to
    # 0.97-0.99 of its stored total and none came out above it: a transcript
    # lacks a few calls Claude Code bills. These five sessions sit at 0.98-1.00.
    LOW, HIGH = 0.97, 1.001

    def test_each_session_reprices_to_its_stored_total(self):
        sessions = fixture_sessions()
        self.assertEqual(len(sessions), 5)
        for msgs, state in sessions:
            models = sorted(state["modelUsage"])
            ratio = cc.price(msgs) / state["totalCostUSD"]
            self.assertTrue(self.LOW <= ratio <= self.HIGH, f"{models}: ours/stored = {ratio:.4f}")
            for model, stored in state["modelUsage"].items():
                ours = cc.price({k: u for k, u in msgs.items() if u["model"] == model})
                self.assertTrue(self.LOW <= ours / stored["costUSD"] <= self.HIGH,
                                f"{model}: ours/stored = {ours / stored['costUSD']:.4f}")

    def test_the_fixture_covers_the_models_in_use_and_the_higher_tier(self):
        models, over = set(), 0
        for msgs, _ in fixture_sessions():
            for u in msgs.values():
                models.add(u["model"])
                prompt = u["input_tokens"] + u["cache_read_input_tokens"] + u["cache_creation_input_tokens"]
                over += "haiku-5-5" in u["model"] and prompt > 100_000
        self.assertEqual(models, {"claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"})
        self.assertGreater(over, 0)

    def test_the_fixture_holds_nothing_but_models_and_counts(self):
        def strings(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from strings(v)
            elif isinstance(o, str):
                yield o
        words = {"type", "assistant", "message", "id", "model", "usage", "cache_creation", *cc.FIELDS[:4],
                 "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens", "cost-state", "totalCostUSD",
                 "modelUsage", "inputTokens", "outputTokens", "cacheReadInputTokens",
                 "cacheCreationInputTokens", "costUSD", *(f"claude-{m}" for m in OFFICIAL)}
        for line in FIXTURE.read_text().splitlines():
            for text in strings(json.loads(line)):
                self.assertTrue(text in words or text[:1] == "m" and text[1:].isdigit(), text)


class CheckTest(unittest.TestCase):
    def projects(self, d, sessions):
        paths = []
        for i, (events, state) in enumerate(sessions):
            p = Path(d) / "proj" / f"s{i}.jsonl"
            p.parent.mkdir(exist_ok=True)
            p.write_text("".join(json.dumps(e) + "\n" for e in events + ([state] if state else [])))
            paths.append(str(p))
        return paths

    def test_compares_trusted_sessions_per_model_with_their_subagents(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self.projects(d, [([call(FIRST)], cost_state(41.0, T0)),
                                      ([call(FIRST)], None)])  # still running: no record
            sub = Path(d) / "proj" / "s0" / "subagents" / "agent-x.jsonl"
            sub.parent.mkdir(parents=True)
            sub.write_text(json.dumps(call(LATER, "sub")) + "\n")
            rows, covered, seen = check.compare(paths)
            self.assertEqual((covered, seen), (1, 2))
            n, ours, stored = rows["claude-opus-5-5"]
            self.assertEqual((n, stored), (1, 41.0))
            self.assertAlmostEqual(ours, 40.0)

    def test_a_model_with_volume_outside_the_bounds_fails_and_a_small_one_does_not(self):
        self.assertEqual(check.failing({"a": [9, 98.0, 100.0], "b": [1, 0.5, 1.0]}), [])
        self.assertEqual(check.failing({"a": [9, 150.0, 100.0], "b": [9, 99.0, 100.0]}), ["a"])
        self.assertEqual(check.failing({"a": [9, 90.0, 100.0]}), ["a"])

    def test_the_command_exits_by_the_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            self.projects(d, [([call(FIRST)], cost_state(20.0, T0))])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check.main(["--projects", d]), 0)
            self.projects(d, [([call(FIRST)], cost_state(10.0, T0))])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(check.main(["--projects", d]), 1)


class BackfillTest(unittest.TestCase):
    SID = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        (self.d / "projects" / "proj").mkdir(parents=True)
        (self.d / "sessions" / "11").mkdir(parents=True)
        self.record = self.d / "sessions" / "11" / f"{self.SID}.json"
        self.record.write_text(json.dumps({"session_id": self.SID, "cost_usd": 99.0, "model": "claude-opus-5-5"},
                                          separators=(",", ":")))

    def session(self, *lines):
        p = self.d / "projects" / "proj" / f"{self.SID}.jsonl"
        p.write_text("".join(json.dumps(e) + "\n" for e in lines))
        return p

    def run_it(self, write=True):
        return backfill.run(str(self.d / "sessions"), str(self.d / "projects"), write)

    def stored(self):
        return json.loads(self.record.read_text())

    def test_a_trusted_stored_total_is_the_record_split_as_claude_code_split_it(self):
        self.session(call(FIRST), cost_state(41.0, T0, modelUsage={
            "claude-opus-5-5": {"costUSD": 30.0}, "claude-opus-5-5[1m]": {"costUSD": 10.0},
            "claude-haiku-5-5": {"costUSD": 1.0}}))
        self.assertEqual(self.run_it()["changed"], [1, 99.0, 41.0])
        rec = self.stored()
        self.assertEqual((rec["cost_usd"], rec["cost_source"], rec["model"]), (41.0, "claude-code", "claude-opus-5-5"))
        self.assertEqual(rec["cost_usd_by_model"], {"claude-haiku-5-5": 1.0, "claude-opus-5-5": 40.0})

    def test_without_one_the_table_prices_the_transcript_and_its_subagents(self):
        p = self.session(call(FIRST))
        sub = p.with_suffix("") / "subagents" / "agent-x.jsonl"
        sub.parent.mkdir(parents=True)
        sub.write_text(json.dumps(call(LATER, "sub")) + "\n")
        self.run_it()
        rec = self.stored()
        self.assertEqual((rec["cost_usd"], rec["cost_source"]), (40.0, "price-table"))
        self.assertEqual(rec["cost_usd_by_model"], {"claude-opus-5-5": 40.0})

    def test_a_second_run_writes_nothing_and_a_later_exit_total_replaces_the_price(self):
        self.session(call(FIRST))
        self.run_it()
        first = self.record.read_bytes()
        self.assertEqual(self.run_it()["same"][0], 1)
        self.assertEqual(self.record.read_bytes(), first)
        self.session(call(FIRST), cost_state(21.0, T0))
        self.assertEqual(self.run_it()["changed"], [1, 20.0, 21.0])
        self.assertEqual(self.stored()["cost_source"], "claude-code")

    def test_a_dry_run_reports_and_leaves_the_record(self):
        self.session(call(FIRST))
        before = self.record.read_bytes()
        self.assertEqual(self.run_it(write=False)["changed"], [1, 99.0, 20.0])
        self.assertEqual(self.record.read_bytes(), before)

    def test_a_record_with_no_transcript_here_and_a_file_that_is_no_record_are_left_alone(self):
        junk = self.d / "sessions" / "junk.json"
        junk.write_text("not json")
        before = self.record.read_bytes()
        self.assertEqual(self.run_it()["skipped"][0], 2)
        self.assertEqual((self.record.read_bytes(), junk.read_text()), (before, "not json"))

    def test_a_record_rewritten_while_the_transcript_parses_is_left_as_the_writer_left_it(self):
        self.session(call(FIRST))
        real = backfill.answer

        def answer_then_stop_hook_writes(path):
            out = real(path)
            self.record.write_text(json.dumps({"session_id": self.SID, "cost_usd": 5.0}))
            return out

        with unittest.mock.patch.object(backfill, "answer", answer_then_stop_hook_writes):
            self.assertEqual(self.run_it()["skipped"][0], 1)
        self.assertEqual(self.stored()["cost_usd"], 5.0)

    def test_both_record_layouts_and_the_command(self):
        self.session(call(FIRST))
        flat = self.d / "sessions" / f"{self.SID}.json"
        flat.write_text(json.dumps({"session_id": self.SID}, indent=2) + "\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(backfill.main(["--sessions", str(self.d / "sessions"),
                                            "--projects", str(self.d / "projects")]), 0)
        self.assertIn("changed 2 records: $99.00 -> $40.00", out.getvalue())
        self.assertEqual(json.loads(flat.read_text())["cost_usd"], 20.0)
        self.assertTrue(flat.read_text().startswith("{\n") and flat.read_text().endswith("}\n"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(backfill.main(["--sessions", str(self.d / "absent")]), 1)


class ShellTest(unittest.TestCase):
    def test_rates_from_the_command_line(self):
        out = subprocess.run([sys.executable, str(LIB / "claude_costing"), "rates", "fable-5-1"],
                             capture_output=True, text=True, check=True, cwd=os.sep).stdout
        self.assertEqual(out.split(), ["10", "50", "0.25", "12.5"])

    def test_pricing_never_loads_the_module_that_fetches(self):
        code = ("import sys, claude_costing; claude_costing.rates('opus'); "
                "sys.exit(any(m in sys.modules for m in ('claude_costing.sync', 'urllib.request')))")
        p = subprocess.run([sys.executable, "-c", code], env={**os.environ, "PYTHONPATH": str(LIB)}, cwd=os.sep)
        self.assertEqual(p.returncode, 0)


class JqTest(unittest.TestCase):
    def test_session_metrics_prices_from_the_same_table(self):
        got = jq_costs([event("m", "claude-fable-5-1", output_tokens=1_000_000,
                              cache_read_input_tokens=1_000_000)])
        self.assertAlmostEqual(got["cost_usd"], 50.25)

    def test_jq_and_python_price_every_rule_and_tier_alike(self):
        # The lookup is written twice, once per language; this holds them to
        # one answer for every rule, both tiers, and a name no rule matches.
        names = ([f"claude-{n}" for n in OFFICIAL] + [f"claude-{n}-20260101" for n in OFFICIAL]
                 + [n for n, _ in ALIASES] + ["sonnet[1m]", "some-new-model"])
        hit = {id(cc._rule(n)) for n in names}
        self.assertEqual(hit, {id(r) for r in cc.TABLE["rules"]} | {id(cc.TABLE["fallback"])})
        for scale in (1_000_000, 10_000):  # over and under the prompt-size threshold
            usage = {"input_tokens": scale, "output_tokens": scale,
                     "cache_read_input_tokens": scale, "cache_creation_input_tokens": 3 * scale,
                     "cache_creation": {"ephemeral_5m_input_tokens": scale,
                                        "ephemeral_1h_input_tokens": 2 * scale}}
            got = jq_costs([event(f"m{i}", n, **usage) for i, n in enumerate(names)])["cost_usd_by_model"]
            for n in names:
                msgs = {}
                cc.add_usage(event("m", n, **usage), msgs)
                self.assertAlmostEqual(got[n], cc.price(msgs), places=3, msg=f"{n} at {scale}")
        self.assertNotEqual(card(cc.rates("haiku", 5 * 1_000_000)), card(cc.rates("haiku", 5 * 10_000)))


def row(i, o, read, w5, w1, **more):
    """A LiteLLM-shaped row from USD per 1M tokens."""
    return {"litellm_provider": "anthropic", "input_cost_per_token": i / 1e6,
            "output_cost_per_token": o / 1e6, "cache_read_input_token_cost": read / 1e6,
            "cache_creation_input_token_cost": w5 / 1e6,
            "cache_creation_input_token_cost_above_1hr": w1 / 1e6, **more}


def above(k, i, o, read, w5, w1):
    s = f"_above_{k}k_tokens"
    return {"input_cost_per_token" + s: i / 1e6, "output_cost_per_token" + s: o / 1e6,
            "cache_read_input_token_cost" + s: read / 1e6, "cache_creation_input_token_cost" + s: w5 / 1e6,
            "cache_creation_input_token_cost_above_1hr" + s: w1 / 1e6}


def source():
    return {
        "sample_spec": {"litellm_provider": "one of https://docs.litellm.ai/docs/providers"},
        "gpt-9": {"litellm_provider": "openai", "input_cost_per_token": 1e-6},
        "claude-opus-5-5": row(4, 20, 0.2, 5, 8),
        "claude-opus-5": row(5, 25, 0.5, 6.25, 10),
        "claude-opus-5-20260101": row(5, 25, 0.5, 6.25, 10),
        "claude-fable-5-2": row(8, 40, 0.2, 10, 16),
        "claude-mythos-5-2": row(8, 40, 0.2, 10, 16),
        "claude-haiku-5-5": row(0.1, 0.5, 0.01, 0.125, 0.2, **above(100, 0.5, 2.5, 0.05, 0.625, 1)),
        "claude-haiku-4-5-20251001": row(1, 5, 0.1, 1.25, 2,
                                         input_cost_per_token_batches=0.5e-6),
        "claude-mythos-preview": row(10, 50, 1, 12.5, 20),
    }


MANUAL = {"match": "opus-4-1(?![0-9])", "input": 15, "output": 75, "cache_read": 1.5,
          "cache_write_5m": 18.75, "cache_write_1h": 30, "manual": True}


class SyncTest(unittest.TestCase):
    def setUp(self):
        def no_network(url):
            raise AssertionError(f"a test reached for {url}")
        self._fetch, sync.fetch = sync.fetch, no_network
        self.addCleanup(setattr, sync, "fetch", self._fetch)

    def rates_of(self, table, name, prompt=0):
        import re
        rule = next((r for r in table["rules"] if re.search(r["match"], name)), table["fallback"])
        tier = rule["above"] if "above" in rule and prompt > rule["above"]["prompt_tokens"] else rule
        return card(tier)

    def test_builds_version_alias_and_family_rules_in_that_order(self):
        table, notes = sync.build(source(), {"rules": [MANUAL]})
        want = {"claude-opus-5-5": (4, 5, 8, 0.2, 20), "claude-opus-5": (5, 6.25, 10, 0.5, 25),
                "claude-opus-5-20270101": (5, 6.25, 10, 0.5, 25),
                "claude-opus-4-1-20250805": (15, 18.75, 30, 1.5, 75),      # the manual rule
                "opus": (4, 5, 8, 0.2, 20),                                # newest
                "claude-opus-7": (5, 6.25, 10, 0.5, 25),                    # dearest listed
                "claude-opus-5-9": (5, 6.25, 10, 0.5, 25),
                "claude-mythos-5-2": (8, 10, 16, 0.2, 40), "fable[1m]": (8, 10, 16, 0.2, 40),
                "claude-haiku-4-5": (1, 1.25, 2, 0.1, 5), "haiku": (0.1, 0.125, 0.2, 0.01, 0.5),
                "claude-haiku-9": (1, 1.25, 2, 0.1, 5),
                "gpt-9": (8, 10, 16, 0.2, 40)}                             # fallback: dearest in the source
        for name, rates in want.items():
            self.assertEqual(self.rates_of(table, name), rates, name)
        self.assertEqual(self.rates_of(table, "claude-haiku-5-5", 100_001), (0.5, 0.625, 1, 0.05, 2.5))
        self.assertEqual([r["match"] for r in table["rules"] if r.get("manual")], [MANUAL["match"]])
        self.assertEqual(sum(r["match"].startswith("(fable|mythos)") for r in table["rules"]), 1)
        self.assertTrue(any("claude-mythos-preview" in n for n in notes))

    def test_output_is_stable_and_a_rule_is_a_line(self):
        a, _ = sync.build(source(), {"rules": [MANUAL]})
        b, _ = sync.build(dict(reversed(list(source().items()))), a)
        self.assertEqual(sync.dumps(a), sync.dumps(b))
        text = sync.dumps(a)
        self.assertEqual(json.loads(text), a)
        self.assertEqual(sum(line.startswith('    {"match"') for line in text.splitlines()), len(a["rules"]))

    def test_refuses_a_source_it_cannot_trust(self):
        def broken(**change):
            return {**source(), **change}
        cases = {
            "dated and undated ids of one version disagree": broken(**{"claude-opus-5-20260101": row(6, 25, 0.5, 6.25, 10)}),
            "output not above input": broken(**{"claude-opus-5-5": row(20, 4, 0.2, 5, 8)}),
            "cache read not below input": broken(**{"claude-opus-5-5": row(4, 20, 4, 5, 8)}),
            "1h write below 5m write": broken(**{"claude-opus-5-5": row(4, 20, 0.2, 8, 5)}),
            "5m write below input": broken(**{"claude-opus-5-5": row(4, 20, 0.2, 3, 8)}),
            "a zero rate": broken(**{"claude-opus-5-5": row(4, 20, 0, 5, 8)}),
            "per-token and per-million confused": broken(**{"claude-opus-5-5": row(4e6, 20e6, 2e5, 5e6, 8e6)}),
            "a rate missing": broken(**{"claude-opus-5-5": {"litellm_provider": "anthropic",
                                                            "input_cost_per_token": 4e-6}}),
            "a rate that is text": broken(**{"claude-opus-5-5": row(4, 20, 0.2, 5, 8, output_cost_per_token="20")}),
            "two prompt-size tiers": broken(**{"claude-haiku-5-5": row(
                0.1, 0.5, 0.01, 0.125, 0.2, **above(100, 0.5, 2.5, 0.05, 0.625, 1), **above(200, 1, 5, 0.1, 1.25, 2))}),
            "a higher tier that is cheaper": broken(**{"claude-haiku-5-5": row(
                1, 5, 0.1, 1.25, 2, **above(100, 0.5, 2.5, 0.05, 0.625, 1))}),
            "a higher tier with a rate missing": broken(**{"claude-haiku-5-5": row(
                0.1, 0.5, 0.01, 0.125, 0.2, input_cost_per_token_above_100k_tokens=0.5e-6)}),
            "no Anthropic model": {"gpt-9": {"litellm_provider": "openai"}},
            "not an object": [],
        }
        for what, data in cases.items():
            with self.assertRaises(sync.SyncError, msg=what):
                sync.build(data)

    def test_manual_rules_survive_until_the_source_lists_the_model(self):
        with_41 = {**source(), "claude-opus-4-1": row(15, 75, 1.5, 18.75, 30)}
        table, notes = sync.build(with_41, {"rules": [MANUAL]})
        self.assertFalse(any(r.get("manual") for r in table["rules"]))
        self.assertTrue(any("manual" in n for n in notes))
        with self.assertRaises(sync.SyncError):  # the two disagree: a person settles it
            sync.build({**source(), "claude-opus-4-1": row(14, 75, 1.5, 18.75, 30)}, {"rules": [MANUAL]})
        with self.assertRaises(sync.SyncError):  # a manual rule must be a version rule in bounds
            sync.build(source(), {"rules": [{**MANUAL, "match": "opus"}]})
        with self.assertRaises(sync.SyncError):
            sync.build(source(), {"rules": [{**MANUAL, "output": 1}]})

    def run_sync(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sync.main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_command_writes_checks_and_fails_without_touching_the_table(self):
        with tempfile.TemporaryDirectory() as d:
            src, table = Path(d) / "src.json", Path(d) / "prices.json"
            src.write_text(json.dumps(source()))
            table.write_text(json.dumps({"rules": [MANUAL]}))
            rc, out, _ = self.run_sync("--from", str(src), "--table", str(table), "--check")
            self.assertEqual(rc, 1)                      # differs, and --check wrote nothing
            self.assertIn("opus-5-5", out)
            self.assertEqual(json.loads(table.read_text()), {"rules": [MANUAL]})
            rc, _, _ = self.run_sync("--from", str(src), "--table", str(table), "--commit", "a" * 40)
            self.assertEqual(rc, 0)
            written = table.read_text()
            self.assertEqual(json.loads(written)["source"]["commit"], "a" * 40)
            self.assertEqual(self.run_sync("--from", str(src), "--table", str(table), "--check")[0], 0)
            # the same prices at a newer commit leave the file, and its pin, alone
            self.run_sync("--from", str(src), "--table", str(table), "--commit", "b" * 40)
            self.assertEqual(table.read_text(), written)
            changed = {**source(), "claude-opus-5-5": row(3, 15, 0.2, 5, 8)}
            src.write_text(json.dumps(changed))
            rc, out, _ = self.run_sync("--from", str(src), "--table", str(table), "--check")
            self.assertEqual(rc, 1)
            self.assertIn('"input": 3', out)
            src.write_text(json.dumps({**changed, "claude-opus-5": row(25, 5, 0.5, 6.25, 10)}))
            rc, _, err = self.run_sync("--from", str(src), "--table", str(table))
            self.assertEqual(rc, 2)
            self.assertIn("claude-opus-5", err)
            src.write_text("not json")
            self.assertEqual(self.run_sync("--from", str(src), "--table", str(table))[0], 2)
            self.assertEqual(table.read_text(), written)

    def test_a_commit_must_be_a_full_sha(self):
        with tempfile.TemporaryDirectory() as d:
            rc, _, err = self.run_sync("--commit", "main", "--table", str(Path(d) / "p.json"))
            self.assertEqual(rc, 2)
            self.assertIn("40-hex", err)

    def test_the_committed_table_is_as_sync_writes_it_and_pinned_to_a_commit(self):
        text = (LIB / "claude_costing" / "prices.json").read_text()
        self.assertEqual(sync.dumps(json.loads(text)), text)
        self.assertRegex(cc.TABLE["source"]["commit"], r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
