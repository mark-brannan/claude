#!/usr/bin/env python3
# Tests for input-export. Run: python3 bin/input-export.test.py
#
# Offline and synthetic: a fake ActivityWatch server on a loopback port and a
# throwaway state directory. No real events, apps or titles.
#
# What matters: counts land on their UTC minute; spans spread across the
# minutes they touch; a title picks a category and is never written; the
# minute in progress is left out; a rerun writes nothing new; a host with no
# ActivityWatch exits 0 having written nothing.
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
ENGINE = Path(__file__).resolve().parent / "input-export"
spec = importlib.util.spec_from_loader("input_export", importlib.machinery.SourceFileLoader("input_export", str(ENGINE)))
ie = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ie)

M = 29875363  # 2026-10-20T18:43Z, a fixed minute well in the past
def at(minute, sec=0):
    return ie.iso(minute * 60 + sec)

SECRET = "acme/private-roadmap - Pull request · GitHub"
BUCKETS = {
    "aw-watcher-input_FixtureBox": {"hostname": "FixtureBox"},
    "aw-watcher-afk_FixtureBox": {"hostname": "FixtureBox"},
    "aw-watcher-window_FixtureBox": {"hostname": "FixtureBox"},
}
EVENTS = {
    "aw-watcher-input_FixtureBox": [
        {"timestamp": at(M, 0), "duration": 5, "data": {"presses": 30, "clicks": 1, "deltaX": 10, "deltaY": -5, "scrollX": 0, "scrollY": -3}},
        {"timestamp": at(M, 55), "duration": 5, "data": {"presses": 12, "clicks": 0, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}},
        {"timestamp": at(M + 1, 0), "duration": 5, "data": {"presses": 2, "clicks": 3, "deltaX": 0, "deltaY": 0, "scrollX": 0, "scrollY": 0}},
    ],
    "aw-watcher-afk_FixtureBox": [
        {"timestamp": at(M, 0), "duration": 90, "data": {"status": "not-afk"}},
        {"timestamp": at(M + 1, 30), "duration": 30, "data": {"status": "afk"}},
    ],
    "aw-watcher-window_FixtureBox": [
        {"timestamp": at(M, 0), "duration": 40, "data": {"app": "chrome.exe", "title": SECRET}},
        {"timestamp": at(M, 40), "duration": 50, "data": {"app": "claude.exe", "title": "Claude"}},
    ],
}

class FakeAW(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/0/buckets/":
            body = BUCKETS
        else:
            body = EVENTS.get(urllib.parse.unquote(u.path.split("/")[4]), [])
        data = json.dumps(body).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

class Aggregate(unittest.TestCase):
    def rows(self):
        return {r["minute"]: r for r in ie.aggregate(EVENTS["aw-watcher-input_FixtureBox"],
                EVENTS["aw-watcher-afk_FixtureBox"], EVENTS["aw-watcher-window_FixtureBox"], before=M + 10)}

    def test_counts_land_on_their_minute(self):
        r = self.rows()
        self.assertEqual((r[M]["keys"], r[M]["clicks"], r[M]["scroll"], r[M]["move"]), (42, 1, 3, 15))
        self.assertEqual((r[M + 1]["keys"], r[M + 1]["clicks"]), (2, 3))

    def test_spans_spread_across_minutes(self):
        r = self.rows()
        self.assertEqual((r[M]["seen"], r[M]["afk"]), (60, 0))
        self.assertEqual((r[M + 1]["seen"], r[M + 1]["afk"]), (60, 30))
        self.assertEqual(r[M]["win"], {"claude": 20, "github": 40})
        self.assertEqual(r[M + 1]["win"], {"claude": 30})

    def test_the_minute_in_progress_is_left_out(self):
        rows = ie.aggregate(EVENTS["aw-watcher-input_FixtureBox"], [], [], before=M + 1)
        self.assertEqual([r["minute"] for r in rows], [M])

    def test_categories_match_whole_words(self):
        self.assertEqual(ie.category("SearchHost.exe", ""), "system")  # "arc" is not a browser here
        self.assertEqual(ie.category("Google Chrome", "news"), "browser")
        self.assertEqual(ie.category("iTerm2", ""), "terminal")
        self.assertEqual(ie.category("Mystery.exe", ""), "other")

class Export(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), FakeAW)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sd = Path(self.tmp.name)
        self.out = self.sd / "metrics" / "input" / "fixturebox"

    def tearDown(self):
        self.tmp.cleanup()

    def run_export(self, url=None, *extra):
        return subprocess.run([sys.executable, str(ENGINE), "--state", str(self.sd), "--url", url or self.url,
                               "--days", "10000", *extra], capture_output=True, text=True, timeout=30)

    def test_writes_a_day_file_and_host_json_without_titles(self):
        p = self.run_export()
        self.assertEqual(p.returncode, 0, p.stderr)
        day = self.out / (ie.day_of(M) + ".jsonl")
        lines = [json.loads(l) for l in day.read_text().splitlines()]
        self.assertEqual([l["minute"] for l in lines], [M, M + 1])
        self.assertNotIn("private-roadmap", day.read_text())
        self.assertEqual(json.loads((self.out / "host.json").read_text()),
                         {"host": "fixturebox", "home": os.path.expanduser("~")})

    def test_a_rerun_rewrites_nothing(self):
        self.run_export()
        day = self.out / (ie.day_of(M) + ".jsonl")
        before = day.stat().st_mtime_ns
        time.sleep(0.01)
        p = self.run_export()
        self.assertIn("0 files written", p.stdout)
        self.assertEqual(day.stat().st_mtime_ns, before)
        self.assertEqual([f for f in os.listdir(self.out) if f.startswith(".")], [])

    def test_no_activitywatch_exits_0_and_writes_nothing(self):
        p = self.run_export("http://127.0.0.1:9")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertFalse((self.sd / "metrics" / "input").exists())

if __name__ == "__main__":
    unittest.main()
