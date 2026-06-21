"""A machine→machine edge bound authored alongside a node hierarchy (the machine-
only per-provider model) binds the actual fanned edge — the fan-out must NOT also
create a second, unbounded parallel channel for the same triple."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _wb() -> dict[str, Any]:
    # co/p1 cheap (gas @10), co/p2 dear (gas2 @100) both make elec; co/c turns
    # elec→steel. Connections are machine→machine. Demand 100 steel ⇒ 100 elec.
    return {
        "nodes": [
            {"node_id": "co", "parent_id": None, "kind": "group", "level": "company"},
            {"node_id": "co/p1", "parent_id": "co", "kind": "machine"},
            {"node_id": "co/p2", "parent_id": "co", "kind": "machine"},
            {"node_id": "co/c", "parent_id": "co", "kind": "machine"},
        ],
        "machines": [
            {"machine_id": "co/p1", "baseline_technology": "PT", "capacity": 1000},
            {"machine_id": "co/p2", "baseline_technology": "PT2", "capacity": 1000},
            {"machine_id": "co/c", "baseline_technology": "CT", "capacity": 1000},
        ],
        "technologies": [
            {"technology_id": "PT"},
            {"technology_id": "PT2"},
            {"technology_id": "CT"},
        ],
        "io": [
            {"technology_id": "PT", "target": "gas", "role": "input", "coefficient": 1},
            {"technology_id": "PT", "target": "elec", "role": "output", "coefficient": 1},
            {"technology_id": "PT2", "target": "gas2", "role": "input", "coefficient": 1},
            {"technology_id": "PT2", "target": "elec", "role": "output", "coefficient": 1},
            {"technology_id": "CT", "target": "elec", "role": "input", "coefficient": 1},
            {
                "technology_id": "CT",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 10},
            {"commodity_id": "gas2", "kind": "energy", "price": 100},
            {"commodity_id": "elec", "kind": "energy"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "connections": [
            {"from_node": "co/p1", "to_node": "co/c", "commodity_id": "elec"},
            {"from_node": "co/p2", "to_node": "co/c", "commodity_id": "elec"},
        ],
        "periods": [{"year": 2025}],
        "demand": [{"company": "all", "commodity_id": "steel", "amount": 100}],
    }


def test_baseline_uses_cheap_provider() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)


def test_authored_machine_edge_bound_binds_without_duplication() -> None:
    wb = _wb()
    # Cap the cheap provider's machine→machine edge at 30 (what the popup writes).
    # If the fan-out also created an unbounded co/p1→co/c edge, this cap would be
    # bypassed and cost would stay $1000; seeding seen_edges makes it bind.
    wb["edges"] = [
        {"from_process": "co/p1", "to_process": "co/c", "commodity_id": "elec", "max_flow": 30}
    ]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 30 cheap ($300) + 70 dear ($7000) = $7300.
    np.testing.assert_allclose(res["objective"], 7300.0, rtol=1e-6)
