"""Maximum production: a hard ceiling on delivered product (mirror of min_production)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.core.entities import ObjectiveMode
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb(max_cap: float | None) -> dict:
    """One plant that can make up to 1000 t steel; demand pulls 100 t."""
    wb: dict = {
        "periods": [{"year": 2025}],
        "flows": [{"flow_id": "steel", "kind": "product"}],
        "technologies": [{"technology_id": "EAF", "opex": 1.0}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "EAF", "capacity": 1000}
        ],
        "io": [
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": True,
            }
        ],
        "demand": [{"company": "C", "flow_id": "steel", "year": 2025, "amount": 100.0}],
    }
    if max_cap is not None:
        wb["max_production"] = [
            {"company": "C", "flow_id": "steel", "year": 2025, "amount": max_cap}
        ]
    return wb


def _produced(res: dict, flow: str) -> float:
    return sum(s["produced"] for s in res["summary"]["flow"] if s["flow"] == flow)


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, _sc()))))


def test_max_production_is_assembled() -> None:
    prob = assemble_problem(_wb(40.0), _sc())
    assert prob.max_production[("C", "steel", 2025)] == 40.0


def test_max_production_caps_delivery() -> None:
    # Demand pulls 100 t but the ceiling is 40 t → production is capped at 40.
    res = _solve(_wb(40.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 40.0, rtol=1e-6, atol=1e-6)


def test_no_ceiling_meets_demand() -> None:
    res = _solve(_wb(None))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "steel"), 100.0, rtol=1e-6, atol=1e-6)


def test_scenario_objective_is_the_company_default() -> None:
    # The Optimisation tab's goal becomes the default objective for every company
    # without a company_config override.
    sc = ScenarioConfig.from_dict({"objective": "profit"})
    prob = assemble_problem(_wb(None), sc)
    assert prob.default_objective == ObjectiveMode.PROFIT
    assert prob.objective_of("C") == ObjectiveMode.PROFIT
    # Default scenario stays least-cost.
    assert assemble_problem(_wb(None), _sc()).objective_of("C") == ObjectiveMode.COST
