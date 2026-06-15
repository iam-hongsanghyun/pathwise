"""Composite components: reuse-by-name, instantiate to a fresh instance tree.

A group is a reusable named composite (children + their internal connections);
placing it stamps a fresh instance of every descendant (path-qualified ids), so
one definition can be reused many times and a reused group brings its wiring
along. The instantiated workbook solves through the normal engine.
"""

from __future__ import annotations

import pytest

from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.components import ChildRef, ComponentLibrary, instantiate

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _library() -> ComponentLibrary:
    return ComponentLibrary.model_validate(
        {
            "commodities": [
                {"commodity_id": "power", "kind": "energy", "price": 1.0},
                {"commodity_id": "iron", "kind": "material"},
                {"commodity_id": "steel", "kind": "product"},
            ],
            "technologies": [
                {
                    "technology_id": "BF",
                    "io": [
                        {"target": "power", "role": "input", "coefficient": 2},
                        {"target": "iron", "role": "output", "coefficient": 1},
                    ],
                },
                {
                    "technology_id": "BOF",
                    "io": [
                        {"target": "iron", "role": "input", "coefficient": 1},
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                    ],
                },
            ],
            "machines": [
                {"name": "bf", "technology": "BF", "capacity": 100},
                {"name": "bof", "technology": "BOF", "capacity": 100},
            ],
            "groups": [
                {
                    "name": "mill",
                    "level": "facility",
                    "children": [{"component": "bf"}, {"component": "bof"}],
                    "connections": [{"source": "bf", "target": "bof", "commodity": "iron"}],
                },
                {
                    "name": "co",
                    "level": "company",
                    "children": [{"component": "mill", "alias": "m1"}],
                },
            ],
        }
    )


def test_instantiate_builds_path_qualified_instance_tree() -> None:
    wb = instantiate(_library(), "co")
    ids = {n["node_id"] for n in wb["nodes"]}
    assert ids == {"co", "co/m1", "co/m1/bf", "co/m1/bof"}
    assert {m["machine_id"] for m in wb["machines"]} == {"co/m1/bf", "co/m1/bof"}
    # the group's internal connection is stamped between the child instances.
    conn = wb["connections"][0]
    assert (conn["from_node"], conn["to_node"], conn["commodity_id"]) == (
        "co/m1/bf",
        "co/m1/bof",
        "iron",
    )


def test_instantiated_workbook_solves() -> None:
    wb = instantiate(_library(), "co")
    wb["periods"] = [{"year": 2025, "duration_years": 1}]
    wb["demand"] = [{"company": "all", "commodity_id": "steel", "year": 2025, "amount": 80}]
    res = run_model(wb, SC)
    assert res["status"] == "optimal"
    produced = {r["commodity"]: r["produced"] for r in res["summary"]["commodity"]}
    assert produced.get("steel") == pytest.approx(80.0)


def test_a_component_can_be_reused_as_distinct_instances() -> None:
    lib = _library()
    # A company with TWO mills: each placement is a fresh, independent instance.
    co = lib.group("co")
    assert co is not None
    co.children.append(ChildRef(component="mill", alias="m2"))
    wb = instantiate(lib, "co")
    ids = {n["node_id"] for n in wb["nodes"]}
    assert {"co/m1/bf", "co/m1/bof", "co/m2/bf", "co/m2/bof"} <= ids
    wb["periods"] = [{"year": 2025, "duration_years": 1}]
    wb["demand"] = [{"company": "all", "commodity_id": "steel", "year": 2025, "amount": 150}]
    res = run_model(wb, SC)
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
