"""Impact cap as an intensity (impact per unit production)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb(intensity: bool, limit: float) -> dict:
    # Facility burns gas (1/unit) emitting 1 CO2/unit to make `widget`; demand 100.
    # An intensity cap of 0.4 tCO2 per widget ⇒ emit ≤ 0.4·production. The only
    # lever is the must-run-free gas → to cut intensity it underproduces (slack).
    return {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 0},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {"technology_id": "T", "target": "gas", "role": "input", "coefficient": 1},
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodity_impacts": [{"commodity_id": "gas", "impact_id": "CO2", "factor": 1}],
        "impact_caps": [
            {
                "company": "all",
                "impact_id": "CO2",
                "year": 2025,
                "limit": limit,
                "soft": False,
                "intensity": intensity,
            }
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }


def test_intensity_cap_binds_per_production() -> None:
    p = assemble_problem(_wb(intensity=True, limit=0.4), _sc())
    assert p.impact_cap_intensity[("all", "CO2")] is True
    res = extract_results(solve(build(p)))
    assert res["status"] == "optimal"
    # emit = production (1 CO2/widget); cap emit ≤ 0.4·production ⇒ 1·q ≤ 0.4·q,
    # only satisfied at q = 0 — hard intensity cap ⇒ produce 0, demand 100 short.
    slack = {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}
    np.testing.assert_allclose(slack["C|widget|2025"], 100.0, rtol=1e-6)


def test_intensity_cap_slack_when_met() -> None:
    # Intensity limit 1.0 = the actual intensity ⇒ full production feasible.
    res = extract_results(solve(build(assemble_problem(_wb(intensity=True, limit=1.0), _sc()))))
    assert res["status"] == "optimal"
    slack = {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}
    np.testing.assert_allclose(slack.get("C|widget|2025", 0.0), 0.0, atol=1e-6)
