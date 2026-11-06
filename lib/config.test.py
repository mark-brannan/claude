#!/usr/bin/env python3
# Tests for lib/config.py. Run: python3 lib/config.test.py
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        config._cache.clear()

    def tearDown(self):
        self.tmp.cleanup()
        config._cache.clear()

    def places(self, cfg):
        p = Path(self.tmp.name) / "config.json"
        p.write_text(cfg if isinstance(cfg, str) else json.dumps(cfg))
        return (str(Path(self.tmp.name) / "absent.json"), str(p))

    def test_first_readable_place_wins(self):
        pl = self.places({"state_repo": {"github": "o/r", "search": ["~"]}})
        self.assertEqual(config.state_repo_github(pl), "o/r")

    def test_no_file_is_an_error_not_a_default(self):
        with self.assertRaises(config.ConfigError):
            config.load((str(Path(self.tmp.name) / "absent.json"),))

    def test_unparseable_file_is_an_error(self):
        with self.assertRaises(config.ConfigError):
            config.load(self.places("{not json"))

    def test_a_name_that_escapes_its_directory_is_refused(self):
        for bad in ("o/..", "o/.", "o/r/x", "o", "o/", "/r", "o/r name"):
            config._cache.clear()
            with self.subTest(bad), self.assertRaises(config.ConfigError):
                config.state_repo_name(self.places({"state_repo": {"github": bad}}))

    def test_dirs_put_the_name_under_each_search_place(self):
        pl = self.places({"state_repo": {"github": "o/st", "search": ["/w", "~", "~/src"]}})
        self.assertEqual(config.state_repo_dirs("/h", pl), ["/w/st", "/h/st", "/h/src/st"])

    def test_the_shipped_config_has_the_plan_figures(self):
        self.assertGreater(config.get("plan.week_usd"), 0)
        self.assertGreater(config.get("plan.fable_week_usd"), 0)

    def test_settings_json_names_the_configured_state_repo(self):
        # settings.json is static JSON and cannot read config.json; this keeps its copies in step.
        s = json.loads((ROOT / "settings.json").read_text())
        gh, name = config.state_repo_github(), config.state_repo_name()
        opts = s["pluginConfigs"]["languette@languette"]["options"]
        self.assertEqual(opts["private_repos"], gh)
        self.assertIn(f"~/{name}", s["permissions"]["additionalDirectories"])
        for k in ("redacted_terms_file", "blocked_terms_file"):
            self.assertTrue(opts[k].startswith(f"~/{name}/"), k)


if __name__ == "__main__":
    unittest.main()
