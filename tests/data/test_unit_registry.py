"""The project unit registry (`units` sheet) drives conversion at assembly.

Each base-anchored row becomes a pint `unit_overrides` definition, so a project
can introduce or re-rate a unit (e.g. a custom `kt = 1000 t`, or `KRW = 1/1300
USD`) and coefficients authored in that unit convert correctly. Base rows are
skipped (defined globally); scenario overrides still win.
"""

from __future__ import annotations

from typing import Any

from pathwise.data import ScenarioConfig, assemble_problem
from pathwise.data.assemble import _model_unit_overrides


def test_unit_rows_become_base_anchored_definitions() -> None:
    wb = {
        "units": [
            {"unit": "t", "dimension": "mass", "factor_to_base": 1},  # base → skipped
            {"unit": "kt", "dimension": "mass", "factor_to_base": 1000},
            {"unit": "KRW", "dimension": "currency", "factor_to_base": 1 / 1300},
            {"unit": "", "dimension": "mass", "factor_to_base": 5},  # junk → skipped
        ]
    }
    defs = _model_unit_overrides(wb, {})
    assert "kt = 1000 * t" in defs
    assert any(d.startswith("KRW = ") and d.endswith("* USD") for d in defs)
    assert not any(d.startswith("t = ") for d in defs)  # base skipped


def test_scenario_overrides_appended_after_model() -> None:
    defs = _model_unit_overrides(
        {"units": [{"unit": "kt", "dimension": "mass", "factor_to_base": 1000}]},
        ["KRW = USD / 1200"],
    )
    assert defs == ["kt = 1000 * t", "KRW = USD / 1200"]


def test_custom_unit_coefficient_converts() -> None:
    """A coefficient authored in a registry-defined custom unit is converted."""
    wb: dict[str, Any] = {
        "units": [{"unit": "kt", "dimension": "mass", "factor_to_base": 1000}],
        "periods": [{"year": 2025}],
        "commodities": [{"commodity_id": "p", "kind": "product", "unit": "t"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1}
        ],
        # 2 kt/throughput of product p → canonical 2000 t/throughput.
        "io": [
            {"technology_id": "T", "target": "p", "role": "output", "coefficient": 2, "unit": "kt"}
        ],
    }
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    prob = assemble_problem(wb, sc)
    assert prob.technologies["T"].output_yield["p"] == 2000.0
