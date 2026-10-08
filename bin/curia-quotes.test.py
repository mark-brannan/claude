#!/usr/bin/env python3
# Tests for curia-quotes. Run: python3 bin/curia-quotes.test.py
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
TOOL = Path(__file__).resolve().parent / "curia-quotes"

ROLL = """
### 20261003t030107z
```
Initially a reference implementation, but in a later stage, hypothetically
(optimistically), a product. I want it public from the start.
```

### 20261003t030503z
````
As a reference implementation, I want all our claude stuff together in one place.
```
fenced inside
```
````
"""


def run(digest_text, extra_roll=None):
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a").mkdir()
        (root / "b").mkdir()
        (root / "a" / "roll.md").write_text(ROLL)
        (root / "b" / "roll.md").write_text("\n### 20261004t010101z\n```\nthe other curia says yes\n```\n")
        (root / "a" / "digest.md").write_text(digest_text)
        p = subprocess.run([sys.executable, str(TOOL), str(root / "a")], capture_output=True, text=True)
        return p.returncode, p.stdout.replace(d, "")


class QuoteCheckTest(unittest.TestCase):
    def ok(self, text):
        code, out = run(text)
        self.assertEqual((code, out), (0, ""))

    def bad(self, text, *needles):
        code, out = run(text)
        self.assertEqual(code, 1, out)
        for n in needles:
            self.assertIn(n, out)
        return out

    def test_exact_quote_passes(self):
        self.ok('Solace (`a/roll.md#20261003t030503z`): "I want all our claude stuff together in one place."\n')

    def test_case_punctuation_and_whitespace_ignored(self):
        self.ok('(a/roll.md#20261003t030107z) "initially a reference implementation but in a later stage"\n')

    def test_cut_and_bracketed_edit_allowed(self):
        self.ok('(a/roll.md#20261003t030107z) "Initially [the layer is] a reference implementation [...] a product."\n')
        self.ok('(a/roll.md#20261003t030107z) "Initially a reference implementation ... a product."\n')

    def test_typo_fix_allowed(self):
        self.ok('(a/roll.md#20261003t030503z) "I want all our claude stuf together in one place"\n')

    def test_mismatch_named(self):
        self.bad('(a/roll.md#20261003t030503z) "I want nothing together anywhere"\n', "digest.md:1", "I want nothing together")

    def test_segments_must_keep_order(self):
        self.bad('(a/roll.md#20261003t030107z) "a product [...] initially a reference implementation"\n', "a product")

    def test_bare_stamp_uses_curia_last_named_or_own(self):
        self.ok('"the other curia says yes" (b/roll.md#20261004t010101z)\n')
        self.bad('"the other curia says yes" (#20261003t030107z)\n', "the other curia")

    def test_missing_entry_named(self):
        self.bad('(a/roll.md#20261009t000000z) "whatever it said"\n', "no entry 20261009t000000z in a/roll.md")

    def test_any_cited_entry_on_the_line_may_match(self):
        self.ok('(`a/roll.md#20261003t030107z`, `#20261003t030503z`): "claude stuff together in one place"\n')

    def test_fenced_content_inside_entry_matches(self):
        self.ok('(a/roll.md#20261003t030503z) "one place [...] fenced inside"\n')

    def test_curly_quotes_and_each_mismatch_listed(self):
        out = self.bad('(a/roll.md#20261003t030503z) “nope not here” and "also not here"\n', "nope not here", "also not here")
        self.assertEqual(len(out.splitlines()), 2)

    def test_lines_without_a_citation_and_one_word_quotes_ignored(self):
        self.ok('He said "this is nowhere in any roll".\n(a/roll.md#20261003t030503z) the "claude" word\n')

    def test_segments_match_whole_words(self):
        self.bad('(a/roll.md#20261003t030107z) "a prod"\n', "a prod")
        self.bad('(a/roll.md#20261003t030503z) "I want [...] the"\n', "I want")

    def test_bracket_may_cut_into_a_word(self):
        self.ok('(a/roll.md#20261003t030503z) "[A]s a reference implementation, I want[ed] all our claude stuff"\n')

    def test_typo_fix_right_after_a_cut(self):
        self.ok('(a/roll.md#20261003t030107z) "Initially [...] in a latr stage"\n')

    def test_stamp_anchor_on_another_file_is_no_citation(self):
        self.ok('(agent_decisions.md#20261009t000000z) "whatever it said"\n')

    def test_bad_path_exits_2(self):
        p = subprocess.run([sys.executable, str(TOOL), "/nonexistent/digest.md"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


if __name__ == "__main__":
    unittest.main()
