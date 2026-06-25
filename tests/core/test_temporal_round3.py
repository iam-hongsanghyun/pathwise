"""Year-varying coverage for the remaining per-period numbers.

Completes the "every number can be a scalar OR a per-year trajectory" guarantee:
technology must-run floor, blend/slate share bounds, facility outage rate, edge
capacity, storage costs/efficiencies, and lever reduction.
"""

from __future__ import annotations

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

YEARS = [2025, 2030]
SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})


def _solve(wb: dict) -> dict:
    return extract_results(solve(build(assemble_problem(wb, SC))))


def _throughput(res: dict) -> dict[int, float]:
    return {r["period"]: r["value"] for r in res["outputs"]["throughput"]}


def _consumed(res: dict, commodity: str) -> dict[int, float]:
    return {
        r["period"]: r["consumed"]
        for r in res["summary"]["commodity"]
        if r["commodity"] == commodity
    }


def _slack(res: dict) -> dict[str, float]:
    return {s["key"]: s["value"] for s in res["outputs"]["demand_slack"]}


def test_min_capacity_factor_can_be_year_varying() -> None:
    # Must-run floor rises 0 → 0.9: in 2030 the plant must run ≥ 90 even though
    # only 10 is demanded; in 2025 it just meets demand.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [],
        "technologies": [{"technology_id": "T", "actions": "continue", "opex": 1.0}],
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
        "technologies_t__min_capacity_factor": [{"year": 2025, "T": 0.0}, {"year": 2030, "T": 0.9}],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 10} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    tp = _throughput(res)
    assert tp[2025] == pytest.approx(10.0, rel=1e-6)
    assert tp[2030] == pytest.approx(90.0, rel=1e-6)


def test_blend_share_bounds_can_be_year_varying() -> None:
    # A coal/gas fuel blend; coal is cheap but its max share falls 1.0 → 0.0, so
    # by 2030 the mix is forced fully onto (pricey) gas.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [
            {"commodity_id": "coal", "kind": "energy", "unit": "t", "price": 1.0},
            {"commodity_id": "gas", "kind": "energy", "unit": "t", "price": 5.0},
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
                "target": "coal",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
            },
            {
                "technology_id": "T",
                "target": "gas",
                "role": "input",
                "coefficient": 1,
                "group": "fuel",
            },
            {
                "technology_id": "T",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        # coal max share declines to zero by 2030
        "io_t": [
            {
                "technology_id": "T",
                "target": "coal",
                "role": "input",
                "year": 2025,
                "share_max": 1.0,
            },
            {
                "technology_id": "T",
                "target": "coal",
                "role": "input",
                "year": 2030,
                "share_max": 0.0,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    coal, gas = _consumed(res, "coal"), _consumed(res, "gas")
    # Fuel requirement is 2 per widget (coal + gas baseline intensities) × 100.
    assert coal[2025] == pytest.approx(200.0, rel=1e-6)
    assert coal[2030] == pytest.approx(0.0, abs=1e-6)
    assert gas[2030] == pytest.approx(200.0, rel=1e-6)


def test_edge_capacity_can_be_year_varying() -> None:
    # F1 → F2 link for `mid` is capped per year (100 → 40), throttling F2's output.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [
            {"commodity_id": "mid", "kind": "material", "unit": "t", "purchasable": False},
            {"commodity_id": "widget", "kind": "product", "unit": "t"},
        ],
        "impacts": [],
        "technologies": [
            {"technology_id": "MK", "actions": "continue"},
            {"technology_id": "WK", "actions": "continue"},
        ],
        "processes": [
            {"process_id": "F1", "company": "C", "baseline_technology": "MK", "capacity": 1000},
            {"process_id": "F2", "company": "C", "baseline_technology": "WK", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "MK", "target": "mid", "role": "output", "coefficient": 1},
            {"technology_id": "WK", "target": "mid", "role": "input", "coefficient": 1},
            {
                "technology_id": "WK",
                "target": "widget",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "edges": [{"from_process": "F1", "to_process": "F2", "commodity_id": "mid"}],
        "edges_t": [
            {
                "from_process": "F1",
                "to_process": "F2",
                "commodity_id": "mid",
                "year": 2025,
                "max_flow": 100,
            },
            {
                "from_process": "F1",
                "to_process": "F2",
                "commodity_id": "mid",
                "year": 2030,
                "max_flow": 40,
            },
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    flow = {f["period"]: f["value"] for f in res["outputs"]["flows"] if f["commodity"] == "mid"}
    assert flow[2025] == pytest.approx(100.0, rel=1e-6)
    assert flow[2030] == pytest.approx(40.0, rel=1e-6)
    assert _slack(res).get("C|widget|2030") == pytest.approx(60.0, rel=1e-6)


def test_failure_rate_can_be_year_varying() -> None:
    # Forced-outage fraction rises 0 → 0.5, halving available throughput in 2030.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [],
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
        "processes_t__failure_rate": [{"year": 2025, "P": 0.0}, {"year": 2030, "P": 0.5}],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    tp = _throughput(res)
    assert tp[2025] == pytest.approx(100.0, rel=1e-6)
    assert tp[2030] == pytest.approx(50.0, rel=1e-6)  # 100 · (1 − 0.5)
    assert _slack(res).get("C|widget|2030") == pytest.approx(50.0, rel=1e-6)


def test_storage_costs_and_efficiencies_assemble_per_year() -> None:
    # Assemble-level: the storage entity carries year-varying overrides that the
    # objective / level dynamics read through its ``*_at`` accessors.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "gas", "kind": "energy", "unit": "t"}],
        "impacts": [],
        "storage": [
            {
                "storage_id": "S",
                "commodity_id": "gas",
                "max_capacity": 100,
                "capex_per_capacity": 10,
                "fixed_opex_per_capacity": 1,
                "charge_efficiency": 0.9,
                "discharge_efficiency": 0.9,
                "standing_loss": 0.0,
            }
        ],
        "storage_t__fixed_opex_per_capacity": [{"year": 2025, "S": 1}, {"year": 2030, "S": 3}],
        "storage_t__charge_efficiency": [{"year": 2025, "S": 0.9}, {"year": 2030, "S": 0.5}],
        "storage_t__capex_per_capacity": [{"year": 2025, "S": 10}, {"year": 2030, "S": 4}],
    }
    prob = assemble_problem(wb, SC)
    s = prob.storages[0]
    assert s.fixed_opex_per_capacity_at(2025) == pytest.approx(1.0)
    assert s.fixed_opex_per_capacity_at(2030) == pytest.approx(3.0)
    assert s.charge_efficiency_at(2030) == pytest.approx(0.5)
    assert s.capex_per_capacity_at(2030) == pytest.approx(4.0)


def test_lever_reduction_assembles_per_year() -> None:
    # Assemble-level: a lever block's abatement fraction can grow over time.
    wb = {
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": [{"commodity_id": "widget", "kind": "product", "unit": "t"}],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2e"}],
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
            },
            {"technology_id": "T", "target": "CO2", "role": "impact", "coefficient": 1.0},
        ],
        "levers": [
            {"lever_id": "M", "type": "emission_reduction", "facility": "P", "target": "CO2"}
        ],
        "lever_blocks": [{"lever_id": "M", "block": 0, "reduction": 0.2, "capex": 5}],
        "lever_blocks_t": [
            {"lever_id": "M", "block": 0, "year": 2025, "reduction": 0.2},
            {"lever_id": "M", "block": 0, "year": 2030, "reduction": 0.6},
        ],
        "demand": [
            {"company": "C", "commodity_id": "widget", "year": y, "amount": 100} for y in YEARS
        ],
    }
    prob = assemble_problem(wb, SC)
    block = prob.levers[0].blocks[0]
    assert block.reduction_at(2025) == pytest.approx(0.2)
    assert block.reduction_at(2030) == pytest.approx(0.6)
