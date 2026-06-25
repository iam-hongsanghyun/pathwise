"""Per-edge (provider → consumer, flow) flow bounds.

An edge ``min_flow`` is a take-or-pay floor on ONE provider's link: even when a
cheaper provider exists, at least ``min_flow`` must be taken from this one. The
``max_flow`` ceiling (already enforced) caps it.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _wb(p2_to_c: dict[str, Any] | None = None) -> dict[str, Any]:
    # Two power plants make elec — P1 cheap (gas @10), P2 dear (gas2 @100); the
    # consumer C turns elec into steel. Demand = 100 steel ⇒ 100 elec needed.
    edge_p2 = {"from_process": "P2", "to_process": "C", "flow_id": "elec"}
    if p2_to_c:
        edge_p2.update(p2_to_c)
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 10},
            {"flow_id": "gas2", "kind": "energy", "price": 100},
            {"flow_id": "elec", "kind": "energy"},
            {"flow_id": "steel", "kind": "product"},
        ],
        "technologies": [
            {"technology_id": "PT"},
            {"technology_id": "PT2"},
            {"technology_id": "CT"},
        ],
        "processes": [
            {"process_id": "P1", "company": "X", "baseline_technology": "PT", "capacity": 1000},
            {"process_id": "P2", "company": "X", "baseline_technology": "PT2", "capacity": 1000},
            {"process_id": "C", "company": "X", "baseline_technology": "CT", "capacity": 1000},
        ],
        "process_inputs": [
            {"technology_id": "PT", "flow_id": "gas", "intensity": 1.0},
            {"technology_id": "PT2", "flow_id": "gas2", "intensity": 1.0},
            {"technology_id": "CT", "flow_id": "elec", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "PT", "flow_id": "elec", "yield": 1.0},
            {"technology_id": "PT2", "flow_id": "elec", "yield": 1.0},
            {"technology_id": "CT", "flow_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "edges": [
            {"from_process": "P1", "to_process": "C", "flow_id": "elec"},
            edge_p2,
        ],
        "demand": [{"company": "X", "flow_id": "steel", "year": 2025, "amount": 100}],
    }


def test_without_floor_uses_only_the_cheap_provider() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    # All 100 elec from P1 (gas) → 100 × $10 = $1000; P2 (gas2 @100) stays off.
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)


def test_min_flow_forces_offtake_from_the_dear_provider() -> None:
    res = _solve(_wb({"min_flow": 40}))
    assert res["status"] == "optimal"
    # ≥40 elec must come from P2 (gas2 @100 = $4000) + 60 from P1 (gas @10 = $600).
    np.testing.assert_allclose(res["objective"], 4600.0, rtol=1e-6)


def test_max_flow_caps_a_provider() -> None:
    # Cap P1→C at 30 ⇒ only 30 cheap elec, the other 70 forced through P2 (dear).
    wb = _wb()
    wb["edges"][0]["max_flow"] = 30  # P1→C
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 30 from P1 ($300) + 70 from P2 ($7000) = $7300.
    np.testing.assert_allclose(res["objective"], 7300.0, rtol=1e-6)
