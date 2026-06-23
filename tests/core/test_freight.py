"""Optional per-stream freight physics (the spatial-transport edge layer).

A producer's commodity reaches one sink by two competing connections — a cheap,
dirty route and a pricey, clean route. With no carbon price the optimiser routes
over the cheap-freight edge; a CO2 price above the breakeven flips it to the
low-CO2 edge. Freight cost + CO2 + energy are reported in outputs.transport.
Untagged edges stay free (no cost/co2), so the feature is opt-in per stream.
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
    # Two producers make commodity X for free; each ships X to one sink over its own
    # connection. Route A: cheap freight (5), dirty (2.0 t CO2/t). Route B: pricey
    # freight (20), clean (0.1). The sink turns X into product Y (demand 100).
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "X", "kind": "material", "unit": "t"},
            {"commodity_id": "Y", "kind": "product", "unit": "t"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "t"}, {"impact_id": "GWP", "unit": "t CO2e"}],
        "characterisation": [{"flow_impact_id": "CO2", "category_id": "GWP", "factor": 1.0}],
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
            {"node_id": "vc/a", "kind": "machine", "level": "machine", "parent_id": "vc"},
            {"node_id": "vc/b", "kind": "machine", "level": "machine", "parent_id": "vc"},
            {"node_id": "vc/sink", "kind": "machine", "level": "machine", "parent_id": "vc"},
        ],
        "machines": [
            {"machine_id": "vc/a", "baseline_technology": "Prod", "capacity": 1000},
            {"machine_id": "vc/b", "baseline_technology": "Prod", "capacity": 1000},
            {"machine_id": "vc/sink", "baseline_technology": "Make", "capacity": 1000},
        ],
        "connections": [
            {
                "from_node": "vc/a",
                "to_node": "vc/sink",
                "commodity_id": "X",
                "freight_cost": 5,
                "freight_co2": 2.0,
                "freight_energy": 0.3,
            },
            {
                "from_node": "vc/b",
                "to_node": "vc/sink",
                "commodity_id": "X",
                "freight_cost": 20,
                "freight_co2": 0.1,
                "freight_energy": 0.5,
            },
        ],
        "demand": [{"company": "vc/sink", "commodity_id": "Y", "year": 2025, "amount": 100}],
    }


def _run(carbon: float) -> dict:
    wb = {**_wb(), "impact_prices": [{"impact_id": "CO2", "year": 2025, "price": carbon}]}
    return get_backend("linopy").run(wb, _SCENARIO, {})


def _route(res: dict) -> str:
    """Which producer the X flow came from (the chosen freight route)."""
    flows = [f for f in res["outputs"]["flows"] if f["commodity"] == "X" and f["value"] > 1e-6]
    return max(flows, key=lambda f: f["value"])["from"] if flows else ""


def test_zero_carbon_takes_cheap_freight_route() -> None:
    res = _run(0)
    assert res["status"] == "optimal"
    assert _route(res) == "vc/a"  # cheap freight (5) beats pricey (20) when CO2 is free


def test_carbon_price_flips_to_low_co2_route() -> None:
    res = _run(50)
    assert res["status"] == "optimal"
    # Route A's dirty freight (2.0 t/t) is now penalised → flip to the clean route B.
    assert _route(res) == "vc/b"


def test_transport_block_reports_cost_co2_energy() -> None:
    res = _run(0)
    transport = res["outputs"]["transport"]
    assert transport, "tagged edges must populate outputs.transport"
    row = next(t for t in transport if t["from"] == "vc/a")
    # 100 t shipped on route A → freight cost 500, CO2 200, energy 30.
    assert row["flow"] == pytest.approx(100.0)
    assert row["cost"] == pytest.approx(500.0)
    assert row["co2"] == pytest.approx(200.0)
    assert row["energy"] == pytest.approx(30.0)


def test_untagged_edges_have_no_transport_rows() -> None:
    wb = _wb()
    for c in wb["connections"]:
        c.pop("freight_cost"), c.pop("freight_co2"), c.pop("freight_energy")
    res = get_backend("linopy").run({**wb, "impact_prices": []}, _SCENARIO, {})
    assert res["status"] == "optimal"
    assert res["outputs"]["transport"] == []  # opt-in: untagged streams stay free
