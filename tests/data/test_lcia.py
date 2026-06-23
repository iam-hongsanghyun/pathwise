"""LCIA factor library: bundled GWP method, CSV importers, and apply_lcia merge."""

from __future__ import annotations

import pytest

from pathwise.backends.simulation_backend import SimulationBackend
from pathwise.data.lcia import (
    apply_lcia,
    background_rows,
    characterisation_rows,
    load_background_csv,
    load_method_csv,
)

_SCENARIO = {"economics": {"base_year": 2025, "discount_rate": 0.0}}


def test_bundled_gwp_method() -> None:
    rows = characterisation_rows("ipcc_gwp100")
    cf = {(r["flow_impact_id"], r["category_id"]): r["factor"] for r in rows}
    assert cf[("CO2", "GWP")] == 1.0
    assert cf[("CH4", "GWP")] == 27.0
    assert cf[("N2O", "GWP")] == 273.0
    with pytest.raises(KeyError):
        characterisation_rows("nope")


def test_csv_importers() -> None:
    method = load_method_csv("flow_impact_id,category_id,factor\nSO2,AP,1.0\nNOx,AP,0.74\n")
    assert {(r["flow_impact_id"], r["category_id"]): r["factor"] for r in method} == {
        ("SO2", "AP"): 1.0,
        ("NOx", "AP"): 0.74,
    }
    bg = load_background_csv("commodity_id,impact_id,factor\nelectricity,CO2,0.35\n")
    assert bg == [{"commodity_id": "electricity", "impact_id": "CO2", "factor": 0.35}]


def test_background_rows_default_seed() -> None:
    rows = background_rows()
    assert {"commodity_id": "electricity", "impact_id": "CO2", "factor": 0.40} in rows


def test_apply_lcia_then_run_characterises() -> None:
    """A model with CO2+CH4 flows but no CFs → apply the GWP method → GWP appears."""
    model = {
        "periods": [{"year": 2025, "duration_years": 1}],
        "commodities": [
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 10},
            {"commodity_id": "widget", "kind": "product", "unit": "ea"},
        ],
        "impacts": [
            {"impact_id": "CO2", "unit": "tCO2"},
            {"impact_id": "CH4", "unit": "tCH4"},
            {"impact_id": "GWP", "unit": "tCO2e"},
        ],
        "technologies": [{"technology_id": "Plant", "actions": "continue"}],
        "nodes": [
            {"node_id": "co", "kind": "group", "level": "company", "label": "Co"},
            {"node_id": "co/p", "kind": "machine", "level": "machine", "parent_id": "co"},
        ],
        "machines": [{"machine_id": "co/p", "baseline_technology": "Plant", "capacity": 1000}],
        "io": [
            {"technology_id": "Plant", "target": "ore", "role": "input", "coefficient": 1.0},
            {
                "technology_id": "Plant",
                "target": "widget",
                "role": "output",
                "coefficient": 1.0,
                "is_product": 1,
            },
            {"technology_id": "Plant", "target": "CO2", "role": "impact", "coefficient": 2.0},
            {"technology_id": "Plant", "target": "CH4", "role": "impact", "coefficient": 0.1},
        ],
        "demand": [{"company": "co", "commodity_id": "widget", "year": 2025, "amount": 100}],
    }
    assert "characterisation" not in model
    enriched = apply_lcia(model, characterisation=characterisation_rows("ipcc_gwp100"))
    assert "characterisation" not in model  # input untouched
    lca = SimulationBackend().run(enriched, _SCENARIO)["outputs"]["lca"]
    by_impact = {d["impact"]: d["total"] for d in lca["by_impact"]}
    assert by_impact["GWP"] == pytest.approx(470.0)  # 200·1 + 10·27
