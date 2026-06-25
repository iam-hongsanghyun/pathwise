"""P8a: per-company profit objective + non-replaceable facilities."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _profit_wb(sale_price: float) -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "company_config": [{"company": "C", "objective": "profit"}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 10},
            {"flow_id": "p", "kind": "product", "sale_price": sale_price},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "gas", "intensity": 1.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "p", "yield": 1.0, "is_product": True}
        ],
        "demand": [{"company": "C", "flow_id": "p", "year": 2025, "amount": 100}],
    }


def test_profit_skips_unprofitable_production() -> None:
    # Unit cost (gas) = $10 > sale price $5 ⇒ produce nothing; profit = 0.
    res = _solve(_profit_wb(5.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 0.0, atol=1e-6)
    assert sum(t["value"] for t in res["outputs"]["throughput"]) < 1e-6


def test_profit_produces_up_to_demand_when_profitable() -> None:
    # Sale $15 > cost $10 ⇒ sell up to demand 100; net cost = 1000 − 1500 = −500.
    res = _solve(_profit_wb(15.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], -500.0, rtol=1e-6)
    assert sum(t["value"] for t in res["outputs"]["throughput"]) >= 100 - 1e-6


def test_cost_company_must_meet_demand() -> None:
    # Same data, default cost objective (no company_config) ⇒ must produce 100.
    wb = _profit_wb(5.0)
    del wb["company_config"]
    res = _solve(wb)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)  # forced 100 × $10
    assert res["outputs"]["demand_slack"] == []


def _carbon_switch_wb() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "flows": [
            {"flow_id": "fuel", "kind": "energy", "price": 1},
            {"flow_id": "p", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}],
        "technologies": [{"technology_id": "BASE"}, {"technology_id": "CLEAN"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "BASE", "capacity": 100}
        ],
        "process_inputs": [
            {"technology_id": "BASE", "flow_id": "fuel", "intensity": 1},
            {"technology_id": "CLEAN", "flow_id": "fuel", "intensity": 1},
        ],
        "process_outputs": [
            {"technology_id": "BASE", "flow_id": "p", "yield": 1, "is_product": True},
            {"technology_id": "CLEAN", "flow_id": "p", "yield": 1, "is_product": True},
        ],
        "tech_impacts": [{"technology_id": "BASE", "impact_id": "CO2", "factor": 10}],
        "transitions": [
            {
                "from_technology": "BASE",
                "to_technology": "CLEAN",
                "action": "replace",
                "capex_per_capacity": 1,
                "compatible": True,
            }
        ],
        "impact_prices": [{"impact_id": "CO2", "year": 2030, "price": 1000}],
        "demand": [
            {"company": "C", "flow_id": "p", "year": 2025, "amount": 10},
            {"company": "C", "flow_id": "p", "year": 2030, "amount": 10},
        ],
    }


def test_non_replaceable_blocks_transition() -> None:
    free = _solve(_carbon_switch_wb())
    assert any(t["to_technology"] == "CLEAN" for t in free["outputs"]["transitions"])

    fixed = _carbon_switch_wb()
    fixed["processes"][0]["replaceable"] = False
    res = _solve(fixed)
    assert res["status"] == "optimal"
    assert not res["outputs"]["transitions"]  # locked to baseline
