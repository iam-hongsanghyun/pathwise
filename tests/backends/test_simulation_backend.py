"""Simulation backend: evaluate a pinned configuration's lifecycle inventory.

The simulator is a *what-if / LCA* lens over the same value-chain model (not a new
schema): it pins the configuration, evaluates it, and decomposes the emissions by
value-chain stage. The minimal model below has hand-computable emissions; the
green-steel case guards it on a realistic multi-stage chain.
"""

from __future__ import annotations

from importlib.resources import files

import pytest

from pathwise.api.workbook_io import parse_sqlite
from pathwise.backends.registry import available_backends, get_backend
from pathwise.backends.simulation_backend import SimulationBackend


def _two_stage_model() -> dict:
    """Steel maker (ore→steel, 2 tCO2/t) → car maker (steel→car, 0.5 tCO2/car).

    100 cars ⇒ 100 steel ⇒ steel stage emits 200, auto stage emits 50, total 250.
    """
    return {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"commodity_id": "steel", "kind": "material", "unit": "t"},
            {"commodity_id": "car", "kind": "product", "unit": "veh"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "technologies": [
            {"technology_id": "SteelMaker", "actions": "continue"},
            {"technology_id": "CarMaker", "actions": "continue"},
        ],
        "nodes": [
            {"node_id": "steelco", "kind": "group", "level": "company", "label": "Steel"},
            {
                "node_id": "steelco/sm",
                "kind": "machine",
                "level": "machine",
                "parent_id": "steelco",
            },
            {"node_id": "autoco", "kind": "group", "level": "company", "label": "Auto"},
            {"node_id": "autoco/cm", "kind": "machine", "level": "machine", "parent_id": "autoco"},
        ],
        "machines": [
            {"machine_id": "steelco/sm", "baseline_technology": "SteelMaker", "capacity": 1000},
            {"machine_id": "autoco/cm", "baseline_technology": "CarMaker", "capacity": 1000},
        ],
        "io": [
            {"technology_id": "SteelMaker", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "SteelMaker",
                "target": "steel",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "SteelMaker", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "CarMaker", "target": "steel", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "CarMaker",
                "target": "car",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "CarMaker", "target": "CO2", "role": "impact", "coefficient": 0.5},
        ],
        "connections": [{"from_node": "steelco", "to_node": "autoco", "commodity_id": "steel"}],
        "demand": [{"company": "autoco", "commodity_id": "car", "year": 2025, "amount": 100}],
    }


_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}}


def test_simulate_backend_is_registered() -> None:
    names = {b["name"] for b in available_backends()}
    assert "simulate" in names
    assert get_backend("simulate").name == "simulate"


def test_lifecycle_inventory_decomposes_by_stage() -> None:
    res = SimulationBackend().run(_two_stage_model(), _SCENARIO)
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]

    assert lca["functional_unit"] == {"commodity": "car", "amount": 100.0}

    co2 = next(d for d in lca["by_impact"] if d["impact"] == "CO2")
    assert co2["total"] == pytest.approx(250.0)
    assert co2["per_unit"] == pytest.approx(2.5)

    stages = {(d["stage"], d["impact"]): d["total"] for d in lca["by_stage"]}
    assert stages[("steelco", "CO2")] == pytest.approx(200.0)
    assert stages[("autoco", "CO2")] == pytest.approx(50.0)
    # The per-stage decomposition reconstructs the engine's per-impact total.
    assert sum(v for (_s, i), v in stages.items() if i == "CO2") == pytest.approx(co2["total"])


def test_carbon_cost_uses_the_impact_price() -> None:
    model = _two_stage_model()
    model["impact_prices"] = [{"impact_id": "CO2", "year": 2025, "price": 30}]
    lca = SimulationBackend().run(model, _SCENARIO)["outputs"]["lca"]
    # 250 tCO2 × $30 = $7,500.
    assert lca["cost"]["carbon"] == pytest.approx(7500.0)


@pytest.mark.slow
def test_green_steel_as_is_lifecycle_inventory() -> None:
    """The shipped green-steel example yields a steel-dominated cradle-to-gate LCA."""
    wb = parse_sqlite((files("pathwise.assets.examples") / "green_steel_chain.sqlite").read_bytes())
    res = SimulationBackend().run(
        wb, {"economics": {"base_year": 2025}, "solver": {"mip_gap": 0.05}}
    )
    assert res["status"] == "optimal"
    lca = res["outputs"]["lca"]

    assert lca["functional_unit"]["commodity"] == "car"
    co2 = next(d for d in lca["by_impact"] if d["impact"] == "CO2")
    assert co2["total"] > 0 and co2["per_unit"] > 0

    co2_stages = {d["stage"]: d["total"] for d in lca["by_stage"] if d["impact"] == "CO2"}
    # The integrated steel mill dominates the car's cradle-to-gate footprint.
    assert max(co2_stages, key=lambda s: co2_stages[s]).endswith("kr_steel")
    # The stage decomposition reconstructs the engine's CO2 total.
    assert sum(co2_stages.values()) == pytest.approx(co2["total"], rel=1e-6)
