"""A provider→consumer edge availability window: outside it the link carries zero
flow, so providers with different windows act as alternative supply over time."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _wb(edge_p1: dict[str, Any] | None = None) -> dict[str, Any]:
    # P1 cheap (gas @10), P2 dear (gas2 @100) both make elec; C turns elec→steel.
    # 100 steel each of two years ⇒ 100 elec/yr.
    e1 = {"from_process": "P1", "to_process": "C", "commodity_id": "elec"}
    if edge_p1:
        e1.update(edge_p1)
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 10},
            {"commodity_id": "gas2", "kind": "energy", "price": 100},
            {"commodity_id": "elec", "kind": "energy"},
            {"commodity_id": "steel", "kind": "product"},
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
            {"technology_id": "PT", "commodity_id": "gas", "intensity": 1.0},
            {"technology_id": "PT2", "commodity_id": "gas2", "intensity": 1.0},
            {"technology_id": "CT", "commodity_id": "elec", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "PT", "commodity_id": "elec", "yield": 1.0},
            {"technology_id": "PT2", "commodity_id": "elec", "yield": 1.0},
            {"technology_id": "CT", "commodity_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "edges": [e1, {"from_process": "P2", "to_process": "C", "commodity_id": "elec"}],
        "demand": [{"company": "all", "commodity_id": "steel", "amount": 100}],
    }


def test_baseline_uses_cheap_every_year() -> None:
    res = _solve(_wb())
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)  # 100 cheap × 2 yr


def test_cheap_link_unavailable_after_2025_forces_alternative() -> None:
    # The cheap P1→C link is only available up to 2025; in 2030 it carries zero, so
    # the dear P2 must supply — the textbook "different windows ⇒ alternatives".
    res = _solve(_wb({"available_to": 2025}))
    assert res["status"] == "optimal"
    # 2025: 100 cheap ($1000); 2030: 100 dear ($10000) = $11000.
    np.testing.assert_allclose(res["objective"], 11000.0, rtol=1e-6)
