"""Typed workbook-edit applier used by the ``simulate`` backend's variants."""

from __future__ import annotations

import pytest

from pathwise.backends.overrides import OverrideError, apply_overrides


def _model() -> dict:
    return {
        "commodities": [{"commodity_id": "ore", "price": 10}],
        "technologies": [{"technology_id": "A"}, {"technology_id": "B"}],
        "machines": [{"machine_id": "m1", "baseline_technology": "A"}],
        "impact_prices": [{"impact_id": "CO2", "year": 2025, "price": 0}],
        "measures": [{"measure_id": "HP", "type": "emission_reduction", "target": "CO2"}],
        "measure_blocks": [{"measure_id": "HP", "block": 0, "reduction": 0.1}],
    }


def test_apply_overrides_does_not_mutate_input() -> None:
    base = _model()
    apply_overrides(base, [{"op": "set_machine_tech", "machine": "m1", "technology": "B"}])
    assert base["machines"][0]["baseline_technology"] == "A"  # original untouched


def test_set_machine_tech() -> None:
    out = apply_overrides(
        _model(), [{"op": "set_machine_tech", "machine": "m1", "technology": "B"}]
    )
    assert out["machines"][0]["baseline_technology"] == "B"


def test_set_machine_tech_rejects_unknown() -> None:
    with pytest.raises(OverrideError, match="technology"):
        apply_overrides(_model(), [{"op": "set_machine_tech", "machine": "m1", "technology": "Z"}])
    with pytest.raises(OverrideError, match="machine"):
        apply_overrides(_model(), [{"op": "set_machine_tech", "machine": "mX", "technology": "B"}])


def test_set_price_static_and_year() -> None:
    out = apply_overrides(_model(), [{"op": "set_price", "commodity": "ore", "price": 2}])
    assert out["commodities"][0]["price"] == 2.0

    out = apply_overrides(
        _model(), [{"op": "set_price", "commodity": "ore", "price": 7, "year": 2030}]
    )
    assert out["commodities"][0]["price"] == 10  # static price untouched
    assert {"year": 2030, "ore": 7.0} in out["commodities_t__price"]


def test_set_carbon_price_static_fills_every_year() -> None:
    base = _model()
    base["impact_prices"] = [
        {"impact_id": "CO2", "year": 2025, "price": 0},
        {"impact_id": "CO2", "year": 2030, "price": 0},
    ]
    out = apply_overrides(base, [{"op": "set_carbon_price", "impact": "CO2", "price": 50}])
    prices = {(r["impact_id"], r["year"]): r["price"] for r in out["impact_prices"]}
    assert prices == {("CO2", 2025): 50.0, ("CO2", 2030): 50.0}


def test_toggle_measure_off_then_on() -> None:
    base = _model()
    stripped = {k: v for k, v in base.items() if k not in ("measures", "measure_blocks")}

    # Off (already absent): stays absent.
    off = apply_overrides(stripped, [{"op": "toggle_measure", "measure": "HP", "on": False}])
    assert off["measures"] == []

    # On: re-introduced from the full model passed as `source`.
    on = apply_overrides(
        stripped, [{"op": "toggle_measure", "measure": "HP", "on": True}], source=base
    )
    assert [r["measure_id"] for r in on["measures"]] == ["HP"]
    assert [r["measure_id"] for r in on["measure_blocks"]] == ["HP"]


def test_unknown_op_raises() -> None:
    with pytest.raises(OverrideError, match="unknown override op"):
        apply_overrides(_model(), [{"op": "frobnicate"}])
