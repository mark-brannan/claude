#!/usr/bin/env python3
# Tests for vend-secrets. Run: python3 bin/vend-secrets.test.py
# Offline only: `gh secret set` is not called.
import base64
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "vend-secrets"
spec = importlib.util.spec_from_loader("vend_secrets", importlib.machinery.SourceFileLoader("vend_secrets", str(ENGINE)))
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)

PEM = "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\n"


class ParseTest(unittest.TestCase):
    def test_export_comments_and_quotes(self):
        text = "# header\nexport A=1\nB='two'\nC=\"th=ree\"\n\nnot a line\n"
        self.assertEqual(vs.parse_env(text), {"A": "1", "B": "two", "C": "th=ree"})

    def test_read_repos_skips_blanks_and_comments(self):
        self.assertEqual(vs.read_repos("a\n\n# x\n b \n"), ["a", "b"])


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def write(self, name, text):
        with open(os.path.join(self.dir, name), "w") as f:
            f.write(text)

    def test_all_three(self):
        self.write("claude-token.env", "export CLAUDE_CODE_OAUTH_TOKEN=tok\n")
        self.write("agent-bot.env", "AGENT_BOT_APP_ID=42\nAGENT_BOT_PRIVATE_KEY_B64=%s\n"
                   % base64.b64encode(PEM.encode()).decode())
        got = vs.resolve(list(vs.SOURCES), self.dir)
        self.assertEqual(got, {"CLAUDE_CODE_OAUTH_TOKEN": "tok", "AGENT_BOT_APP_ID": "42",
                               "AGENT_BOT_PRIVATE_KEY": PEM})

    def test_missing_key_exits(self):
        self.write("claude-token.env", "# empty\n")
        with self.assertRaises(SystemExit):
            vs.resolve(["CLAUDE_CODE_OAUTH_TOKEN"], self.dir)

    def test_missing_file_exits(self):
        with self.assertRaises(SystemExit):
            vs.resolve(["AGENT_BOT_APP_ID"], self.dir)

    def test_key_not_pem_exits(self):
        self.write("agent-bot.env", "AGENT_BOT_PRIVATE_KEY_B64=%s\n" % base64.b64encode(b"nope").decode())
        with self.assertRaises(SystemExit):
            vs.resolve(["AGENT_BOT_PRIVATE_KEY"], self.dir)


if __name__ == "__main__":
    unittest.main()
