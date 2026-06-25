"""Flexible optimisation: choose a level, the units at it, and independent/joint.

- independent (>1 unit) → a coupled cascade (one problem per unit);
- joint, or a single unit → the selected subtrees solved as ONE problem.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/a", "parent_id": "chain", "kind": "group", "level": "company"},
            {"node_id": "chain/b", "parent_id": "chain", "kind": "group", "level": "company"},
            {"node_id": "chain/a/m", "parent_id": "chain/a", "kind": "asset"},
            {"node_id": "chain/b/m", "parent_id": "chain/b", "kind": "asset"},
        ],
        "assets": [
            {"asset_id": "chain/a/m", "baseline_technology": "TA", "capacity": 100},
            {"asset_id": "chain/b/m", "baseline_technology": "TB", "capacity": 100},
        ],
        "technologies": [{"technology_id": "TA", "io": []}, {"technology_id": "TB", "io": []}],
        "io": [
            {"technology_id": "TA", "target": "coal", "role": "input", "coefficient": 1},
            {
                "technology_id": "TA",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
            {"technology_id": "TB", "target": "coal", "role": "input", "coefficient": 1},
            {
                "technology_id": "TB",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "flows": [
            {"flow_id": "coal", "kind": "material", "price": 100},
            {"flow_id": "steel", "kind": "product"},
        ],
        "periods": [{"year": 2025, "duration_years": 1}],
        "demand": [
            {"company": "chain/a", "flow_id": "steel", "year": 2025, "amount": 50},
            {"company": "chain/b", "flow_id": "steel", "year": 2025, "amount": 50},
        ],
    }


def _sc(**kw: Any) -> ScenarioConfig:
    return ScenarioConfig.from_dict({"economics": {"base_year": 2025}, **kw})


def test_joint_solves_selected_units_as_one_problem() -> None:
    res = run_model(_model(), _sc(optimisation_scope="company", optimisation_mode="joint"))
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
    procs = {t["process"] for t in res["outputs"]["technology"]}
    assert {"chain/a/m", "chain/b/m"} <= procs  # both companies in one problem


def test_value_chain_solves_as_a_coupled_cascade() -> None:
    res = run_model(_model(), _sc(optimisation_scope="company", optimisation_mode="valuechain"))
    assert "stages" in res  # cascade result shape
    assert set(res["stages"]) == {"chain/a", "chain/b"}


def test_independent_solves_each_unit_on_its_own() -> None:
    res = run_model(_model(), _sc(optimisation_scope="company", optimisation_mode="independent"))
    assert "stages" in res and res["couplings"] == []  # per-unit, no coupling
    assert set(res["stages"]) == {"chain/a", "chain/b"}
    assert all(s["status"] == "optimal" for s in res["stages"].values())


def test_targets_restrict_to_chosen_units() -> None:
    # optimise only company A (joint over the selection ⇒ a single subtree)
    res = run_model(
        _model(),
        _sc(
            optimisation_scope="company",
            optimisation_targets=["chain/a"],
            optimisation_mode="joint",
        ),
    )
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
    procs = {t["process"] for t in res["outputs"]["technology"]}
    assert procs == {"chain/a/m"}, "company B is excluded from the selection"


def test_single_unit_is_solved_alone() -> None:
    # one unit selected, mode independent ⇒ not partitionable ⇒ a plain solve
    res = run_model(
        _model(),
        _sc(
            optimisation_scope="company",
            optimisation_targets=["chain/b"],
            optimisation_mode="independent",
        ),
    )
    assert "outputs" in res and res["status"] == "optimal"
    procs = {t["process"] for t in res["outputs"]["technology"]}
    assert procs == {"chain/b/m"}
