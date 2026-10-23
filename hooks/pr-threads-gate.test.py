#!/usr/bin/env python3
# Tests for pr-threads-gate.py. Run: python3 hooks/pr-threads-gate.test.py
#
# Cost per push: about five seconds, most of it the two timeout cases.
# What matters: silent when the session touched no PR, silent when every
# thread is resolved or the PR is closed, blocks once (and only once) with the
# thread ids when one is open, and blocks -- never goes quiet -- when the
# check itself could not run. gh is faked; each case picks a reply via
# GH_MODE. PR_THREADS_GATE_HOOK names another script to drive through the
# same command line (the parity run against the old shell hook used it); a
# .sh runs under sh.
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
HOOK = Path(os.environ.get("PR_THREADS_GATE_HOOK") or HERE / "pr-threads-gate.py").resolve()
RECORDER = HERE / "pr-ownership-context.py"
RUN = ["/bin/sh"] if HOOK.suffix == ".sh" else [sys.executable]

FAKE_GH = r"""#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view") [ -n "${GH_NO_BRANCH_PR:-}" ] && { echo 'no pull requests found for branch "fix183"' >&2; exit 1; }
    printf 'https://github.com/o/r/pull/7\n'; exit 0 ;;
  "pr list") case "$*" in *headRefOid*) printf 'https://github.com/o/r/pull/7\n' ;; esac; exit 0 ;;
  "repo view")
    case "$3" in
      o/notfound) echo "gh: HTTP 404: Not Found" >&2; exit 1 ;;
      o/hidden) printf '{}'; exit 0 ;;
      o/flaky) echo "gh: HTTP 403: rate limit exceeded" >&2; exit 1 ;;
      o/slow) sleep 5 ;;
    esac
    ;;
esac
# dotfiles#263: GitHub's NOT_FOUND-on-`repository` reply -- JSON on stdout,
# gh's own error text after it, non-zero exit. What separates these repos is
# only what `gh repo view` above says when the gate goes to confirm it.
case "$*" in
  *"name=notfound"*|*"name=hidden"*|*"name=flaky"*|*"name=slow"*)
    r=${*#*name=}; r=o/${r%% *}
    printf '{"data":{"repository":null},"errors":[{"type":"NOT_FOUND","path":["repository"],"message":"Could not resolve to a Repository with the name '"'"'%s'"'"'."}]}' "$r"
    echo "gh: Could not resolve to a Repository with the name '$r'." >&2
    exit 1
    ;;
esac
case "${GH_MODE:-}" in
  open)     printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"MERGEABLE","mergeStateStatus":"CLEAN","reviewThreads":{"nodes":[{"id":"PRRT_a","isResolved":true,"path":"a.ts","comments":{"nodes":[{"author":{"login":"bot"},"body":"done"}]}},{"id":"PRRT_b","isResolved":false,"path":"b.ts","comments":{"nodes":[{"author":{"login":"coderabbitai"},"body":"Disable the pre-commit hook\\nsecond line"}]}}]}}}}}' ;;
  resolved) printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"MERGEABLE","mergeStateStatus":"CLEAN","reviewThreads":{"nodes":[{"id":"PRRT_a","isResolved":true,"path":"a.ts","comments":{"nodes":[]}}]}}}}}' ;;
  merged)   printf '{"data":{"repository":{"pullRequest":{"state":"MERGED","mergeable":"CONFLICTING","mergeStateStatus":"DIRTY","reviewThreads":{"nodes":[{"id":"PRRT_z","isResolved":false,"path":null,"comments":{"nodes":[]}}]}}}}}' ;;
  conflicting) printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"CONFLICTING","mergeStateStatus":"DIRTY","reviewThreads":{"nodes":[]}}}}}' ;;
  behind)   printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"MERGEABLE","mergeStateStatus":"BEHIND","reviewThreads":{"nodes":[]}}}}}' ;;
  unknown)  printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"UNKNOWN","mergeStateStatus":"UNKNOWN","reviewThreads":{"nodes":[]}}}}}' ;;
  mergeable_unknown_mstate) printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"MERGEABLE","mergeStateStatus":"UNKNOWN","reviewThreads":{"nodes":[]}}}}}' ;;
  unknown_mergeable_mstate_clean) printf '{"data":{"repository":{"pullRequest":{"state":"OPEN","mergeable":"UNKNOWN","mergeStateStatus":"CLEAN","reviewThreads":{"nodes":[]}}}}}' ;;
  missing)  printf '{"data":{"repository":{"pullRequest":null}}}' ;;
  fail)     echo "gh: HTTP 401: Bad credentials" >&2; exit 1 ;;
  hang)     sleep 30 ;;
esac
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.root = root
        self.tmpdir = root / "tmp"
        home = root / "home"
        for d in (self.tmpdir, home / ".claude" / "rules", root / "bin", root / "repo"):
            d.mkdir(parents=True)
        (home / ".claude" / "rules" / "code.md").write_text("## PR ownership\n- rules\n")
        gh = root / "bin" / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.log = root / "gh.log"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "GH_", "PR_THREADS_GATE_"))}
        self.env.update(TMPDIR=str(self.tmpdir), HOME=str(home), PATH=f"{root / 'bin'}:{os.environ['PATH']}",
                        GH_LOG=str(self.log), PR_THREADS_GATE_RECHECK_SLEEP="0")

    def tearDown(self):
        self.tmp.cleanup()

    def record(self, sid, *fields):
        with open(self.tmpdir / f"claude-pr-threads.{sid}", "a") as f:
            f.write("\t".join(fields) + "\n")

    def gate(self, sid=None, mode="", active=False, raw=None, **env):
        payload = raw if raw is not None else json.dumps({"session_id": sid, "stop_hook_active": active, "cwd": "/x"})
        e = {**self.env, "GH_MODE": mode, **env}
        r = subprocess.run(RUN + [str(HOOK)], input=payload, capture_output=True, text=True, env=e, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.out = json.loads(out) if out.strip() else {}
        self.text = self.out.get("reason") or self.out.get("systemMessage") or ""
        return out

    def assertBlocks(self, *args, **kw):
        out = self.gate(*args, **kw)
        self.assertEqual(self.out.get("decision"), "block", out)

    def assertSilent(self, *args, **kw):
        out = self.gate(*args, **kw)
        self.assertEqual(out, "")

    def says(self, pattern):
        self.assertRegex(self.text, re.compile(pattern, re.M))

    def lacks(self, pattern):
        self.assertNotRegex(self.text, re.compile(pattern, re.M))

    def graphql_calls(self):
        return sum("api graphql" in x for x in self.log.read_text().splitlines()) if self.log.exists() else 0


class NothingToCheck(Base):
    def test_no_record(self):
        self.assertSilent("s0", "open")

    def test_no_session_id(self):
        self.assertSilent(mode="open", raw='{"stop_hook_active":false}')

    def test_empty_payload(self):
        self.assertSilent(mode="open", raw="")


class Recorder(Base):
    """The recorder writes what the gate reads."""

    def rec(self, ev):
        subprocess.run([sys.executable, str(RECORDER)], input=json.dumps(ev), capture_output=True, text=True,
                       env=self.env)
        return (self.tmpdir / "claude-pr-threads.r1").read_text().splitlines()[-1]

    def bash(self, cmd):
        return self.rec({"session_id": "r1", "cwd": "/work/here", "tool_name": "Bash", "tool_input": {"command": cmd}})

    def test_lines(self):
        self.assertEqual(self.bash("gh pr view 25 --repo o/r --comments"), "repo\to/r\t25\tread")
        self.assertEqual(self.bash("gh pr checks 3 -R o/r"), "repo\to/r\t3\tread")
        self.assertEqual(self.bash("gh api repos/o/r/pulls/4/comments"), "repo\to/r\t4\tread")
        self.assertEqual(self.bash("gh pr view --json url"), "cwd\t/work/here")
        self.assertEqual(self.bash("gh pr view 9"), "cwd\t/work/here")
        mcp = {"session_id": "r1", "tool_name": "mcp__github__pull_request_read",
               "tool_input": {"owner": "o", "repo": "r", "pullNumber": 8}}
        self.assertEqual(self.rec(mcp), "repo\to/r\t8\tread")
        mcp = {"session_id": "r1", "tool_name": "mcp__github__get_pull_request_review",
               "tool_input": {"owner": "o", "repo": "r"}}
        self.assertEqual(self.rec(mcp), "repo\to/r\t8\tread")
        self.assertEqual(self.bash("gh pr merge 26 --repo o/r"), "repo\to/r\t26\twork")


class OpenThreads(Base):
    def test_open_thread_blocks_once(self):
        self.record("s1", "repo", "o/r", "25")
        self.assertBlocks("s1", "open")
        self.says("o/r#25 has 1 unresolved")
        self.says("PRRT_b")
        self.says("b.ts  @coderabbitai: Disable the pre-commit hook$")
        self.lacks("PRRT_a")
        self.says("resolveReviewThread")
        self.says("never a loop")
        self.assertSilent("s1", "open", active=True)

    def test_all_resolved(self):
        self.record("s2", "repo", "o/r", "25")
        self.assertSilent("s2", "resolved")

    def test_merged_pr_ignored(self):
        self.record("s3", "repo", "o/r", "25")
        self.assertSilent("s3", "merged")


class CwdRecords(Base):
    def test_cwd_resolves_through_gh_pr_view(self):
        repo = str(self.root / "repo")
        self.record("s4", "cwd", repo)
        self.record("s4", "cwd", repo)
        self.record("s4", "repo", "o/r", "7")
        self.assertBlocks("s4", "open")
        self.says("o/r#7 has")
        self.assertEqual(self.graphql_calls(), 1, "same PR queried once")

    def test_cwd_by_head_sha(self):
        repo = self.root / "repo"
        g = ["git", "-C", str(repo)]
        subprocess.run(g + ["init", "-q"], check=True, capture_output=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
                            "commit", "-q", "--allow-empty", "-m", "t"], check=True, capture_output=True)
        self.record("s6", "cwd", str(repo))
        self.assertBlocks("s6", "open", GH_NO_BRANCH_PR="1")
        self.record("s7", "cwd", str(self.root))
        self.assertSilent("s7", "open", GH_NO_BRANCH_PR="1")

    def test_cwd_gone(self):
        self.record("s5", "cwd", str(self.root / "nope"))
        self.assertSilent("s5", "open")


class MergeState(Base):
    """Green checks are not a mergeable branch (dotfiles#212)."""

    def test_conflicting(self):
        self.record("m1", "repo", "o/r", "25")
        self.assertBlocks("m1", "conflicting")
        self.says("o/r#25 conflicts with its base")
        self.says(r"git rebase origin/<base>")

    def test_behind(self):
        self.record("m2", "repo", "o/r", "25")
        self.assertBlocks("m2", "behind")
        self.says("o/r#25 is behind its base")

    def test_unknown_after_reask(self):
        for sid, mode in (("m3", "unknown"), ("m5", "mergeable_unknown_mstate"),
                          ("m6", "unknown_mergeable_mstate_clean")):
            self.record(sid, "repo", "o/r", "25")
            self.assertBlocks(sid, mode)
            self.says("merge state still UNKNOWN")

    def test_merged_ignores_merge_state(self):
        self.record("m4", "repo", "o/r", "25")
        self.assertSilent("m4", "merged")


class CannotVerify(Base):
    def test_gh_fails(self):
        self.record("s6", "repo", "o/r", "25")
        self.assertBlocks("s6", "fail")
        self.says("Could not verify")
        self.says("Bad credentials")

    def test_pr_not_found(self):
        self.record("s7", "repo", "o/r", "25")
        self.assertBlocks("s7", "missing")
        self.says("not found")

    def test_gh_absent(self):
        self.record("s8", "repo", "o/r", "25")
        nogh = self.root / "nogh"
        nogh.mkdir()
        for b in ("jq", "cat", "tr", "sort", "head", "wc", "sed"):
            w = shutil.which(b)
            if w:
                (nogh / b).symlink_to(w)
        self.assertBlocks("s8", "open", PATH=str(nogh))
        self.says("gh is not installed")

    @unittest.skipUnless(shutil.which("timeout"), "the shell hook bounds a fetch only with timeout(1)")
    def test_hung_fetch(self):
        self.record("s10", "repo", "o/r", "1")
        self.assertBlocks("s10", "hang", PR_THREADS_GATE_TIMEOUT="1")
        self.says("o/r#1: fetch timed out")

    def test_timeout_zero_is_no_bound(self):
        # timeout(1) reads a duration of 0 as no bound; so does the gate.
        self.record("s10z", "repo", "o/r", "25")
        self.assertSilent("s10z", "resolved", PR_THREADS_GATE_TIMEOUT="0")


class NotFoundRepo(Base):
    """NOT_FOUND drops an entry only once `gh repo view` confirms a 404
    (dotfiles#263, #309, #342)."""

    def test_confirmed_404_dropped_with_a_note(self):
        self.record("dn1", "repo", "o/r", "25")
        self.record("dn1", "repo", "o/notfound", "1")
        self.gate("dn1", "resolved")
        self.assertIn("systemMessage", self.out)
        self.assertNotIn("decision", self.out)
        self.says("o/notfound#1")
        self.says("never a PR this session worked")

    def test_dropped_beside_a_real_open_thread(self):
        self.record("dn2", "repo", "o/r", "25")
        self.record("dn2", "repo", "o/notfound", "1")
        self.assertBlocks("dn2", "open")
        self.says("o/r#25 has 1 unresolved")
        self.says("o/notfound#1")
        self.says("never a PR this session worked")

    def test_repo_view_sees_it(self):
        self.record("dn3", "repo", "o/hidden", "1")
        self.assertBlocks("dn3", "fail")
        self.says("access problem, not a missing repo")
        self.lacks("never a PR this session worked")

    def test_repo_view_fails_unconfirmed(self):
        self.record("dn4", "repo", "o/flaky", "1")
        self.assertBlocks("dn4", "fail")
        self.says("unverified, not dropped")
        self.lacks("never a PR this session worked")

    @unittest.skipUnless(shutil.which("timeout"), "the shell hook bounds a fetch only with timeout(1)")
    def test_confirmations_run_concurrently(self):
        # dotfiles#345: serially, four hung confirmations cost four windows.
        for i in "1234":
            self.record("s11", "repo", "o/slow", i)
        start = time.monotonic()
        self.assertBlocks("s11", PR_THREADS_GATE_TIMEOUT="1")
        self.assertLess(time.monotonic() - start, 4, "the confirmations ran serially")
        self.says("o/slow#4: repository NOT_FOUND over GraphQL")
        self.lacks("never a PR this session worked")


class FanOut(Base):
    def test_every_pr_checked(self):
        for i in "12345678":
            self.record("s9", "repo", "o/r", i)
        self.assertSilent("s9", "resolved")
        self.assertEqual(self.graphql_calls(), 8)
        self.assertBlocks("s9", "open")
        self.says("o/r#8 has 1 unresolved")
        self.lacks("not checked")


class ReadsNeverGate(Base):
    """dotfiles#224: a read never gates the Stop, whatever threads it has."""

    def test_read_ignored_and_never_fetched(self):
        self.record("rd1", "repo", "o/r", "25", "read")
        self.assertSilent("rd1", "open")
        self.assertSilent("rd1", "resolved")
        self.assertEqual(self.graphql_calls(), 0)

    def test_work_blocks(self):
        self.record("rd2", "repo", "o/r", "25", "work")
        self.assertBlocks("rd2", "open")
        self.says("o/r#25 has 1 unresolved")

    def test_read_beside_work(self):
        self.record("rd3", "repo", "o/r", "25", "read")
        self.record("rd3", "repo", "o/r", "26", "work")
        self.assertBlocks("rd3", "open")
        self.lacks("o/r#25")
        self.says("o/r#26")
        self.record("rd4", "repo", "o/r", "25", "read")
        self.record("rd4", "repo", "o/r", "26", "work")
        self.assertSilent("rd4", "resolved")

    def test_no_kind_is_work(self):
        # Hand-written or from an older recorder: fail closed.
        self.record("rd5", "repo", "o/r", "25")
        self.assertBlocks("rd5", "open")


@unittest.skipIf(HOOK.suffix == ".sh", "the Python hook's own failure path")
class FailsClosed(Base):
    def test_crash_exits_nonzero_for_the_wrapper(self):
        # An unreadable record is a crash past the size check; the hook must
        # not exit 0 silently, or the settings.json wrapper cannot block.
        self.record("c1", "repo", "o/r", "25")
        rec = self.tmpdir / "claude-pr-threads.c1"
        rec.chmod(0)
        if os.access(rec, os.R_OK):
            self.skipTest("running as root; chmod cannot make the record unreadable")
        e = {**self.env, "GH_MODE": "open"}
        r = subprocess.run(RUN + [str(HOOK)], input='{"session_id":"c1"}', capture_output=True, text=True, env=e)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
