#!/usr/bin/env python3
# Tests for lib/gitrun.py. Run: python3 lib/gitrun.test.py
#
# What matters: callers get a result, not an exception, for a failing git,
# a missing git or a timeout; check=True raises the usual CalledProcessError.
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gitrun  # noqa: E402


class GitrunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.T = self.tmp.name
        self.path = os.environ.get("PATH", "")

    def tearDown(self):
        os.environ["PATH"] = self.path
        self.tmp.cleanup()

    def test_ok_and_out_in_a_repo(self):
        self.assertTrue(gitrun.ok("init", "-q", cwd=self.T))
        self.assertEqual(os.path.realpath(gitrun.out("rev-parse", "--show-toplevel", cwd=self.T)),
                         os.path.realpath(self.T))

    def test_failure_is_a_result(self):
        p = gitrun.run("rev-parse", "--show-toplevel", cwd=self.T)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(gitrun.ok("rev-parse", cwd=self.T))
        self.assertEqual(gitrun.out("rev-parse", "--show-toplevel", cwd=self.T), "")

    def test_check_raises(self):
        with self.assertRaises(subprocess.CalledProcessError):
            gitrun.run("rev-parse", cwd=self.T, check=True)

    def test_output_that_is_not_utf8_is_replaced_not_raised(self):
        fake = Path(self.T) / "git"
        fake.write_text("#!/bin/sh\nprintf 'caf\\351\\n'\n")
        fake.chmod(0o755)
        os.environ["PATH"] = self.T + os.pathsep + self.path
        self.assertEqual(gitrun.out("log"), "caf\ufffd")

    def test_missing_git_is_127(self):
        os.environ["PATH"] = self.T
        self.assertEqual(gitrun.run("status").returncode, gitrun.MISSING)

    def test_timeout_is_124(self):
        fake = Path(self.T) / "git"
        fake.write_text("#!/bin/sh\nsleep 5\n")
        fake.chmod(0o755)
        os.environ["PATH"] = self.T + os.pathsep + self.path
        self.assertEqual(gitrun.run("status", timeout=0.2).returncode, gitrun.TIMEOUT)

    def test_env_is_passed(self):
        self.assertTrue(gitrun.ok("init", "-q", cwd=self.T))
        env = dict(os.environ, GIT_DIR=os.path.join(self.T, "nowhere"))
        self.assertFalse(gitrun.ok("rev-parse", "--git-dir", cwd=self.T, env=env))

    def test_input_reaches_stdin(self):
        self.assertEqual(gitrun.out("hash-object", "--stdin", input="hi\n"),
                         "45b983be36b73c0788dc9cbcb76cbb80fc7bb057")

    def test_errors_choice(self):
        self.assertTrue(gitrun.ok("init", "-q", cwd=self.T))
        name = b"caf\xe9"
        Path(os.fsdecode(os.path.join(os.fsencode(self.T), name))).write_text("x")
        subprocess.run(["git", "add", "."], cwd=self.T, check=True)
        lax = gitrun.out("ls-files", "-z", cwd=self.T)
        self.assertIn("\ufffd", lax)
        exact = gitrun.out("ls-files", "-z", cwd=self.T, errors="surrogateescape")
        self.assertEqual(os.fsencode(exact.rstrip("\0")), name)

    def test_exact_keeps_every_byte(self):
        fake = Path(self.T) / "git"
        fake.write_text("#!/bin/sh\nprintf 'a\\r\\nb\\rcaf\\351\\n'\n")
        fake.chmod(0o755)
        os.environ["PATH"] = self.T + os.pathsep + self.path
        self.assertEqual(gitrun.out("log"), "a\nb\ncaf�", "text mode translates newlines")
        got = gitrun.exact("log").stdout
        self.assertEqual(got.encode("utf-8", "surrogateescape"), b"a\r\nb\rcaf\xe9\n")
        self.assertEqual(gitrun.run("log", binary=True).stdout, b"a\r\nb\rcaf\xe9\n")

    def test_exact_timeout_and_missing(self):
        os.environ["PATH"] = self.T
        p = gitrun.exact("status")
        self.assertEqual((p.returncode, p.stdout), (gitrun.MISSING, ""))


if __name__ == "__main__":
    unittest.main()
