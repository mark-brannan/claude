#!/usr/bin/env python3
# Tests for post-comment. Run: python3 bin/post-comment.test.py
#
# What matters: a body file is taken only from a scratchpad (or $RUNNER_TEMP in
# CI), resolved through symlinks, never from /proc, /dev, a .git or anywhere
# else, and never over GitHub's 65536-character limit; the languette guards see
# the equivalent `gh <kind> comment --body-file` call on a copy of the text,
# and a deny, an ask, a crash or no install posts nothing; what gh is sent is
# exactly the text screened; --marker edits the newest own comment holding it,
# or posts a new one. The tool runs in a subprocess with its home, /tmp and gh
# pointed into a temp dir; a fake languette denies on a word. One test runs
# the real installed languette, when there is one, on a blocked term.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "post-comment"

# Loads the tool, points its home, /tmp and gh at argv[1..3], runs main on the rest.
RUN = """
import importlib.machinery, sys
m = importlib.machinery.SourceFileLoader("post_comment", sys.argv[4]).load_module()
m.home = lambda: sys.argv[1]
m.TMP = sys.argv[2]
m.GH = sys.argv[3]
sys.exit(m.main(sys.argv[5:]))
"""

# A fake gh: logs argv and stdin as one JSON line, answers the lookups --marker makes.
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
stdin = sys.stdin.read() if "-" in a else ""
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps({"argv": a, "stdin": stdin}) + "\\n")
if a[:2] == ["api", "graphql"]:
    print("me")
elif a[:2] == ["api", "--paginate"]:
    for c in json.loads(os.environ.get("FAKE_GH_COMMENTS", "[]")):
        print(json.dumps(c))
elif a[:2] == ["repo", "view"]:
    print("o/r")
elif a[:3] == ["api", "-X", "PATCH"]:
    print("https://github.com/o/r/issues/1#issuecomment-" + a[3].rsplit("/", 1)[1])
else:
    print("https://github.com/o/r/pull/1#issuecomment-1")
"""

# A fake languette run.py: logs the payload and the option env, denies a body holding BLOCKME.
FAKE_RUN = """import json, os, shlex, sys
p = json.load(sys.stdin)
words = shlex.split(p["tool_input"]["command"])
body = open(words[words.index("--body-file") + 1]).read()
with open(os.environ["FAKE_RUN_LOG"], "a") as f:
    f.write(json.dumps({"payload": p, "body": body,
                        "opts": {k: v for k, v in os.environ.items() if k.startswith("CLAUDE_PLUGIN_")}}) + "\\n")
mode = os.environ.get("FAKE_RUN_MODE", "")
if mode == "crash":
    sys.exit(3)
if mode == "ask":
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "ask", "permissionDecisionReason": "asked"}}))
elif mode == "rewrite":
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow", "updatedInput": {"command": "x"}}}))
elif "BLOCKME" in body:
    print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny",
                                             "permissionDecisionReason": "guard-private-terms: blocked BLOCKME"}}))
"""


def real_languette():
    """The real user-scope languette install path, when it knows the blocked_terms_file
    option (CI pins an older languette that does not), or None."""
    try:
        with open(os.path.expanduser("~/.claude/plugins/installed_plugins.json")) as f:
            for i in json.load(f)["plugins"]["languette@languette"]:
                pkg = Path(i["installPath"]) / "languette"
                if i.get("scope") == "user" and (pkg / "run.py").is_file() and any(
                        "blocked_terms_file" in py.read_text(errors="replace") for py in pkg.rglob("*.py")):
                    return i["installPath"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


class PostComment(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.systmp = self.tmp / "systmp"
        self.scratch = self.home / ".local/state/claude-tmpdir" / ("claude-%d" % os.getuid()) / "proj/sess/scratchpad"
        self.scratch.mkdir(parents=True)
        self.systmp.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()
        self.gh = self.tmp / "gh"
        self.gh.write_text(FAKE_GH)
        self.gh.chmod(0o755)
        self.plugin = self.tmp / "plugin"
        (self.plugin / "languette").mkdir(parents=True)
        (self.plugin / "languette/run.py").write_text(FAKE_RUN)
        self.install(self.plugin)
        self.settings({"blocked_terms_file": "~/b.tsv", "guard_signed_comments": True})
        self.env = dict(os.environ, FAKE_GH_LOG=str(self.tmp / "gh.log"), FAKE_RUN_LOG=str(self.tmp / "run.log"))
        for k in ("GITHUB_ACTIONS", "RUNNER_TEMP"):
            self.env.pop(k, None)

    def install(self, root):
        p = self.home / ".claude/plugins"
        p.mkdir(parents=True, exist_ok=True)
        (p / "installed_plugins.json").write_text(json.dumps(
            {"plugins": {"languette@languette": [{"scope": "user", "installPath": str(root)}]}}))

    def settings(self, options):
        (self.home / ".claude/settings.json").write_text(json.dumps(
            {"pluginConfigs": {"languette@languette": {"options": options}}}))

    def body(self, text, base=None, name="c.md"):
        p = (base or self.scratch) / name
        p.write_text(text)
        return p

    def run_tool(self, *args, **env):
        """Run the tool; the gh and guard logs then hold this run alone."""
        for name in ("gh.log", "run.log"):
            (self.tmp / name).unlink(missing_ok=True)
        return subprocess.run([sys.executable, "-c", RUN, str(self.home), str(self.systmp), str(self.gh), str(TOOL),
                               *map(str, args)], cwd=self.tmp, text=True, capture_output=True,
                              env=dict(self.env, **env))

    def log(self, name):
        p = self.tmp / name
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def assertRefused(self, r, *needles):
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("nothing posted", r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)
        self.assertEqual(self.log("gh.log"), [])

    def test_posts_screened_text_on_stdin(self):
        p = self.body("hello\nworld\n")
        r = self.run_tool("pr", "7", "--repo", "o/r", "--body-file", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("issuecomment-1", r.stdout)
        [call] = self.log("gh.log")
        self.assertEqual(call["argv"], ["pr", "comment", "7", "--body-file", "-", "--repo", "o/r"])
        self.assertEqual(call["stdin"], "hello\nworld\n")
        [seen] = self.log("run.log")
        self.assertEqual(seen["body"], "hello\nworld\n")
        cmd = seen["payload"]["tool_input"]["command"]
        self.assertTrue(cmd.startswith("%s pr comment 7 --repo o/r --body-file " % self.gh), cmd)
        self.assertNotIn(str(p) + " ", cmd + " ")             # the guards read a copy, never the file itself
        self.assertEqual(seen["payload"]["hook_event_name"], "PreToolUse")
        self.assertEqual(seen["opts"]["CLAUDE_PLUGIN_OPTION_BLOCKED_TERMS_FILE"], "~/b.tsv")
        self.assertEqual(seen["opts"]["CLAUDE_PLUGIN_OPTION_GUARD_SIGNED_COMMENTS"], "true")
        self.assertEqual(seen["opts"]["CLAUDE_PLUGIN_ROOT"], str(self.plugin))
        self.assertEqual(sorted(os.listdir(self.scratch)), ["c.md"])  # the copy is gone

    def test_issue_without_repo(self):
        r = self.run_tool("issue", "3", "--body-file", self.body("x"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log("gh.log")[0]["argv"], ["issue", "comment", "3", "--body-file", "-"])

    def test_guard_deny_posts_nothing(self):
        r = self.run_tool("pr", "7", "--body-file", self.body("say BLOCKME now"))
        self.assertRefused(r, "guard-private-terms: blocked BLOCKME")

    def test_guard_ask_crash_and_rewrite_post_nothing(self):
        for mode, needle in (("ask", "asked"), ("crash", "exit 3"), ("rewrite", "rewrite")):
            with self.subTest(mode):
                self.assertRefused(self.run_tool("pr", "7", "--body-file", self.body("x"), FAKE_RUN_MODE=mode), needle)

    def test_no_languette_posts_nothing(self):
        self.install(self.tmp / "nowhere")
        self.assertRefused(self.run_tool("pr", "7", "--body-file", self.body("x")), "not installed")

    def test_paths_outside_the_scratchpads_are_refused(self):
        git = self.scratch / ".git"
        git.mkdir()
        cases = [(self.body("x", self.outside), "outside the scratchpads"),
                 (self.body("x", git), "in a .git"),
                 ("/proc/self/environ", "/proc"),
                 ("/dev/null", "/proc, /dev or /sys"),
                 (self.scratch / "missing.md", "cannot be read")]
        link = self.scratch / "link.md"
        link.symlink_to(self.body("secret", self.outside, "s.md"))
        cases.append((link, "outside the scratchpads"))
        for path, needle in cases:
            with self.subTest(str(path)):
                self.assertRefused(self.run_tool("pr", "7", "--body-file", path), needle)
        self.assertEqual(self.log("run.log"), [])

    def test_tmp_scratchpad_and_runner_temp(self):
        t = self.systmp / ("claude-%d" % os.getuid())
        t.mkdir()
        self.assertEqual(self.run_tool("pr", "1", "--body-file", self.body("x", t)).returncode, 0)
        rt = self.tmp / "runner"
        rt.mkdir()
        p = self.body("x", rt)
        self.assertRefused(self.run_tool("pr", "1", "--body-file", p, RUNNER_TEMP=str(rt)), "outside")
        r = self.run_tool("pr", "1", "--body-file", p, RUNNER_TEMP=str(rt), GITHUB_ACTIONS="true")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_size_encoding_and_kind(self):
        self.assertRefused(self.run_tool("pr", "1", "--body-file", self.body("x" * 65537)), "65536")
        self.assertEqual(self.run_tool("pr", "1", "--body-file", self.body("é" * 65536)).returncode, 0)
        p = self.scratch / "bin.md"
        p.write_bytes(b"\xff\xfe")
        self.assertRefused(self.run_tool("pr", "1", "--body-file", p), "not UTF-8")
        self.assertRefused(self.run_tool("pr", "1", "--body-file", self.body(" \n")), "empty")
        os.mkfifo(self.scratch / "fifo")
        self.assertRefused(self.run_tool("pr", "1", "--body-file", self.scratch / "fifo"), "not a regular file")

    def test_bad_arguments(self):
        p = self.body("x")
        for args in (("pr", "abc", "--body-file", p), ("pr", "1", "--repo", "o/r;rm", "--body-file", p),
                     ("gist", "1", "--body-file", p), ("pr", "1")):
            with self.subTest(args):
                self.assertEqual(self.run_tool(*args).returncode, 2)

    def test_marker_edits_newest_own_comment(self):
        comments = [{"id": 10, "login": "me", "body": "<!-- m --> old"},
                    {"id": 11, "login": "other", "body": "<!-- m --> theirs"},
                    {"id": 12, "login": "me[bot]", "body": "<!-- m --> newer"},
                    {"id": 13, "login": "me", "body": "unmarked"}]
        r = self.run_tool("pr", "1", "--marker", "<!-- m -->", "--body-file", self.body("<!-- m --> new"),
                          FAKE_GH_COMMENTS=json.dumps(comments))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("issuecomment-12", r.stdout)
        patch = self.log("gh.log")[-1]
        self.assertEqual(patch["argv"][:4], ["api", "-X", "PATCH", "repos/o/r/issues/comments/12"])
        self.assertEqual(json.loads(patch["stdin"]), {"body": "<!-- m --> new"})
        self.assertIn("--edit-last", self.log("run.log")[0]["payload"]["tool_input"]["command"])

    def test_marker_none_found_posts_new(self):
        r = self.run_tool("pr", "1", "--repo", "o/r", "--marker", "MK", "--body-file", self.body("MK body"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log("gh.log")[-1]["argv"][:2], ["pr", "comment"])

    def test_marker_must_be_in_body(self):
        self.assertRefused(self.run_tool("pr", "1", "--marker", "MK", "--body-file", self.body("no mark")), "--marker")

    @unittest.skipUnless(real_languette(), "no languette installed that knows blocked_terms_file")
    def test_real_languette_blocks_a_blocked_term(self):
        self.install(real_languette())
        terms = self.tmp / "blocked.tsv"
        terms.write_text("find\tmessage\tcomment\nzebraquux\tno zebras here\t\n")
        self.settings({"blocked_terms_file": str(terms), "redacted_terms_file": str(self.tmp / "none.tsv")})
        (self.tmp / "none.tsv").write_text("find\tput\tcomment\n")
        r = self.run_tool("pr", "1", "--repo", "mark-brannan/claude", "--body-file", self.body("a zebraquux"))
        self.assertRefused(r, "guard-private-terms", "zebraquux")
        r = self.run_tool("pr", "1", "--repo", "mark-brannan/claude", "--body-file", self.body("fine text"))
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
