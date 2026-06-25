"""Optional per-stream freight physics (the spatial-transport edge layer).

A producer's flow reaches one sink by two competing connections — a cheap,
dirty route and a pricey, clean route. With no impact price the optimiser routes
over the cheap-freight edge; pricing the pollutant flips it to the clean edge. The
pollutant here is "SOx" (NOT CO2) to prove freight pricing is impact-agnostic.
Freight cost + per-impact emissions + energy are reported in outputs.transport;
untagged edges stay free, so the feature is opt-in per stream.
"""

from __future__ import annotations

import pytest

from pathwise.backends.registry import get_backend

_SCENARIO = {
    "economics": {"base_year": 2025, "discount_rate": 0.0},
    "optimisation_scope": "system",
    "optimisation_mode": "joint",
    "objective": "cost",
}


def _wb() -> dict:
    # Two producers make flow X for free; each ships X to one sink over its own
    # connection. Route A: cheap freight (5), dirty (2.0 t/t of a priced pollutant).
    # Route B: pricey freight (20), clean (0.1). The pollutant is "SOx" — deliberately
    # NOT CO2 — to prove freight emissions are impact-agnostic. Sink turns X into Y.
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "flows": [
            {"flow_id": "X", "kind": "material", "unit": "t"},
            {"flow_id": "Y", "kind": "product", "unit": "t"},
        ],
        "impacts": [{"impact_id": "SOx", "unit": "t"}],
        "technologies": [
            {"technology_id": "Prod", "actions": "continue"},
            {"technology_id": "Make", "actions": "continue"},
        ],
        "io": [
            {"technology_id": "Prod", "target": "X", "role": "output", "coefficient": 1.0},
            {"technology_id": "Make", "target": "X", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Make",
                "target": "Y",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
        ],
        "nodes": [
            {"node_id": "vc", "kind": "group", "level": "value_chain", "label": "Freight test"},
            {"node_id": "vc/a", "kind": "asset", "level": "asset", "parent_id": "vc"},
            {"node_id": "vc/b", "kind": "asset", "level": "asset", "parent_id": "vc"},
            {"node_id": "vc/sink", "kind": "asset", "level": "asset", "parent_id": "vc"},
        ],
        "assets": [
            {"asset_id": "vc/a", "baseline_technology": "Prod", "capacity": 1000},
            {"asset_id": "vc/b", "baseline_technology": "Prod", "capacity": 1000},
            {"asset_id": "vc/sink", "baseline_technology": "Make", "capacity": 1000},
        ],
        "links": [
            {
                "from_node": "vc/a",
                "to_node": "vc/sink",
                "flow_id": "X",
                "freight_cost": 5,
                "freight_energy": 0.3,
            },
            {
                "from_node": "vc/b",
                "to_node": "vc/sink",
                "flow_id": "X",
                "freight_cost": 20,
                "freight_energy": 0.5,
            },
        ],
        # Per-impact freight emissions live in their own sheet (impact-agnostic).
        "link_impacts": [
            {
                "from_node": "vc/a",
                "to_node": "vc/sink",
                "flow_id": "X",
                "impact_id": "SOx",
                "factor": 2.0,
            },
            {
                "from_node": "vc/b",
                "to_node": "vc/sink",
                "flow_id": "X",
                "impact_id": "SOx",
                "factor": 0.1,
            },
        ],
        "demand": [{"company": "vc/sink", "flow_id": "Y", "year": 2025, "amount": 100}],
    }


def _run(price: float) -> dict:
    wb = {**_wb(), "impact_prices": [{"impact_id": "SOx", "year": 2025, "price": price}]}
    return get_backend("linopy").run(wb, _SCENARIO, {})


def _route(res: dict) -> str:
    """Which producer the X flow came from (the chosen freight route)."""
    flows = [f for f in res["outputs"]["flows"] if f["flow"] == "X" and f["value"] > 1e-6]
    return max(flows, key=lambda f: f["value"])["from"] if flows else ""


def test_zero_price_takes_cheap_freight_route() -> None:
    res = _run(0)
    assert res["status"] == "optimal"
    assert _route(res) == "vc/a"  # cheap freight (5) beats pricey (20) when SOx is free


def test_impact_price_flips_to_low_emission_route() -> None:
    res = _run(50)
    assert res["status"] == "optimal"
    # Route A's dirty freight (2.0 t/t SOx) is now penalised → flip to clean route B.
    # Proves freight pricing rides ANY impact, not a hardcoded CO2.
    assert _route(res) == "vc/b"


def test_transport_block_reports_cost_emissions_energy() -> None:
    res = _run(0)
    transport = res["outputs"]["transport"]
    assert transport, "tagged edges must populate outputs.transport"
    row = next(t for t in transport if t["from"] == "vc/a")
    assert row["flow"] == "X"  # the flow (substance) carried on this edge
    # 100 t shipped on route A → freight cost 500, SOx 200, energy 30.
    assert row["value"] == pytest.approx(100.0)
    assert row["cost"] == pytest.approx(500.0)
    assert row["emissions"]["SOx"] == pytest.approx(200.0)
    assert row["energy"] == pytest.approx(30.0)


def test_untagged_edges_have_no_transport_rows() -> None:
    wb = _wb()
    wb["links"] = [
        {k: v for k, v in c.items() if k not in ("freight_cost", "freight_energy")}
        for c in wb["links"]
    ]
    wb["link_impacts"] = []
    res = get_backend("linopy").run({**wb, "impact_prices": []}, _SCENARIO, {})
    assert res["status"] == "optimal"
    assert res["outputs"]["transport"] == []  # opt-in: untagged streams stay free
