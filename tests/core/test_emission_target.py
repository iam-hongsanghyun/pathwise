"""Emission targets as hard or soft constraints (B2)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, _sc())))).copy()


def _wb(cap: float, soft: bool | None, penalty: float | None) -> dict:
    # One facility burns 1 gas/unit; gas emits 1 CO2/unit; must make 100 widgets
    # ⇒ 100 CO2 unavoidable. Cap CO2 below 100 to force the target to bind.
    row: dict = {"company": "all", "impact_id": "CO2", "year": 2025, "limit": cap}
    if soft is not None:
        row["soft"] = soft
    if penalty is not None:
        row["penalty"] = penalty
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
        "impact_caps": [row],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }


def test_soft_target_allows_exceedance_at_penalty() -> None:
    # Cap 40, soft, penalty 5 /unit over. 100 CO2 - 40 = 60 over × $5 = $300.
    res = _solve(_wb(cap=40, soft=True, penalty=5))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 300.0, rtol=1e-6)


def test_hard_target_binds_and_forces_underproduction() -> None:
    # Cap 40, hard ⇒ CO2 ≤ 40 ⇒ at most 40 widgets; demand 100 unmet (60 short).
    # Demand slack is penalised at slack_penalty (1e9) ⇒ huge objective.
    res = _solve(_wb(cap=40, soft=False, penalty=None))
    assert res["status"] == "optimal"
    assert res["objective"] > 1.0e9  # demand shortfall dominates
    slack = {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}
    np.testing.assert_allclose(slack["C|widget|2025"], 60.0, rtol=1e-6)


def test_system_scope_pools_soft_per_impact_not_globally() -> None:
    """Regression: under system-scope pooling, a SOFT cap on one impact must not
    soften a HARD cap on a *different* impact.

    Two impacts (CO2 hard, NOx soft); the engine pools caps economy-wide when the
    scope is ``system``. Previously a single soft cap flipped *every* impact's pooled
    cap to soft, silently defeating the hard CO2 cap. The per-impact pooling keeps CO2
    hard (→ it binds: underproduction) while NOx stays soft.
    """
    wb = {
        "periods": [{"year": 2025}],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 0},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2"}, {"impact_id": "NOx"}],
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
            {"technology_id": "T", "target": "CO2", "role": "impact", "coefficient": 1},
            {"technology_id": "T", "target": "NOx", "role": "impact", "coefficient": 1},
        ],
        "impact_caps": [
            {"company": "all", "impact_id": "CO2", "year": 2025, "limit": 40, "soft": False},
            {
                "company": "all",
                "impact_id": "NOx",
                "year": 2025,
                "limit": 10,
                "soft": True,
                "penalty": 5,
            },
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }
    sc = ScenarioConfig.from_dict(
        {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
    )
    prob = assemble_problem(wb, sc)
    # The hard CO2 cap stays hard; the soft NOx cap stays soft (and keeps its penalty).
    assert prob.impact_cap_soft[("all", "CO2")] is False
    assert prob.impact_cap_soft[("all", "NOx")] is True
    np.testing.assert_allclose(prob.impact_cap_penalty[("all", "NOx")], 5.0)

    # End-to-end: the hard CO2 cap binds ⇒ underproduction (60 widgets short).
    res = extract_results(solve(build(prob))).copy()
    assert res["status"] == "optimal"
    slack = {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}
    np.testing.assert_allclose(slack["C|widget|2025"], 60.0, rtol=1e-6)
