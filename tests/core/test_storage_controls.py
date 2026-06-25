"""P7: storage arbitrage, failure-rate derate, min production, investment budget."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict, scenario: dict | None = None) -> dict:
    sc = ScenarioConfig.from_dict(
        scenario or {"economics": {"base_year": 2025, "discount_rate": 0.0}}
    )
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _base_wb() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 10},
            {"flow_id": "p", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1000}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "gas", "intensity": 1.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "p", "yield": 1.0, "is_product": True}
        ],
        "flow_prices": [
            {"flow_id": "gas", "year": 2025, "price": 10},
            {"flow_id": "gas", "year": 2030, "price": 100},
        ],
        "demand": [
            {"company": "C", "flow_id": "p", "year": 2025, "amount": 10},
            {"company": "C", "flow_id": "p", "year": 2030, "amount": 10},
        ],
    }


def test_storage_arbitrages_rising_prices() -> None:
    without = _solve(_base_wb())
    # No storage: 10 gas @ $10 + 10 gas @ $100 = $1100.
    np.testing.assert_allclose(without["objective"], 1100.0, rtol=1e-6)

    wb = _base_wb()
    wb["storage"] = [
        {
            "storage_id": "S",
            "flow_id": "gas",
            "company": "all",
            "max_capacity": 100,
            "capex_per_capacity": 1.0,
            "charge_efficiency": 1.0,
            "discharge_efficiency": 1.0,
        }
    ]
    withs = _solve(wb)
    # Buy 20 @ $10 (use 10, store 10), release 10 in 2030 → $200 + $10 capex = $210.
    np.testing.assert_allclose(withs["objective"], 210.0, rtol=1e-6)
    assert withs["objective"] < without["objective"]
    store = withs["outputs"]["storage"]
    assert store and store[0]["capacity"] > 0


def _energy_storage_wb(
    *, energy_price: float, energy_per_throughput: float, elec_cap: float | None = None
) -> dict:
    """The arbitrage base + a store that burns a priced ``elec`` flow per throughput."""
    wb = _base_wb()
    elec: dict = {"flow_id": "elec", "kind": "energy", "price": energy_price}
    if elec_cap is not None:
        elec["max_purchase"] = elec_cap
    wb["flows"] = [*wb["flows"], elec]
    wb["storage"] = [
        {
            "storage_id": "S",
            "flow_id": "gas",
            "company": "all",
            "max_capacity": 100,
            "capex_per_capacity": 1.0,
            "charge_efficiency": 1.0,
            "discharge_efficiency": 1.0,
            "energy_flow": "elec",
            "energy_per_throughput": energy_per_throughput,
        }
    ]
    return wb


def test_storage_running_energy_adds_cost() -> None:
    # Base storage objective is 210. Throughput = charge 10 + discharge 10 = 20; at
    # elec $1/unit that adds $20 ⇒ 230, and the store still beats the $1100 no-store cost.
    res = _solve(_energy_storage_wb(energy_price=1.0, energy_per_throughput=1.0))
    np.testing.assert_allclose(res["objective"], 230.0, rtol=1e-6)
    assert res["outputs"]["storage"][0]["capacity"] > 0


def test_expensive_running_energy_kills_storage_arbitrage() -> None:
    # 20 throughput at $100 running-energy = $2000 makes the store (210 + 2000) dearer
    # than just buying the dear gas ($1100) ⇒ the optimiser abandons the store.
    res = _solve(_energy_storage_wb(energy_price=100.0, energy_per_throughput=1.0))
    np.testing.assert_allclose(res["objective"], 1100.0, rtol=1e-6)
    store = res["outputs"]["storage"]
    assert not store or store[0]["capacity"] <= 1e-6


def test_storage_energy_counts_against_a_supply_cap() -> None:
    # The store's running energy (charge+discharge) must fit under elec's per-year cap,
    # so a 5/yr cap throttles cycling to ≤5 units — less than the uncapped 10.
    free = _solve(_energy_storage_wb(energy_price=1.0, energy_per_throughput=1.0))
    capped = _solve(_energy_storage_wb(energy_price=1.0, energy_per_throughput=1.0, elec_cap=5.0))
    assert capped["status"] == "optimal"
    fcap = free["outputs"]["storage"][0]["capacity"]
    cstore = capped["outputs"]["storage"]
    ccap = cstore[0]["capacity"] if cstore else 0.0
    assert ccap <= 5.0 + 1e-6
    assert ccap < fcap


def test_zero_discharge_efficiency_does_not_crash_the_build() -> None:
    # A 0 in the per-year discharge-efficiency sheet used to reach 1/0 in the
    # storage balance and crash the build; it must be clamped, not divided by.
    wb = _base_wb()
    wb["storage"] = [
        {
            "storage_id": "S",
            "flow_id": "gas",
            "company": "all",
            "max_capacity": 100,
            "charge_efficiency": 1.0,
            "discharge_efficiency": 1.0,
        }
    ]
    wb["storage_t__discharge_efficiency"] = [{"year": 2025, "S": 0.0}, {"year": 2030, "S": 0.0}]
    res = _solve(wb)  # must not raise ZeroDivisionError
    assert res["status"] == "optimal"


def test_failure_rate_derates_capacity() -> None:
    wb = _base_wb()
    del wb["flow_prices"]  # flat price
    wb["processes"][0]["capacity"] = 10
    wb["demand"] = [{"company": "C", "flow_id": "p", "year": 2025, "amount": 10}]
    wb["periods"] = [{"year": 2025, "duration_years": 1}]
    ok = _solve(wb)
    assert ok["outputs"]["demand_slack"] == []  # cap 10 meets demand 10

    wb["processes"][0]["failure_rate"] = 0.2  # available = 8 < demand 10
    short = _solve(wb)
    assert short["outputs"]["demand_slack"]  # 2 units unmet


def test_min_production_forces_output() -> None:
    wb = _base_wb()
    del wb["flow_prices"]
    wb["periods"] = [{"year": 2025, "duration_years": 1}]
    wb["demand"] = [{"company": "C", "flow_id": "p", "year": 2025, "amount": 0}]
    no_floor = _solve(wb)
    assert sum(t["value"] for t in no_floor["outputs"]["throughput"]) < 1e-6  # nothing forced

    wb["min_production"] = [{"company": "C", "flow_id": "p", "year": 2025, "amount": 50}]
    floored = _solve(wb)
    assert sum(t["value"] for t in floored["outputs"]["throughput"]) >= 50 - 1e-6


def _carbon_switch_wb() -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}, {"year": 2030, "duration_years": 1}],
        "flows": [
            {"flow_id": "fuel", "kind": "energy", "price": 1},
            {"flow_id": "p", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}],
        "technologies": [{"technology_id": "BASE"}, {"technology_id": "CLEAN"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "BASE", "capacity": 100}
        ],
        "process_inputs": [
            {"technology_id": "BASE", "flow_id": "fuel", "intensity": 1},
            {"technology_id": "CLEAN", "flow_id": "fuel", "intensity": 1},
        ],
        "process_outputs": [
            {"technology_id": "BASE", "flow_id": "p", "yield": 1, "is_product": True},
            {"technology_id": "CLEAN", "flow_id": "p", "yield": 1, "is_product": True},
        ],
        "tech_impacts": [{"technology_id": "BASE", "impact_id": "CO2", "factor": 10}],
        "transitions": [
            {
                "from_technology": "BASE",
                "to_technology": "CLEAN",
                "action": "replace",
                "capex_per_capacity": 1,
                "compatible": True,
            }
        ],
        "impact_prices": [{"impact_id": "CO2", "year": 2030, "price": 1000}],
        "demand": [
            {"company": "C", "flow_id": "p", "year": 2025, "amount": 10},
            {"company": "C", "flow_id": "p", "year": 2030, "amount": 10},
        ],
    }


def test_investment_budget_blocks_profitable_switch() -> None:
    # Carbon price makes switching BASE→CLEAN highly profitable.
    free = _solve(_carbon_switch_wb())
    assert any(t["to_technology"] == "CLEAN" for t in free["outputs"]["transitions"])

    capped = _carbon_switch_wb()
    capped["investment_budget"] = [{"company": "all", "year": 2030, "limit": 0}]
    res = _solve(capped)
    assert not any(t["to_technology"] == "CLEAN" for t in res["outputs"]["transitions"])
