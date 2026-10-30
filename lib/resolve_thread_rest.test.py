#!/usr/bin/env python3
"""Tests for the REST route of gh-resolve-thread, run through the wrapper with
a stub `gh` serving fixtures. No network. Run: python3 lib/resolve_thread_rest.test.py"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "bin" / "gh-resolve-thread"
SIGNED = "\U0001f916 Fixed in abc1234.\n\n\U0001f916 claude-opus-5-5 · high · a0e46df2"
STUB = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["STUB"]
a = sys.argv[1:]
open(d + "/calls", "a").write(json.dumps(a) + "\n")
assert a[0] == "api" and "graphql" not in a, a
if a[1:3] == ["-X", "POST"]:
    path = a[3]
    if path.endswith("/resolve"):
        if os.path.exists(d + "/resolvefail"):
            sys.stderr.write("HTTP 500\n"); sys.exit(1)
        if not os.path.exists(d + "/noeffect"):
            st = json.load(open(d + "/state.json")); st["resolved"] = True; json.dump(st, open(d + "/state.json", "w"))
        print("{}")
    else:
        print(json.dumps({"html_url": "https://github.com/o/r/pull/7#r9"}))
elif a[1] == "user":
    print("agent[bot]")
elif a[1].endswith("/ccr/review_threads"):
    st = json.load(open(d + "/state.json"))
    print(json.dumps([{"resolved": st["resolved"], "comment_ids": [99, 100]}]))
elif a[1].startswith("repos/o/r/pulls/comments/"):
    print(open(d + "/last.json").read())
elif a[1] == "repos/o/r/pulls/7":
    print(json.dumps({"head": {"ref": "feat"}}))
else:
    sys.exit(1)
'''


class RestRoute(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.T = Path(self._t.name)
        (self.T / "bin").mkdir()
        (self.T / "bin" / "gh").write_text(STUB)
        (self.T / "bin" / "gh").chmod(0o755)
        (self.T / "state.json").write_text('{"resolved": false}')
        self.repo = self.T / "repo"
        subprocess.run(["git", "init", "-q", "-b", "feat", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "git@github.com:o/r.git"], check=True)
        self.last("agent[bot]", SIGNED)

    def tearDown(self):
        self._t.cleanup()

    def last(self, login, body):
        (self.T / "last.json").write_text(json.dumps({"user": {"login": login}, "body": body}))

    def run_w(self, *args):
        env = dict(os.environ, STUB=str(self.T), PATH=f"{self.T / 'bin'}:{os.environ['PATH']}")
        p = subprocess.run(["sh", str(WRAPPER), *args], cwd=self.repo, env=env, capture_output=True, text=True)
        calls = [json.loads(x) for x in (self.T / "calls").read_text().splitlines()] if (self.T / "calls").exists() else []
        return p.returncode, p.stdout + p.stderr, calls

    def posts(self, calls):
        return [c for c in calls if c[1:3] == ["-X", "POST"]]

    H = "o/r#7:99"

    def test_bare_resolve_after_a_signed_reply_of_the_callers(self):
        rc, out, calls = self.run_w(self.H)
        self.assertEqual((rc, out.strip()), (0, f"resolved {self.H}"))
        self.assertEqual([c[3] for c in self.posts(calls)], ["repos/o/r/pulls/7/ccr/comments/99/resolve"])

    def test_bare_resolve_refused_without_an_agent_reply(self):
        for login, body in (("rev", "please fix"), ("rev", SIGNED), ("agent[bot]", "\U0001f916 no signature")):
            self.last(login, body)
            rc, out, calls = self.run_w(self.H)
            self.assertEqual(rc, 1)
            self.assertIn("no signed reply of yours", out)
            self.assertEqual(self.posts(calls), [])

    def test_reply_posts_then_resolves(self):
        rc, out, calls = self.run_w(self.H, "--reply", SIGNED)
        self.assertEqual((rc, out.strip()), (0, f"resolved {self.H}"))
        self.assertEqual([c[3] for c in self.posts(calls)],
                         ["repos/o/r/pulls/7/comments/99/replies", "repos/o/r/pulls/7/ccr/comments/99/resolve"])
        self.assertIn("body=" + SIGNED, calls[[c[3] if len(c) > 3 else "" for c in calls].index("repos/o/r/pulls/7/comments/99/replies")])

    def test_reply_only_leaves_it_open(self):
        rc, out, calls = self.run_w(self.H, "--reply-only", SIGNED)
        self.assertEqual((rc, out.strip()), (0, f"replied on {self.H}"))
        self.assertEqual(len(self.posts(calls)), 1)

    def test_unsigned_reply_never_reaches_gh(self):
        rc, out, calls = self.run_w(self.H, "--reply", "Fixed.")
        self.assertEqual((rc, calls), (1, []))

    def test_reply_refused_off_the_pr_branch(self):
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-b", "other"], check=True)
        rc, out, calls = self.run_w(self.H, "--reply", SIGNED)
        self.assertEqual(rc, 1)
        self.assertIn("repos/o/r/pulls/7/comments/99/replies", out)
        self.assertEqual(self.posts(calls), [])

    def test_resolve_failure_after_reply_says_not_to_repost(self):
        (self.T / "resolvefail").write_text("")
        rc, out, _ = self.run_w(self.H, "--reply", SIGNED)
        self.assertEqual(rc, 1)
        self.assertIn(f"do not post it again, finish with: gh-resolve-thread {self.H}", out)

    def test_an_unconfirmed_resolve_is_a_failure(self):
        (self.T / "noeffect").write_text("")
        rc, out, _ = self.run_w(self.H)
        self.assertEqual(rc, 1)
        self.assertIn("not resolved", out)

    def test_unknown_thread(self):
        rc, out, calls = self.run_w("o/r#7:5")
        self.assertEqual(rc, 1)
        self.assertIn("no review thread", out)
        self.assertEqual(self.posts(calls), [])


if __name__ == "__main__":
    unittest.main()
