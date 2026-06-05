"""Workbook schema for the process-network model.

Declares the sheets and columns the assembler expects and the UI renders. This
is the contract the React Flow designer and the editable tables both target.
"""

from __future__ import annotations

from typing import Any

#: Sheets that must be present for a run.
REQUIRED_SHEETS: list[str] = [
    "periods",
    "commodities",
    "technologies",
    "processes",
    "demand",
]

#: UI label overrides for generic concepts.
TERMINOLOGY: dict[str, str] = {
    "process": "Facility",
    "technology": "Technology",
    "commodity": "Stream",
    "impact": "Environmental impact",
    "measure": "Measure (MACC)",
    "company": "Company",
    "throughput": "Production",
}

#: Column descriptors per sheet (drives the frontend grid + tooltips/validation).
SCHEMA: dict[str, Any] = {
    "periods": {
        "label": "Years",
        "columns": {
            "year": {"label": "Year", "type": "integer", "required": True},
            "duration_years": {"label": "Duration (yr)", "type": "number"},
        },
    },
    "commodities": {
        "label": "Streams",
        "columns": {
            "commodity_id": {"label": "Stream", "type": "string", "required": True},
            "kind": {"label": "Kind", "type": "string", "required": True},
            "unit": {"label": "Unit", "type": "string"},
            "price": {"label": "Purchase price (/unit)", "type": "number"},
            "sale_price": {"label": "Sale price (/unit)", "type": "number"},
            "sellable": {"label": "Sellable", "type": "boolean"},
            "purchasable": {"label": "Purchasable", "type": "boolean"},
        },
    },
    "impacts": {
        "label": "Impacts",
        "columns": {
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "unit": {"label": "Unit", "type": "string"},
        },
    },
    "technologies": {
        "label": "Technologies",
        "columns": {
            "technology_id": {"label": "Technology", "type": "string", "required": True},
            "lifespan": {"label": "Lifespan (yr)", "type": "integer"},
            "introduction_year": {"label": "Available from", "type": "integer"},
            "actions": {"label": "Actions (replace,renew,continue)", "type": "string"},
            "capex": {"label": "Replace CAPEX (/cap)", "type": "number"},
            "renewal": {"label": "Renewal cost (/cap)", "type": "number"},
            "opex": {"label": "Fixed O&M (/throughput)", "type": "number"},
        },
    },
    "processes": {
        "label": "Facilities",
        "columns": {
            "process_id": {"label": "Facility", "type": "string", "required": True},
            "company": {"label": "Company", "type": "string", "required": True},
            "baseline_technology": {"label": "Baseline tech", "type": "string", "required": True},
            "capacity": {"label": "Capacity (throughput/yr)", "type": "number"},
            "introduced_year": {"label": "Installed", "type": "integer"},
            "capex": {"label": "Build CAPEX", "type": "number"},
            "fixed_opex": {"label": "Fixed O&M (/yr)", "type": "number"},
            "failure_rate": {"label": "Failure rate (0-1)", "type": "number"},
            "replaceable": {"label": "Replaceable", "type": "boolean"},
        },
    },
    "company_config": {
        "label": "Company settings",
        "columns": {
            "company": {"label": "Company", "type": "string", "required": True},
            "objective": {"label": "Objective (cost|profit)", "type": "string"},
        },
    },
    "process_inputs": {
        "label": "Technology inputs",
        "columns": {
            "technology_id": {"label": "Technology", "type": "string", "required": True},
            "commodity_id": {"label": "Input stream", "type": "string", "required": True},
            "intensity": {"label": "Use per throughput", "type": "number", "required": True},
        },
    },
    "process_outputs": {
        "label": "Technology outputs",
        "columns": {
            "technology_id": {"label": "Technology", "type": "string", "required": True},
            "commodity_id": {"label": "Output stream", "type": "string", "required": True},
            "yield": {"label": "Yield per throughput", "type": "number", "required": True},
            "is_product": {"label": "Is product", "type": "boolean"},
        },
    },
    "technologies_t__capex": {
        "label": "Technology CAPEX · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "technologies_t__opex": {
        "label": "Technology O&M · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "technologies_t__renewal": {
        "label": "Technology renewal · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "io": {
        "label": "Technology I/O (unified)",
        "columns": {
            "technology_id": {"label": "Technology", "type": "string", "required": True},
            "target": {"label": "Stream / impact", "type": "string", "required": True},
            "role": {"label": "Role (input|output|impact)", "type": "string", "required": True},
            "coefficient": {"label": "Per throughput", "type": "number", "required": True},
            "is_product": {"label": "Is product", "type": "boolean"},
        },
    },
    "commodities_t__price": {
        "label": "Stream price · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "commodities_t__sale_price": {
        "label": "Stream sale price · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "impacts_t__price": {
        "label": "Impact price · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "markets_t__price": {
        "label": "Market buy price · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "markets_t__sell_price": {
        "label": "Market sell price · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "markets_t__allocation": {
        "label": "ETS allocation · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "tech_impacts": {
        "label": "Direct (process) impacts",
        "columns": {
            "technology_id": {"label": "Technology", "type": "string", "required": True},
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "factor": {"label": "Impact per throughput", "type": "number", "required": True},
        },
    },
    "commodity_impacts": {
        "label": "Stream impact factors",
        "columns": {
            "commodity_id": {"label": "Stream", "type": "string", "required": True},
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "factor": {"label": "Impact per unit", "type": "number", "required": True},
        },
    },
    "edges": {
        "label": "Flows between facilities",
        "columns": {
            "from_process": {"label": "From facility", "type": "string", "required": True},
            "to_process": {"label": "To facility", "type": "string", "required": True},
            "commodity_id": {"label": "Stream", "type": "string", "required": True},
            "max_flow": {"label": "Max flow (/yr)", "type": "number"},
        },
    },
    "measures": {
        "label": "Measures (MACC)",
        "columns": {
            "measure_id": {"label": "Measure", "type": "string", "required": True},
            "type": {"label": "Type", "type": "string", "required": True},
            "applies_to": {"label": "On facility", "type": "string", "required": True},
            "target": {"label": "Target stream/impact", "type": "string", "required": True},
            "lifetime": {"label": "Lifetime (yr)", "type": "integer"},
        },
    },
    "measure_blocks": {
        "label": "Measure cost curve",
        "columns": {
            "measure_id": {"label": "Measure", "type": "string", "required": True},
            "block": {"label": "Block", "type": "integer", "required": True},
            "reduction": {"label": "Reduction (frac)", "type": "number", "required": True},
            "capex": {"label": "CAPEX", "type": "number", "required": True},
        },
    },
    "transitions": {
        "label": "Technology transitions",
        "columns": {
            "from_technology": {"label": "From tech", "type": "string", "required": True},
            "to_technology": {"label": "To tech", "type": "string", "required": True},
            "action": {"label": "Action", "type": "string"},
            "capex_per_capacity": {"label": "CAPEX (/cap)", "type": "number"},
            "compatible": {"label": "Reusable (compatible)", "type": "boolean"},
        },
    },
    "storage": {
        "label": "Storage",
        "columns": {
            "storage_id": {"label": "Store", "type": "string", "required": True},
            "commodity_id": {"label": "Stream", "type": "string", "required": True},
            "company": {"label": "Company (or all)", "type": "string"},
            "max_capacity": {"label": "Max capacity", "type": "number"},
            "capex_per_capacity": {"label": "CAPEX (/capacity)", "type": "number"},
            "fixed_opex_per_capacity": {"label": "Fixed O&M (/capacity/yr)", "type": "number"},
            "charge_efficiency": {"label": "Charge eff (0-1)", "type": "number"},
            "discharge_efficiency": {"label": "Discharge eff (0-1)", "type": "number"},
            "standing_loss": {"label": "Standing loss (/yr)", "type": "number"},
            "initial_level": {"label": "Initial level", "type": "number"},
        },
    },
    "markets": {
        "label": "Markets",
        "columns": {
            "market_id": {"label": "Market", "type": "string", "required": True},
            "target": {"label": "Stream / impact", "type": "string", "required": True},
            "target_kind": {"label": "Kind (commodity|impact)", "type": "string"},
            "company": {"label": "Company (or all)", "type": "string"},
            "price": {"label": "Buy price (/unit)", "type": "number"},
            "sell_price": {"label": "Sell price (/unit)", "type": "number"},
            "max_buy": {"label": "Max buy (/yr)", "type": "number"},
            "max_sell": {"label": "Max sell (/yr)", "type": "number"},
            "allocation": {"label": "ETS allocation (/yr)", "type": "number"},
            "tag": {"label": "Tag (e.g. RE100)", "type": "string"},
        },
    },
    "market_prices": {
        "label": "Market price trajectory",
        "columns": {
            "market_id": {"label": "Market", "type": "string", "required": True},
            "year": {"label": "Year", "type": "integer", "required": True},
            "price": {"label": "Buy price", "type": "number"},
            "sell_price": {"label": "Sell price", "type": "number"},
            "allocation": {"label": "Allocation", "type": "number"},
        },
    },
    "investment_budget": {
        "label": "Investment budget",
        "columns": {
            "budget_id": {"label": "Budget", "type": "string"},
            "company": {"label": "Company (or all)", "type": "string"},
            "year": {"label": "Year (legacy)", "type": "integer"},
            "limit": {"label": "Max CAPEX (legacy /yr)", "type": "number"},
        },
    },
    "investment_budget_t__limit": {
        "label": "Investment budget · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "min_production": {
        "label": "Minimum production",
        "columns": {
            "min_id": {"label": "Floor", "type": "string"},
            "company": {"label": "Company (or all)", "type": "string"},
            "commodity_id": {"label": "Product", "type": "string", "required": True},
            "year": {"label": "Year (legacy)", "type": "integer"},
            "amount": {"label": "Min produced (legacy /yr)", "type": "number"},
        },
    },
    "min_production_t__amount": {
        "label": "Minimum production · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "demand": {
        "label": "Product demand",
        "columns": {
            "demand_id": {"label": "Demand", "type": "string"},
            "company": {"label": "Company", "type": "string", "required": True},
            "commodity_id": {"label": "Product", "type": "string", "required": True},
            "year": {"label": "Year (legacy)", "type": "integer"},
            "amount": {"label": "Demand (legacy /yr)", "type": "number"},
        },
    },
    "demand_t__amount": {
        "label": "Demand · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "impact_caps": {
        "label": "Impact caps",
        "columns": {
            "cap_id": {"label": "Cap", "type": "string"},
            "company": {"label": "Company (or all)", "type": "string"},
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "year": {"label": "Year (legacy)", "type": "integer"},
            "limit": {"label": "Limit (legacy /yr)", "type": "number"},
        },
    },
    "impact_caps_t__limit": {
        "label": "Impact caps · by year",
        "columns": {"year": {"label": "Year", "type": "integer", "required": True}},
    },
    "impact_prices": {
        "label": "Impact prices (carbon/ETS)",
        "columns": {
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "year": {"label": "Year", "type": "integer", "required": True},
            "price": {"label": "Price (/unit)", "type": "number", "required": True},
        },
    },
    "commodity_prices": {
        "label": "Stream price trajectory",
        "columns": {
            "commodity_id": {"label": "Stream", "type": "string", "required": True},
            "year": {"label": "Year", "type": "integer", "required": True},
            "price": {"label": "Purchase price", "type": "number"},
            "sale_price": {"label": "Sale price", "type": "number"},
        },
    },
}
