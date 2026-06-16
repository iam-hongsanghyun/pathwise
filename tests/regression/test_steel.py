"""Regression: a realistic steel-decarbonisation pathway.

Iron-making (BF coal route) feeds steel-making (EAF). Over the horizon the
optimiser can (a) replace BF with H2-DRI, or (b) buy HBI/iron from a market and
idle the iron plant. A rising ETS price makes the coal route progressively
uneconomic, so the least-cost pathway decarbonises by the later years.
"""

from __future__ import annotations

import pytest

from pathwise.core import build, extract_results, solve
from pathwise.data import ScenarioConfig, assemble_problem

# A full 6-period decarbonisation pathway — heavy; skip in fast runs.
pytestmark = pytest.mark.slow

YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


def steel_workbook() -> dict:
    return {
        "periods": [{"year": y, "duration_years": 5} for y in YEARS],
        "commodities": [
            {"commodity_id": "coal", "kind": "energy", "unit": "t", "price": 40},
            {"commodity_id": "ore", "kind": "material", "unit": "t", "price": 100},
            {"commodity_id": "elec", "kind": "energy", "unit": "MWh", "price": 70},
            {"commodity_id": "h2", "kind": "energy", "unit": "t", "price": 200},
            {"commodity_id": "iron", "kind": "material", "unit": "t"},
            {"commodity_id": "steel", "kind": "product", "unit": "t"},
        ],
        "impacts": [{"impact_id": "CO2", "unit": "tCO2e"}],
        "technologies": [
            {"technology_id": "BF", "lifespan": 40, "actions": "continue,replace", "opex": 20},
            {"technology_id": "H2DRI", "lifespan": 30, "actions": "continue,replace", "opex": 25},
            {"technology_id": "EAF", "lifespan": 30, "actions": "continue", "opex": 30},
        ],
        "processes": [
            {
                "process_id": "IRON",
                "company": "Steelco",
                "baseline_technology": "BF",
                "capacity": 1200,
                "fixed_opex": 1000,
            },
            {
                "process_id": "STEEL",
                "company": "Steelco",
                "baseline_technology": "EAF",
                "capacity": 1200,
                "fixed_opex": 1000,
            },
        ],
        "io": [
            {"technology_id": "BF", "target": "coal", "role": "input", "coefficient": 5},
            {"technology_id": "BF", "target": "ore", "role": "input", "coefficient": 1.5},
            {"technology_id": "BF", "target": "iron", "role": "output", "coefficient": 1},
            {"technology_id": "BF", "target": "CO2", "role": "impact", "coefficient": 1.8},
            {"technology_id": "H2DRI", "target": "h2", "role": "input", "coefficient": 3},
            {"technology_id": "H2DRI", "target": "ore", "role": "input", "coefficient": 1.4},
            {"technology_id": "H2DRI", "target": "iron", "role": "output", "coefficient": 1},
            {"technology_id": "H2DRI", "target": "CO2", "role": "impact", "coefficient": 0.1},
            {"technology_id": "EAF", "target": "iron", "role": "input", "coefficient": 1.05},
            {"technology_id": "EAF", "target": "elec", "role": "input", "coefficient": 0.6},
            {
                "technology_id": "EAF",
                "target": "steel",
                "role": "output",
                "coefficient": 1,
                "is_product": True,
            },
        ],
        "commodity_impacts": [
            {"commodity_id": "coal", "impact_id": "CO2", "factor": 0.3},
            {"commodity_id": "elec", "impact_id": "CO2", "factor": 0.2},
        ],
        "edges": [{"from_process": "IRON", "to_process": "STEEL", "commodity_id": "iron"}],
        "transitions": [
            {
                "from_technology": "BF",
                "to_technology": "H2DRI",
                "action": "replace",
                "capex_per_capacity": 300,
                "compatible": True,
            },
        ],
        "markets": [
            {
                "market_id": "HBI",
                "target": "iron",
                "target_kind": "commodity",
                "price": 520,
                "tag": "imported",
            },
            {
                "market_id": "ETS",
                "target": "CO2",
                "target_kind": "impact",
                "company": "all",
                "price": 30,
            },
        ],
        # H2 gets cheaper; the ETS price climbs steeply — both push off coal.
        "commodities_t__price": [
            {"year": 2025, "h2": 200},
            {"year": 2050, "h2": 60},
        ],
        "markets_t__price": [
            {"year": 2025, "ETS": 30},
            {"year": 2050, "ETS": 260},
        ],
        "demand": [
            {"company": "Steelco", "commodity_id": "steel", "year": y, "amount": 1000}
            for y in YEARS
        ],
    }


def test_steel_pathway_solves_and_decarbonises() -> None:
    sc = ScenarioConfig.from_dict(
        {"economics": {"base_year": 2025, "discount_rate": 0.05}, "domain": "process"}
    )
    res = extract_results(solve(build(assemble_problem(steel_workbook(), sc))))
    assert res["status"] == "optimal"

    # Steel demand met every year.
    assert res["outputs"]["demand_slack"] == []

    # Early on the coal blast furnace runs; by 2050 the route has decarbonised —
    # either H2-DRI replaces BF, or iron (HBI) is bought and the BF idled.
    tech = {(c["process"], c["period"]): c["technology"] for c in res["outputs"]["technology"]}
    assert tech.get(("IRON", 2025)) == "BF"
    hbi_2050 = next((m for m in res["outputs"]["markets"] if m["market"] == "HBI"), None)
    bought_iron_2050 = bool(hbi_2050) and any(
        b["period"] == 2050 and b["buy"] > 1 for b in hbi_2050["by_period"]
    )
    switched_2050 = tech.get(("IRON", 2050)) == "H2DRI"
    assert switched_2050 or bought_iron_2050

    # Per-year cost + commodity consumption series are populated for analytics.
    assert all("cost" in p for p in res["summary"]["periods"])
    assert any(s["commodity"] == "coal" and s["consumed"] > 0 for s in res["summary"]["commodity"])


def test_steel_emissions_fall_by_2050() -> None:
    sc = ScenarioConfig.from_dict({"economics": {"base_year": 2025, "discount_rate": 0.05}})
    res = extract_results(solve(build(assemble_problem(steel_workbook(), sc))))
    co2 = {s["period"]: s["total"] for s in res["summary"]["impacts"] if s["impact"] == "CO2"}
    assert co2[2050] < co2[2025]  # decarbonised
