"""Discount rate resolution: scenario value wins, else model `meta`, else 0.08.

The discount rate is a project-wide economic setting stored on the model's
``meta`` sheet (edited in the Project tab) and sent into the run. Assembly must
prefer an explicit scenario value, fall back to ``meta.discount_rate``, and only
then the engine default — so the Project-tab setting actually drives NPV.
"""

from __future__ import annotations

from typing import Any

from pathwise.data import ScenarioConfig, assemble_problem


def _wb(meta: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "meta": meta or [],
        "periods": [{"year": 2025}, {"year": 2030}],
        "commodities": [{"commodity_id": "p", "kind": "product"}],
        "technologies": [{"technology_id": "T"}],
        "processes": [
            {"process_id": "P", "company": "C", "baseline_technology": "T", "capacity": 10}
        ],
        "io": [{"technology_id": "T", "target": "p", "role": "output", "coefficient": 1}],
    }


def _sc(**econ: Any) -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025, **econ}})


def test_scenario_discount_wins() -> None:
    prob = assemble_problem(_wb([{"key": "discount_rate", "value": 0.05}]), _sc(discount_rate=0.1))
    assert prob.discount_rate == 0.1


def test_meta_discount_used_when_scenario_unset() -> None:
    # No discount in the scenario (None) → the model's meta value drives NPV.
    prob = assemble_problem(_wb([{"key": "discount_rate", "value": 0.05}]), _sc())
    assert prob.discount_rate == 0.05


def test_engine_default_when_neither_set() -> None:
    prob = assemble_problem(_wb(), _sc())
    assert prob.discount_rate == 0.08
