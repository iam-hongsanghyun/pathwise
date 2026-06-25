"""The engine privileges no impact id — a model with NO ``CO2`` runs end-to-end.

Two parallel assets feed one demand: dirty (2 SOx/unit, free) and clean
(0.5 SOx/unit, $5/unit). The only impact is ``SOx``. The frontier backend, given
no explicit impact, must default to the model's first impact (SOx, not a hardcoded
CO2); the simulate backend must key its headline on SOx. Guards the de-CO2 work.
"""

from __future__ import annotations

from pathwise.backends.registry import get_backend
from pathwise.data.workbook import default_impact

_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}


def _sox_model() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "feed", "kind": "material", "unit": "t", "price": 1},
            {"commodity_id": "widget", "kind": "product", "unit": "ea"},
        ],
        "impacts": [{"impact_id": "SOx", "unit": "t"}],  # NOTE: no CO2 anywhere
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
            {"technology_id": "Dirty", "target": "SOx", "role": "impact", "coefficient": 2.0},
            {"technology_id": "Clean", "target": "feed", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Clean",
                "target": "widget",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "Clean", "target": "SOx", "role": "impact", "coefficient": 0.5},
        ],
        "demand": [{"company": "co", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }


def test_default_impact_helper_picks_first_declared() -> None:
    assert default_impact(_sox_model()) == "SOx"
    assert default_impact({"impacts": []}) == ""  # no impact → empty, never "CO2"


def test_frontier_defaults_to_models_only_impact() -> None:
    # No frontier.impact given → must default to SOx (the model's first impact).
    fr = get_backend("frontier").run(
        _sox_model(),
        {**_SCENARIO, "frontier": {"from": 50, "to": 200, "step": 50}},
    )
    block = fr["outputs"]["frontier"]
    assert block["impact"] == "SOx"
    pts = [p for p in block["points"] if p.get("status") == "optimal"]
    assert len(pts) >= 2  # a real curve on a non-CO2 impact


def test_simulate_headline_is_the_non_co2_impact() -> None:
    res = get_backend("simulate").run(
        _sox_model(), {**_SCENARIO, "simulate": {"baseline": {"plan": "as-is"}}}
    )
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]
    assert lca["primary_impact"] == "SOx"
    assert any(d["impact"] == "SOx" and d["total"] > 0 for d in lca["by_impact"])
    assert all(d["impact"] != "CO2" for d in lca["by_impact"])  # nothing invented a CO2


def test_carbon_price_override_defaults_to_first_impact() -> None:
    """set_carbon_price with no impact targets the model's impact, not a CO2 literal."""
    from pathwise.backends.overrides import apply_overrides

    wb = apply_overrides(_sox_model(), [{"op": "set_carbon_price", "price": 9.0}])
    prices = {(r["impact_id"]) for r in wb.get("impact_prices", [])}
    assert prices == {"SOx"}
