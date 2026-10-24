#!/usr/bin/env python3
# Tests for npm-publish-auth.py. Run: python3 hooks/npm-publish-auth.test.py
#
# The hook only decides -- nothing here runs npm -- so every case is a
# payload in and a decision out.
#
# The hook reads commands through the languette plugin's scanner: the user-scope
# install this machine's installed_plugins.json records (ci.yml clones languette
# and records it). Each case runs under a scratch HOME whose
# installed_plugins.json points there.
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HOOK = Path(__file__).resolve().parent / "npm-publish-auth.py"


def real_root():
    conf = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    try:
        plugins = json.loads((Path(conf) / "plugins" / "installed_plugins.json").read_text())["plugins"]
        return next(i["installPath"] for k, v in plugins.items() if k.startswith("languette@")
                    for i in v if i.get("scope") == "user")
    except (OSError, ValueError, KeyError, StopIteration):
        return ""


ROOT = real_root()


def scan_works(root):
    p = subprocess.run([sys.executable, "-I", f"{root}/languette/__main__.py", "scan"],
                       input="x", capture_output=True, text=True)
    return p.returncode == 0


class NpmPublishAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ROOT or not scan_works(ROOT):
            raise RuntimeError(f"no languette with `scan` at {ROOT!r} (install the languette plugin)")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".claude" / "plugins").mkdir(parents=True)
        self.plugins(ROOT)

    def tearDown(self):
        self.tmp.cleanup()

    def plugins(self, install_path):
        (self.home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps(
            {"version": 2, "plugins": {"languette@languette": [
                {"scope": "user", "installPath": str(install_path)}]}}))

    def run_hook(self, payload):
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
        env["HOME"] = str(self.home)
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    def decide(self, payload):
        p = self.run_hook(payload)
        if not p.stdout.strip():
            return "allow"
        return json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")

    def decide_cmd(self, cmd):
        return self.decide({"tool_name": "Bash", "tool_input": {"command": cmd}})

    def test_matches(self):
        for desc, cmd in [
            ("plain", "npm publish"),
            ("with flags", "npm publish --access public --tag next"),
            ("compound", "cd packages/foo && npm publish"),
            ("nested sh -c", "sh -c 'npm publish'"),
            ("absolute path", "/usr/local/bin/npm publish"),
            ("after a semicolon", "npm run build; npm publish"),
            ("dry run switched off", "npm publish --dry-run=false"),
            ("dry run in another segment", "npm pack --dry-run && npm publish"),
        ]:
            with self.subTest(desc):
                self.assertEqual(self.decide_cmd(cmd), "deny")

    def test_non_matches(self):
        for desc, cmd in [
            ("npm install", "npm install"),
            ("a script named publish", "npm run publish"),
            ("npm view", "npm view left-pad dist-tags"),
            ("the wrapper itself", "npm-publish-bg --access public"),
            ("prose in a commit", 'git commit -m "document that npm publish is wrapped"'),
            ("prose in a PR body", "gh pr create --title x --body 'run npm publish by hand'"),
            ("a heredoc mentioning it", "cat <<EOF > notes.md\nthen run npm publish\nEOF"),
            ("another tool entirely", "yarn publish"),
            ("a dry run needs no auth", "npm publish --dry-run"),
            ("a dry run, compound", "cd packages/foo && npm publish --access public --dry-run"),
        ]:
            with self.subTest(desc):
                self.assertEqual(self.decide_cmd(cmd), "allow")

    def test_deny_reason_names_the_replacement(self):
        p = self.run_hook({"tool_name": "Bash", "tool_input": {"command": "npm publish"}})
        reason = json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("npm-publish-bg", reason)

    def test_non_bash_tools_ignored(self):
        self.assertEqual(self.decide(
            {"tool_name": "Read", "tool_input": {"file_path": "npm publish"}}), "allow")

    def test_fails_open_without_installed_plugins(self):
        (self.home / ".claude" / "plugins" / "installed_plugins.json").unlink()
        self.assertEqual(self.decide_cmd("npm publish"), "allow")

    def test_fails_open_when_install_path_is_gone(self):
        self.plugins(Path(self.tmp.name) / "nowhere")
        self.assertEqual(self.decide_cmd("npm publish"), "allow")

    def test_fails_open_when_languette_has_no_scan(self):
        old = Path(self.tmp.name) / "old" / "languette"
        old.mkdir(parents=True)
        (old / "__main__.py").write_text("import sys\nsys.exit(2)\n")
        self.plugins(old.parent)
        self.assertEqual(self.decide_cmd("npm publish"), "allow")


if __name__ == "__main__":
    unittest.main()
