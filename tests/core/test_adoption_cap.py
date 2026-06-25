"""Fleet-wide technology adoption cap: at most N processes run a technology/year.

(Used by the steel port, where the source model caps how many facilities may run
each route — e.g. ≤3 EAF, ≤13 H2-DRI — in any year.)
"""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

YEARS = [2025, 2030]
SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _wb(cap: int | None) -> dict:
    # Two facilities on a dirty baseline B that can switch (from 2030) to a clean,
    # cheap alternative G. A high carbon price makes both want G; a cap of 1 forces
    # one to stay on B. (The first period is locked to the baseline, so the switch
    # can only happen in 2030 — hence two periods.)
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "flows": [{"flow_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2e"}],
        "technologies": [
            {"technology_id": "B", "actions": "continue,replace"},
            {"technology_id": "G", "actions": "continue"},
        ],
        "processes": [
            {"process_id": "P1", "company": "C", "baseline_technology": "B", "capacity": 100},
            {"process_id": "P2", "company": "C", "baseline_technology": "B", "capacity": 100},
        ],
        "io": [
            {
                "technology_id": "B",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "B", "target": "CO2", "role": "impact", "coefficient": 1.0},
            {
                "technology_id": "G",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "transitions": [
            {
                "from_technology": "B",
                "to_technology": "G",
                "action": "replace",
                "capex_per_capacity": 1,
            },
        ],
        "impact_prices": [{"impact_id": "CO2", "year": y, "price": 1000} for y in YEARS],
        # 200 total forces BOTH facilities (capacity 100 each) to run every year.
        "demand": [{"company": "C", "flow_id": "widget", "year": y, "amount": 200} for y in YEARS],
    }
    if cap is not None:
        wb["technology_caps"] = [{"technology_id": "G", "max_count": cap}]
    return wb


def _on_G_in(res: dict, year: int) -> int:
    return sum(
        1 for t in res["outputs"]["technology"] if t["technology"] == "G" and t["period"] == year
    )


def test_without_cap_both_facilities_adopt_the_clean_route() -> None:
    res = extract_results(solve(build(assemble_problem(_wb(None), SC))))
    assert res["status"] == "optimal"
    assert _on_G_in(res, 2030) == 2


def test_adoption_cap_limits_simultaneous_adopters() -> None:
    res = extract_results(solve(build(assemble_problem(_wb(1), SC))))
    assert res["status"] == "optimal"
    assert _on_G_in(res, 2030) == 1  # cap of 1 → only one facility may run G
