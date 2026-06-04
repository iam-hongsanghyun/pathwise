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
    "process_inputs",
    "process_outputs",
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
    "demand": {
        "label": "Product demand",
        "columns": {
            "company": {"label": "Company", "type": "string", "required": True},
            "commodity_id": {"label": "Product", "type": "string", "required": True},
            "year": {"label": "Year", "type": "integer", "required": True},
            "amount": {"label": "Demand (/yr)", "type": "number", "required": True},
        },
    },
    "impact_caps": {
        "label": "Impact caps",
        "columns": {
            "company": {"label": "Company (or all)", "type": "string"},
            "impact_id": {"label": "Impact", "type": "string", "required": True},
            "year": {"label": "Year", "type": "integer", "required": True},
            "limit": {"label": "Limit (/yr)", "type": "number", "required": True},
        },
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
