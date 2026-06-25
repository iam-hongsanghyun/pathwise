"""Impact-aware optimisation: minimise a characterised category, and the Pareto front.

Two parallel assets feed one demand — a dirty one (2 tCO2/unit, free) and a clean
one (0.5 tCO2/unit, $5/unit). The optimiser splits production; capping or pricing the
GWP category shifts the split. (Parallel assets avoid the period-0 baseline lock a
single-asset transition would hit.)
"""

from __future__ import annotations

import pytest

from pathwise.backends.registry import get_backend

_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}}


def _dirty_clean() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "feed", "kind": "material", "unit": "t", "price": 1},
            {"commodity_id": "widget", "kind": "product", "unit": "ea"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}, {"impact_id": "GWP", "unit": "tCO2e"}],
        "characterisation": [{"flow_impact_id": "CO2", "category_id": "GWP", "factor": 1.0}],
        "technologies": [
            {"technology_id": "Dirty", "actions": "continue"},
            {"technology_id": "Clean", "actions": "continue", "opex": 5},
        ],
        "nodes": [
            {"node_id": "co", "kind": "group", "level": "company", "label": "Co"},
            {"node_id": "co/dirty", "kind": "asset", "level": "asset", "parent_id": "co"},
            {"node_id": "co/clean", "kind": "asset", "level": "asset", "parent_id": "co"},
        ],
        "assets": [
            {"asset_id": "co/dirty", "baseline_technology": "Dirty", "capacity": 1000},
            {"asset_id": "co/clean", "baseline_technology": "Clean", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "Dirty", "target": "feed", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Dirty",
                "target": "widget",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "Dirty", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "Clean", "target": "feed", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Clean",
                "target": "widget",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "Clean", "target": "CO2", "role": "impact", "coefficient": 0.5},
        ],
        "demand": [{"company": "co", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }


def _gwp(result: dict) -> float:
    return sum(float(r["total"]) for r in result["summary"]["impacts"] if r["impact"] == "GWP")


def test_minimise_impact_objective() -> None:
    """Minimising the GWP category picks the clean route (lower GWP, higher cost)."""
    model = _dirty_clean()
    least_cost = get_backend("linopy").run(model, {**_SCENARIO, "optimisation_scope": "system"})
    # objective = GWP only (cost_weight 0) ⇒ minimise the characterised category.
    min_gwp = get_backend("linopy").run(
        model,
        {
            **_SCENARIO,
            "optimisation_scope": "system",
            "objective_impact": "GWP",
            "impact_weight": 1.0,
            "cost_weight": 0.0,
        },
    )
    assert least_cost["status"] == "optimal" and min_gwp["status"] == "optimal"
    # Least-cost runs the dirty asset (free) ⇒ GWP 200; min-GWP runs clean ⇒ GWP 50.
    assert _gwp(least_cost) == pytest.approx(200.0)
    assert _gwp(min_gwp) == pytest.approx(50.0)


def test_cost_impact_frontier_is_monotone() -> None:
    """The ε-constraint frontier: tighter GWP cap ⇒ higher cost, lower achieved GWP."""
    fr = get_backend("frontier").run(
        _dirty_clean(),
        {
            **_SCENARIO,
            "optimisation_scope": "system",
            "frontier": {"impact": "GWP", "from": 50, "to": 200, "step": 50},
        },
    )
    pts = [p for p in fr["outputs"]["frontier"]["points"] if p.get("status") == "optimal"]
    assert len(pts) >= 3
    by_cap = sorted(pts, key=lambda p: p["cap"])
    # Cost is non-increasing as the cap loosens; achieved GWP is non-decreasing.
    costs = [p["cost"] for p in by_cap]
    gwps = [p["impact"] for p in by_cap]
    assert costs == sorted(costs, reverse=True)  # tightest cap costs the most
    assert gwps == sorted(gwps)  # tightest cap achieves the least GWP
    assert by_cap[0]["impact"] <= by_cap[-1]["impact"]
    assert by_cap[0]["cost"] >= by_cap[-1]["cost"]


def test_frontier_binds_despite_preexisting_soft_cap() -> None:
    """Regression: the frontier's hard ε-constraint must bind even when the model
    already carries a SOFT cap on the swept impact.

    This is the green_steel failure mode. The frontier backend used to *append* its
    hard cap to the model's caps; under system-scope pooling a single pre-existing
    soft cap softened the whole set (penalty cheaper than abating), so every frontier
    point collapsed to the least-cost plan (GWP 200) — the curve was flat. The fix
    REPLACES the swept impact's caps with the hard ε-constraint, so it binds.
    """
    model = _dirty_clean()
    # A pre-existing SOFT cap on the swept impact, generous (above the uncapped GWP of
    # 200) and cheap to violate — exactly what defeated the old append-based code.
    model["impact_caps"] = [
        {
            "company": "all",
            "impact_id": "GWP",
            "year": 2025,
            "limit": 300,
            "soft": True,
            "penalty": 1,
        }
    ]
    fr = get_backend("frontier").run(
        model,
        {
            **_SCENARIO,
            "optimisation_scope": "system",
            "frontier": {"impact": "GWP", "from": 50, "to": 200, "step": 50},
        },
    )
    by_cap = sorted(
        (p for p in fr["outputs"]["frontier"]["points"] if p.get("status") == "optimal"),
        key=lambda p: p["cap"],
    )
    assert len(by_cap) >= 3
    # The tightest cap (50) must actually bind → the all-clean plan (GWP 50), NOT the
    # least-cost GWP of 200 the soft cap would have allowed.
    assert by_cap[0]["impact"] == pytest.approx(50.0)
    assert by_cap[-1]["impact"] == pytest.approx(200.0)
    assert by_cap[0]["cost"] > by_cap[-1]["cost"]  # tighter ⇒ strictly costlier
