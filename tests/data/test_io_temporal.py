"""P15a: unified `io` table + PyPSA-style wide temporal (static/varying by name)."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem, validate


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _io_wb() -> dict:
    # Single process via the unified `io` table (no process_inputs/outputs).
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 10},
            {"commodity_id": "widget", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {"technology_id": "T", "target": "gas", "role": "input", "coefficient": 2},
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "demand": [{"company": "C", "commodity_id": "widget", "year": 2025, "amount": 50}],
    }


def test_io_table_drives_the_model() -> None:
    res = _solve(_io_wb())
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)  # 50 × 2 gas × $10


def test_io_validation_requires_io_or_legacy() -> None:
    wb = _io_wb()
    del wb["io"]
    report = validate(wb)
    assert not report.ok
    assert any("I/O" in e for e in report.errors)
    assert validate(_io_wb()).ok


def test_wide_temporal_overrides_static_by_name() -> None:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025}})
    wb = {
        "periods": [{"year": 2025}, {"year": 2030}],
        "commodities": [{"commodity_id": "gas", "kind": "energy", "price": 10}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1}
        ],
        "io": [{"technology_id": "T", "target": "gas", "role": "input", "coefficient": 1}],
        "demand": [{"company": "C", "commodity_id": "gas", "year": 2025, "amount": 0}],
        # Wide temporal: columns are commodity names, rows are snapshots (years).
        "commodities_t__price": [
            {"year": 2025, "gas": 12},
            {"year": 2030, "gas": 99},
        ],
    }
    prob = assemble_problem(wb, sc)
    assert prob.commodities["gas"].price(2025) == 12.0  # temporal overrides static 10
    assert prob.commodities["gas"].price(2030) == 99.0


def test_any_attribute_can_be_temporal() -> None:
    # Technology CAPEX varies by year via technologies_t__capex (wide, by name).
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025}})
    wb = {
        "periods": [{"year": 2025}, {"year": 2030}],
        "commodities": [{"commodity_id": "gas", "kind": "energy"}],
        "technologies": [{"technology_id": "T", "capex": 100}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1}
        ],
        "io": [{"technology_id": "T", "target": "gas", "role": "input", "coefficient": 1}],
        "demand": [{"company": "C", "commodity_id": "gas", "year": 2025, "amount": 0}],
        "technologies_t__capex": [
            {"year": 2025, "T": 100},
            {"year": 2030, "T": 250},
        ],
    }
    prob = assemble_problem(wb, sc)
    assert prob.technologies["T"].capex(2025) == 100.0
    assert prob.technologies["T"].capex(2030) == 250.0  # temporal override


def test_named_demand_component_with_temporal() -> None:
    # Demand as a named component (demand_id + wide demand_t__amount), not long-format.
    wb = _io_wb()
    wb["demand"] = [{"demand_id": "D1", "company": "C", "commodity_id": "widget"}]
    wb["demand_t__amount"] = [{"year": 2025, "D1": 50}]
    res = _solve(wb)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)  # same as legacy demand 50
    assert res["outputs"]["demand_slack"] == []
