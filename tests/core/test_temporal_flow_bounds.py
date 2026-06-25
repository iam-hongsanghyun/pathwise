"""Per-year (temporal) flow bounds on a provider→consumer link.

A connection's ``min_flow`` / ``max_flow`` may vary by year: a take-or-pay floor
(or cap) that binds in some years but not others. Two storage paths feed this:

* the flat model's ``edges_t`` sheet (process-space), read directly, and
* the node model's ``connections_t`` sheet (node-space), which ``_expand_hierarchy``
  fans out onto the synthesized edges.

Both are interpolated onto the run periods and enforced per period by build.py
(``min_flow_at`` / ``max_flow_at``).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem


def _solve(wb: dict[str, Any]) -> dict[str, Any]:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.0}})
    return extract_results(solve(build(assemble_problem(wb, sc))))


# ── Flat model: edges_t per-year min_flow ────────────────────────────────────


def _flat_wb() -> dict[str, Any]:
    # P1 cheap (gas @10), P2 dear (gas2 @100) both make elec; C turns elec→steel.
    # 100 steel demanded each of two years ⇒ 100 elec needed each year.
    return {
        "periods": [
            {"year": 2025, "duration_years": 1},
            {"year": 2030, "duration_years": 1},
        ],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 10},
            {"commodity_id": "gas2", "kind": "energy", "price": 100},
            {"commodity_id": "elec", "kind": "energy"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "technologies": [
            {"technology_id": "PT"},
            {"technology_id": "PT2"},
            {"technology_id": "CT"},
        ],
        "processes": [
            {"process_id": "P1", "company": "X", "baseline_technology": "PT", "capacity": 1000},
            {"process_id": "P2", "company": "X", "baseline_technology": "PT2", "capacity": 1000},
            {"process_id": "C", "company": "X", "baseline_technology": "CT", "capacity": 1000},
        ],
        "process_inputs": [
            {"technology_id": "PT", "commodity_id": "gas", "intensity": 1.0},
            {"technology_id": "PT2", "commodity_id": "gas2", "intensity": 1.0},
            {"technology_id": "CT", "commodity_id": "elec", "intensity": 1.0},
        ],
        "process_outputs": [
            {"technology_id": "PT", "commodity_id": "elec", "yield": 1.0},
            {"technology_id": "PT2", "commodity_id": "elec", "yield": 1.0},
            {"technology_id": "CT", "commodity_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "edges": [
            {"from_process": "P1", "to_process": "C", "commodity_id": "elec"},
            {"from_process": "P2", "to_process": "C", "commodity_id": "elec"},
        ],
        "demand": [{"company": "all", "commodity_id": "steel", "amount": 100}],
    }


def test_flat_baseline_uses_cheap_provider_every_year() -> None:
    res = _solve(_flat_wb())
    assert res["status"] == "optimal"
    # 100 cheap elec each of 2 years → 2 × $1000 = $2000.
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)


def test_flat_edges_t_min_flow_varies_by_year() -> None:
    wb = _flat_wb()
    # A floor that is 0 in 2025 and 40 in 2030 on the dear P2→C link. (A row per
    # period — mirroring the editor's materialised output; a lone 2030 row would
    # flat-hold back onto 2025.)
    wb["edges_t"] = [
        {
            "from_process": "P2",
            "to_process": "C",
            "commodity_id": "elec",
            "year": 2025,
            "min_flow": 0,
        },
        {
            "from_process": "P2",
            "to_process": "C",
            "commodity_id": "elec",
            "year": 2030,
            "min_flow": 40,
        },
    ]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 2025: 100 cheap = $1000. 2030: 40 dear ($4000) + 60 cheap ($600) = $4600. Σ = $5600.
    np.testing.assert_allclose(res["objective"], 5600.0, rtol=1e-6)


# ── Node model: connections_t fanned onto edges ──────────────────────────────


def _hier_wb() -> dict[str, Any]:
    return {
        "nodes": [
            {"node_id": "co", "parent_id": None, "kind": "group", "level": "company"},
            {"node_id": "co/p1", "parent_id": "co", "kind": "asset"},
            {"node_id": "co/p2", "parent_id": "co", "kind": "asset"},
            {"node_id": "co/c", "parent_id": "co", "kind": "asset"},
        ],
        "assets": [
            {"asset_id": "co/p1", "baseline_technology": "PT", "capacity": 1000},
            {"asset_id": "co/p2", "baseline_technology": "PT2", "capacity": 1000},
            {"asset_id": "co/c", "baseline_technology": "CT", "capacity": 1000},
        ],
        "technologies": [
            {"technology_id": "PT"},
            {"technology_id": "PT2"},
            {"technology_id": "CT"},
        ],
        "io": [
            {"technology_id": "PT", "target": "gas", "role": "input", "coefficient": 1},
            {"technology_id": "PT", "target": "elec", "role": "output", "coefficient": 1},
            {"technology_id": "PT2", "target": "gas2", "role": "input", "coefficient": 1},
            {"technology_id": "PT2", "target": "elec", "role": "output", "coefficient": 1},
            {"technology_id": "CT", "target": "elec", "role": "input", "coefficient": 1},
            {
                "technology_id": "CT",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodities": [
            {"commodity_id": "gas", "kind": "energy", "price": 10},
            {"commodity_id": "gas2", "kind": "energy", "price": 100},
            {"commodity_id": "elec", "kind": "energy"},
            {"commodity_id": "steel", "kind": "product"},
        ],
        "connections": [
            {"from_node": "co/p1", "to_node": "co/c", "commodity_id": "elec"},
            {"from_node": "co/p2", "to_node": "co/c", "commodity_id": "elec"},
        ],
        "periods": [
            {"year": 2025, "duration_years": 1},
            {"year": 2030, "duration_years": 1},
        ],
        "demand": [{"company": "all", "commodity_id": "steel", "amount": 100}],
    }


def test_hierarchy_baseline_uses_cheap_provider_every_year() -> None:
    res = _solve(_hier_wb())
    assert res["status"] == "optimal"
    np.testing.assert_allclose(res["objective"], 2000.0, rtol=1e-6)


def test_hierarchy_connections_t_min_flow_varies_by_year() -> None:
    wb = _hier_wb()
    # A take-or-pay floor on the dear provider's link: none in 2025, 40 in 2030.
    wb["connections_t"] = [
        {
            "from_node": "co/p2",
            "to_node": "co/c",
            "commodity_id": "elec",
            "year": 2025,
            "min_flow": 0,
        },
        {
            "from_node": "co/p2",
            "to_node": "co/c",
            "commodity_id": "elec",
            "year": 2030,
            "min_flow": 40,
        },
    ]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 2025 unconstrained ($1000) + 2030 floored ($4600) = $5600.
    np.testing.assert_allclose(res["objective"], 5600.0, rtol=1e-6)


def test_hierarchy_connections_t_max_flow_varies_by_year() -> None:
    wb = _hier_wb()
    # Cap the cheap provider's link at 30 in 2030 (1000 = no real cap in 2025)
    # ⇒ 70 forced through the dear provider in 2030 only.
    wb["connections_t"] = [
        {
            "from_node": "co/p1",
            "to_node": "co/c",
            "commodity_id": "elec",
            "year": 2025,
            "max_flow": 1000,
        },
        {
            "from_node": "co/p1",
            "to_node": "co/c",
            "commodity_id": "elec",
            "year": 2030,
            "max_flow": 30,
        },
    ]
    res = _solve(wb)
    assert res["status"] == "optimal"
    # 2025 unconstrained ($1000) + 2030: 30 cheap ($300) + 70 dear ($7000) = $7300. Σ = $8300.
    np.testing.assert_allclose(res["objective"], 8300.0, rtol=1e-6)
