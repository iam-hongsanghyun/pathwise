"""Shipping workbook schema and terminology.

Shipping uses the canonical generic sheets; this module documents the columns
the shipping pack expects and the sector vocabulary the UI should display.
"""

from __future__ import annotations

from typing import Any

#: Sheets that must be present for a shipping run.
REQUIRED_SHEETS: list[str] = [
    "assets",
    "technologies",
    "carriers",
    "carrier_compatibility",
    "periods",
]

#: Sector vocabulary overrides for generic concepts.
TERMINOLOGY: dict[str, str] = {
    "asset": "Ship",
    "technology": "Engine",
    "carrier": "Fuel",
    "measure": "Efficiency measure",
    "group": "Operator",
    "period": "Year",
    "target": "GFI limit",
    "intensity": "GHG intensity (gCO2e/MJ)",
    "size": "Gross tonnage",
    "activity": "Annual energy (MJ)",
}

#: Column descriptors per sheet (drives the frontend grid + tooltips).
SCHEMA: dict[str, Any] = {
    "assets": {
        "label": "Ships",
        "columns": {
            "asset_id": {"label": "Ship", "type": "string", "required": True},
            "group": {"label": "Operator", "type": "string", "required": True},
            "capacity": {"label": "Capacity (MJ/yr)", "type": "number"},
            "size": {"label": "Gross tonnage", "type": "number"},
            "technology_id": {"label": "Engine", "type": "string", "required": True},
            "built_year": {"label": "Built", "type": "integer"},
            "retire_year": {"label": "Retire", "type": "integer"},
            "activity": {"label": "Annual energy (MJ)", "type": "number"},
            "is_candidate": {"label": "New build slot", "type": "boolean"},
        },
    },
    "technologies": {
        "label": "Engines",
        "columns": {
            "technology_id": {"label": "Engine", "type": "string", "required": True},
            "specific_energy": {"label": "MJ per activity", "type": "number"},
            "fixed_opex": {"label": "Fixed O&M (USD/GT/yr)", "type": "number"},
        },
    },
    "carriers": {
        "label": "Fuels",
        "columns": {
            "carrier_id": {"label": "Fuel", "type": "string", "required": True},
            "intensity": {"label": "WtW intensity (gCO2e/MJ)", "type": "number"},
            "cost": {"label": "Price (USD/MJ)", "type": "number"},
            "class": {"label": "Fuel class", "type": "string"},
        },
    },
    "carrier_compatibility": {
        "label": "Engine–fuel pairing",
        "columns": {
            "technology_id": {"label": "Engine", "type": "string", "required": True},
            "carrier_id": {"label": "Fuel", "type": "string", "required": True},
        },
    },
    "baseline_mix": {
        "label": "Baseline fuel mix",
        "columns": {
            "technology_id": {"label": "Engine", "type": "string"},
            "carrier_id": {"label": "Fuel", "type": "string"},
            "share": {"label": "Share", "type": "number"},
        },
    },
    "periods": {
        "label": "Years",
        "columns": {
            "year": {"label": "Year", "type": "integer", "required": True},
            "duration_years": {"label": "Duration (yr)", "type": "number"},
            "activity_multiplier": {"label": "Activity multiplier", "type": "number"},
        },
    },
    "transitions": {
        "label": "Engine retrofits",
        "columns": {
            "from_technology_id": {"label": "From engine", "type": "string"},
            "to_technology_id": {"label": "To engine", "type": "string"},
            "capex_per_size": {"label": "Retrofit CAPEX (USD/GT)", "type": "number"},
            "lifetime": {"label": "Lifetime (yr)", "type": "integer"},
            "earliest_year": {"label": "Earliest year", "type": "integer"},
        },
    },
    "measures": {
        "label": "Efficiency measures (MACC)",
        "columns": {
            "measure_id": {"label": "Measure", "type": "string"},
            "applicable_asset": {"label": "Applies to ship", "type": "string"},
            "block": {"label": "Block", "type": "integer"},
            "abatement": {"label": "Abatement (tCO2e/yr)", "type": "number"},
            "capex": {"label": "CAPEX (USD)", "type": "number"},
            "lifetime": {"label": "Lifetime (yr)", "type": "integer"},
        },
    },
    "new_build_options": {
        "label": "New ship options",
        "columns": {
            "option_id": {"label": "Option", "type": "string"},
            "group": {"label": "Operator", "type": "string"},
            "technology_id": {"label": "Engine", "type": "string"},
            "capacity": {"label": "Capacity (MJ/yr)", "type": "number"},
            "unit_capex": {"label": "Unit CAPEX (USD/GT)", "type": "number"},
            "max_units": {"label": "Max units", "type": "integer"},
            "lead_time": {"label": "Lead time (yr)", "type": "integer"},
        },
    },
    "targets": {
        "label": "GFI limits",
        "columns": {
            "target_set": {"label": "Scenario", "type": "string"},
            "group": {"label": "Operator", "type": "string"},
            "target_type": {"label": "Type", "type": "string"},
            "year": {"label": "Year", "type": "integer"},
            "limit": {"label": "Limit", "type": "number"},
        },
    },
    "carbon_price": {
        "label": "Carbon price",
        "columns": {
            "price_set": {"label": "Set", "type": "string"},
            "year": {"label": "Year", "type": "integer"},
            "price": {"label": "USD/tCO2e", "type": "number"},
        },
    },
}
