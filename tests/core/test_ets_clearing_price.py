"""Cross-sector cap-and-trade: a shared CO2 cap clears at the marginal abater.

Worked example for the "competition between sectors" claim. Two sectors share
ONE CO2 cap (scope ``all``). Each makes its own product and can produce it dirty
(emits 1 t CO2/unit) or clean (0 emissions) at a higher cost — so each has a
constant marginal abatement cost:

    power:  clean opex 30 − dirty opex 10  →  20 / t CO2   (cheap)
    steel:  clean opex 60 − dirty opex 10  →  50 / t CO2   (dear)

Under a binding shared cap the planner abates cheapest-first, so the sectors
"compete" for the scarce allowance. The **clearing carbon price** is the cost of
the marginal tonne — recovered here as the slope of total cost vs the cap
(a finite difference, the same primal route ``network.marginal_price`` and the
frontier backend use; LP-dual extraction is a later increment). It equals the
marginal abater's cost: 20 when only power abates, 50 once power is exhausted and
steel sets the margin.
"""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

_SC = ScenarioConfig.from_dict(
    {"economics": {"base_year": 2025, "discount_rate": 0.0}, "optimisation_scope": "system"}
)


def _wb(cap: float | None) -> dict:
    caps = (
        [{"company": "all", "impact_id": "CO2", "year": 2025, "limit": cap, "soft": 0}]
        if cap is not None
        else []
    )
    return {
        "periods": [{"year": 2025}],
        "flows": [
            {"flow_id": "steel", "kind": "product", "unit": "t"},
            {"flow_id": "power", "kind": "product", "unit": "MWh"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}],
        # Dirty/clean variants of each sector's product (clean costs more, emits nothing).
        "technologies": [
            {"technology_id": "steel_dirty", "opex": 10},
            {"technology_id": "steel_clean", "opex": 60},
            {"technology_id": "power_dirty", "opex": 10},
            {"technology_id": "power_clean", "opex": 30},
        ],
        "io": [
            {
                "technology_id": "steel_dirty",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "steel_dirty", "target": "CO2", "role": "impact", "coefficient": 1},
            {
                "technology_id": "steel_clean",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {
                "technology_id": "power_dirty",
                "target": "power",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "power_dirty", "target": "CO2", "role": "impact", "coefficient": 1},
            {
                "technology_id": "power_clean",
                "target": "power",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        # Two processes per sector (a dirty and a clean line) so demand splits continuously.
        "processes": [
            {
                "process_id": "steel_d",
                "company": "steel",
                "baseline_technology": "steel_dirty",
                "capacity": 100,
            },
            {
                "process_id": "steel_c",
                "company": "steel",
                "baseline_technology": "steel_clean",
                "capacity": 100,
            },
            {
                "process_id": "power_d",
                "company": "power",
                "baseline_technology": "power_dirty",
                "capacity": 100,
            },
            {
                "process_id": "power_c",
                "company": "power",
                "baseline_technology": "power_clean",
                "capacity": 100,
            },
        ],
        "impact_caps": caps,
        "demand": [
            {"company": "steel", "flow_id": "steel", "year": 2025, "amount": 100},
            {"company": "power", "flow_id": "power", "year": 2025, "amount": 100},
        ],
    }


def _solve(cap: float | None) -> dict:
    return extract_results(solve(build(assemble_problem(_wb(cap), _SC)))).copy()


def _co2(res: dict) -> float:
    return sum(float(r["total"]) for r in res["summary"]["impacts"] if str(r["impact"]) == "CO2")


def _by_tech(res: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in res["outputs"].get("throughput", []):
        out[str(r["technology"])] = out.get(str(r["technology"]), 0.0) + float(r["value"])
    return out


def _clearing_price(cap: float) -> float:
    """Slope of total cost vs the cap at ``cap`` — the marginal tonne's cost."""
    return _solve(cap - 1.0)["objective"] - _solve(cap)["objective"]


def test_baseline_runs_all_dirty() -> None:
    res = _solve(None)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)  # 200 units × 10
    np.testing.assert_allclose(_co2(res), 200.0, rtol=1e-6)


def test_loose_cap_clears_at_cheap_sector() -> None:
    # Cap 150 ⇒ abate 50 t; only power (the cheap abater) moves, steel stays dirty.
    res = _solve(150.0)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_co2(res), 150.0, rtol=1e-6)  # cap binds
    tech = _by_tech(res)
    assert tech.get("steel_clean", 0.0) < 1e-6  # steel does NOT abate yet
    assert tech.get("power_clean", 0.0) > 1e-6  # power does
    np.testing.assert_allclose(_clearing_price(150.0), 20.0, rtol=1e-6)  # power's marginal cost


def test_tight_cap_makes_sectors_compete_and_steel_sets_the_price() -> None:
    # Cap 50 ⇒ abate 150 t; power abates to its limit (cheap), steel abates the rest
    # (dear) — both sectors compete and steel, the marginal abater, sets the price.
    res = _solve(50.0)
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_co2(res), 50.0, rtol=1e-6)
    tech = _by_tech(res)
    np.testing.assert_allclose(tech.get("power_clean", 0.0), 100.0, rtol=1e-6)  # power fully clean
    np.testing.assert_allclose(tech.get("steel_clean", 0.0), 50.0, rtol=1e-6)  # steel abates 50
    np.testing.assert_allclose(_clearing_price(50.0), 50.0, rtol=1e-6)  # steel's marginal cost
