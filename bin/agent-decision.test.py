#!/usr/bin/env python3
# Tests for agent-decision. Run: python3 bin/agent-decision.test.py
#
# What matters: an entry lands on the `decisions` branch of a bare origin (no
# network), never in the caller's working tree or index; a missing branch is
# created as an orphan seeded from main's log; a push that loses a race is
# re-applied on the new tip; every bullet carries its PR; `list` filters by
# the last read-from and by PR state. A curia copy still gets the same
# stamped entry, never roll.md. `gh` is a stub reading JSON from $GH_STUB.
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

AD = Path(__file__).resolve().parent / "agent-decision"
STAMP = re.compile(r"^### \d{8}t\d{6}z$")
GH = """#!/bin/sh
f="$GH_STUB/$1_$2.json"
[ -f "$f" ] && cat "$f" || exit 1
"""
OLD = "# Agent decisions\n\nmain's old header\n\n### 20261001t000000z\n- seeded call ([#5](https://github.com/o/r/pull/5))\n"


def git(*args, cwd=None, env=None):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


class AgentDecisionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.origin, self.repo, self.state = t / "origin.git", t / "repo", t / "state"
        self.stub, self.bin = t / "stub", t / "bin"
        self.stub.mkdir()
        self.bin.mkdir()
        (self.bin / "gh").write_text(GH)
        (self.bin / "gh").chmod(0o755 | stat.S_IXUSR)
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                    "GIT_COMMITTER_EMAIL": "t@t", "PATH": f"{self.bin}:{os.environ['PATH']}",
                    "GH_STUB": str(self.stub), "CLAUDE_STATE_REPO": str(self.state)}
        for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            self.env.pop(k, None)
        git("init", "-q", "--bare", "-b", "main", str(self.origin), env=self.env)
        self.repo = self.clone("repo")
        (self.repo / "docs").mkdir()
        (self.repo / "docs/agent_decisions.md").write_text(OLD)
        git("add", ".", cwd=self.repo, env=self.env)
        git("commit", "-q", "-m", "init", cwd=self.repo, env=self.env)
        git("push", "-q", "origin", "main", cwd=self.repo, env=self.env)
        (self.state / ".git").mkdir(parents=True)
        self.curia = self.state / "state/global/curia/one-entry-point"
        self.curia.mkdir(parents=True)
        (self.curia / "roll.md").write_text("words\n")

    def tearDown(self):
        self.tmp.cleanup()

    def clone(self, name):
        d = Path(self.tmp.name) / name
        git("clone", "-q", str(self.origin), str(d), env=self.env)
        git("checkout", "-q", "-B", "main", cwd=d, env=self.env)
        return d

    def pr(self, n=7):
        (self.stub / "pr_view.json").write_text(f'{{"number":{n},"url":"https://github.com/o/r/pull/{n}"}}')

    def run_ad(self, *args, repo=None):
        return subprocess.run([sys.executable, str(AD), "--repo", str(repo or self.repo), *args],
                              env=self.env, capture_output=True, text=True)

    def branch_log(self):
        return git("show", "decisions:docs/agent_decisions.md", cwd=self.origin, env=self.env)

    def bullets(self, text):
        return [l for l in text.splitlines() if l.startswith("- ")]

    def test_orphan_created_from_main_with_branch_header_and_tree_untouched(self):
        self.pr()
        before = git("status", "--porcelain", "-b", cwd=self.repo, env=self.env)
        head = git("rev-parse", "HEAD", cwd=self.repo, env=self.env)
        p = self.run_ad("--undo", "revert it", "first call")
        self.assertEqual(p.returncode, 0, p.stderr)
        log = self.branch_log()
        self.assertTrue(log.startswith("# Agent decisions\n"))
        self.assertNotIn("main's old header", log)
        self.assertEqual(self.bullets(log), ["- seeded call ([#5](https://github.com/o/r/pull/5))",
                         "- first call Undo: revert it ([#7](https://github.com/o/r/pull/7))"])
        self.assertEqual(git("rev-list", "--max-parents=0", "decisions", cwd=self.origin, env=self.env).count("\n"), 1)
        self.assertEqual(git("log", "--format=%P", "-1", "decisions", cwd=self.origin, env=self.env).strip().count(" "), 0)
        self.assertEqual(git("status", "--porcelain", "-b", cwd=self.repo, env=self.env), before)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.repo, env=self.env), head)
        self.assertEqual((self.repo / "docs/agent_decisions.md").read_text(), OLD)
        self.assertEqual(git("ls-tree", "-r", "--name-only", "decisions", cwd=self.origin, env=self.env),
                         "docs/agent_decisions.md\n")

    def test_append_and_curia_copy(self):
        self.pr()
        a = self.run_ad("--curia", "one-entry-point", "--link", "[x](u)", "first")
        b = self.run_ad("--curia", "one-entry-point", "--link", "u\n### 20990101t000000z", "second\n  call")
        self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
        log = self.branch_log()
        heads = [l for l in log.splitlines() if l.startswith("### ")]
        self.assertTrue(all(STAMP.match(h) for h in heads), heads)
        self.assertEqual(heads, sorted(heads))
        pr = "([#7](https://github.com/o/r/pull/7))"
        self.assertEqual(self.bullets(log)[1:], [f"- first ([x](u)) {pr}", f"- second call (u ### 20990101t000000z) {pr}"])
        copy = (self.curia / "agent_decisions.md").read_text()
        self.assertEqual(self.bullets(copy), self.bullets(log)[1:])
        self.assertEqual((self.curia / "roll.md").read_text(), "words\n")
        self.assertEqual(copy.count("# Agent decisions"), 1)

    def test_pr_flag_link_and_no_pr_tags(self):
        none = self.run_ad("no pr here")
        self.assertEqual(none.returncode, 0, none.stderr)
        self.assertIn("- no pr here (no PR, branch main)", self.bullets(self.branch_log())[-1])
        self.pr(9)
        self.run_ad("--pr", "9", "by flag")
        url = "https://github.com/o/r/pull/12"
        self.run_ad("--link", url, "by link")
        self.run_ad("--link", "https://github.com/o/r/issues/3", "plus issue")
        got = self.bullets(self.branch_log())[-3:]
        self.assertEqual(got[0], "- by flag ([#9](https://github.com/o/r/pull/9))")
        self.assertEqual(got[1], f"- by link ([#12]({url}))")
        self.assertEqual(got[2], "- plus issue ([#3](https://github.com/o/r/issues/3)) ([#9](https://github.com/o/r/pull/9))")

    def test_pr_flag_beats_link_and_survives_gh_down(self):
        self.pr(9)
        url = "https://github.com/o/r/pull/12"
        self.assertEqual(self.run_ad("--pr", "9", "--link", url, "both").returncode, 0)
        self.assertEqual(self.bullets(self.branch_log())[-1],
                         f"- both ([#12]({url})) ([#9](https://github.com/o/r/pull/9))")
        (self.stub / "pr_view.json").unlink()
        self.run_ad("--pr", "4", "gh down")
        self.assertEqual(self.bullets(self.branch_log())[-1], "- gh down (PR #4)")
        git("config", "remote.origin.url", "git@github.com:o/r.git", cwd=self.repo, env=self.env)
        git("config", "url." + str(self.origin) + ".insteadOf", "git@github.com:o/r.git", cwd=self.repo, env=self.env)
        self.assertEqual(self.run_ad("--pr", "4", "from origin").returncode, 0)
        self.assertEqual(self.bullets(self.branch_log())[-1], "- from origin ([#4](https://github.com/o/r/pull/4))")

    def test_list_looks_up_prs_past_the_list(self):
        self.pr(2000)
        self.run_ad("old call")
        (self.stub / "pr_list.json").write_text("[]")
        (self.stub / "pr_view.json").write_text('{"state":"MERGED"}')
        self.assertRegex(self.run_ad("list").stdout, r"in force\s+old call")

    def test_race_is_reapplied_on_the_new_tip(self):
        self.pr()
        self.run_ad("one")
        other = self.clone("other")
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_text(f"""#!/bin/sh
[ -e "{self.repo}/.git/raced" ] && exit 0
touch "{self.repo}/.git/raced"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
exec {sys.executable} {AD} --repo {other} "rival"
""")
        hook.chmod(0o755)
        p = self.run_ad("mine")
        self.assertEqual(p.returncode, 0, p.stderr)
        got = [b.split(" (")[0] for b in self.bullets(self.branch_log())]
        self.assertEqual(got[-3:], ["- one", "- rival", "- mine"])

    def test_rival_every_time_gives_up_loudly(self):
        self.pr()
        self.run_ad("one")
        other = self.clone("other")
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_text(f"""#!/bin/sh
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
exec {sys.executable} {AD} --repo {other} "rival $(date +%N)"
""")
        hook.chmod(0o755)
        p = self.run_ad("mine")
        self.assertEqual(p.returncode, 1)
        self.assertIn("gave up", p.stderr)
        self.assertNotIn("- mine", self.branch_log())

    def test_refused_push_is_not_retried_and_writes_no_curia_copy(self):
        self.pr()
        self.run_ad("one")
        hook = self.repo / ".git/hooks/pre-push"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        p = self.run_ad("--curia", "one-entry-point", "mine")
        self.assertEqual(p.returncode, 1)
        self.assertFalse((self.curia / "agent_decisions.md").exists())

    def test_list_filters_by_state_and_read_from(self):
        for n, call in [(1, "pending call"), (2, "merged call"), (3, "void call")]:
            self.pr(n)
            self.assertEqual(self.run_ad(call).returncode, 0)
        self.run_ad("--link", "https://github.com/o/r/pull/9", "unknown pr call")
        (self.stub / "pr_list.json").write_text(
            "[" + ",".join(f'{{"url":"https://github.com/o/r/pull/{n}","state":"{st}"}}'
                           for n, st in [(1, "OPEN"), (2, "MERGED"), (3, "CLOSED"), (5, "MERGED")]) + "]")
        out = self.run_ad("list").stdout
        self.assertRegex(out, r"pending\s+pending call")
        self.assertRegex(out, r"in force\s+merged call")
        self.assertRegex(out, r"in force\s+seeded call")
        self.assertRegex(out, r"unknown\s+unknown pr call")
        self.assertNotIn("void call", out)
        self.assertRegex(self.run_ad("list", "--all").stdout, r"void\s+void call")
        stamp = "20261231t235959z"
        self.assertEqual(self.run_ad("read-from", stamp).returncode, 0)
        self.assertEqual(self.run_ad("list").stdout, "")
        self.assertIn("void call", self.run_ad("list", "--all").stdout)
        self.pr(2)
        self.run_ad("after the read")
        self.assertEqual(len(self.run_ad("list").stdout.splitlines()), 1)

    def test_read_from_appends_under_a_heading_and_edits_nothing(self):
        self.pr()
        self.run_ad("one")
        before = self.branch_log()
        stamp = "20261231t235959z"
        self.assertEqual(self.run_ad("read-from", stamp).returncode, 0)
        after = self.branch_log()
        self.assertTrue(after.startswith(before))
        tail = after[len(before):]
        self.assertRegex(tail, rf"^(\n### \d{{8}}t\d{{6}}z\n)?- read-from {stamp}\n$")
        self.assertEqual(self.run_ad("read-from", "soon").returncode, 2)

    def test_dash_call_is_not_empty(self):
        self.pr()
        self.assertEqual(self.run_ad("--", "-").returncode, 0)
        self.assertEqual(self.run_ad("--", "  ").returncode, 2)

    def test_symlinked_curia_log_is_refused(self):
        self.pr()
        (self.curia / "agent_decisions.md").symlink_to(self.curia / "roll.md")
        self.assertEqual(self.run_ad("--curia", "one-entry-point", "a call").returncode, 1)
        self.assertEqual((self.curia / "roll.md").read_text(), "words\n")

    def test_not_a_checkout_is_refused(self):
        p = subprocess.run([sys.executable, str(AD), "--repo", self.tmp.name, "a call"],
                           env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)

    def test_unknown_curia_writes_nothing(self):
        self.pr()
        p = self.run_ad("--curia", "no-such", "a call")
        self.assertEqual(p.returncode, 1)
        self.assertNotEqual(subprocess.run(["git", "rev-parse", "--verify", "-q", "decisions"], cwd=self.origin,
                                           env=self.env, capture_output=True).returncode, 0)

    CLAIMS = ["Solace chose the scale", "Solace ruled the scale", "the user ruled the scale", "scale set per Solace",
              "scale kept on the user's order", "the user asked for the scale", "scale kept as ordered",
              "scale kept, ruled by Solace", "the owner chose the scale", "per the owner, the scale stays",
              "the owner decided the scale", "THE USER DECIDED the scale", "Solace has ordered the scale",
              "scale is the user's choice", "scale kept on the user\u2019s order", "Ruling (Solace): the scale stays",
              "the user explicitly chose the scale", "Solace said to keep the scale"]

    def test_provenance_claims_are_refused_and_write_nothing(self):
        self.pr()
        for call in self.CLAIMS:
            with self.subTest(call=call):
                p = self.run_ad(call)
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("--ruling <url>", p.stderr)
        for extra in (["--undo", "revert; the user asked for it"], ["--link", "per Solace"]):
            with self.subTest(extra=extra):
                self.assertEqual(self.run_ad(*extra, "scale stays").returncode, 2)
        self.assertNotEqual(subprocess.run(["git", "rev-parse", "--verify", "-q", "decisions"], cwd=self.origin,
                                           env=self.env, capture_output=True).returncode, 0)

    def test_ruling_link_is_written_and_lets_a_claim_through(self):
        self.pr()
        url = "https://github.com/o/r/issues/9#issuecomment-1"
        p = self.run_ad("--ruling", url, "--undo", "revert it", "Solace chose the scale")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.bullets(self.branch_log())[-1],
                         f"- Solace chose the scale Undo: revert it (ruling: {url}) ([#7](https://github.com/o/r/pull/7))")
        for bad in ["not a url", "https://example.com/x", "http://x",
                    "https://github.com/o/r/issues/9)[#5](https://github.com/o/r/pull/5"]:
            with self.subTest(ruling=bad):
                self.assertEqual(self.run_ad("--ruling", bad, "x").returncode, 2)

    def test_ordinary_pencil_calls_are_unaffected(self):
        self.pr()
        for call in ["Points on the brief are 1 2 3 5 8 13", "Sorted the user table by name",
                     "Order of the steps follows the ordered list in the doc", "Rows are ordered by time",
                     "The user's session ends with a wrap-up", "The user-facing text says Retry",
                     "Kept the default; the user decides at merge"]:
            with self.subTest(call=call):
                self.assertEqual(self.run_ad(call).returncode, 0)
        self.assertNotIn("ruling:", self.branch_log())


if __name__ == "__main__":
    unittest.main()
