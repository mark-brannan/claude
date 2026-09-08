#!/usr/bin/env python3
# Tests for prose-budget. Run: python3 .local/bin/prose-budget.test.py
#
# Every rule gets a positive and a negative case, symphony's runbook-lint
# cases are ported one for one, and the false positives that bit the three
# source repos each get a regression: hyphenated identifiers, a cited
# surname on the voice list, prose hidden in a fence, tables without a
# leading pipe, indented test titles.
import importlib.util
import importlib.machinery
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ENGINE = Path(__file__).resolve().parent / "prose-budget"
spec = importlib.util.spec_from_loader("prose_budget", importlib.machinery.SourceFileLoader("prose_budget", str(ENGINE)))
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)


class ProseCountingTest(unittest.TestCase):
    """Symphony's cases, verbatim."""

    def test_ignores_fences_headings_tables_blanks(self):
        text = ("# Title\n\none two three\n\n```sh\nthis whole fenced block is free of charge entirely\n```\n\n"
                "| col | col |\n| --- | --- |\n| a | b |\n")
        self.assertEqual(pb.count_prose_words(text), 3)

    def test_shell_comments_inside_fences_count(self):
        text = "## A\n\n```bash\n#!/bin/sh\n# four words of prose\nrun --flag  # not counted\n```\n"
        self.assertEqual(pb.count_prose_words(text), 4)

    def test_inline_code_spans_are_free(self):
        self.assertEqual(pb.count_prose_words("## A\n\nrun `docker compose up -d` now\n"), 2)

    def test_index_section_is_exempt(self):
        self.assertEqual(pb.count_prose_words("## Where things are\n\nlink one link two link three\n"), 0)

    def test_words_attributed_to_enclosing_section(self):
        counts = [(t, n) for t, n, _ in pb.section_word_counts("## A\n\none two\n\n## B\n\nthree four five\n")]
        self.assertEqual(counts, [("A", 2), ("B", 3)])

    def test_repeated_section_titles_stay_separate(self):
        counts = [(t, n) for t, n, _ in pb.section_word_counts("## Backup\n\none two\n\n## Backup\n\nthree four five\n")]
        self.assertEqual(counts, [("Backup", 2), ("Backup", 3)])

    def test_four_backtick_fence_survives_a_nested_triple_backtick(self):
        self.assertEqual(pb.count_prose_words("## A\n\n````\nsome prose with ``` inside a fence\n````\n\nafter\n"), 1)

    def test_table_without_leading_pipes_is_free(self):
        text = "## A\n\nHeader | Header\n------ | ------\nvalue | value\n\nreal words here\n"
        self.assertEqual(pb.count_prose_words(text), 3)

    def test_section_heading_line_is_reported(self):
        self.assertEqual(pb.section_word_counts("intro\n\n## A\n\nx\n")[1][2], 3)


class HelpersTest(unittest.TestCase):
    def test_glob_double_star(self):
        self.assertTrue(pb.matches(["docs/**/*.md"], "docs/a.md"))
        self.assertTrue(pb.matches(["docs/**/*.md"], "docs/adr/0001.md"))
        self.assertFalse(pb.matches(["docs/*.md"], "docs/adr/0001.md"))
        self.assertFalse(pb.matches(["*.md"], "docs/a.md"))
        self.assertTrue(pb.matches(["reference/**"], "reference/x/y.txt"))

    def test_line_count(self):
        self.assertEqual(pb.line_count(""), 0)
        self.assertEqual(pb.line_count("a\nb\n"), 2)
        self.assertEqual(pb.line_count("a\nb"), 2)

    def test_json_pointer_escapes(self):
        self.assertEqual(pb.json_pointer(("a/b", 0, "c~d")), "/a~1b/0/c~0d")

    def test_prose_strings_takes_strings_and_string_lists(self):
        data = {"note": "x", "items": [{"why": "y", "notes": ["p", "q"], "id": "skip"}]}
        self.assertEqual(list(pb.prose_strings(data, ["note", "why", "notes"])),
                         [("/note", "x"), ("/items/0/why", "y"), ("/items/0/notes/0", "p"), ("/items/0/notes/1", "q")])

    def test_test_titles_indented_and_skip_forms(self):
        src = "    test('deep title', () => {})\ntest.skip(\"skipped\", x)\nit(`tmpl`)\nfoo.test('method call')\n"
        self.assertEqual([t for _, t in pb.test_titles(src, "a.test.mjs")], ["deep title", "skipped", "tmpl"])
        self.assertEqual([t for _, t in pb.test_titles("it('esc\\'d quote', x)", "a.ts")], ["esc\\'d quote"])
        self.assertEqual(pb.test_titles('it("' + "\\a" * 40 + "x", "a.ts"), [], "no backtracking blowup")
        self.assertEqual([t for _, t in pb.test_titles("class T:\n    def test_x(self): pass\n", "t.py")], ["test_x"])

    def test_header_comment_forms(self):
        self.assertEqual(len(pb.header_comment("#!/bin/sh\n# a\n# b\ncode\n# c\n", "x.sh")), 2)
        self.assertEqual(len(pb.header_comment("/* a\n b */\n// not header\n", "x.ts")), 2)
        self.assertEqual(len(pb.header_comment("// a\n// b\n\n// c\n", "x.ts")), 2)
        self.assertEqual(pb.header_comment("x", "x.md"), [])

    def test_issue_pattern_skips_markdown_anchors(self):
        rx = pb.re.compile(pb.NARRATION["issue"], pb.re.I)
        self.assertIsNone(rx.search("see [Q-5](docs/requirements.md#9-open-questions)"))
        self.assertEqual(rx.search("fixed in colregs-engine#12").group(0), "colregs-engine#12")
        self.assertEqual(rx.search("fixed in mark-brannan/colregs#12").group(0), "mark-brannan/colregs#12")


class RepoCase(unittest.TestCase):
    """A throwaway git repo with a config; cli() invokes the engine CLI in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True, check=True)

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def config(self, cfg, path=".prose-budgets.json"):
        self.write(path, json.dumps(cfg))

    def commit(self, *paths, msg="c"):
        self.git("add", "--", *paths)
        self.git("commit", "-qm", msg)

    def cli(self, *args, cwd=None):
        r = subprocess.run([sys.executable, str(ENGINE), *args], cwd=cwd or self.root, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def findings(self, *args):
        code, out, err = self.cli("--json", *args)
        self.assertIn(code, (0, 1), err)
        return json.loads(out)

    def rules(self, *args):
        return sorted(f["rule"] for f in self.findings(*args))


class CliTest(RepoCase):
    def test_no_config_is_a_noop(self):
        code, out, _ = self.cli("--tree")
        self.assertEqual((code, out.strip()), (0, "no prose-budget config"))

    def test_require_config_fails_without_one(self):
        self.assertEqual(self.cli("--tree", "--require-config")[0], 1)

    def test_bad_config_exits_2(self):
        self.write(".prose-budgets.json", "{not json")
        self.assertEqual(self.cli("--tree")[0], 2)
        self.config({"voice": {"scope": "sometimes"}})
        self.assertEqual(self.cli("--tree")[0], 2)
        self.config({"nonsense": 1})
        self.assertEqual(self.cli("--tree")[0], 2)
        self.config({"narration": {"patterns": {"bad": "(unclosed"}}})
        self.assertEqual(self.cli("--tree")[0], 2)
        self.config({"unique_ids": [{"file": "README.md", "pattern": "(unclosed"}]})
        self.assertEqual(self.cli("--tree")[0], 2)

    def test_version(self):
        self.assertEqual(self.cli("--version")[1].strip(), f"prose-budget {pb.VERSION}")

    def test_findings_end_with_the_budget_line_and_name_the_config(self):
        self.config({"lines": {"README.md": 1}}, path="docs/budgets.json")
        self.write("README.md", "a\nb\nc\n")
        code, out, _ = self.cli("--tree")
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines()[0], "README.md:3: lines: 3 lines, budget 1")
        self.assertEqual(out.splitlines()[-1], pb.RAISE.format("docs/budgets.json"))

    def test_warn_only_exits_zero(self):
        self.config({"lines": {"README.md": 1}})
        self.write("README.md", "a\nb\n")
        self.assertEqual(self.cli("--tree", "--warn-only")[0], 0)

    def test_json_shape(self):
        self.config({"lines": {"README.md": 1}})
        self.write("README.md", "a\nb\n")
        f = self.findings("--tree")
        self.assertEqual(set(f[0]), {"rule", "file", "line", "pointer", "hash", "message"})

    def test_config_discovered_walking_up_and_docs_first(self):
        self.config({"lines": {"README.md": 1}}, path="docs/budgets.json")
        self.config({}, path=".prose-budgets.json")
        self.write("README.md", "a\nb\n")
        (self.root / "sub" / "dir").mkdir(parents=True)
        self.assertEqual(self.cli("--tree", cwd=self.root / "sub" / "dir")[0], 1)

    def test_tree_is_the_default_and_covers_untracked_files(self):
        self.config({"lines": {"README.md": 1}})
        self.write("README.md", "a\nb\n")
        self.assertEqual(self.cli()[0], 1)

    def test_file_restricts_scope_and_skips_unused_grandfather_checks(self):
        self.config({"lines": {"README.md": 1, "OTHER.md": 1},
                     "json_prose": {"targets": ["d.json"], "grandfathered": ["d.json#/note"]}})
        self.write("README.md", "a\nb\n")
        self.write("OTHER.md", "a\nb\n")
        self.write("d.json", '{"note": "short"}')
        f = self.findings("--tree", "--file", "README.md")
        self.assertEqual([x["file"] for x in f], ["README.md"])
        f = self.findings("--tree", "--file", str(self.root / "sub" / "outside.md"))
        self.assertEqual(f, [])


class LinesTest(RepoCase):
    def test_over_and_under(self):
        self.config({"lines": {"README.md": 2, "docs/a.md": 2}})
        self.write("README.md", "a\nb\nc\n")
        self.write("docs/a.md", "a\nb\n")
        self.assertEqual([f["file"] for f in self.findings("--tree")], ["README.md"])

    def test_missing_file_skipped_unless_required(self):
        self.config({"lines": {"gone.md": 2}})
        self.assertEqual(self.findings("--tree"), [])
        self.config({"lines": {"gone.md": 2, "required": True}})
        self.assertEqual(self.rules("--tree"), ["lines"])
        self.config({"lines": {"gone.md": 2, "required": True, "pending": ["gone.md"]}})
        self.assertEqual(self.findings("--tree"), [])

    def test_must_budget(self):
        self.config({"lines": {"README.md": 5, "must_budget": ["docs/**/*.md"]}})
        self.write("README.md", "a\n")
        self.write("docs/x.md", "a\n")
        self.assertEqual([f["file"] for f in self.findings("--tree")], ["docs/x.md"])
        self.config({"lines": {"README.md": 5, "docs/x.md": 5, "must_budget": ["docs/**/*.md"]}})
        self.assertEqual(self.findings("--tree"), [])


class SectionsTest(RepoCase):
    def test_section_over_budget_fails(self):
        self.config({"delta": False})
        self.write("RUNBOOK.md", "## Big\n\n" + ("word " * 145) + "\n")
        self.git("add", "RUNBOOK.md")
        f = self.findings("--staged")
        self.assertEqual([(x["rule"], x["line"]) for x in f], [("sections", 1)])
        self.assertIn("Big", f[0]["message"])

    def test_section_within_budget_passes(self):
        self.config({})
        self.write("RUNBOOK.md", "## Small\n\nshort enough\n")
        self.git("add", "RUNBOOK.md")
        self.assertEqual(self.findings("--staged"), [])

    def test_prose_in_a_fence_costume_still_counts(self):
        self.config({"sections": {"max_words": 5}})
        self.write("RUNBOOK.md", "## A\n\n```sh\n# one two three four five six\nls\n```\n")
        self.assertEqual(self.rules("--tree"), ["sections"])

    def test_exempt_and_custom_targets(self):
        self.config({"sections": {"targets": ["docs/*.md"], "max_words": 2, "exempt": ["Index"]}})
        self.write("docs/a.md", "## Index\n\none two three four\n\n## Body\n\none two\n")
        self.write("RUNBOOK.md", "## Big\n\none two three four\n")
        self.assertEqual(self.findings("--tree"), [])


class DeltaTest(RepoCase):
    def test_new_file_counts_fully_as_added(self):
        self.config({"delta": {"targets": ["RUNBOOK.md", "runbooks/*.md"]}})
        self.write("RUNBOOK.md", "seed\n")
        self.commit("RUNBOOK.md", ".prose-budgets.json")
        self.write("runbooks/new.md", "## S\n\n" + ("word " * 60) + "\n")
        self.git("add", "runbooks/new.md")
        f = self.findings("--staged")
        self.assertEqual([x["rule"] for x in f], ["delta"])
        self.assertIn("adds 60 net prose words", f[0]["message"])

    def test_removal_credits_against_addition(self):
        self.config({})
        self.write("RUNBOOK.md", "## A\n\n" + ("word " * 100) + "\n")
        self.commit("RUNBOOK.md", ".prose-budgets.json")
        self.write("RUNBOOK.md", "## A\n\n" + ("term " * 100) + "\n")
        self.git("add", "RUNBOOK.md")
        self.assertEqual(self.findings("--staged"), [])

    def test_deleted_runbook_credits_its_words(self):
        self.config({})
        self.write("RUNBOOK.md", "## A\n")
        self.write("runbooks/old.md", "## S\n\n" + ("word " * 100) + "\n")
        self.commit("RUNBOOK.md", "runbooks/old.md", ".prose-budgets.json")
        self.git("rm", "-q", "runbooks/old.md")
        self.write("RUNBOOK.md", "## A\n\n" + ("word " * 120) + "\n")
        self.git("add", "RUNBOOK.md")
        self.assertEqual(self.findings("--staged"), [])

    def test_pure_rename_is_net_zero(self):
        self.config({})
        self.write("RUNBOOK.md", "seed\n")
        self.write("runbooks/a.md", "## S\n\n" + ("word " * 100) + "\n")
        self.commit("RUNBOOK.md", "runbooks/a.md", ".prose-budgets.json")
        self.git("mv", "runbooks/a.md", "runbooks/b.md")
        self.assertEqual(self.findings("--staged"), [])

    def test_preset_delta_skips_files_with_a_line_budget_and_runs_under_base(self):
        self.config({"lines": {"README.md": 500}})
        self.write("README.md", "seed\n")
        self.write("docs/a.md", "seed\n")
        self.commit("README.md", "docs/a.md", ".prose-budgets.json")
        self.git("checkout", "-qb", "feature")
        self.write("README.md", "## A\n\n" + ("word " * 100) + "\n")
        self.commit("README.md")
        self.assertEqual(self.findings("--base", "main"), [])
        self.write("docs/a.md", "## A\n\n" + ("word " * 100) + "\n")
        self.commit("docs/a.md")
        self.assertEqual(self.rules("--base", "main"), ["delta"])
        self.assertEqual(self.findings("--tree"), [], "delta never runs on the tree")


class LandAloneTest(RepoCase):
    def stage(self, *paths):
        for p in paths:
            self.write(p, "x\n")
        self.git("add", "--", *paths)

    def test_code_alongside_runbook_fails(self):
        self.config({})
        self.stage("RUNBOOK.md", "scripts/foo.py")
        f = [x for x in self.findings("--staged") if x["rule"] == "land_alone"]
        self.assertEqual(len(f), 1)
        self.assertIn("scripts/foo.py", f[0]["message"])

    def test_allowlisted_neighbours_pass(self):
        self.config({"land_alone": {"with": ["README.md", "CLAUDE.md", "reference/**"]}})
        self.stage("RUNBOOK.md", "README.md", "CLAUDE.md", "reference/x.md", "runbooks/y.md")
        self.assertNotIn("land_alone", self.rules("--staged"))

    def test_no_runbook_staged_is_not_our_business(self):
        self.config({})
        self.stage("scripts/foo.py", "ansible/x.yml")
        self.assertEqual(self.findings("--staged"), [])


class JsonProseTest(RepoCase):
    def test_over_cap_and_grandfather_consumed(self):
        long = "x" * 20
        self.config({"json_prose": {"targets": ["data/*.json"], "max_chars": 10,
                                    "grandfathered": ["data/a.json#/items/0/note"]}})
        self.write("data/a.json", json.dumps({"items": [{"note": long}, {"why": long, "id": long}]}))
        f = self.findings("--tree")
        self.assertEqual([(x["file"], x["pointer"]) for x in f], [("data/a.json", "/items/1/why")])
        _, _, err = self.cli("--tree")
        self.assertIn("1 grandfathered field(s) still over 10 chars", err)

    def test_unused_grandfather_is_a_finding_only_on_a_full_scan(self):
        self.config({"json_prose": {"targets": ["data/*.json"], "max_chars": 10, "grandfathered": ["data/a.json#/note"]}})
        self.write("data/a.json", '{"note": "short"}')
        self.assertEqual(self.rules("--tree"), ["json_prose"])
        self.git("add", "data/a.json")
        self.assertEqual(self.findings("--staged"), [])

    def test_config_comment_is_subject_to_the_cap(self):
        self.config({"$comment": "y" * 30, "json_prose": {"max_chars": 10}})
        f = self.findings("--tree")
        self.assertEqual([(x["file"], x["pointer"]) for x in f], [(".prose-budgets.json", "/$comment")])

    def test_invalid_json_is_a_finding(self):
        self.config({"json_prose": {"targets": ["data/*.json"]}})
        self.write("data/a.json", "{oops")
        self.assertEqual(self.rules("--tree"), ["json_prose"])


class NarrationTest(RepoCase):
    def hits(self, text, cfg=None, name="README.md"):
        self.config({"narration": cfg or {}})
        self.write(name, text)
        return [f["message"].split('"')[1] for f in self.findings("--tree") if f["rule"] == "narration"]

    def test_builtins(self):
        self.assertEqual(self.hits("done in PR #12\n"), ["PR #12"])
        self.assertEqual(self.hits("see colregs#4\n"), ["colregs#4"])
        self.assertEqual(self.hits("during P2.1\n"), ["P2.1"])
        self.assertEqual(self.hits("earlier in this session\n"), ["this session"])
        self.assertEqual(self.hits("seeded 2026-01-01\n"), ["seeded 2026-"])
        self.assertEqual(self.hits("split out of the big one\n"), ["split out of"])
        self.assertEqual(self.hits("clean prose\n"), [])

    def test_disable_scope_and_extra_patterns(self):
        self.assertEqual(self.hits("PR #12\n", {"disable": ["pr"]}), [])
        self.assertEqual(self.hits("PR #12\n", {"scope": {"pr": ["docs/**"]}}), [])
        self.assertEqual(self.hits("PR #12\n", {"scope": {"pr": ["docs/**"]}, "targets": ["docs/*.md"]}, "docs/a.md"),
                         ["PR #12"])
        os.remove(self.root / "docs" / "a.md")
        self.assertEqual(self.hits("TODO later\n", {"patterns": {"todo": r"\bTODO\b"}}), ["TODO"])

    def test_grandfather_by_hash_and_by_match_and_unused(self):
        line = "done in PR #12 and PR #13"
        h = pb.hash12(line)
        self.assertEqual(self.hits(line + "\n", {"grandfathered": [{"file": "README.md", "hash": h}]}), ["PR #13"])
        self.assertEqual(self.hits(line + "\n", {"grandfathered": [{"file": "README.md", "match": "PR #12"},
                                                                    {"file": "README.md", "match": "PR #13"}]}), [])
        f = self.findings("--tree")
        self.config({"narration": {"grandfathered": [{"file": "README.md", "match": "PR #99"}]}})
        self.write("README.md", "clean\n")
        self.assertEqual(self.rules("--tree"), ["narration"])

    def test_grandfather_hash_is_printed_for_the_fix(self):
        self.config({})
        self.write("README.md", "  done in PR #12  \n")
        f = self.findings("--tree")
        self.assertEqual(f[0]["hash"], pb.hash12("done in PR #12"))
        self.assertIn(f[0]["hash"], f[0]["message"])

    def test_code_files_scan_titles_and_header_only(self):
        src = "// header mentions PR #1\nconst x = 'PR #2 in code is fine'\n    test('indented PR #3', () => {})\n"
        self.assertEqual(self.hits(src, {"targets": ["test/*.mjs"]}, "test/a.test.mjs"), ["PR #1", "PR #3"])

    def test_config_file_itself_is_not_scanned(self):
        self.config({"narration": {"targets": ["*.json"], "grandfathered": [{"file": "x.json", "match": "PR #1"}]}})
        self.write("x.json", '{"a": "PR #1"}')
        self.assertEqual(self.findings("--tree"), [])


class VoiceTest(RepoCase):
    def tree(self, text, cfg=None, name="README.md"):
        c = {"scope": "tree"}
        c.update(cfg or {})
        self.config({"voice": c})
        self.write(name, text)
        return [f["message"].split('"')[1] for f in self.findings("--tree") if f["rule"] == "voice"]

    def test_words_and_phrases(self):
        self.assertEqual(self.tree("a robust design\n"), ["robust"])
        self.assertEqual(self.tree("It's worth noting that\n"), ["It's worth noting"])
        self.assertEqual(self.tree("not just fast but correct\n"), ["not just fast but"])
        self.assertEqual(self.tree("whether you're new or old\n"), ["whether you're new or"])
        self.assertEqual(self.tree("Done. Moreover, more.\n"), [". Moreover"])
        self.assertEqual(self.tree("a plain sentence\n"), [])
        self.assertEqual(self.tree("we extrapolate\n", {"words": ["extrapolate"]}), ["extrapolate"])

    def test_hyphenated_identifier_is_not_prose(self):
        self.assertEqual(self.tree("see no-robust-policy-in-model and `foster-care`\n"), [])

    def test_allow_lets_a_citation_through(self):
        self.assertEqual(self.tree("per Foster/Gleirscher 2020\n"), ["Foster"])
        self.assertEqual(self.tree("per Foster/Gleirscher 2020\n", {"allow": ["Foster/Gleirscher"]}), [])

    def test_count_is_reported_never_failed(self):
        self.assertEqual(self.tree("this rather than that\n"), [])
        self.assertIn('"rather than": README.md 1', self.cli("--tree")[2])

    def test_json_prose_strings_are_checked_in_tree_scope(self):
        self.assertEqual(self.tree('{"note": "a seamless flow", "id": "seamless-id"}', {"targets": ["*.json"]}, "a.json"),
                         ["seamless"])

    def test_diff_scope_never_judges_the_config_file(self):
        self.config({"voice": {"targets": ["**/*.json"]}}, path="docs/budgets.json")
        self.git("add", "docs/budgets.json")
        self.assertEqual(self.findings("--staged"), [])
        self.config({"$comment": "a robust comment", "voice": {"targets": ["**/*.json"]}}, path="docs/budgets.json")
        self.git("add", "docs/budgets.json")
        self.assertEqual(self.findings("--staged"), [])

    def test_file_scope_is_scanned_even_under_default_diff_scope(self):
        # The edit hook runs `--tree --file <path>`; with the default voice.scope
        # ("diff") this used to hit the diff-only branch, see self.only is not
        # None, and bail without scanning the file at all.
        self.config({})
        self.write("README.md", "a robust design\n")
        f = self.findings("--tree", "--file", "README.md")
        self.assertEqual([x["rule"] for x in f], ["voice"])

    def test_malformed_json_reported_once_under_the_enabled_rule(self):
        self.config({"json_prose": {"targets": ["*.json"]}, "voice": {"targets": ["*.json"]}})
        self.write("a.json", "{oops")
        f = self.findings("--tree")
        self.assertEqual([(x["rule"], x["file"]) for x in f], [("json_prose", "a.json")])
        self.config({"voice": {"scope": "tree", "targets": ["*.json"]}})
        self.write("b.json", "{oops")
        f = [x for x in self.findings("--tree") if x["file"] == "b.json"]
        self.assertEqual([(x["rule"], x["file"]) for x in f], [("voice", "b.json")])

    def test_diff_scope_judges_only_added_lines(self):
        self.config({})
        self.write("README.md", "a robust line Mark wrote\nkeep\n")
        self.commit("README.md", ".prose-budgets.json")
        self.assertEqual(self.findings("--tree"), [], "diff scope never judges the tree")
        self.write("README.md", "a robust line Mark wrote\nkeep\nnew and comprehensive\n")
        self.git("add", "README.md")
        f = [x for x in self.findings("--staged") if x["rule"] == "voice"]
        self.assertEqual([(x["line"], x["message"].split('"')[1]) for x in f], [(3, "comprehensive")])
        self.git("commit", "-qm", "x")
        self.git("checkout", "-qb", "feature")
        self.write("README.md", "a robust line Mark wrote\nkeep\nnew and comprehensive\nleverage it\n")
        self.commit("README.md")
        f = [x for x in self.findings("--base", "main") if x["rule"] == "voice"]
        self.assertEqual([x["message"].split('"')[1] for x in f], ["leverage"])


class HeadersTest(RepoCase):
    def test_cap_grandfather_and_shebang(self):
        self.config({"headers": {"targets": ["src/*.ts", "bin/*"], "max_lines": 2, "grandfathered": {"src/old.ts": 3}}})
        self.write("src/a.ts", "// 1\n// 2\n// 3\nx\n")
        self.write("src/ok.ts", "/* 1\n 2 */\n// 3\nx\n")
        self.write("src/old.ts", "// 1\n// 2\n// 3\nx\n")
        self.write("bin/tool", "#!/bin/sh\n# 1\n# 2\necho\n")
        self.assertEqual([f["file"] for f in self.findings("--tree")], ["src/a.ts"])
        self.assertIn("src/a.ts: 3/4 comment lines (75%), header 3", self.cli("--tree")[2])


class UniqueIdsTest(RepoCase):
    def test_duplicate_id(self):
        self.config({"unique_ids": [{"file": "docs/r.md", "pattern": r"\*\*(Q-\d+|REQ-[A-Z]+-\d+)\*\*"}]})
        self.write("docs/r.md", "**Q-1** a\n**REQ-X-1** b\n**Q-1** again\n")
        f = self.findings("--tree")
        self.assertEqual([(x["rule"], x["message"]) for x in f], [("unique_ids", "Q-1 defined 2 times")])
        self.write("docs/r.md", "**Q-1** a\n**Q-2** b\n")
        self.assertEqual(self.findings("--tree"), [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
