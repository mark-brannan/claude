"""The join between a hook's acceptance table and its feature file.

hooks/<hook>-requirements.md ends in a table whose rows are numbered
`<job>.<n>`, with an Evidence column saying what proves each row. A
scenario in features/<hook>.feature proves a row by starting its title with
the row's id as `row <id>`. Both ways must hold: a scenario names a row that exists and is
not struck through, and a row whose Evidence is `feature` has a scenario.
A row with other evidence (`test`, `code`, an item) may or may not have one.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FEATURES = sorted((ROOT / "features").glob("*.feature"))
ROW = re.compile(r"^\| (\d+\.\d+) \|(?: [^|]*\|){3} ([^|]*)\|\s*$")
STRUCK = re.compile(r"^\| ~~")
TITLE = re.compile(r"^\s*Scenario(?: Outline)?: row (\d+\.\d+)\b")


def table(hook):
    rows = {}
    for line in (ROOT / "hooks" / f"{hook}-requirements.md").read_text().splitlines():
        if STRUCK.match(line):
            continue
        m = ROW.match(line)
        if m:
            rows[m.group(1)] = m.group(2).strip()
    return rows


def titles(feature):
    return [m.group(1) for m in map(TITLE.match, feature.read_text().splitlines()) if m]


@pytest.mark.parametrize("feature", FEATURES, ids=lambda p: p.stem)
def test_every_scenario_is_a_row(feature):
    rows = table(feature.stem)
    assert rows, f"no acceptance table for {feature.stem}"
    ids = titles(feature)
    assert sorted(set(ids)) == sorted(ids), "a row has two scenarios"
    assert [i for i in ids if i not in rows] == [], "scenarios naming no live row"


@pytest.mark.parametrize("feature", FEATURES, ids=lambda p: p.stem)
def test_every_feature_row_has_a_scenario(feature):
    ids = set(titles(feature))
    claimed = [i for i, ev in table(feature.stem).items() if ev == "feature"]
    assert [i for i in claimed if i not in ids] == [], "rows whose Evidence says feature"
