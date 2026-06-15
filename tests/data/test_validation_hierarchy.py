"""Hierarchy-aware validation: connections, structure, and zero-edge warnings."""

from __future__ import annotations

from typing import Any

from pathwise.data.validation import validate


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": [
            {"node_id": "mill", "parent_id": None, "kind": "group", "level": "facility"},
            {"node_id": "mill/bf", "parent_id": "mill", "kind": "machine"},
            {"node_id": "mill/bof", "parent_id": "mill", "kind": "machine"},
        ],
        "machines": [
            {"machine_id": "mill/bf", "baseline_technology": "BF", "capacity": 100},
            {"machine_id": "mill/bof", "baseline_technology": "BOF", "capacity": 100},
        ],
        "connections": [
            {"from_node": "mill/bf", "to_node": "mill/bof", "commodity_id": "iron"},
        ],
        "technologies": [{"technology_id": "BF", "io": []}, {"technology_id": "BOF", "io": []}],
        "io": [
            {"technology_id": "BF", "target": "iron", "role": "output", "coefficient": 1},
            {"technology_id": "BOF", "target": "iron", "role": "input", "coefficient": 1},
            {
                "technology_id": "BOF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodities": [
            {"commodity_id": "iron", "kind": "material"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "periods": [{"year": 2025, "duration_years": 1}],
        "demand": [{"company": "all", "commodity_id": "steel", "year": 2025, "amount": 50}],
    }


def test_valid_hierarchy_passes_with_no_warnings() -> None:
    report = validate(_model())
    assert report.ok, report.errors
    assert report.warnings == []


def test_connection_to_unknown_node_is_error() -> None:
    m = _model()
    m["connections"].append({"from_node": "mill/bf", "to_node": "ghost", "commodity_id": "iron"})
    report = validate(m)
    assert any("unknown node 'ghost'" in e for e in report.errors)


def test_connection_to_unknown_commodity_is_error() -> None:
    m = _model()
    m["connections"][0]["commodity_id"] = "plasma"
    report = validate(m)
    assert any("unknown stream 'plasma'" in e for e in report.errors)


def test_parent_cycle_is_error() -> None:
    m = _model()
    # make the facility point at its own child → cycle
    m["nodes"][0]["parent_id"] = "mill/bf"
    report = validate(m)
    assert any("cycle" in e for e in report.errors)


def test_zero_edge_connection_warns() -> None:
    m = _model()
    # bf does not output 'steel' and bof does not input 'steel' → no edges
    m["connections"].append(
        {"from_node": "mill/bf", "to_node": "mill/bof", "commodity_id": "steel"}
    )
    report = validate(m)
    assert report.ok, report.errors  # still valid (just a warning)
    assert any("expands to no edges" in w for w in report.warnings)
