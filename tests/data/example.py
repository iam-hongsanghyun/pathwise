"""A tiny 2-facility process-network workbook used across tests.

Iron-making (F1) feeds steel-making (F2) via an `iron` stream; F2 makes the
final `steel` product. Energy streams (`coal`, `elec`) carry CO2 factors.
"""

from __future__ import annotations

from typing import Any

Workbook = dict[str, list[dict[str, Any]]]


def example_workbook() -> Workbook:
    """Return the canonical 2-facility example workbook."""
    return {
        "periods": [
            {"year": 2025, "duration_years": 1},
            {"year": 2030, "duration_years": 1},
        ],
        "flows": [
            {"flow_id": "coal", "kind": "energy", "unit": "MWh", "price": 30.0},
            {"flow_id": "elec", "kind": "energy", "unit": "MWh", "price": 80.0},
            {"flow_id": "ore", "kind": "material", "unit": "t", "price": 100.0},
            {"flow_id": "iron", "kind": "material", "unit": "t", "price": 0.0},
            {"flow_id": "steel", "kind": "product", "unit": "t", "price": 0.0},
            {"flow_id": "slag", "kind": "byproduct", "unit": "t", "sale_price": 5.0},
        ],
        "impacts": [
            {"impact_id": "CO2", "unit": "tCO2e"},
        ],
        "technologies": [
            {
                "technology_id": "BF",
                "lifespan": 25,
                "actions": "replace,renew,continue",
                "capex": 200.0,
                "renewal": 50.0,
                "opex": 10.0,
            },
            {
                "technology_id": "EAF",
                "lifespan": 20,
                "actions": "replace,renew,continue",
                "capex": 150.0,
                "renewal": 40.0,
                "opex": 12.0,
            },
        ],
        "processes": [
            {
                "process_id": "F1",
                "company": "Acme",
                "baseline_technology": "BF",
                "capacity": 1000.0,
                "introduced_year": 2010,
            },
            {
                "process_id": "F2",
                "company": "Acme",
                "baseline_technology": "EAF",
                "capacity": 1000.0,
                "introduced_year": 2012,
            },
        ],
        "process_inputs": [
            {"technology_id": "BF", "flow_id": "coal", "intensity": 4.0},
            {"technology_id": "BF", "flow_id": "ore", "intensity": 1.6},
            {"technology_id": "EAF", "flow_id": "iron", "intensity": 1.1},
            {"technology_id": "EAF", "flow_id": "elec", "intensity": 0.6},
        ],
        "process_outputs": [
            {"technology_id": "BF", "flow_id": "iron", "yield": 1.0, "is_product": False},
            {"technology_id": "BF", "flow_id": "slag", "yield": 0.3, "is_product": False},
            {"technology_id": "EAF", "flow_id": "steel", "yield": 1.0, "is_product": True},
        ],
        "flow_impacts": [
            {"flow_id": "coal", "impact_id": "CO2", "factor": 0.34},
            {"flow_id": "elec", "impact_id": "CO2", "factor": 0.05},
        ],
        "tech_impacts": [
            {"technology_id": "BF", "impact_id": "CO2", "factor": 1.2},
        ],
        "edges": [
            {"from_process": "F1", "to_process": "F2", "flow_id": "iron"},
        ],
        "levers": [
            {
                "lever_id": "M_eff",
                "type": "energy_efficiency",
                "applies_to": "F1",
                "target": "coal",
                "lifetime": 15,
            },
        ],
        "lever_blocks": [
            {"lever_id": "M_eff", "block": 0, "reduction": 0.1, "capex": 500.0},
        ],
        "transitions": [
            {
                "from_technology": "BF",
                "to_technology": "EAF",
                "action": "replace",
                "capex_per_capacity": 180.0,
                "compatible": True,
            },
        ],
        "demand": [
            {"company": "Acme", "flow_id": "steel", "year": 2025, "amount": 800.0},
            {"company": "Acme", "flow_id": "steel", "year": 2030, "amount": 900.0},
        ],
        "impact_caps": [
            {"company": "all", "impact_id": "CO2", "year": 2030, "limit": 5000.0},
        ],
        "impact_prices": [
            {"impact_id": "CO2", "year": 2025, "price": 50.0},
            {"impact_id": "CO2", "year": 2030, "price": 120.0},
        ],
    }
