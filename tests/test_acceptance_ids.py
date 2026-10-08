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
ID = re.compile(r"\d+\.\d+")
STRUCK = re.compile(r"^\| ~~")
TITLE = re.compile(r"^\s*Scenario(?: Outline)?: row (\d+\.\d+)\b")


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def table(hook):
    """The acceptance table as {row id: evidence}, read by its header row so
    a column added or removed is loud, not a silently shorter table."""
    header, rows = None, {}
    for line in (ROOT / "hooks" / f"{hook}-requirements.md").read_text().splitlines():
        if not line.startswith("|") or STRUCK.match(line):
            continue
        row = cells(line)
        if header is None:
            if row[0] == "#":
                header = row
            continue
        if all(re.fullmatch(r"-*", c) for c in row):
            continue
        assert len(row) == len(header), f"{len(row)} cells under a {len(header)}-column header: {line}"
        if ID.fullmatch(row[0]):
            rows[row[0]] = row[header.index("Evidence")]
    assert header and "Evidence" in header, f"no acceptance table with an Evidence column for {hook}"
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
