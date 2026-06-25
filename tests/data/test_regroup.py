"""Regrouping bare assets under a Technology kind-group is engine-equivalent and
actually produces the grouping."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem
from pathwise.data.regroup import regroup_machines


def _wb() -> dict[str, Any]:
    return {
        "nodes": [
            {"node_id": "vc", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "vc/co", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "vc/co/s", "parent_id": "vc/co", "kind": "asset"},
            {"node_id": "vc/co/c", "parent_id": "vc/co", "kind": "asset"},
        ],
        "assets": [
            {"asset_id": "vc/co/s", "baseline_technology": "ST", "capacity": 1000},
            {"asset_id": "vc/co/c", "baseline_technology": "CT", "capacity": 1000},
        ],
        "technologies": [{"technology_id": "ST"}, {"technology_id": "CT"}],
        "io": [
            {"technology_id": "ST", "target": "ore", "role": "input", "coefficient": 1},
            {"technology_id": "ST", "target": "steel", "role": "output", "coefficient": 1},
            {"technology_id": "CT", "target": "steel", "role": "input", "coefficient": 1},
            {
                "technology_id": "CT",
                "target": "car",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "flows": [
            {"flow_id": "ore", "kind": "material", "price": 5},
            {"flow_id": "steel", "kind": "material"},
            {"flow_id": "car", "kind": "product"},
        ],
        "links": [{"from_node": "vc/co/s", "to_node": "vc/co/c", "flow_id": "steel"}],
        "periods": [{"year": 2025}],
        "demand": [{"company": "all", "flow_id": "car", "amount": 100}],
    }


def _objective(wb: dict[str, Any]) -> float:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return float(extract_results(solve(build(assemble_problem(wb, sc))))["objective"])


def test_regroup_inserts_technology_groups() -> None:
    out = regroup_machines(_wb())
    groups = [n for n in out["nodes"] if n.get("level") == "Technology"]
    assert len(groups) == 1  # one Technology group under vc/co
    # both assets now sit under it
    kg = groups[0]["node_id"]
    assets = [n for n in out["nodes"] if n.get("kind") == "asset"]
    assert all(m["parent_id"] == kg for m in assets)
    # asset ids unchanged (wiring preserved)
    assert {m["node_id"] for m in assets} == {"vc/co/s", "vc/co/c"}


def test_regroup_is_engine_equivalent() -> None:
    wb = _wb()
    before = _objective(wb)
    after = _objective(regroup_machines(wb))
    np.testing.assert_allclose(after, before, rtol=1e-9)


def test_regroup_is_idempotent() -> None:
    once = regroup_machines(_wb())
    twice = regroup_machines(once)
    assert len([n for n in twice["nodes"] if n.get("level") == "Technology"]) == 1
