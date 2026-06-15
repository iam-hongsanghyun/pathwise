"""Generic SQLite workbook I/O — one table per sheet, sparse rows round-trip."""

from __future__ import annotations

from pathwise.api.workbook_io import parse_sqlite, write_sqlite


def test_sqlite_round_trips_sheets_and_sparse_rows() -> None:
    wb = {
        "nodes": [
            {"node_id": "a", "parent_id": None, "kind": "group", "level": "vc"},
            {"node_id": "a/m", "parent_id": "a", "kind": "machine"},
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
