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
        "levers": [{"lever_id": "HP", "type": "emission_reduction", "target": "CO2"}],
        "lever_blocks": [{"lever_id": "HP", "block": 0, "reduction": 0.1}],
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


def test_toggle_lever_off_then_on() -> None:
    base = _model()
    stripped = {k: v for k, v in base.items() if k not in ("levers", "lever_blocks")}

    # Off (already absent): stays absent.
    off = apply_overrides(stripped, [{"op": "toggle_lever", "lever": "HP", "on": False}])
    assert off["levers"] == []

    # On: re-introduced from the full model passed as `source`.
    on = apply_overrides(stripped, [{"op": "toggle_lever", "lever": "HP", "on": True}], source=base)
    assert [r["lever_id"] for r in on["levers"]] == ["HP"]
    assert [r["lever_id"] for r in on["lever_blocks"]] == ["HP"]


def test_unknown_op_raises() -> None:
    with pytest.raises(OverrideError, match="unknown override op"):
        apply_overrides(_model(), [{"op": "frobnicate"}])


# ── Value edits (Stage 2): tech cost, I/O coefficient, stream cap ──────────────


def _value_model() -> dict:
    return {
        "commodities": [{"commodity_id": "ore", "price": 10, "max_purchase": 1000}],
        "technologies": [{"technology_id": "A", "capex": 100, "opex": 5}],
        "io": [
            {"technology_id": "A", "target": "ore", "role": "input", "coefficient": 2.0},
            {"technology_id": "A", "target": "steel", "role": "output", "coefficient": 1.0},
        ],
    }


def test_set_tech_cost_static_and_year() -> None:
    out = apply_overrides(
        _value_model(), [{"op": "set_tech_cost", "technology": "A", "field": "capex", "value": 250}]
    )
    assert out["technologies"][0]["capex"] == 250.0

    out = apply_overrides(
        _value_model(),
        [{"op": "set_tech_cost", "technology": "A", "field": "opex", "value": 9, "year": 2030}],
    )
    assert out["technologies"][0]["opex"] == 5  # static untouched
    assert {"year": 2030, "A": 9.0} in out["technologies_t__opex"]


def test_set_tech_cost_rejects_bad_field() -> None:
    with pytest.raises(OverrideError, match=r"capex|opex"):
        apply_overrides(
            _value_model(),
            [{"op": "set_tech_cost", "technology": "A", "field": "lifespan", "value": 1}],
        )


def test_set_io_coef_static_and_year() -> None:
    out = apply_overrides(
        _value_model(), [{"op": "set_io_coef", "technology": "A", "commodity": "ore", "value": 1.5}]
    )
    ore_in = next(r for r in out["io"] if r["target"] == "ore")
    assert ore_in["coefficient"] == 1.5
    # the steel output row is untouched
    assert next(r for r in out["io"] if r["target"] == "steel")["coefficient"] == 1.0

    out = apply_overrides(
        _value_model(),
        [{"op": "set_io_coef", "technology": "A", "commodity": "ore", "value": 1.2, "year": 2035}],
    )
    assert (
        next(r for r in out["io"] if r["target"] == "ore")["coefficient"] == 2.0
    )  # static untouched
    assert {
        "technology_id": "A",
        "target": "ore",
        "role": "input",
        "year": 2035,
        "coefficient": 1.2,
    } in out["io_t"]


def test_set_io_coef_rejects_missing_row() -> None:
    with pytest.raises(OverrideError, match="io row"):
        apply_overrides(
            _value_model(),
            [{"op": "set_io_coef", "technology": "A", "commodity": "nope", "value": 1}],
        )


def test_set_stream_cap_max_purchase_and_availability() -> None:
    out = apply_overrides(
        _value_model(),
        [{"op": "set_stream_cap", "commodity": "ore", "field": "max_purchase", "value": 50}],
    )
    assert out["commodities"][0]["max_purchase"] == 50.0

    out = apply_overrides(
        _value_model(),
        [
            {
                "op": "set_stream_cap",
                "commodity": "ore",
                "field": "max_purchase",
                "value": 40,
                "year": 2040,
            }
        ],
    )
    assert {"year": 2040, "ore": 40.0} in out["commodities_t__max_purchase"]

    out = apply_overrides(
        _value_model(),
        [{"op": "set_stream_cap", "commodity": "ore", "field": "available_from", "value": 2032}],
    )
    assert out["commodities"][0]["available_from"] == 2032  # int


def test_value_edits_do_not_mutate_input() -> None:
    base = _value_model()
    apply_overrides(
        base, [{"op": "set_tech_cost", "technology": "A", "field": "capex", "value": 999}]
    )
    assert base["technologies"][0]["capex"] == 100  # original untouched
