"""Generic SQLite workbook I/O — one table per sheet, sparse rows round-trip."""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite, write_sqlite

_EXAMPLES = files("pathwise.assets.examples")
_EXAMPLE_FILES = sorted(p.name for p in _EXAMPLES.iterdir() if p.name.endswith(".sqlite"))


def test_sqlite_round_trips_sheets_and_sparse_rows() -> None:
    wb = {
        "nodes": [
            {"node_id": "a", "parent_id": None, "kind": "group", "level": "vc"},
            {"node_id": "a/m", "parent_id": "a", "kind": "asset"},
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "x",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        "blank": [],
    }
    back = parse_sqlite(write_sqlite(wb))
    assert set(back) == {"nodes", "io", "blank"}
    # NULL cells (the root's parent_id) are dropped on read (sparse)
    assert "parent_id" not in back["nodes"][0]
    assert back["nodes"][1]["parent_id"] == "a"
    # booleans store as 0/1 (sqlite has no bool) but stay truthy
    assert back["io"][0]["is_product"] == 1
    # an empty sheet survives as an empty table
    assert back["blank"] == []


@pytest.mark.parametrize("name", _EXAMPLE_FILES)
def test_shipped_example_is_a_well_formed_hierarchy(name: str) -> None:
    # Guards against the petrochemical regression: a `nodes` sheet with duplicate
    # ids or a self-parent edge makes the UI tree walks loop forever (frozen tab).
    wb = parse_sqlite((_EXAMPLES / name).read_bytes())
    nodes = wb.get("nodes", [])
    assert nodes, f"{name}: no nodes sheet"
    ids = [str(r.get("node_id")) for r in nodes]
    assert len(ids) == len(set(ids)), (
        f"{name}: duplicate node ids {sorted({i for i in ids if ids.count(i) > 1})}"
    )
    id_set = set(ids)
    for r in nodes:
        nid, parent = str(r.get("node_id")), r.get("parent_id")
        assert parent != nid, f"{name}: node {nid!r} is its own parent"
        if parent not in (None, ""):
            assert str(parent) in id_set, f"{name}: node {nid!r} has dangling parent {parent!r}"
