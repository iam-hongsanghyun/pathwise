"""A time-lagged edge: flow leaving the producer in year t arrives at the consumer
in t+lag. Models a use-phase / recycling return (e.g. steel → cars → scrap years
later); the quality change is just the producer emitting a different flow."""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


def _produced(res: dict[str, Any], flow: str) -> float:
    return sum(s["produced"] for s in res["summary"]["flow"] if s["flow"] == flow)


def _wb(lag: int) -> dict[str, Any]:
    # S turns ore→X; C turns X→Y (the product). The S→C link carries `lag` years,
    # so X made in 2025 only reaches C in 2025+lag. Demand pulls 100 Y in BOTH years.
    return {
        "periods": [{"year": 2025, "duration_years": 5}, {"year": 2030, "duration_years": 5}],
        "flows": [
            {"flow_id": "ore", "kind": "material", "price": 1},
            {"flow_id": "x", "kind": "material"},
            {"flow_id": "y", "kind": "product"},
        ],
        "technologies": [{"technology_id": "ST"}, {"technology_id": "CT"}],
        "processes": [
            {"process_id": "S", "company": "Z", "baseline_technology": "ST", "capacity": 1000},
            {"process_id": "C", "company": "Z", "baseline_technology": "CT", "capacity": 1000},
        ],
        "process_inputs": [
            {"technology_id": "ST", "flow_id": "ore", "intensity": 1.0},
            {"technology_id": "CT", "flow_id": "x", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "ST", "flow_id": "x", "yield": 1.0},
            {"technology_id": "CT", "flow_id": "y", "yield": 1.0, "is_product": True},
        ],
        "edges": [{"from_process": "S", "to_process": "C", "flow_id": "x", "lag_years": lag}],
        "demand": [
            {"company": "all", "flow_id": "y", "year": 2025, "amount": 100},
            {"company": "all", "flow_id": "y", "year": 2030, "amount": 100},
        ],
    }


def test_no_lag_meets_both_years() -> None:
    res = _solve(_wb(0))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "y"), 200.0, rtol=1e-6, atol=1e-6)


def test_lag_defers_delivery_so_first_year_cannot_be_met() -> None:
    # 5-yr lag: Y in 2025 would need X delivered in 2025 = produced in 2020 (before
    # the horizon) ⇒ impossible. Only 2030 can be met (from X made in 2025).
    res = _solve(_wb(5))
    assert res["status"] == "optimal"
    np.testing.assert_allclose(_produced(res, "y"), 100.0, rtol=1e-6, atol=1e-6)
