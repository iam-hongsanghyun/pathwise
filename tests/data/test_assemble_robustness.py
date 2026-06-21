"""Robustness of workbook → :class:`Problem` assembly against messy cell values.

xlsx / sqlite round-trips routinely coerce integers to floats and back to
strings (``"2025.0"``) and leave blank/``NaN`` cells; assembly must tolerate that
rather than crashing on ``int("2025.0")`` or propagating a ``NaN`` coefficient.
"""

from __future__ import annotations

from pathwise.data import ScenarioConfig, assemble_problem


def _sc() -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb(periods: list[dict]) -> dict:
    return {
        "periods": periods,
        "commodities": [{"commodity_id": "p", "kind": "product"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 10}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "p",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
    }


def test_period_year_accepts_float_strings_and_floats() -> None:
    # "2025.0" (xlsx round-trip) and 2030.0 must both parse to integer years.
    prob = assemble_problem(_wb([{"year": "2025.0"}, {"year": 2030.0}]), _sc())
    assert prob.years == [2025, 2030]


def test_blank_year_rows_are_skipped_not_crashing() -> None:
    # A stray blank/None year row must be dropped rather than raise KeyError.
    prob = assemble_problem(_wb([{"year": 2025}, {"year": None}, {"foo": 1}]), _sc())
    assert prob.years == [2025]


def test_nan_string_coefficient_is_treated_as_absent() -> None:
    # A literal "nan" cell must not become a NaN coefficient.
    wb = _wb([{"year": 2025}])
    wb["technologies"] = [{"technology_id": "T", "opex": "nan"}]
    prob = assemble_problem(wb, _sc())
    assert prob.technologies["T"].opex(2025) == 0.0
