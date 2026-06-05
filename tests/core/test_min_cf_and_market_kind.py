"""Minimum capacity factor (must-run floor) + auto-inferred market kind."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.core.entities import MarketTarget
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def test_min_capacity_factor_forces_minimum_throughput() -> None:
    # Demand is only 10, but the facility's technology must run at ≥ 50% of its
    # 100-unit capacity when active ⇒ throughput is forced up to 50, not 10.
    wb = {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 1},
            {"commodity_id": "widget", "kind": "product", "sale_price": 0},
        ],
        "technologies": [{"technology_id": "T", "min_capacity_factor": 0.5}],
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
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 10}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 50 throughput × 1 gas × $1 = 50 (must-run floor dominates the demand of 10).
    np.testing.assert_allclose(res["objective"], 50.0, rtol=1e-6)


def test_market_kind_inferred_from_target() -> None:
    wb = {
        "periods": [{"year": 2025}],
        "commodities": [{"commodity_id": "elec", "kind": "energy"}],
        "impacts": [{"impact_id": "CO2"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1}
        ],
        "io": [{"technology_id": "T", "target": "elec", "role": "input", "coefficient": 1}],
        "demand": [{"company": "C", "commodity_id": "elec", "year": 2025, "amount": 0}],
        # No explicit target_kind — inferred from whether the target is an impact.
        "markets": [
            {"market_id": "KEPCO", "target": "elec", "price": 50},
            {"market_id": "ETS", "target": "CO2", "price": 80, "allocation": 100},
        ],
    }
    prob = assemble_problem(wb, _sc())
    by_id = {m.market_id: m for m in prob.markets}
    assert by_id["KEPCO"].target_kind is MarketTarget.COMMODITY
    assert by_id["ETS"].target_kind is MarketTarget.IMPACT


def test_disabled_technology_is_excluded_with_its_transitions() -> None:
    # H2DRI is unchecked (enabled=false) ⇒ dropped from the model, and the
    # transition that targets it is dropped too (no dangling endpoint).
    wb = {
        "periods": [{"year": 2025}],
        "commodities": [{"commodity_id": "gas", "kind": "energy"}],
        "technologies": [
            {"technology_id": "BF"},
            {"technology_id": "H2DRI", "enabled": False},
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "BF", "capacity": 1}
        ],
        "io": [{"technology_id": "BF", "target": "gas", "role": "input", "coefficient": 1}],
        "transitions": [{"from_technology": "BF", "to_technology": "H2DRI"}],
        "demand": [{"company": "C", "commodity_id": "gas", "year": 2025, "amount": 0}],
    }
    prob = assemble_problem(wb, _sc())
    assert "H2DRI" not in prob.technologies
    assert prob.transitions == []
