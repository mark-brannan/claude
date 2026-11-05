#!/usr/bin/env python3
# Tests for sign-commits. Run: python3 bin/sign-commits.test.py
#
# What matters: it runs only a signing rebase or amend that branch_brief
# recommends, after a fetch and before a leased push, on the checked-out
# branch alone; every other recommendation is printed and left alone; a
# brief that errors is shown, never swallowed into a bare line; a failed
# fetch or command stops before the push; --dry-run touches nothing. The
# brief and the acting subprocesses are injected, so no key is needed.
import importlib.machinery
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "sign-commits"
spec = importlib.util.spec_from_file_location("sign_commits", TOOL, loader=importlib.machinery.SourceFileLoader("sign_commits", str(TOOL)))
sign_commits = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sign_commits)

REBASE = "git rebase -S --force-rebase 0123abcd   # 2 unsigned commit(s); push it with git push --force-with-lease"
AMEND = "git commit --amend -S --no-edit   # the unsigned commit is the merge itself, at the tip; push it with git push --force-with-lease"
HANDOVER = ("do not rebase and do not re-sign -- an unsigned commit sits at or below one of the 1 merge commit(s), "
            "so the branch cannot be re-signed without losing the merge; hand it over saying so")
KEYLESS = ("cannot sign on this machine (no user.signingkey) -- 2 unsigned commit(s) will block the PR; "
           "hand over saying `git rebase -S --force-rebase 0123abcd` then `git push --force-with-lease` has to run where the key is")
CLEAN = ("nothing on the base -- signed, no conflict; a branch merely behind origin/main is left as is, "
         "the queue updates it (fixup contract, pickup skill section 6)")


def brief_text(rec):
    return f"worktrees: none\nbase: main (open PR)\nahead: 2\nbehind: 0\nconflicts: no\nunsigned: 2\nmerges: 0\nrecommend: {rec}\n"


class Recorder:
    """Stands in for subprocess.run on the acting calls; fails the commands named in `fail`."""

    def __init__(self, fail=()):
        self.calls, self.fail = [], fail

    def __call__(self, argv, **kw):
        self.calls.append(argv[3:] if argv[:2] == ["git", "-C"] else argv)
        rc = 1 if any(argv[3:][:len(f)] == list(f) for f in self.fail) else 0
        return subprocess.CompletedProcess(argv, rc)


class SignCommitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@x"], ["config", "user.name", "t"],
                  ["config", "commit.gpgsign", "false"], ["commit", "-q", "--allow-empty", "-m", "one"],
                  ["checkout", "-q", "-b", "feature"]):
            subprocess.run(["git", "-C", self.repo, *a], check=True, env=env, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def go(self, argv, rec, brief_rc=0, fail=()):
        run, out, err = Recorder(fail), io.StringIO(), io.StringIO()

        def brief(root, br):
            self.assertEqual(os.path.realpath(root), os.path.realpath(self.repo))
            return (brief_rc, f"error: no branch {br} in {root}\n") if brief_rc else (0, brief_text(rec))

        rc = sign_commits.main(argv, cwd=self.repo, brief=brief, run=run, out=out, err=err)
        return rc, run.calls, out.getvalue(), err.getvalue()

    def test_rebase_recommendation_runs_after_a_fetch_and_before_a_leased_push(self):
        rc, calls, out, err = self.go([], REBASE)
        self.assertEqual(rc, 0, err)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"],
                                 ["rebase", "-S", "--force-rebase", "0123abcd"],
                                 ["push", "--force-with-lease", "origin", "feature"]])
        self.assertIn("unsigned: 2\n", out)  # the brief is on screen before the command
        self.assertIn("+ git rebase -S --force-rebase 0123abcd\n", out)  # the note after `   #` is not run

    def test_amend_recommendation_runs_the_same_way(self):
        rc, calls, out, err = self.go([], AMEND)
        self.assertEqual(rc, 0, err)
        self.assertEqual(calls[1], ["commit", "--amend", "-S", "--no-edit"])
        self.assertEqual(calls[2][:2], ["push", "--force-with-lease"])

    def test_a_signed_branch_is_left_alone(self):
        rc, calls, out, err = self.go([], CLEAN)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("nothing to re-sign on feature", out)

    def test_a_handover_recommendation_is_printed_and_not_run(self):
        rc, calls, out, err = self.go([], HANDOVER)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("not a step this runs by itself -- do not rebase", err)

    def test_no_key_on_this_machine_runs_nothing(self):
        rc, calls, out, err = self.go([], KEYLESS)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("cannot sign on this machine", err)

    def test_dry_run_prints_both_commands_and_touches_nothing(self):
        rc, calls, out, err = self.go(["-n"], REBASE)
        self.assertEqual(rc, 0, err)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("+ git rebase -S --force-rebase 0123abcd\n+ git push --force-with-lease origin feature\n", out)
        self.assertIn("dry run, nothing touched", out)

    def test_a_branch_not_checked_out_is_refused_before_any_rewrite(self):
        rc, calls, out, err = self.go(["other"], REBASE)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("check out other first", err)

    def test_a_brief_error_is_shown_whole(self):
        rc, calls, out, err = self.go(["nope"], REBASE, brief_rc=1)
        self.assertEqual(rc, 1)
        self.assertIn("sign-commits: error: no branch nope in", err)

    def test_a_failed_fetch_stops_before_the_brief(self):
        rc, calls, out, err = self.go([], REBASE, fail=[("fetch",)])
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertEqual(out, "")

    def test_a_failed_rebase_is_not_pushed(self):
        rc, calls, out, err = self.go([], REBASE, fail=[("rebase",)])
        self.assertEqual(rc, 1)
        self.assertEqual(calls[-1][0], "rebase")
        self.assertIn("nothing pushed", err)
        self.assertIn("git rebase --abort", err)

    def test_a_failed_push_says_the_branch_is_re_signed_locally(self):
        rc, calls, out, err = self.go([], REBASE, fail=[("push",)])
        self.assertEqual(rc, 1)
        self.assertIn("re-signed locally", err)

    def test_detached_head_needs_a_branch_name(self):
        subprocess.run(["git", "-C", self.repo, "checkout", "-q", "--detach"], check=True, capture_output=True)
        rc, calls, out, err = self.go([], REBASE)
        self.assertEqual(rc, 2)
        self.assertEqual(calls, [])
        self.assertIn("detached", err)

    def test_outside_a_repository(self):
        with tempfile.TemporaryDirectory() as d:
            run, err = Recorder(), io.StringIO()
            rc = sign_commits.main([], cwd=d, brief=None, run=run, out=io.StringIO(), err=err)
        self.assertEqual(rc, 1)
        self.assertEqual(run.calls, [])
        self.assertIn("not inside a git repository", err.getvalue())

    def test_usage(self):
        for argv, rc in ((["-h"], 0), (["--bogus"], 2), (["a", "b"], 2)):
            run, out, err = Recorder(), io.StringIO(), io.StringIO()
            self.assertEqual(sign_commits.main(argv, cwd=self.repo, brief=None, run=run, out=out, err=err), rc, argv)
            self.assertEqual(run.calls, [])

    def origin_ahead(self, br="feature", local_extra=False):
        """origin/<br> one commit past the local branch, as when a bot pushed to the PR."""
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        g = lambda *a: subprocess.run(["git", "-C", self.repo, *a], check=True, env=env,  # noqa: E731
                                      capture_output=True, text=True).stdout.strip()
        tree = g("rev-parse", "HEAD^{tree}")
        g("update-ref", f"refs/remotes/origin/{br}", g("commit-tree", tree, "-p", "HEAD", "-m", "bot"))
        if local_extra:
            g("commit", "-q", "--allow-empty", "-m", "local")

    def test_a_branch_behind_origin_is_fast_forwarded_before_the_brief(self):
        self.origin_ahead()
        rc, calls, out, err = self.go([], REBASE)
        self.assertEqual(rc, 0, err)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"],
                                 ["merge", "--ff-only", "origin/feature"],
                                 ["rebase", "-S", "--force-rebase", "0123abcd"],
                                 ["push", "--force-with-lease", "origin", "feature"]])
        self.assertIn("1 commit(s) behind origin/feature", out)

    def test_dry_run_on_a_branch_behind_origin_touches_nothing(self):
        self.origin_ahead()
        rc, calls, out, err = self.go(["-n"], CLEAN)
        self.assertEqual(rc, 0, err)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("+ git merge --ff-only origin/feature\n", out)
        self.assertNotIn("nothing to re-sign", out)  # a stale branch never briefs as signed

    def test_a_failed_fast_forward_stops_before_the_brief(self):
        self.origin_ahead()
        rc, calls, out, err = self.go([], REBASE, fail=[("merge",)])
        self.assertEqual(rc, 1)
        self.assertEqual(calls[-1][:2], ["merge", "--ff-only"])  # no rebase, no push after it
        self.assertIn("fast-forward to origin/feature failed", err)

    def test_a_branch_diverged_from_origin_is_refused(self):
        self.origin_ahead(local_extra=True)
        rc, calls, out, err = self.go([], REBASE)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("diverged", err)

    def test_a_branch_behind_origin_and_not_checked_out_is_refused(self):
        self.origin_ahead("other")
        subprocess.run(["git", "-C", self.repo, "branch", "other", "main"], check=True, capture_output=True)
        rc, calls, out, err = self.go(["other"], REBASE)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [["fetch", "--quiet", "origin"]])
        self.assertIn("behind origin/other; check it out", err)

    def test_no_local_branch_but_one_on_origin_says_how_to_make_it(self):
        self.origin_ahead("remote-only")
        rc, calls, out, err = self.go(["remote-only"], REBASE)
        self.assertEqual(rc, 1)
        self.assertIn("git switch remote-only", err)

    def test_recommendation_parsing(self):
        self.assertEqual(sign_commits.recommendation(brief_text(REBASE))[0], "git rebase -S --force-rebase 0123abcd")
        self.assertEqual(sign_commits.recommendation(brief_text(CLEAN))[0], CLEAN)
        self.assertEqual(sign_commits.recommendation("ahead: 1\n"), ("", ""))


if __name__ == "__main__":
    unittest.main()
