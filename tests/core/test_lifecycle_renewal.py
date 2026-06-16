"""End-of-life renewal and the capex-charge conventions.

A facility whose baseline vintage expires inside the horizon must rebuild
(renew) the technology — paying its renewal cost — to keep operating. The cost
is expensed under the scenario's :class:`CapexConvention` (NPV lump by default,
annuity when opted in). Models that do not declare ``introduced_year`` are
unaffected (covered implicitly by the rest of the suite, which sets no install
dates yet keeps its pinned objectives).
"""

from __future__ import annotations

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.core.entities import CapexConvention
from pathwise.core.problem import Problem
from pathwise.data import ScenarioConfig, assemble_problem

YEARS = [2025, 2030]


def _workbook(lifespan: int) -> dict:
    """One facility making ``widget`` to a fixed demand; only opex + renewal."""
    return {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [
            {
                "technology_id": "T",
                "lifespan": lifespan,
                "actions": "continue,renew",
                "opex": 1.0,
                "renewal": 2.0,
            }
        ],
        "processes": [
            {
                "process_id": "P",
                "company": "C",
                "baseline_technology": "T",
                "capacity": 100,
                "introduced_year": 2010,
            }
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
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }


def _run(lifespan: int, *, convention: str = "npv", renewal_priced: bool = True) -> dict:
    sc = ScenarioConfig.from_dict(
        {
            "economics": {"base_year": 2020, "discount_rate": 0.0, "capex_convention": convention},
            "cost_components": {"renewal": renewal_priced},
        }
    )
    return extract_results(solve(build(assemble_problem(_workbook(lifespan), sc))))


def test_expiring_vintage_forces_and_prices_a_renewal() -> None:
    # Baseline installed 2010, life 15 → expires 2025. In the {2025, 2030}
    # horizon, 2025 (live0=0) can only be covered by a renewal in 2025, which
    # also covers 2030 — so exactly one renewal, uniquely in 2025.
    res = _run(15)
    assert res["status"] == "optimal"
    # opex 100·1·2 = 200; renewal 2/cap · 100 cap = 200 (NPV, undiscounted) → 400.
    assert res["objective"] == pytest.approx(400.0, rel=1e-6)
    renewals = res["outputs"]["renewals"]
    assert renewals == [{"process": "P", "technology": "T", "period": 2025}]


def test_young_vintage_needs_no_renewal() -> None:
    # Life 50 → expires 2075, never inside the horizon: no renewal, opex only.
    res = _run(50)
    assert res["status"] == "optimal"
    assert res["objective"] == pytest.approx(200.0, rel=1e-6)
    assert res["outputs"]["renewals"] == []


def test_renewal_toggle_keeps_the_event_but_drops_its_cost() -> None:
    # Forcing still applies (the vintage expires), but with the renewal cost
    # component off the rebuild is free → opex-only objective.
    res = _run(15, renewal_priced=False)
    assert res["status"] == "optimal"
    assert res["objective"] == pytest.approx(200.0, rel=1e-6)


def test_annuity_charges_less_than_npv_when_horizon_truncates_life() -> None:
    npv = _run(15, convention="npv")
    annuity = _run(15, convention="annuity")
    # Annuity-due of the 2025 renewal over its 15-yr life sees only the periods
    # in [2025, 2040) ∩ {2025, 2030} = two years: CRF_due(0,15)·2 · 200 = (2/15)·200.
    assert annuity["objective"] == pytest.approx(200.0 + (2.0 / 15.0) * 200.0, rel=1e-6)
    assert annuity["objective"] < npv["objective"]


def _bare_problem(years: list[int], rate: float, convention: CapexConvention) -> Problem:
    from pathwise.core.entities import Period

    return Problem(
        periods=[Period(year=y, duration_years=1.0) for y in years],
        processes=[],
        technologies={},
        commodities={},
        impacts={},
        discount_rate=rate,
        base_year=years[0],
        capex_convention=convention,
    )


@pytest.mark.parametrize("rate", [0.0, 0.1])
def test_capex_charge_npv_is_the_discount_factor(rate: float) -> None:
    prob = _bare_problem([2020, 2021, 2022], rate, CapexConvention.NPV)
    for y in prob.years:
        assert prob.capex_charge(y, 10) == pytest.approx(prob.discount_factor(y))


@pytest.mark.parametrize("rate", [0.0, 0.1])
def test_capex_charge_annuity_equals_npv_when_life_fits_horizon(rate: float) -> None:
    # Annual horizon 2020–2024; a 5-yr life fits exactly, so the annuity stream's
    # present value equals the lump (== discount_factor at the event year).
    years = [2020, 2021, 2022, 2023, 2024]
    prob = _bare_problem(years, rate, CapexConvention.ANNUITY)
    assert prob.capex_charge(2020, 5) == pytest.approx(prob.discount_factor(2020))


@pytest.mark.parametrize("rate", [0.0, 0.1])
def test_capex_charge_annuity_undercharges_when_life_exceeds_horizon(rate: float) -> None:
    years = [2020, 2021, 2022, 2023, 2024]
    prob = _bare_problem(years, rate, CapexConvention.ANNUITY)
    # A 10-yr life only half-covered by the 5-yr horizon charges strictly less.
    assert prob.capex_charge(2020, 10) < prob.capex_charge(2020, 5)
