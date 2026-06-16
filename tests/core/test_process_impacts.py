"""Per-facility direct emissions: two facilities on the SAME technology can carry
different real emission intensities (added on top of the technology's own
``direct_impact``). Used by the sector ports where each plant has its own
measured intensity.
"""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb(facility_factor: float | None, by_year: list[dict] | None = None) -> dict:
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            }
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100}
            for y in (2025, 2030)
        ],
    }
    if facility_factor is not None:
        wb["process_impacts"] = [{"process_id": "P", "impact_id": "CO2", "factor": facility_factor}]
    if by_year is not None:
        wb["process_impacts_t"] = by_year
    return wb


def _co2(res: dict, year: int) -> float:
    return next(
        s["total"]
        for s in res["summary"]["impacts"]
        if s["impact"] == "CO2" and s["period"] == year
    )


def test_facility_direct_emission_scales_with_throughput() -> None:
    res = extract_results(solve(build(assemble_problem(_wb(2.0), SC))))
    assert res["status"] == "optimal"
    assert _co2(res, 2025) == 2.0 * 100  # factor × throughput


def test_facility_direct_emission_year_varying() -> None:
    # Grid greening: the facility's CO2 intensity falls from 2.0 (2025) to 1.0 (2030).
    by_year = [
        {"process_id": "P", "impact_id": "CO2", "year": 2025, "factor": 2.0},
        {"process_id": "P", "impact_id": "CO2", "year": 2030, "factor": 1.0},
    ]
    res = extract_results(solve(build(assemble_problem(_wb(None, by_year), SC))))
    assert res["status"] == "optimal"
    assert _co2(res, 2025) == 200.0
    assert _co2(res, 2030) == 100.0
