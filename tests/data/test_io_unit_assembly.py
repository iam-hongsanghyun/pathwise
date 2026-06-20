"""Per-row IO units are converted to the stream's canonical unit at assembly.

PR3 wires :class:`CoefficientConverter` into ``assemble_problem``. The invariance
guarantee: a recipe with NO declared IO unit is converted by a factor of exactly 1,
so existing libraries assemble identically; a declared, differing unit is converted.
"""

from __future__ import annotations

import numpy as np

from pathwise.data import ScenarioConfig, assemble_problem, validate

_SCN = ScenarioConfig.from_dict({})


def _wb(io: list[dict[str, object]], *, props: list[dict[str, object]] | None = None) -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "electricity", "kind": "energy", "unit": "MWh"},
            {"commodity_id": "gas", "kind": "energy", "unit": "GJ"},
            {"commodity_id": "steel", "kind": "product", "unit": "t"},
        ],
        "commodity_properties": props or [],
        "technologies": [{"technology_id": "EAF", "lifespan": 20}],
        "io": io,
        # processes + demand make the workbook pass required-sheet validation, so
        # validate() reaches the io-unit check (it skips deeper checks on a broken wb).
        "processes": [
            {"process_id": "P", "company": "co", "baseline_technology": "EAF", "capacity": 100}
        ],
        "demand": [{"company": "co", "commodity_id": "steel", "year": 2025, "amount": 1}],
    }


def _product(coef: float = 1.0) -> dict[str, object]:
    return {
        "technology_id": "EAF",
        "target": "steel",
        "role": "output",
        "coefficient": coef,
        "is_product": True,
    }


def test_no_declared_unit_is_identity() -> None:
    wb = _wb(
        [
            _product(),
            {"technology_id": "EAF", "target": "electricity", "role": "input", "coefficient": 40.0},
        ]
    )
    t = assemble_problem(wb, _SCN).technologies["EAF"]
    assert t.input_intensity["electricity"] == 40.0  # unchanged — factor 1


def test_same_dimension_converts_to_stream_unit() -> None:
    # 3.6 GJ of electricity authored against the MWh stream -> 1.0 MWh.
    wb = _wb(
        [
            _product(),
            {
                "technology_id": "EAF",
                "target": "electricity",
                "role": "input",
                "coefficient": 3.6,
                "unit": "GJ",
            },
        ]
    )
    t = assemble_problem(wb, _SCN).technologies["EAF"]
    np.testing.assert_allclose(t.input_intensity["electricity"], 1.0, rtol=1e-9)


def test_cross_dimension_converts_via_commodity_lhv() -> None:
    # 2 t of gas at 50 MJ/kg = 100 GJ (the gas stream's canonical unit).
    wb = _wb(
        [
            _product(),
            {
                "technology_id": "EAF",
                "target": "gas",
                "role": "input",
                "coefficient": 2.0,
                "unit": "t",
            },
        ],
        props=[{"commodity_id": "gas", "property": "lhv_MJ_per_kg", "value": 50.0}],
    )
    t = assemble_problem(wb, _SCN).technologies["EAF"]
    np.testing.assert_allclose(t.input_intensity["gas"], 100.0, rtol=1e-9)


def test_io_t_inherits_static_unit() -> None:
    # io_t carries no unit; it inherits the static row's GJ and converts to MWh.
    wb = _wb(
        [
            _product(),
            {
                "technology_id": "EAF",
                "target": "electricity",
                "role": "input",
                "coefficient": 3.6,
                "unit": "GJ",
            },
        ]
    )
    wb["io_t"] = [
        {
            "technology_id": "EAF",
            "target": "electricity",
            "role": "input",
            "year": 2030,
            "coefficient": 7.2,
        }
    ]
    t = assemble_problem(wb, _SCN).technologies["EAF"]
    np.testing.assert_allclose(t.input_intensity_at("electricity", 2030), 2.0, rtol=1e-9)


def test_missing_factor_degrades_and_warns() -> None:
    # gas in tonnes but no LHV: assembly leaves it unchanged, validation warns.
    wb = _wb(
        [
            _product(),
            {
                "technology_id": "EAF",
                "target": "gas",
                "role": "input",
                "coefficient": 2.0,
                "unit": "t",
            },
        ]
    )
    t = assemble_problem(wb, _SCN).technologies["EAF"]
    assert t.input_intensity["gas"] == 2.0  # degraded — left as authored
    report = validate(wb)
    assert any("io unit" in w for w in report.warnings)


def test_project_override_changes_conversion() -> None:
    # A USD-denominated output authored in KRW; a project FX override changes it.
    wb = _wb([_product()])
    wb["commodities"].append({"commodity_id": "cash", "kind": "byproduct", "unit": "USD"})
    wb["io"].append(
        {
            "technology_id": "EAF",
            "target": "cash",
            "role": "output",
            "coefficient": 1300.0,
            "unit": "KRW",
        }
    )
    glob = assemble_problem(wb, _SCN).technologies["EAF"].output_yield["cash"]
    over = (
        assemble_problem(wb, ScenarioConfig.from_dict({"unit_overrides": ["KRW = USD / 1000"]}))
        .technologies["EAF"]
        .output_yield["cash"]
    )
    # 1300 KRW -> USD: global /1300 = 1.0, override /1000 = 1.3.
    np.testing.assert_allclose(glob, 1.0, rtol=1e-6)
    np.testing.assert_allclose(over, 1.3, rtol=1e-9)
