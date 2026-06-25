"""P2 core MILP: analytic cost, network flow, MACC, full example solve."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem
from tests.data.example import example_workbook


def _solve(workbook: dict, scenario: dict | None = None) -> dict:
    sc = ScenarioConfig.from_dict(scenario or {"economics": {"base_year": 2025}})
    prob = assemble_problem(workbook, sc)
    res = solve(build(prob))
    return extract_results(res)


def test_single_process_cost_is_analytic() -> None:
    # 1 facility, 1 tech: 2 units of gas per widget @ $10/unit; demand 50 widgets.
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "unit": "MWh", "price": 10.0},
            {"flow_id": "widget", "kind": "product", "unit": "u"},
        ],
        "technologies": [{"technology_id": "T", "opex": 0.0}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100.0}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "gas", "intensity": 2.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "widget", "yield": 1.0, "is_product": True}
        ],
        "demand": [{"company": "C", "flow_id": "widget", "year": 2025, "amount": 50.0}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 50 widgets × 2 gas/widget × $10 = $1000.
    np.testing.assert_allclose(res["objective"], 1000.0, rtol=1e-6)
    assert res["outputs"]["demand_slack"] == []


def test_network_flow_routes_intermediate() -> None:
    # F1 makes `mid` from gas; an edge carries `mid` to F2 which makes `prod`.
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 5.0},
            {"flow_id": "mid", "kind": "material", "sellable": False},
            {"flow_id": "prod", "kind": "product"},
        ],
        "technologies": [{"technology_id": "A"}, {"technology_id": "B"}],
        "processes": [
            {"process_id": "F1", "company": "C", "baseline_technology": "A", "capacity": 1000.0},
            {"process_id": "F2", "company": "C", "baseline_technology": "B", "capacity": 1000.0},
        ],
        "process_inputs": [
            {"technology_id": "A", "flow_id": "gas", "intensity": 3.0},
            {"technology_id": "B", "flow_id": "mid", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "A", "flow_id": "mid", "yield": 1.0},
            {"technology_id": "B", "flow_id": "prod", "yield": 1.0, "is_product": True},
        ],
        "edges": [{"from_process": "F1", "to_process": "F2", "flow_id": "mid"}],
        "demand": [{"company": "C", "flow_id": "prod", "year": 2025, "amount": 40.0}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 40 prod ← 40 mid ← 120 gas × $5 = $600.
    np.testing.assert_allclose(res["objective"], 600.0, rtol=1e-6)
    flows = {(f["from"], f["to"], f["flow"]): f["value"] for f in res["outputs"]["flows"]}
    np.testing.assert_allclose(flows[("F1", "F2", "mid")], 40.0, rtol=1e-6)


def test_carbon_price_makes_emissions_show() -> None:
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "coal", "kind": "energy", "price": 1.0},
            {"flow_id": "p", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 100.0}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "coal", "intensity": 1.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "p", "yield": 1.0, "is_product": True}
        ],
        "flow_impacts": [{"flow_id": "coal", "impact_id": "CO2", "factor": 2.0}],
        "impact_prices": [{"impact_id": "CO2", "year": 2025, "price": 7.0}],
        "demand": [{"company": "C", "flow_id": "p", "year": 2025, "amount": 10.0}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    # coal: 10×1×$1 = 10; CO2: 10×1×2 = 20 t × $7 = 140 ⇒ 150.
    np.testing.assert_allclose(res["objective"], 150.0, rtol=1e-6)
    co2 = next(s for s in res["summary"]["impacts"] if s["impact"] == "CO2")
    np.testing.assert_allclose(co2["total"], 20.0, rtol=1e-6)


def test_full_example_solves_and_locks_baseline() -> None:
    res = _solve(example_workbook())
    assert res["status"] == "optimal"
    base = {(c["process"], c["period"]): c["technology"] for c in res["outputs"]["technology"]}
    assert base[("F1", 2025)] == "BF"
    assert base[("F2", 2025)] == "EAF"
