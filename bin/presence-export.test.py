#!/usr/bin/env python3
# Tests for presence-export. Run: python3 bin/presence-export.test.py
#
# Offline and synthetic: a fake Home Assistant on a loopback port, shaped like
# the real /api/history/period answer with minimal_response, and a throwaway
# state directory.
#
# What matters: on and off spans spread across the minutes they touch;
# unknown and unavailable leave gaps, never zeros; the first state is clipped
# to the window's start; the minute in progress is left out; a rerun writes
# nothing new; no token or no HA exits 0 having written nothing; a refused
# token exits 1.
import http.server
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "presence-export"
spec = importlib.util.spec_from_loader("presence_export", importlib.machinery.SourceFileLoader("presence_export", str(ENGINE)))
pe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pe)

M = 29875363  # 2026-10-20T18:43Z, a fixed minute well in the past
ENTITY = "binary_sensor.desk_presence_presence"
TOKEN = "fixture-token"
def at(minute, sec=0.0):
    return pe.iso(minute * 60 + sec)

# Before M: unknown since long ago (HA clips it to the window start). Then
# on 30 s into M for 60 s, off 30 s, unavailable for a minute, on again from
# M+3 for 30 s, then unknown until now.
HISTORY = [[
    {"entity_id": ENTITY, "state": "unknown", "last_changed": at(M - 600, 0.841337),
     "last_updated": at(M - 600, 0.841337), "attributes": {}},
    {"state": "on", "last_changed": at(M, 30)},
    {"state": "off", "last_changed": at(M + 1, 30)},
    {"state": "unavailable", "last_changed": at(M + 2, 0)},
    {"state": "on", "last_changed": at(M + 3, 0)},
    {"state": "unknown", "last_changed": at(M + 3, 30)},
]]

class FakeHA(http.server.BaseHTTPRequestHandler):
    seen = []
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        FakeHA.seen.append(u)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            self.send_response(401); self.end_headers(); return
        q = urllib.parse.parse_qs(u.query, keep_blank_values=True)
        body = HISTORY if u.path.startswith("/api/history/period/") and q.get("filter_entity_id") == [ENTITY] else []
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

class Aggregate(unittest.TestCase):
    def rows(self, before=M + 10):
        return {r["minute"]: r for r in pe.aggregate(HISTORY[0], (M - 5) * 60, (M + 10) * 60, before=before)}

    def test_on_and_off_spread_across_minutes(self):
        r = self.rows()
        self.assertEqual((r[M]["present"], r[M]["seen"]), (30, 30))
        self.assertEqual((r[M + 1]["present"], r[M + 1]["seen"]), (30, 60))
        self.assertEqual((r[M + 3]["present"], r[M + 3]["seen"]), (30, 30))

    def test_unknown_and_unavailable_leave_gaps(self):
        r = self.rows()
        self.assertEqual(sorted(r), [M, M + 1, M + 3])

    def test_the_first_state_is_clipped_to_the_window(self):
        sp = pe.spans(HISTORY[0], (M - 5) * 60, (M + 10) * 60)
        self.assertEqual(sp[0][:2], ((M - 5) * 60, M * 60 + 30))

    def test_the_minute_in_progress_is_left_out(self):
        self.assertEqual(sorted(self.rows(before=M + 1)), [M])

    def test_an_open_on_state_runs_to_the_end(self):
        rows = pe.aggregate([{"state": "on", "last_changed": at(M, 0)}], M * 60, (M + 2) * 60, before=M + 5)
        self.assertEqual([(r["minute"], r["present"]) for r in rows], [(M, 60), (M + 1, 60)])

    def test_device_comes_from_the_entity(self):
        self.assertEqual(pe.device_of(ENTITY), "desk_presence")
        self.assertEqual(pe.device_of("binary_sensor.Office_Radar"), "office_radar")

class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), FakeHA)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sd = Path(self.tmp.name)
        self.out = self.sd / "metrics" / "presence" / "desk_presence"

    def tearDown(self):
        self.tmp.cleanup()

    def run_export(self, url=None, token=TOKEN, *extra):
        env = {k: v for k, v in os.environ.items() if k not in ("HOME_ASSISTANT_TOKEN", "HA_URL", "PRESENCE_ENTITY")}
        if token:
            env["HOME_ASSISTANT_TOKEN"] = token
        return subprocess.run([sys.executable, str(ENGINE), "--state", str(self.sd), "--url", url or self.url,
                               "--days", "10000", *extra], capture_output=True, text=True, timeout=30, env=env)

    def test_writes_known_minutes_to_a_day_file(self):
        p = self.run_export()
        self.assertEqual(p.returncode, 0, p.stderr)
        day = self.out / (pe.day_of(M) + ".jsonl")
        lines = [json.loads(l) for l in day.read_text().splitlines()]
        self.assertEqual(lines, [{"minute": M, "present": 30, "seen": 30},
                                 {"minute": M + 1, "present": 30, "seen": 60},
                                 {"minute": M + 3, "present": 30, "seen": 30}])
        self.assertNotIn(TOKEN, p.stdout + p.stderr)

    def test_a_rerun_rewrites_nothing(self):
        self.run_export()
        day = self.out / (pe.day_of(M) + ".jsonl")
        before = day.stat().st_mtime_ns
        time.sleep(0.01)
        p = self.run_export()
        self.assertIn("0 files written", p.stdout)
        self.assertEqual(day.stat().st_mtime_ns, before)

    def test_no_token_exits_0_and_writes_nothing(self):
        p = self.run_export(token=None)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.sd / "metrics" / "presence").exists())

    def test_no_home_assistant_exits_0_and_writes_nothing(self):
        p = self.run_export("http://127.0.0.1:9")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.sd / "metrics" / "presence").exists())

    def test_a_refused_token_exits_1_and_writes_nothing(self):
        p = self.run_export(token="wrong")
        self.assertEqual(p.returncode, 1)
        self.assertIn("401", p.stderr)
        self.assertNotIn("wrong", p.stderr)
        self.assertFalse((self.sd / "metrics" / "presence").exists())

if __name__ == "__main__":
    unittest.main()
