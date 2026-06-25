"""Temporal carbon intensity: a flow's impact factor may vary by year.

``flow_impacts`` is the static factor; an optional long-format
``flow_impacts_t`` (flow_id, impact_id, year, factor) overrides it per
year (interpolated between points, flat-held beyond). This is what lets an
upstream network stage's pathway — or a greening grid — change a downstream
input's carbon intensity over time.
"""

from __future__ import annotations

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "flows": [
            {"flow_id": "fuel", "kind": "energy", "price": 1.0},
            {"flow_id": "prod", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "flow_impacts": [{"flow_id": "fuel", "impact_id": "CO2", "factor": 1.0}],
        # Year-varying override: 1.0 tCO2/unit in 2025 rising to 3.0 in 2030.
        "flow_impacts_t": [
            {"flow_id": "fuel", "impact_id": "CO2", "year": 2025, "factor": 1.0},
            {"flow_id": "fuel", "impact_id": "CO2", "year": 2030, "factor": 3.0},
        ],
        "technologies": [{"technology_id": "t"}],
        "io": [
            {"technology_id": "t", "target": "fuel", "role": "input", "coefficient": 2},
            {
                "technology_id": "t",
                "target": "prod",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "t", "capacity": 100}
        ],
        "demand": [
            {"company": "C", "flow_id": "prod", "year": y, "amount": 100} for y in (2025, 2030)
        ],
    }


def test_year_varying_factor_drives_per_year_emissions() -> None:
    res = extract_results(solve(build(assemble_problem(_wb(), SC))))
    assert res["status"] == "optimal"
    co2 = {r["period"]: r["total"] for r in res["summary"]["impacts"] if r["impact"] == "CO2"}
    # fuel use = 2 · 100 = 200/yr; emissions = factor(year) · 200.
    assert co2[2025] == pytest.approx(200.0)  # 1.0 · 200
    assert co2[2030] == pytest.approx(600.0)  # 3.0 · 200


def test_static_factor_is_the_fallback_when_no_year_given() -> None:
    wb = _wb()
    wb.pop("flow_impacts_t")  # only the static 1.0 remains
    res = extract_results(solve(build(assemble_problem(wb, SC))))
    co2 = {r["period"]: r["total"] for r in res["summary"]["impacts"] if r["impact"] == "CO2"}
    assert co2[2025] == pytest.approx(200.0) and co2[2030] == pytest.approx(200.0)
