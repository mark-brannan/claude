#!/usr/bin/env python3
# Tests for no-unsigned-push.py. Run: python3 hooks/no-unsigned-push.test.py
#
# Each case builds a bare origin and a clone signing with a throwaway SSH key,
# so "signed" means a real gpgsig header. Unsigned commits are made with
# -c commit.gpgsign=false. Global git config is ignored throughout.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "no-unsigned-push.py"
STATE = Path(__file__).resolve().parent.parent / "lib" / "state.py"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          env={**os.environ, **GIT_ENV}, check=check)


class NoUnsignedPushTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def setup_repo(self):
        """A clone: main pushed to origin, origin/HEAD set, signing on."""
        self.n += 1
        t = Path(self.tmp.name) / str(self.n)
        t.mkdir()
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(t / "key")], check=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(t / "origin.git")],
                       check=True, env={**os.environ, **GIT_ENV})
        subprocess.run(["git", "clone", "-q", str(t / "origin.git"), str(t / "w")],
                       capture_output=True, env={**os.environ, **GIT_ENV})
        w = t / "w"
        for k, v in [("user.email", "test@example.com"), ("user.name", "Test"), ("gpg.format", "ssh"),
                     ("user.signingkey", str(t / "key")), ("commit.gpgsign", "true")]:
            git(w, "config", k, v)
        git(w, "commit", "-q", "--allow-empty", "-m", "root")
        git(w, "push", "-q", "origin", "main")
        git(w, "remote", "set-head", "origin", "main")
        return w

    def unsigned(self, repo, msg):
        git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", msg)

    def hook(self, cmd, cwd, **env):
        """(verdict, raw stdout): silent / deny / allow."""
        e = {**os.environ, **GIT_ENV}
        e.update(env)
        for k in [k for k, v in env.items() if v is None]:
            e.pop(k)
        p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
            {"tool_input": {"command": cmd}, "cwd": str(cwd)}), capture_output=True, text=True, env=e)
        out = p.stdout.strip()
        return ("silent" if not out else "deny" if '"deny"' in out else "allow"), out

    def verdict(self, cmd, cwd, **env):
        return self.hook(cmd, cwd, **env)[0]

    def test_merged_main_unsigned_commits_are_not_the_branchs(self):
        # The bug: a pushed branch that merges a main carrying unsigned
        # commits was denied for main's commits, which @{u}..HEAD counted.
        w = self.setup_repo()
        git(w, "switch", "-q", "-c", "feat")
        git(w, "commit", "-q", "--allow-empty", "-m", "feat work")
        git(w, "push", "-q", "-u", "origin", "feat")
        git(w, "switch", "-q", "main")
        self.unsigned(w, "unsigned on main")
        git(w, "push", "-q", "origin", "main")
        git(w, "switch", "-q", "feat")
        git(w, "merge", "-q", "--no-edit", "main")
        self.assertEqual(self.verdict("git push", w), "silent")

        # The branch's own unsigned commit is still caught, and only it is named.
        self.unsigned(w, "unsigned on feat")
        verdict, out = self.hook("git push", w)
        self.assertEqual(verdict, "deny")
        self.assertEqual(out.count("1 unsigned commit"), 1)

        # The remedy is the brief; its command re-signs only what sits above
        # the merge, so the merge and main's commits survive and the push clears.
        self.assertIn("state.py branch_brief", out)
        brief = subprocess.run([sys.executable, str(STATE), "branch_brief", str(w), "feat"],
                               capture_output=True, text=True, env={**os.environ, **GIT_ENV}).stdout
        rec = next(ln for ln in brief.split("\n") if ln.startswith("recommend: "))
        self.assertRegex(rec, r"^recommend: git rebase -S --force-rebase [0-9a-f]{12} ")
        git(w, *rec.split("#")[0].split()[2:])
        self.assertEqual(git(w, "rev-list", "--count", "--merges", "origin/main..HEAD").stdout.strip(), "1")
        self.assertEqual(self.verdict("git push", w), "silent")

    def test_no_upstream_falls_back_to_origin_head(self):
        w = self.setup_repo()
        git(w, "switch", "-q", "-c", "fresh")
        self.unsigned(w, "unsigned, never pushed")
        self.assertEqual(self.verdict("git push", w), "deny")

    def test_signed_branch_passes(self):
        w = self.setup_repo()
        git(w, "switch", "-q", "-c", "clean")
        git(w, "commit", "-q", "--allow-empty", "-m", "signed")
        self.assertEqual(self.verdict("git push", w), "silent")

    def test_no_signing_key_allows_with_a_note(self):
        w = self.setup_repo()
        git(w, "switch", "-q", "-c", "keyless")
        self.unsigned(w, "unsigned on a cloud vm")
        git(w, "config", "--unset", "user.signingkey")
        verdict, out = self.hook("git push", w)
        self.assertEqual(verdict, "allow")
        self.assertIn("state.py branch_brief", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_unreadable_payload_denies(self):
        p = subprocess.run([sys.executable, str(HOOK)], input="{not json", capture_output=True, text=True)
        self.assertIn("unreadable hook payload", p.stdout)

    def test_non_push_commands_are_silent(self):
        w = self.setup_repo()
        git(w, "switch", "-q", "-c", "feat")
        self.unsigned(w, "unsigned")
        self.assertEqual(self.verdict("git status", w), "silent")

    def pair(self):
        """(clean, dirty): two repos, only dirty has an unsigned commit."""
        clean, dirty = self.setup_repo(), self.setup_repo()
        git(clean, "switch", "-q", "-c", "feat")
        git(clean, "commit", "-q", "--allow-empty", "-m", "signed on feat")
        git(dirty, "switch", "-q", "-c", "feat")
        self.unsigned(dirty, "unsigned on feat")
        return clean, dirty

    def test_dash_C_checks_the_named_repo_not_cwd(self):
        # cwd is a clean repo; the command names an unsigned one via -C.
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"git -C {dirty} push", clean), "deny")
        # Same, but cwd is the unsigned repo and the -C target is clean.
        self.assertEqual(self.verdict(f"git -C {clean} push", dirty), "silent")

    def test_leading_cd_checks_the_named_repo_not_cwd(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"cd {dirty} && git push", clean), "deny")
        self.assertEqual(self.verdict(f"cd {clean} && git push", dirty), "silent")

    def test_cd_or_C_not_belonging_to_the_push_is_ignored(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"git push && cd {dirty}", clean), "silent")
        self.assertEqual(self.verdict("git commit -C HEAD && git push", dirty), "deny")
        self.assertEqual(self.verdict(f"git -C {dirty} push && git -C {clean} status", clean), "deny")

    def test_cd_or_fallback_does_not_swallow_the_push(self):
        # `|` ends the cd operand, so `|| git push` is not part of the path.
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"cd {dirty} || git push", clean), "deny")

    def test_bare_cd_goes_to_home(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict("cd && git push", clean, HOME=str(dirty)), "deny")

    def test_dash_C_expands_tilde(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"git -C ~/{dirty.name} push", clean, HOME=str(dirty.parent)), "deny")

    def test_home_unset_falls_back_to_cwd(self):
        # ~ is unresolved rather than "": `cd ~/tmp` must not become a check
        # of /tmp (not a repo, so silent) instead of the session cwd.
        _, dirty = self.pair()
        self.assertEqual(self.verdict("cd ~/tmp && git push", dirty, HOME=None), "deny")
        self.assertEqual(self.verdict("git -C '$HOME/tmp' push", dirty, HOME=None), "deny")

    def test_cd_on_a_later_line_is_not_the_pushs_directory(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"git push\ncd {dirty}", clean), "silent")

    def test_chained_dash_C_flags_resolve_like_git(self):
        clean, dirty = self.pair()
        self.assertEqual(self.verdict(f"git -C {dirty.parent} -C {dirty.name} push", clean), "deny")


if __name__ == "__main__":
    unittest.main()
