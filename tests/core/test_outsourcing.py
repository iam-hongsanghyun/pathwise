"""P10: facility on/off — make-vs-buy outsourcing of an upstream process."""

from __future__ import annotations

import copy

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _chain_wb() -> dict:
    # F1: gas → iron (intermediate); F2: iron → steel (product). Edge F1→F2.
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "gas", "kind": "energy", "price": 10},
            {"flow_id": "iron", "kind": "material"},
            {"flow_id": "steel", "kind": "product"},
        ],
        "technologies": [{"technology_id": "A"}, {"technology_id": "B"}],
        "processes": [
            {"process_id": "F1", "company": "C", "baseline_technology": "A", "capacity": 1000},
            {"process_id": "F2", "company": "C", "baseline_technology": "B", "capacity": 1000},
        ],
        "process_inputs": [
            {"technology_id": "A", "flow_id": "gas", "intensity": 2.0},
            {"technology_id": "B", "flow_id": "iron", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "A", "flow_id": "iron", "yield": 1.0},
            {"technology_id": "B", "flow_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "edges": [{"from_process": "F1", "to_process": "F2", "flow_id": "iron"}],
        "demand": [{"company": "C", "flow_id": "steel", "year": 2025, "amount": 100}],
    }


def _operating(res: dict) -> set[str]:
    return {t["process"] for t in res["outputs"]["technology"]}


def test_makes_intermediate_when_no_cheaper_market() -> None:
    res = _solve(_chain_wb())
    assert res["status"] == "optimal"
    # Make iron in F1: 100 steel ← 100 iron ← 200 gas × $10 = $2000.
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)
    assert {"F1", "F2"} <= _operating(res)  # both run


def test_outsources_upstream_when_market_is_cheaper() -> None:
    wb = _chain_wb()
    wb["markets"] = [{"market_id": "IRON_MKT", "target": "iron", "target_kind": "flow", "price": 5}]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # Buy iron @ $5 instead of making it (gas would cost $20/unit) → 100 × $5 = $500.
    np.testing.assert_allclose(res["objective"], 500.0, rtol=1e-6)
    # F1 makes no iron (outsourced); F2 still produces steel from bought iron.
    f1_throughput = sum(t["value"] for t in res["outputs"]["throughput"] if t["process"] == "F1")
    assert f1_throughput < 1e-6
    assert "F2" in _operating(res)
    buy = {m["market"]: m["by_period"][0]["buy"] for m in res["outputs"]["markets"]}
    np.testing.assert_allclose(buy["IRON_MKT"], 100.0, rtol=1e-6)


def test_keeps_upstream_when_market_is_dearer() -> None:
    wb = _chain_wb()
    wb["markets"] = [
        {"market_id": "IRON_MKT", "target": "iron", "target_kind": "flow", "price": 50}
    ]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # Making (gas $20/unit) beats buying ($50) → still make in F1.
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)
    assert "F1" in _operating(res)


def test_fixed_opex_only_paid_when_operating() -> None:
    # An idle facility (no demand for its output, no market need) pays no fixed O&M.
    wb = copy.deepcopy(_chain_wb())
    wb["markets"] = [{"market_id": "IRON_MKT", "target": "iron", "target_kind": "flow", "price": 5}]
    wb["processes"][0]["fixed_opex"] = 9999  # F1
    res = _solve(wb)
    # F1 outsourced ⇒ its $9999 fixed O&M is not paid; cost stays $500.
    np.testing.assert_allclose(res["objective"], 500.0, rtol=1e-6)
    assert "F1" not in _operating(res)
