"""A node-hierarchy model validates and runs through the unified front door.

`validate()` accepts a hierarchy (assets stand in for processes), and the
linopy backend routes such a model through `run_model` (joint solve at the
root/system level; per-level partition otherwise).
"""

from __future__ import annotations

from typing import Any

from pathwise.backends.linopy_backend import LinopyBackend
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.validation import validate


def _hierarchy_model() -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/mill", "parent_id": "chain", "kind": "group", "level": "facility"},
            {"node_id": "chain/mill/bf", "parent_id": "chain/mill", "kind": "asset"},
            {"node_id": "chain/mill/bof", "parent_id": "chain/mill", "kind": "asset"},
        ],
        "assets": [
            {"asset_id": "chain/mill/bf", "baseline_technology": "BF", "capacity": 100},
            {"asset_id": "chain/mill/bof", "baseline_technology": "BOF", "capacity": 100},
        ],
        "connections": [
            {"from_node": "chain/mill/bf", "to_node": "chain/mill/bof", "commodity_id": "iron"}
        ],
        "technologies": [
            {"technology_id": "BF", "io": []},
            {"technology_id": "BOF", "io": []},
        ],
        "io": [
            {"technology_id": "BF", "target": "power", "role": "input", "coefficient": 2},
            {"technology_id": "BF", "target": "iron", "role": "output", "coefficient": 1},
            {"technology_id": "BOF", "target": "iron", "role": "input", "coefficient": 1},
            {
                "technology_id": "BOF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodities": [
            {"commodity_id": "power", "kind": "energy", "price": 1.0},
            {"commodity_id": "iron", "kind": "material"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "periods": [{"year": 2025, "duration_years": 1}],
        "demand": [{"company": "all", "commodity_id": "steel", "year": 2025, "amount": 80}],
    }


def test_validate_accepts_a_hierarchy_without_processes() -> None:
    report = validate(_hierarchy_model())
    assert report.ok, report.errors


def test_validate_flags_unknown_asset_technology() -> None:
    model = _hierarchy_model()
    model["assets"][0]["baseline_technology"] = "GHOST"
    report = validate(model)
    assert any("GHOST" in e for e in report.errors)


def test_backend_runs_a_hierarchy_model() -> None:
    res = LinopyBackend().run(
        _hierarchy_model(),
        {"economics": {"base_year": 2025}, "optimisation_scope": "system"},
        {"domain": "process"},
    )
    assert res["status"] == "optimal"
    assert res["validation"]["errors"] == []
    assert res["terminology"], "joint result folds in the domain terminology"


def test_run_model_joint_solves() -> None:
    res = run_model(
        _hierarchy_model(),
        ScenarioConfig.from_dict(
            {"economics": {"base_year": 2025}, "optimisation_scope": "system"}
        ),
    )
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
