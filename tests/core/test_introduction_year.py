"""`introduction_year`: a transition target is not adoptable before it."""

from __future__ import annotations

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _wb(intro_year: int | None) -> dict:
    """One facility on expensive OLD; cheap NEW available from ``intro_year``.

    Switching saves 90/unit of opex with zero switch cost, so the optimiser
    adopts NEW in the first year it is allowed to.
    """
    tech_new: dict = {"technology_id": "NEW", "opex": 10}
    if intro_year is not None:
        tech_new["introduction_year"] = intro_year
    return {
        "periods": [{"year": 2025}, {"year": 2030}, {"year": 2035}],
        "commodities": [{"commodity_id": "widget", "kind": "product"}],
        "technologies": [{"technology_id": "OLD", "opex": 100}, tech_new],
        "io": [
            {
                "technology_id": "OLD",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {
                "technology_id": "NEW",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "OLD", "capacity": 100}
        ],
        "transitions": [{"from_technology": "OLD", "to_technology": "NEW", "action": "replace"}],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 50}
            for y in (2025, 2030, 2035)
        ],
        "impacts": [],
        "markets": [],
        "storage": [],
    }


def _active_by_year(wb: dict) -> dict[int, str]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    res = extract_results(solve(build(assemble_problem(wb, sc))))
    assert res["status"] == "optimal"
    return {r["period"]: r["technology"] for r in res["outputs"]["technology"]}


def test_unrestricted_target_adopted_immediately_after_t0() -> None:
    # The baseline is locked in the first period; the cheap target takes over
    # from the second period (no introduction restriction).
    active = _active_by_year(_wb(None))
    assert active[2025] == "OLD"
    assert active[2030] == "NEW"


def test_target_waits_for_its_introduction_year() -> None:
    active = _active_by_year(_wb(2035))
    assert active[2025] == "OLD"
    assert active[2030] == "OLD", "NEW must not be adoptable before 2035"
    assert active[2035] == "NEW"


def test_baseline_with_future_introduction_year_still_runs() -> None:
    # The installed baseline is exempt: it already exists even if the technology
    # only becomes commercially available later.
    wb = _wb(None)
    wb["technologies"][0]["introduction_year"] = 2030  # OLD, the baseline
    active = _active_by_year(wb)
    assert active[2025] == "OLD"
