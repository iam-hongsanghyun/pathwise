"""The :class:`CoefficientConverter` — recipe IO coefficient → the stream's unit.

Covers the two lanes (universal + flow-specific), the project-override
cascade, and the degrade-never-raise contract (the invariance guarantee).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from pathwise.units import CoefficientConverter, _parse_factor_key, get_registry


def _conv(**kw: object) -> CoefficientConverter:
    base = {
        "flow_units": {
            "elec": "GJ",  # energy stream, native GJ
            "gas": "GJ",
            "coal": "GJ",
            "fuel": "kg",  # mass stream, with a density factor
            "steel": "t",
            "krw_priced": "KRW",
        },
        "flow_props": {
            "gas": {"lhv_MJ_per_kg": 45.0},
            "coal": {"lhv_MJ_per_kg": 30.0},
            "fuel": {"density_kg_per_liter": 0.8},
            "steel": {"value_USD_per_t": 1000.0},
        },
        "impact_units": {"CO2": "tCO2e"},
    }
    base.update(kw)  # type: ignore[arg-type]
    return CoefficientConverter(**base)  # type: ignore[arg-type]


# ── invariance: absent unit is a no-op ────────────────────────────────────────


@pytest.mark.parametrize("row_unit", [None, "", "   "])
def test_absent_unit_is_factor_one(row_unit: str | None) -> None:
    c = _conv()
    assert c.to_canonical(2.5, row_unit, "elec", "input") == 2.5
    assert c.issues == []


def test_unit_equal_to_stream_unit_is_unchanged() -> None:
    c = _conv()
    assert c.to_canonical(7.0, "GJ", "elec", "input") == 7.0
    assert c.issues == []


# ── universal lane (same dimension) ───────────────────────────────────────────


def test_universal_mwh_to_gj() -> None:
    c = _conv()
    np.testing.assert_allclose(c.to_canonical(1.0, "MWh", "elec", "input"), 3.6, rtol=1e-9)
    assert c.issues == []


# ── flow-specific lane (cross dimension) ─────────────────────────────────


def test_lhv_bridges_mass_to_energy() -> None:
    c = _conv()
    # 1 t of gas at 45 MJ/kg = 45 GJ; coal at 30 MJ/kg = 30 GJ.
    np.testing.assert_allclose(c.to_canonical(1.0, "t", "gas", "input"), 45.0, rtol=1e-9)
    np.testing.assert_allclose(c.to_canonical(1.0, "t", "coal", "input"), 30.0, rtol=1e-9)


def test_same_measure_differs_by_flow() -> None:
    c = _conv()
    gas = c.to_canonical(1.0, "t", "gas", "input")
    coal = c.to_canonical(1.0, "t", "coal", "input")
    assert gas != coal  # t-gas -> GJ is not t-coal -> GJ


def test_density_bridges_volume_to_mass() -> None:
    c = _conv()
    # 10 L of fuel at 0.8 kg/L = 8 kg (canonical unit of "fuel" is kg).
    np.testing.assert_allclose(c.to_canonical(10.0, "liter", "fuel", "input"), 8.0, rtol=1e-9)


def test_value_bridges_currency_to_mass() -> None:
    c = _conv()
    # 1000 USD of steel at 1000 USD/t = 1 t (the "express in currency" path).
    np.testing.assert_allclose(c.to_canonical(1000.0, "USD", "steel", "input"), 1.0, rtol=1e-9)


# ── project-override cascade (override beats global) ──────────────────────────


def test_project_override_beats_global() -> None:
    glob = _conv()
    over = _conv(unit_overrides={"custom_units": ["KRW = USD / 1000"]})
    # flow priced in KRW; 1 USD authored -> global 1300 KRW, override 1000 KRW.
    np.testing.assert_allclose(
        glob.to_canonical(1.0, "USD", "krw_priced", "input"), 1300.0, rtol=1e-6
    )
    np.testing.assert_allclose(
        over.to_canonical(1.0, "USD", "krw_priced", "input"), 1000.0, rtol=1e-9
    )


def test_override_as_bare_list() -> None:
    over = _conv(unit_overrides=["KRW = USD / 1000"])
    np.testing.assert_allclose(
        over.to_canonical(1.0, "USD", "krw_priced", "input"), 1000.0, rtol=1e-9
    )


# ── degrade-never-raise ───────────────────────────────────────────────────────


def test_cross_dimension_without_factor_degrades() -> None:
    c = _conv(flow_props={})  # gas now has no LHV
    assert c.to_canonical(1.0, "t", "gas", "input") == 1.0  # unchanged
    assert any("no conversion factor" in m for m in c.issues)


def test_unparseable_unit_degrades() -> None:
    c = _conv()
    assert c.to_canonical(1.0, "wibble", "elec", "input") == 1.0
    assert any("unparseable" in m for m in c.issues)


def test_unknown_target_degrades() -> None:
    c = _conv()
    assert c.to_canonical(1.0, "GJ", "nonesuch", "input") == 1.0
    assert any("no canonical unit" in m for m in c.issues)


# ── impacts are universal-only ────────────────────────────────────────────────


def test_impact_same_dimension_converts() -> None:
    c = _conv()
    np.testing.assert_allclose(c.to_canonical(1000.0, "kgCO2e", "CO2", "impact"), 1.0, rtol=1e-9)


def test_impact_cross_dimension_degrades() -> None:
    c = _conv()
    # A mass unit on an emissions impact has no universal path and no factor lane.
    assert c.to_canonical(1.0, "t", "CO2", "impact") == 1.0
    assert any("impact" in m and "across dimensions" in m for m in c.issues)


# ── hardening (from the adversarial pass) ─────────────────────────────────────


@pytest.mark.parametrize("coef", [0.0, -2.0, float("nan"), float("inf")])
def test_pathological_coefficients_never_raise(coef: float) -> None:
    c = _conv()
    out = c.to_canonical(coef, "MWh", "elec", "input")  # MWh -> GJ universal
    if math.isfinite(coef):
        np.testing.assert_allclose(out, coef * 3.6, rtol=1e-9)
    else:
        assert not math.isfinite(out)  # non-finite passes through, never raises


def test_multi_factor_flow_chains_volume_to_energy() -> None:
    # density (kg/L) + LHV (MJ/kg) together bridge volume -> energy for one stream.
    c = CoefficientConverter(
        flow_units={"oil": "GJ"},
        flow_props={"oil": {"density_kg_per_liter": 0.8, "lhv_MJ_per_kg": 45.0}},
    )
    # 1 L = 0.8 kg = 0.8 * 45 = 36 MJ = 0.036 GJ
    np.testing.assert_allclose(c.to_canonical(1.0, "liter", "oil", "input"), 0.036, rtol=1e-9)


def test_issues_are_deduplicated_per_converter() -> None:
    c = CoefficientConverter(flow_units={"x": "GJ"})
    for _ in range(20):
        c.to_canonical(1.0, "t", "x", "input")  # same cross-dim failure each call
    assert len(c.issues) == 1


def test_converter_does_not_pollute_global_registry() -> None:
    CoefficientConverter(
        flow_units={"gas": "GJ"}, flow_props={"gas": {"lhv_MJ_per_kg": 45.0}}
    ).to_canonical(1.0, "t", "gas", "input")
    leaked = [n for n in getattr(get_registry(), "_contexts", {}) if str(n).startswith("cmdty_")]
    assert leaked == []


@pytest.mark.parametrize(
    "key,expect",
    [
        ("lhv_MJ_per_kg", ("MJ", "kg")),
        ("energy_content_GJ_per_t", ("GJ", "t")),
        ("density_kg_per_liter", ("kg", "liter")),
        ("value_USD_per_t", ("USD", "t")),
        ("temperature_C", None),  # not a factor key
        ("value_chain", None),  # not a factor key
        ("lhv_MJ_per_", None),  # empty denominator
    ],
)
def test_parse_factor_key(key: str, expect: tuple[str, str] | None) -> None:
    assert _parse_factor_key(key) == expect
