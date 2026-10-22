#!/usr/bin/env python3
# Tests for the gh shim. Run: python3 -I bin/gh.test.py
#
# What matters: inside a Claude Code session with the agent App's secret,
# gh runs as the App; asking who the user is and merging stay the user's;
# outside a session, with GH_TOKEN set, with AGENT_BOT_OFF=1 or with no
# secret, it is the real gh, found past any Claude layer's bin/. A failed
# mint fails the call; it never falls back to the user.
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIM = Path(__file__).resolve().parent / "gh"


def script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


class Shim(unittest.TestCase):
    def setUp(self):
        self.T = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.T)
        layer, other, sysbin = (self.T / n for n in ("layer", "worktree", "sys"))
        for d in (layer, other, sysbin):
            d.mkdir()
        shutil.copy(SHIM, layer / "gh")
        shutil.copy(SHIM, other / "gh")
        script(layer / "gh-agent", '[ -f "$MINT_FAILS" ] && { echo "gh-agent: token mint failed" >&2; exit 1; }\n'
                                   'echo "agent $*"\n')
        script(other / "gh-agent", 'echo "wrong layer $*"\n')
        script(sysbin / "gh", 'echo "user $*"\n')
        self.secret = self.T / "agent-bot.env"
        self.secret.write_text("")
        self.env = {"PATH": f"{layer}:{other}:{sysbin}:/usr/bin:/bin", "HOME": str(self.T),
                    "AGENT_BOT_SECRETS": str(self.secret), "CLAUDECODE": "1",
                    "MINT_FAILS": str(self.T / "mint-fails")}

    def gh(self, *args, **env):
        p = subprocess.run([str(self.T / "layer" / "gh"), *args], env={**self.env, **env},
                           capture_output=True, text=True)
        return p.returncode, p.stdout.strip(), p.stderr

    def test_a_session_with_the_secret_runs_as_the_app(self):
        self.assertEqual(self.gh("pr", "comment", "1", "--body", "x")[1], "agent pr comment 1 --body x")

    def test_who_the_user_is_and_merging_stay_the_users(self):
        self.assertEqual(self.gh("api", "user", "--jq", ".login")[1], "user api user --jq .login")
        self.assertEqual(self.gh("api", "/user")[1], "user api /user")
        self.assertEqual(self.gh("pr", "merge", "3")[1], "user pr merge 3")
        self.assertEqual(self.gh("api", "users/x")[1], "agent api users/x")

    def test_the_real_gh_otherwise(self):
        self.assertEqual(self.gh("pr", "list", CLAUDECODE="")[1], "user pr list", "outside a session")
        self.assertEqual(self.gh("pr", "list", GH_TOKEN="t")[1], "user pr list", "GH_TOKEN already set")
        self.assertEqual(self.gh("pr", "list", AGENT_BOT_OFF="1")[1], "user pr list", "the escape")
        self.secret.unlink()
        self.assertEqual(self.gh("pr", "list")[1], "user pr list", "no App secret")

    def test_a_link_to_the_shim_is_not_the_real_gh(self):
        link = self.T / "link"
        link.mkdir()
        (link / "gh").symlink_to(self.T / "layer" / "gh")
        p = subprocess.run([str(link / "gh"), "pr", "list"], env={**self.env, "CLAUDECODE": "",
                           "PATH": f"{link}:{self.T / 'sys'}:/usr/bin:/bin"}, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.stdout.strip(), "user pr list")

    def test_bare_gh_is_the_real_gh(self):
        self.assertEqual(self.gh()[1], "user")

    def test_a_failed_mint_fails_the_call(self):
        (self.T / "mint-fails").write_text("")
        rc, out, err = self.gh("pr", "list")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("token mint failed", err)

    def test_no_real_gh_says_so(self):
        py = self.T / "py"
        py.mkdir()
        (py / "python3").symlink_to(shutil.which("python3"))
        rc, _, err = self.gh("pr", "list", CLAUDECODE="", PATH=f"{self.T / 'layer'}:{py}")
        self.assertEqual(rc, 1)
        self.assertIn("no gh on PATH but this shim", err)


if __name__ == "__main__":
    unittest.main()
