"""Per-level optimisation: cut the node tree, solve each cut, couple across cuts.

Choosing a finer optimisation level partitions the hierarchy into independent
problems coupled by the value-chain cascade. Decomposed solving is never better
than the joint optimum (it adds internal transfer payments + loses joint
trade-offs), which is the headline correctness invariant.
"""

from __future__ import annotations

import pytest

from pathwise.core.partition import is_partitionable, partition
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.hierarchy import load_hierarchy


def _wb() -> dict:
    # vc → up (makes mid from power) → down (makes final from mid). A company-level
    # connection up→down on 'mid' is the cross-company stream.
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "power", "kind": "energy", "price": 1.0},
            {"commodity_id": "mid", "kind": "material"},
            {"commodity_id": "final", "kind": "product"},
        ],
        "technologies": [{"technology_id": "GEN"}, {"technology_id": "FAB"}],
        "io": [
            {"technology_id": "GEN", "target": "power", "role": "input", "coefficient": 2},
            {"technology_id": "GEN", "target": "mid", "role": "output", "coefficient": 1},
            {"technology_id": "FAB", "target": "mid", "role": "input", "coefficient": 1},
            {
                "technology_id": "FAB",
                "target": "final",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain"},
            {"node_id": "up", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "down", "parent_id": "vc", "kind": "group", "level": "company"},
            {"node_id": "upm", "parent_id": "up", "kind": "machine", "level": "machine"},
            {"node_id": "downm", "parent_id": "down", "kind": "machine", "level": "machine"},
        ],
        "machines": [
            {"machine_id": "upm", "baseline_technology": "GEN", "capacity": 1000},
            {"machine_id": "downm", "baseline_technology": "FAB", "capacity": 1000},
        ],
        "connections": [
            {"from_node": "up", "to_node": "down", "commodity_id": "mid", "lag_years": 0},
        ],
        "demand": [{"company": "down", "commodity_id": "final", "year": 2025, "amount": 100}],
    }


def _coupled_scenario() -> ScenarioConfig:
    return ScenarioConfig.from_dict(
        {
            "economics": {"base_year": 2025, "discount_rate": 0.0},
            "optimisation_scope": "company",
            "coupling": {"signals": ["price"], "iterations": 4, "damping": 1.0},
        }
    )


def _joint_scenario() -> ScenarioConfig:
    return ScenarioConfig.from_dict(
        {
            "economics": {"base_year": 2025, "discount_rate": 0.0},
            "optimisation_scope": "value_chain",
        }
    )


def test_partition_structure_at_company_level() -> None:
    h = load_hierarchy(_wb())
    assert h is not None
    assert is_partitionable(h, "company") and not is_partitionable(h, "value_chain")
    spec, workbooks = partition(_wb(), h, "company")
    assert {s.id for s in spec.stages} == {"up", "down"}
    assert len(spec.links) == 1
    link = spec.links[0]
    assert (link.from_stage, link.to_stage, link.commodity) == ("up", "down", "mid")
    assert link.feedback  # downstream demand drives upstream production
    # up's sub-workbook has only the upstream machine; down only the downstream.
    assert {str(p["process_id"]) for p in workbooks["up"]["processes"]} == {"upm"}
    assert {str(p["process_id"]) for p in workbooks["down"]["processes"]} == {"downm"}


def test_joint_solve_at_root_level() -> None:
    res = run_model(_wb(), _joint_scenario())
    assert res["status"] == "optimal"
    assert not res["outputs"]["demand_slack"]
    final = {r["commodity"]: r["produced"] for r in res["summary"]["commodity"]}
    assert final.get("final") == pytest.approx(100.0)


def test_partitioned_solve_meets_demand_and_is_weakly_worse_than_joint() -> None:
    joint = run_model(_wb(), _joint_scenario())
    coupled = run_model(_wb(), _coupled_scenario())

    assert joint["status"] == "optimal" and coupled["status"] == "optimal"
    # Downstream still delivers its demand under independent optimisation.
    down_final = {
        r["commodity"]: r["produced"] for r in coupled["stages"]["down"]["summary"]["commodity"]
    }
    assert down_final.get("final") == pytest.approx(100.0)

    joint_cost = float(joint["objective"])
    coupled_cost = sum(float(coupled["stages"][s]["objective"]) for s in coupled["stages"])
    # Decomposed solving is never cheaper than the joint optimum.
    assert coupled_cost >= joint_cost - 1e-6


def test_connection_lag_propagates_to_the_coupling_link() -> None:
    wb = _wb()
    wb["connections"][0]["lag_years"] = 5
    h = load_hierarchy(wb)
    assert h is not None
    spec, _ = partition(wb, h, "company")
    assert spec.links[0].lag_years == 5
