"""P8b: flow-market least-cost mixture + tradable ETS allowances."""

from __future__ import annotations

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict) -> dict:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def test_market_mixture_picks_cheapest_first() -> None:
    wb = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "elec", "kind": "energy"},
            {"flow_id": "p", "kind": "product"},
        ],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1000}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "elec", "intensity": 1.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "p", "yield": 1.0, "is_product": True}
        ],
        "markets": [
            {
                "market_id": "PPA",
                "target": "elec",
                "target_kind": "flow",
                "price": 50,
                "max_buy": 60,
                "tag": "RE100",
            },
            {"market_id": "KEPCO", "target": "elec", "target_kind": "flow", "price": 80},
        ],
        "demand": [{"company": "C", "flow_id": "p", "year": 2025, "amount": 100}],
    }
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 60 from PPA @50 + 40 from KEPCO @80 = 3000 + 3200 = 6200.
    np.testing.assert_allclose(res["objective"], 6200.0, rtol=1e-6)
    buy = {m["market"]: m["by_period"][0]["buy"] for m in res["outputs"]["markets"]}
    np.testing.assert_allclose(buy["PPA"], 60.0, rtol=1e-6)
    np.testing.assert_allclose(buy["KEPCO"], 40.0, rtol=1e-6)


def _ets_wb(allocation: float) -> dict:
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "coal", "kind": "energy", "price": 0},
            {"flow_id": "p", "kind": "product"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 1000}
        ],
        "process_inputs": [{"technology_id": "T", "flow_id": "coal", "intensity": 1.0}],
        "process_outputs": [
            {"technology_id": "T", "flow_id": "p", "yield": 1.0, "is_product": True}
        ],
        "flow_impacts": [{"flow_id": "coal", "impact_id": "CO2", "factor": 1.0}],
        "markets": [
            {
                "market_id": "ETS",
                "target": "CO2",
                "target_kind": "impact",
                "company": "all",
                "price": 50,
                "allocation": allocation,
            }
        ],
        "demand": [{"company": "C", "flow_id": "p", "year": 2025, "amount": 60}],
    }


def test_ets_sells_surplus_allowances() -> None:
    # Emit 60, allocation 100 ⇒ sell 40 @ $50 ⇒ net cost −2000.
    res = _solve(_ets_wb(100.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], -2000.0, rtol=1e-6)
    ets = res["outputs"]["ets"][0]["by_period"][0]
    np.testing.assert_allclose(ets["sold"], 40.0, rtol=1e-6)


def test_ets_buys_deficit_allowances() -> None:
    # Emit 60, allocation 20 ⇒ buy 40 @ $50 ⇒ net cost +2000.
    res = _solve(_ets_wb(20.0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)
    ets = res["outputs"]["ets"][0]["by_period"][0]
    np.testing.assert_allclose(ets["bought"], 40.0, rtol=1e-6)
