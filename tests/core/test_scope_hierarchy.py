"""Hierarchy-aware scope: a asset is in-scope for every ancestor level.

This is what lets a market / demand / cap scoped to ANY designed level (sector,
company, facility…) resolve to the right assets — e.g. "this company purchases
coal" pools exactly that company's furnaces.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.entities import Process
from pathwise.core.run import run_model
from pathwise.data import ScenarioConfig
from pathwise.data.assemble import assemble_problem

SC = ScenarioConfig.from_dict({"economics": {"base_year": 2025}})


def _model() -> dict[str, list[dict[str, Any]]]:
    return {
        "nodes": [
            {"node_id": "chain", "parent_id": None, "kind": "group", "level": "value_chain"},
            {"node_id": "chain/steelco", "parent_id": "chain", "kind": "group", "level": "company"},
            {
                "node_id": "chain/steelco/mill",
                "parent_id": "chain/steelco",
                "kind": "group",
                "level": "facility",
            },
            {
                "node_id": "chain/steelco/mill/bf",
                "parent_id": "chain/steelco/mill",
                "kind": "asset",
            },
        ],
        "assets": [
            {"asset_id": "chain/steelco/mill/bf", "baseline_technology": "BF", "capacity": 100}
        ],
        "technologies": [{"technology_id": "BF", "io": []}],
        "io": [
            {"technology_id": "BF", "target": "coal", "role": "input", "coefficient": 1},
            {
                "technology_id": "BF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodities": [
            {"commodity_id": "coal", "kind": "material", "price": 10},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "periods": [{"year": 2025, "duration_years": 1}],
        "demand": [{"company": "all", "commodity_id": "steel", "year": 2025, "amount": 50}],
    }


def test_assemble_stamps_full_ancestor_scopes() -> None:
    prob = assemble_problem(_model(), SC)
    bf = next(p for p in prob.processes if p.process_id == "chain/steelco/mill/bf")
    assert {
        "chain/steelco/mill/bf",
        "chain/steelco/mill",
        "chain/steelco",
        "chain",
        "all",
    } <= bf.scopes
    # in_scope resolves at every designed level, not just the canonical three
    assert bf.in_scope("chain/steelco")  # company
    assert bf.in_scope("chain/steelco/mill")  # facility
    assert bf.in_scope("all")
    assert not bf.in_scope("chain/otherco")


def test_flat_process_scope_is_backward_compatible() -> None:
    # No `scopes` (flat model authored directly) → falls back to id/company/group/all
    p = Process(
        process_id="p1", company="acme", baseline_technology="T", capacity=10, group="plant"
    )
    assert p.in_scope("acme") and p.in_scope("plant") and p.in_scope("p1") and p.in_scope("all")
    assert not p.in_scope("chain/steelco")


def test_company_scoped_market_resolves_to_its_subtree() -> None:
    m = _model()
    # coal is NOT purchasable by default; the ONLY supply is a market scoped to the
    # deep company node. If deep-group scope didn't resolve, the market would serve
    # zero processes and the demand could not be met.
    m["commodities"][0]["purchasable"] = False
    m["markets"] = [
        {"market_id": "coal_mkt", "target": "coal", "company": "chain/steelco", "price": 10}
    ]
    res = run_model(m, SC)
    assert res["status"] == "optimal" and not res["outputs"]["demand_slack"]
