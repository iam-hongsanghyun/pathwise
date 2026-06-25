"""LCIA characterisation: a category (GWP) is a derived impact = Σ flow × factor.

The same characterisation must surface in the simulate inventory, in the optimiser's
objective (a priced category), and in cap compliance — because a category is just
another impact in `ctx.emit`.
"""

from __future__ import annotations

import pytest

from pathwise.backends.registry import get_backend
from pathwise.backends.simulation_backend import SimulationBackend

_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}}


def _gwp_model() -> dict:
    """A plant emitting 2 tCO2 + 0.1 tCH4 per unit; GWP = CO2·1 + CH4·27.

    100 units ⇒ CO2 200, CH4 10, GWP = 200·1 + 10·27 = 470 tCO2e.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"flow_id": "widget", "kind": "product", "unit": "ea"},
        ],
        "impacts": [
            {"impact_id": "CO2", "unit": "tCO2"},
            {"impact_id": "CH4", "unit": "tCH4"},
            {"impact_id": "GWP", "unit": "tCO2e"},
        ],
        "characterisation": [
            {"flow_impact_id": "CO2", "category_id": "GWP", "factor": 1.0},
            {"flow_impact_id": "CH4", "category_id": "GWP", "factor": 27.0},
        ],
        "technologies": [{"technology_id": "Plant", "actions": "continue"}],
        "nodes": [
            {"node_id": "plantco", "kind": "group", "level": "company", "label": "Plant"},
            {"node_id": "plantco/p", "kind": "asset", "level": "asset", "parent_id": "plantco"},
        ],
        "assets": [{"asset_id": "plantco/p", "baseline_technology": "Plant", "capacity": 1000}],
        "io": [
            {"technology_id": "Plant", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Plant",
                "target": "widget",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "Plant", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "Plant", "target": "CH4", "role": "impact", "coefficient": 0.1},
        ],
        "demand": [{"company": "plantco", "flow_id": "widget", "year": 2025, "amount": 100}],
    }


def test_characterisation_gwp_in_inventory() -> None:
    """The simulate inventory reports GWP (characterised) alongside the raw gases."""
    lca = SimulationBackend().run(_gwp_model(), _SCENARIO)["outputs"]["lca"]
    by_impact = {d["impact"]: d["total"] for d in lca["by_impact"]}
    assert by_impact["CO2"] == pytest.approx(200.0)
    assert by_impact["CH4"] == pytest.approx(10.0)
    assert by_impact["GWP"] == pytest.approx(470.0)  # 200·1 + 10·27

    # GWP is also decomposed onto the network stage.
    gwp_stage = {d["stage"]: d["total"] for d in lca["by_stage"] if d["impact"] == "GWP"}
    assert gwp_stage["plantco"] == pytest.approx(470.0)


def test_gwp_price_enters_the_objective() -> None:
    """Pricing the GWP *category* adds price × GWP to the optimiser's objective."""
    model = _gwp_model()
    free = get_backend("linopy").run(model, _SCENARIO)["objective"]

    priced = dict(model)
    priced["impact_prices"] = [{"impact_id": "GWP", "year": 2025, "price": 10}]
    with_gwp = get_backend("linopy").run(priced, _SCENARIO)["objective"]

    # 470 tCO2e × $10 = $4,700 of carbon cost on the characterised category.
    assert with_gwp - free == pytest.approx(4700.0)


def test_gwp_cap_compliance() -> None:
    """A cap on the GWP category is checked against the characterised emission."""
    model = _gwp_model()
    model["impact_caps"] = [{"company": "plantco", "impact_id": "GWP", "year": 2025, "limit": 300}]
    compliance = SimulationBackend().run(model, _SCENARIO)["outputs"]["cap_compliance"]
    base = next(c for c in compliance if c["label"] == "baseline")
    row = next(r for r in base["by_year"] if r["impact"] == "GWP")
    assert row["emissions"] == pytest.approx(470.0)
    assert row["cap"] == pytest.approx(300.0)
    assert row["over"] == pytest.approx(170.0)
    assert base["compliant"] is False


def test_uncertainty_ranges() -> None:
    """Monte-Carlo over factor uncertainty reports per-impact ranges (median ≈ point)."""
    res = SimulationBackend().run(
        _gwp_model(),
        {**_SCENARIO, "simulate": {"uncertainty": {"sigma": 0.2, "n": 3000, "seed": 1}}},
    )
    unc = {d["impact"]: d for d in res["outputs"]["lca"]["uncertainty"]}
    co2 = unc["CO2"]
    assert co2["p5"] < co2["p50"] < co2["p95"]  # a genuine spread
    assert co2["p50"] == pytest.approx(200.0, rel=0.1)  # single lognormal factor ⇒ median ≈ point
    assert co2["std"] > 0
    assert "GWP" in unc  # the characterised category gets a distribution too
