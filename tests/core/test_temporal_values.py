"""Year-varying (temporal) model values.

Every priced or physical coefficient a user can set as a scalar can also be given
a per-year trajectory. These tests cover the gaps that were previously scalar
only: technology I/O coefficients (intensity / yield / emission factor),
transition CAPEX, facility fixed O&M, and market volume caps. (The cost
trajectories already covered elsewhere — capex/opex/renewal, prices, carbon
intensity, demand, caps — are exercised by their own suites.)
"""

from __future__ import annotations

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

YEARS = [2025, 2030]
SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict, sc: ScenarioConfig = SC) -> dict:
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _consumed(res: dict, commodity: str) -> dict[int, float]:
    return {
        r["period"]: r["consumed"]
        for r in res["summary"]["commodity"]
        if r["commodity"] == commodity
    }


def test_input_intensity_can_decline_over_the_horizon() -> None:
    # `fuel` use per unit `widget` falls 2 → 1 across the horizon (efficiency).
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [
            {"commodity_id": "fuel", "kind": "energy", "unit": "MWh", "price": 1.0},
            {"commodity_id": "widget", "kind": "product", "unit": "t"},
        ],
        "impacts": [],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1000}
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "io_t": [
            {
                "technology_id": "T",
                "target": "fuel",
                "role": "input",
                "year": 2025,
                "coefficient": 2,
            },
            {
                "technology_id": "T",
                "target": "fuel",
                "role": "input",
                "year": 2030,
                "coefficient": 1,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    fuel = _consumed(res, "fuel")
    assert fuel[2025] == pytest.approx(200.0)  # 2 · 100
    assert fuel[2030] == pytest.approx(100.0)  # 1 · 100
    # Objective is the fuel bill only (undiscounted): 200·$1 + 100·$1.
    assert res["objective"] == pytest.approx(300.0, rel=1e-6)


def test_emission_factor_can_decline_over_the_horizon() -> None:
    # A process's direct CO2 per unit throughput falls 1.0 → 0.2.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2e"}],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        # Capacity == demand pins throughput to 100 (production is otherwise
        # cost-free, so the emission count would be indeterminate).
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
            },
        ],
        "io_t": [
            {
                "technology_id": "T",
                "target": "CO2",
                "role": "impact",
                "year": 2025,
                "coefficient": 1.0,
            },
            {
                "technology_id": "T",
                "target": "CO2",
                "role": "impact",
                "year": 2030,
                "coefficient": 0.2,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    co2 = {s["period"]: s["total"] for s in res["summary"]["impacts"] if s["impact"] == "CO2"}
    assert co2[2025] == pytest.approx(100.0)  # 1.0 · 100
    assert co2[2030] == pytest.approx(20.0)  # 0.2 · 100


def _transition_wb(with_temporal: bool) -> dict:
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [
            {"technology_id": "B", "actions": "continue,replace", "phase_out_year": 2025},
            {"technology_id": "G", "actions": "continue"},
        ],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "B", "capacity": 100}
        ],
        "io": [
            {
                "technology_id": "B",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
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
                "capex_per_capacity": 50,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    if with_temporal:
        wb["transitions_t"] = [
            {"from_technology": "B", "to_technology": "G", "year": 2025, "capex_per_capacity": 50},
            {"from_technology": "B", "to_technology": "G", "year": 2030, "capex_per_capacity": 5},
        ]
    return wb


def test_transition_capex_can_be_year_varying() -> None:
    # B is phased out after 2025, so P must switch to G in 2030 → exactly one
    # replacement, charged at the 2030 capex. The temporal table (5/cap) overrides
    # the scalar (50/cap): 5·100 = 500 vs 50·100 = 5000.
    temporal = _solve(_transition_wb(with_temporal=True))
    scalar = _solve(_transition_wb(with_temporal=False))
    assert temporal["status"] == scalar["status"] == "optimal"
    assert {(t["to_technology"], t["period"]) for t in temporal["outputs"]["transitions"]} == {
        ("G", 2030)
    }
    assert temporal["objective"] == pytest.approx(500.0, rel=1e-6)
    assert scalar["objective"] == pytest.approx(5000.0, rel=1e-6)


def _fixed_opex_wb(with_temporal: bool) -> dict:
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        "processes": [
            {
                "process_id": "P",
                "company": "C",
                "baseline_technology": "T",
                "capacity": 100,
                "fixed_opex": 10,
            },
        ],
        "io": [
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    if with_temporal:
        wb["processes_t__fixed_opex"] = [{"year": 2025, "P": 10}, {"year": 2030, "P": 20}]
    return wb


def test_fixed_opex_can_be_year_varying() -> None:
    temporal = _solve(_fixed_opex_wb(with_temporal=True))
    scalar = _solve(_fixed_opex_wb(with_temporal=False))
    assert temporal["objective"] == pytest.approx(30.0, rel=1e-6)  # 10 + 20
    assert scalar["objective"] == pytest.approx(20.0, rel=1e-6)  # 10 + 10


def test_market_buy_volume_cap_can_be_year_varying() -> None:
    # `mid` is supplied only by market M; its purchase cap falls 100 → 40, so in
    # 2030 only 40 widgets can be made (60 short of the 100 demand).
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [
            {"commodity_id": "mid", "kind": "material", "unit": "t"},
            {"commodity_id": "widget", "kind": "product", "unit": "t"},
        ],
        "impacts": [],
        "technologies": [{"technology_id": "T", "actions": "continue"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1000}
        ],
        "io": [
            {"technology_id": "T", "target": "mid", "role": "input", "coefficient": 1},
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "markets": [{"market_id": "M", "target": "mid", "target_kind": "commodity", "price": 1}],
        "markets_t__max_buy": [{"year": 2025, "M": 100}, {"year": 2030, "M": 40}],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    buy = {
        r["by_period"][i]["period"]: r["by_period"][i]["buy"]
        for r in res["outputs"]["markets"]
        if r["market"] == "M"
        for i in range(len(r["by_period"]))
    }
    assert buy[2025] == pytest.approx(100.0, rel=1e-6)
    assert buy[2030] == pytest.approx(40.0, rel=1e-6)
    slack = {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}
    assert slack.get("C|widget|2030") == pytest.approx(60.0, rel=1e-6)
