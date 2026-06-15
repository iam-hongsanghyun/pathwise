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
from pathwise.data.components import (
    ChildRef,
    ComponentLibrary,
    instantiate,
    instantiate_into,
    place_technology,
)
from pathwise.data.library import MeasureBlockTemplate, MeasureTemplate

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


def test_machine_measures_are_stamped_per_instance() -> None:
    lib = _library()
    bf = lib.machine("bf")
    assert bf is not None
    bf.measures.append(  # the MACC subgroup authored on the machine
        MeasureTemplate(
            measure_id="eff",
            type="energy_efficiency",
            target="power",
            blocks=[
                MeasureBlockTemplate(reduction=0.1, capex_per_capacity=5.0, opex_per_capacity=1.0)
            ],
        )
    )
    wb = instantiate(lib, "co")
    # one measure stamped onto the bf instance, block capex scaled by capacity (100)
    assert wb["measures"] == [
        {
            "measure_id": "co/m1/bf · eff",
            "type": "energy_efficiency",
            "facility": "co/m1/bf",
            "target": "power",
            "lifetime": 15,
        }
    ]
    blk = wb["measure_blocks"][0]
    assert blk["capex"] == pytest.approx(500.0) and blk["opex"] == pytest.approx(100.0)


def test_instantiate_stamps_a_machines_technology_macc() -> None:
    # a machine with NO embedded measures, but a technology that links a MACC
    lib = ComponentLibrary.model_validate(
        {
            "commodities": [
                {"commodity_id": "power", "kind": "energy", "price": 1.0},
                {"commodity_id": "steel", "kind": "product"},
            ],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "maccs": ["eaf_eff"],
                    "io": [
                        {"target": "power", "role": "input", "coefficient": 2},
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                    ],
                }
            ],
            "measures": [
                {
                    "measure_id": "vfd",
                    "type": "energy_efficiency",
                    "target": "power",
                    "blocks": [{"reduction": 0.1, "capex_per_capacity": 5.0}],
                }
            ],
            "maccs": [{"macc_id": "eaf_eff", "measures": ["vfd"]}],
            "machines": [{"name": "eaf", "technology": "EAF", "capacity": 100}],
            "groups": [{"name": "plant", "level": "facility", "children": [{"component": "eaf"}]}],
        }
    )
    wb = instantiate(lib, "plant")
    assert any(str(m["measure_id"]).endswith("· vfd") for m in wb.get("measures", []))


def test_place_technology_makes_a_machine_with_its_macc() -> None:
    lib = ComponentLibrary.model_validate(
        {
            "commodities": [
                {"commodity_id": "power", "kind": "energy", "price": 1.0},
                {"commodity_id": "steel", "kind": "product"},
            ],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "maccs": ["eaf_eff"],
                    "io": [
                        {"target": "power", "role": "input", "coefficient": 2},
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True},
                    ],
                }
            ],
            "measures": [
                {
                    "measure_id": "vfd",
                    "type": "energy_efficiency",
                    "target": "power",
                    "blocks": [{"reduction": 0.1, "capex_per_capacity": 5.0}],
                }
            ],
            "maccs": [{"macc_id": "eaf_eff", "label": "EAF efficiency", "measures": ["vfd"]}],
        }
    )
    model = {"nodes": [{"node_id": "co", "parent_id": None, "kind": "group", "level": "company"}]}
    model = place_technology(model, lib, "EAF", parent_id="co", capacity=200)
    machine = next(m for m in model["machines"] if m["machine_id"] == "co/EAF")
    assert machine["baseline_technology"] == "EAF" and machine["capacity"] == 200
    # the linked MACC's measure is stamped onto the machine, scaled to capacity
    meas = [m for m in model["measures"] if m["facility"] == "co/EAF"]
    assert meas and meas[0]["measure_id"] == "co/EAF · vfd"
    assert model["measure_blocks"][0]["capex"] == pytest.approx(1000.0)  # 5 × 200
    # solves
    model["periods"] = [{"year": 2025, "duration_years": 1}]
    model["demand"] = [{"company": "co", "commodity_id": "steel", "year": 2025, "amount": 100}]
    res = run_model(model, SC)
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]


def test_place_technology_carries_per_year_costs() -> None:
    # A technology authored with per-year capex must carry that trajectory into
    # the model when placed, so the optimiser (not just the library) sees it.
    lib = ComponentLibrary.model_validate(
        {
            "commodities": [{"commodity_id": "steel", "kind": "product"}],
            "technologies": [
                {
                    "technology_id": "EAF",
                    "capex": 100,
                    "capex_by_year": {2025: 100, 2035: 300},
                    "io": [
                        {"target": "steel", "role": "output", "coefficient": 1, "is_product": True}
                    ],
                }
            ],
        }
    )
    model = {"nodes": [{"node_id": "co", "parent_id": None, "kind": "group", "level": "company"}]}
    model = place_technology(model, lib, "EAF", parent_id="co", capacity=10)
    # the per-year costs ride into the model on the technologies_prices sheet
    tp = model.get("technologies_prices", [])
    assert {(r["technology_id"], r["year"]) for r in tp} == {("EAF", 2025), ("EAF", 2035)}
    # and the assembler turns them into a per-year capex the optimiser sees
    from pathwise.data import assemble_problem

    model["periods"] = [{"year": 2025}, {"year": 2030}, {"year": 2035}]
    prob = assemble_problem(model, SC)
    assert prob.technologies["EAF"].capex(2025) == 100.0
    assert prob.technologies["EAF"].capex(2030) == 200.0  # linear midpoint
    assert prob.technologies["EAF"].capex(2035) == 300.0


def test_instantiate_into_drops_a_fresh_copy_under_a_parent() -> None:
    lib = _library()
    model = {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/steel", "parent_id": "chain", "kind": "group", "level": "company"},
        ]
    }
    model = instantiate_into(model, lib, "mill", parent_id="chain/steel")
    # second drop must NOT share ids with the first (fresh copies)
    model = instantiate_into(model, lib, "mill", parent_id="chain/steel")
    ids = [n["node_id"] for n in model["nodes"]]
    assert len(ids) == len(set(ids)), "fresh copies must have unique node ids"
    roots = [n for n in model["nodes"] if str(n.get("parent_id")) == "chain/steel"]
    assert len(roots) == 2 and roots[0]["node_id"] != roots[1]["node_id"]
    # technologies are merged by id (shared recipe), not duplicated
    assert len({r["technology_id"] for r in model["technologies"]}) == len(model["technologies"])
