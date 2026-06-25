"""A pool asset = a 100%-pass-through node (input flow X → output X). The
node balance makes it route (inflow = outflow), so sources feed it and consumers
draw from it, and a buy limit on a source→pool edge caps that source's supply."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _produced(res: dict[str, Any], flow: str) -> float:
    return sum(s["produced"] for s in res["summary"]["flow"] if s["flow"] == flow)


def _wb(cap_into_pool: float | None = None) -> dict[str, Any]:
    # S makes elec; POOL passes elec through (in elec → out elec); C turns elec→steel.
    edge_s_pool = {"from_process": "S", "to_process": "POOL", "flow_id": "elec"}
    if cap_into_pool is not None:
        edge_s_pool["max_flow"] = cap_into_pool
    return {
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 10},
            {"flow_id": "elec", "kind": "energy"},
            {"flow_id": "steel", "kind": "product"},
        ],
        "technologies": [
            {"technology_id": "ST"},
            {"technology_id": "POOLT"},
            {"technology_id": "CT"},
        ],
        "processes": [
            {"process_id": "S", "company": "X", "baseline_technology": "ST", "capacity": 1000},
            {
                "process_id": "POOL",
                "company": "X",
                "baseline_technology": "POOLT",
                "capacity": 1000,
            },
            {"process_id": "C", "company": "X", "baseline_technology": "CT", "capacity": 1000},
        ],
        "process_inputs": [
            {"technology_id": "ST", "flow_id": "gas", "intensity": 1.0},
            {"technology_id": "POOLT", "flow_id": "elec", "intensity": 1.0},
            {"technology_id": "CT", "flow_id": "elec", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "ST", "flow_id": "elec", "yield": 1.0},
            {"technology_id": "POOLT", "flow_id": "elec", "yield": 1.0},
            {"technology_id": "CT", "flow_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "edges": [
            edge_s_pool,
            {"from_process": "POOL", "to_process": "C", "flow_id": "elec"},
        ],
        "demand": [{"company": "all", "flow_id": "steel", "amount": 100}],
    }


def test_pool_routes_supply_to_the_consumer() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    # 100 steel needs 100 elec, routed S→POOL→C. The pool neither adds nor loses it.
    np.testing.assert_allclose(_produced(res, "steel"), 100.0, rtol=1e-6, atol=1e-6)


def test_buy_limit_on_pool_input_edge_caps_supply() -> None:
    # Cap S→POOL at 40 ⇒ only 40 elec reaches C ⇒ 40 steel (demand soft-unmet).
    res = _solve(_wb(40))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 40.0, rtol=1e-6, atol=1e-6)
