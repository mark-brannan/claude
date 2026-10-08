"""The harness behind features/*.feature: the steps, and the scratch world
they run in.

The world is `World` from hooks/stop-continuity.test.py, loaded by path
because that file's name is not an importable module name: one scratch HOME
and TMPDIR, the fake gh first on PATH, the salvage commit off and the state
dir outside any git repo. Reusing it keeps one definition of "how the hook
is run under test"; a scenario and a unittest case see the same world.

Each scenario gets a fresh world and a fresh Stop event. The Given steps
shape the event, the one When step runs the hook, and the Then steps read
what it left behind.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, then, when

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
HOOK = HOOKS / "stop-continuity.py"
SID = "feature0-1111-2222-3333"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


World = _load("stop_continuity_suite", HOOKS / "stop-continuity.test.py").World


class Stop:
    """One Stop under test: the event the Given steps build, the run, and
    what it left. `stdin` set directly overrides the event (row 0.1)."""

    def __init__(self, world):
        self.world = world
        self.event = {"transcript_path": world_transcript(), "session_id": SID, "cwd": ""}
        self.stdin = None
        self.rc = None

    @property
    def sid(self):
        return self.event.get("session_id", SID)

    def run(self):
        data = self.stdin if self.stdin is not None else json.dumps(self.event).encode()
        p = subprocess.run([sys.executable, str(HOOK)], input=data, env=self.world.env(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        self.rc = p.returncode

    def live_file(self):
        return self.world.GS / "metrics" / "live" / f"{self.sid}.json"

    def metrics_record(self):
        sid = self.sid
        return self.world.GS / "metrics" / "sessions" / sid[:2] / f"{sid}.json"


def world_transcript():
    return str(HOOKS / "fixtures" / "friction-calm.jsonl")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path / "world")


@pytest.fixture
def stop(world):
    return Stop(world)


# ---------------------------------------------------------------- Given

@given(parsers.parse("{what} on the hook's stdin"))
def raw_stdin(stop, what):
    stop.stdin = {"nothing": b"", "text that is not JSON": b"not json\n",
                  "an event with no fields": b"{}"}[what]


@given("a Stop event for a session in a worked repo")
def event_in_worked_repo(stop, world):
    _, work = world.make_work()
    stop.event["cwd"] = str(work)


@given("a Stop event whose cwd is outside any repo")
def event_outside_repo(stop, world):
    nogit = world.S / "nogit"
    nogit.mkdir()
    stop.event["cwd"] = str(nogit)


@given("the event has no transcript_path")
def no_transcript_path(stop):
    del stop.event["transcript_path"]


@given("the event names a transcript that does not exist")
def missing_transcript(stop, world):
    stop.event["transcript_path"] = str(world.S / "no-such-transcript.jsonl")


@given("the event has no session_id")
def no_session_id(stop):
    del stop.event["session_id"]


@given("the session's metrics/live/<id>.json exists")
def live_file_exists(stop):
    stop.live_file().parent.mkdir(parents=True)
    stop.live_file().write_text("{}\n")


# ----------------------------------------------------------------- When

@when("the Stop hook runs")
def run_hook(stop):
    stop.run()


# ----------------------------------------------------------------- Then

@then("it exits 0")
def exits_zero(stop):
    assert stop.rc == 0


@then("nothing is written under the state dir")
def nothing_written(world):
    written = [str(p) for p in world.GS.rglob("*") if p.is_file()] if world.GS.exists() else []
    assert written == []


@then("the session's metrics/live/<id>.json is gone")
def live_file_gone(stop):
    assert not stop.live_file().exists()


@then(parsers.parse('the verdict is "{text}"'))
def verdict_is(stop, text):
    rec = stop.metrics_record()
    assert rec.is_file(), f"no metrics record at {rec}"
    assert json.loads(rec.read_text()).get("verdict") == text
