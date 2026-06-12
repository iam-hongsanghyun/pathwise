"""A compact, synthetic 3-stage aluminium chain (no external source data).

A clean teaching example of a multi-stage process network:

    Stage 1  Refinery  : bauxite + (gas | H2)        → alumina
    Stage 2  Smelter   : alumina + (grid | RE elec)  → liquid aluminium
    Stage 3  Caster    : liquid aluminium + (gas | elec) → aluminium (product)

Each stage has one baseline technology and one lower-carbon transition target, so
the model exercises routing (edges between stages), a rising carbon price, a
declining CO2 cap, and — for the portfolio backend — three candidate switches.

Run:  uv run python examples/converters/aluminium.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer import Workbook, verify, write_workbook

OUT = Path(__file__).resolve().parents[2] / "frontend/pathwise/public/examples/aluminium.xlsx"
YEARS = [2025, 2030, 2035]


def build_workbook() -> Workbook:
    """Assemble the 3-stage aluminium workbook (all data inline)."""
    commodities = [
        {"commodity_id": "bauxite", "kind": "material", "unit": "t", "price": 45.0},
        {"commodity_id": "alumina", "kind": "material", "unit": "t"},  # intermediate (routed)
        {"commodity_id": "liquid_aluminium", "kind": "material", "unit": "t"},  # intermediate
        {"commodity_id": "aluminium", "kind": "product", "unit": "t"},
        {"commodity_id": "gas", "kind": "energy", "unit": "MWh", "price": 28.0},
        {"commodity_id": "grid_elec", "kind": "energy", "unit": "MWh", "price": 75.0},
        {"commodity_id": "re_elec", "kind": "energy", "unit": "MWh", "price": 95.0},
        {"commodity_id": "hydrogen", "kind": "energy", "unit": "MWh", "price": 120.0},
    ]
    commodity_impacts = [
        {"commodity_id": "gas", "impact_id": "CO2", "factor": 0.20},
        {"commodity_id": "grid_elec", "impact_id": "CO2", "factor": 0.42},
        {"commodity_id": "re_elec", "impact_id": "CO2", "factor": 0.0},
        {"commodity_id": "hydrogen", "impact_id": "CO2", "factor": 0.0},
    ]

    # Per-unit-throughput coefficients (throughput unit = output tonne).
    technologies = [
        {
            "technology_id": "Refine_Gas",
            "lifespan": 25,
            "actions": "continue,replace,renew",
            "opex": 16.0,
        },
        {
            "technology_id": "Refine_H2",
            "lifespan": 25,
            "actions": "continue,replace,renew",
            "opex": 24.0,
        },
        {
            "technology_id": "Smelt_Grid",
            "lifespan": 30,
            "actions": "continue,replace,renew",
            "opex": 30.0,
        },
        {
            "technology_id": "Smelt_RE",
            "lifespan": 30,
            "actions": "continue,replace,renew",
            "opex": 34.0,
        },
        {
            "technology_id": "Cast_Gas",
            "lifespan": 20,
            "actions": "continue,replace,renew",
            "opex": 8.0,
        },
        {
            "technology_id": "Cast_Elec",
            "lifespan": 20,
            "actions": "continue,replace,renew",
            "opex": 9.0,
        },
    ]
    io = [
        # Stage 1 — refining: bauxite + fuel → alumina
        {"technology_id": "Refine_Gas", "target": "bauxite", "role": "input", "coefficient": 1.9},
        {"technology_id": "Refine_Gas", "target": "gas", "role": "input", "coefficient": 3.0},
        {"technology_id": "Refine_Gas", "target": "alumina", "role": "output", "coefficient": 1.0},
        {"technology_id": "Refine_H2", "target": "bauxite", "role": "input", "coefficient": 1.9},
        {"technology_id": "Refine_H2", "target": "hydrogen", "role": "input", "coefficient": 3.2},
        {"technology_id": "Refine_H2", "target": "alumina", "role": "output", "coefficient": 1.0},
        # Stage 2 — smelting: alumina + electricity → liquid aluminium
        {"technology_id": "Smelt_Grid", "target": "alumina", "role": "input", "coefficient": 1.9},
        {
            "technology_id": "Smelt_Grid",
            "target": "grid_elec",
            "role": "input",
            "coefficient": 14.0,
        },
        {
            "technology_id": "Smelt_Grid",
            "target": "liquid_aluminium",
            "role": "output",
            "coefficient": 1.0,
        },
        {"technology_id": "Smelt_RE", "target": "alumina", "role": "input", "coefficient": 1.9},
        {"technology_id": "Smelt_RE", "target": "re_elec", "role": "input", "coefficient": 14.0},
        {
            "technology_id": "Smelt_RE",
            "target": "liquid_aluminium",
            "role": "output",
            "coefficient": 1.0,
        },
        # Stage 3 — casting: liquid aluminium + fuel → aluminium (product)
        {
            "technology_id": "Cast_Gas",
            "target": "liquid_aluminium",
            "role": "input",
            "coefficient": 1.02,
        },
        {"technology_id": "Cast_Gas", "target": "gas", "role": "input", "coefficient": 1.5},
        {
            "technology_id": "Cast_Gas",
            "target": "aluminium",
            "role": "output",
            "coefficient": 1.0,
            "is_product": True,
        },
        {
            "technology_id": "Cast_Elec",
            "target": "liquid_aluminium",
            "role": "input",
            "coefficient": 1.02,
        },
        {"technology_id": "Cast_Elec", "target": "grid_elec", "role": "input", "coefficient": 2.0},
        {
            "technology_id": "Cast_Elec",
            "target": "aluminium",
            "role": "output",
            "coefficient": 1.0,
            "is_product": True,
        },
    ]
    processes = [
        {
            "process_id": "Refinery",
            "company": "AluCo",
            "baseline_technology": "Refine_Gas",
            "capacity": 350.0,
        },
        {
            "process_id": "Smelter",
            "company": "AluCo",
            "baseline_technology": "Smelt_Grid",
            "capacity": 220.0,
        },
        {
            "process_id": "Caster",
            "company": "AluCo",
            "baseline_technology": "Cast_Gas",
            "capacity": 200.0,
        },
    ]
    edges = [
        {"from_process": "Refinery", "to_process": "Smelter", "commodity_id": "alumina"},
        {"from_process": "Smelter", "to_process": "Caster", "commodity_id": "liquid_aluminium"},
    ]
    transitions = [
        {
            "from_technology": "Refine_Gas",
            "to_technology": "Refine_H2",
            "action": "replace",
            "capex_per_capacity": 320.0,
        },
        {
            "from_technology": "Smelt_Grid",
            "to_technology": "Smelt_RE",
            "action": "replace",
            "capex_per_capacity": 260.0,
        },
        {
            "from_technology": "Cast_Gas",
            "to_technology": "Cast_Elec",
            "action": "replace",
            "capex_per_capacity": 120.0,
        },
    ]
    demand = [
        {"company": "AluCo", "commodity_id": "aluminium", "year": y, "amount": 150.0} for y in YEARS
    ]
    # Rising carbon price + a declining CO2 cap make the low-carbon switches pay.
    impact_prices = [
        {"impact_id": "CO2", "year": 2025, "price": 30.0},
        {"impact_id": "CO2", "year": 2030, "price": 65.0},
        {"impact_id": "CO2", "year": 2035, "price": 110.0},
    ]
    impact_caps = [
        {
            "company": "all",
            "impact_id": "CO2",
            "year": 2030,
            "limit": 2400.0,
            "soft": True,
            "penalty": 5.0e3,
        },
        {
            "company": "all",
            "impact_id": "CO2",
            "year": 2035,
            "limit": 1600.0,
            "soft": True,
            "penalty": 5.0e3,
        },
    ]

    return {
        "meta": [
            {"key": "title", "value": "Aluminium — 3-stage chain (refine → smelt → cast)"},
            {"key": "base_year", "value": YEARS[0]},
        ],
        "periods": [{"year": y, "duration_years": 1} for y in YEARS],
        "commodities": commodities,
        "impacts": [{"impact_id": "CO2", "unit": "tCO2"}],
        "commodity_impacts": commodity_impacts,
        "technologies": technologies,
        "io": io,
        "processes": processes,
        "edges": edges,
        "transitions": transitions,
        "demand": demand,
        "impact_prices": impact_prices,
        "impact_caps": impact_caps,
    }


def main() -> None:
    wb = build_workbook()
    verify(wb, "aluminium")
    write_workbook(wb, OUT)
    print(f"[aluminium] wrote {OUT}  ({sum(len(v) for v in wb.values())} rows, {len(wb)} sheets)")


if __name__ == "__main__":
    main()
