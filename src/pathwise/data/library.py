"""Facility-template library — the format contract and chain instantiation.

The library is a set of static JSON files (one per sector, served to the
frontend like the example workbooks) holding **prebuilt facility archetypes**
(inputs, outputs incl. slates, costs, emission factors, alternatives) and
**process chains** (ordered stages wired by intermediate streams). Users insert
them into a model instead of authoring cross-referenced tables by hand.

Every facility and chain **must carry a reference** (``source.url``): values are
only as credible as their citation, so an uncited entry is a validation error,
not a style issue. These pydantic models are the single source of truth for the
format — the CI test validates every shipped JSON file against them, and
:func:`instantiate_chain` proves each chain assembles into a solvable workbook.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pathwise.data.workbook import Workbook


class SourceRef(BaseModel):
    """Citation for a template's coefficients (mandatory).

    Attributes:
        name: Human-readable source (report / dataset / paper title).
        url: Reference link — required and must be a http(s) URL.
        year: Publication / data year.
        region: Geographic basis (e.g. ``"global"``, ``"KR"``, ``"EU"``).
        basis: What the numbers represent (e.g. ``"BAT plant average"``,
            ``"illustrative"``).
        notes: Optional caveats.
    """

    name: str = Field(min_length=3)
    url: str
    year: int = Field(ge=1900, le=2100)
    region: str = "global"
    basis: str = "indicative"
    notes: str | None = None

    @field_validator("url")
    @classmethod
    def _http_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("source.url must be a http(s) reference link")
        return v


class IoRow(BaseModel):
    """One technology input/output/impact coefficient (mirrors the io sheet)."""

    target: str
    role: str = Field(pattern="^(input|output|impact)$")
    coefficient: float
    is_product: bool = False
    group: str | None = None  # blend group (inputs) or slate group (outputs)
    share_min: float | None = Field(default=None, ge=0.0, le=1.0)
    share_max: float | None = Field(default=None, ge=0.0, le=1.0)


class TechnologyTemplate(BaseModel):
    """A technology recipe: costs + per-unit-throughput coefficients."""

    technology_id: str
    lifespan: int = Field(default=20, ge=1)
    capex: float = 0.0  # replacement capex [currency / unit capacity]
    opex: float = 0.0  # fixed O&M [currency / unit throughput]
    io: list[IoRow] = Field(min_length=1)


class Alternative(BaseModel):
    """A lower-carbon technology the facility may transition to."""

    technology: TechnologyTemplate
    transition_capex_per_capacity: float = 0.0


class CommodityTemplate(BaseModel):
    """A stream the sector's facilities consume or produce."""

    commodity_id: str
    kind: str = Field(pattern="^(energy|material|indirect|product|byproduct)$")
    unit: str = "unit"
    price: float | None = None
    sale_price: float | None = None


class FacilityTemplate(BaseModel):
    """A prebuilt facility archetype: baseline technology + alternatives."""

    facility_id: str
    label: str
    description: str = ""
    technology: TechnologyTemplate
    alternatives: list[Alternative] = Field(default_factory=list)
    default_capacity: float = Field(default=1000.0, gt=0.0)
    source: SourceRef


class ChainStage(BaseModel):
    """One stage of a process chain; ``feeds`` name the upstream stages."""

    facility: str
    feeds: list[str] = Field(default_factory=list)


class DemandHint(BaseModel):
    """Suggested demand when a chain is instantiated."""

    commodity_id: str
    amount: float = Field(gt=0.0)


class ChainTemplate(BaseModel):
    """A predefined multi-stage route through the sector's facilities."""

    chain_id: str
    label: str
    description: str = ""
    stages: list[ChainStage] = Field(min_length=1)
    demand_hint: DemandHint | None = None
    source: SourceRef


class SectorLibrary(BaseModel):
    """All templates for one sector."""

    sector: str
    label: str
    commodities: list[CommodityTemplate] = Field(default_factory=list)
    facilities: list[FacilityTemplate] = Field(min_length=1)
    chains: list[ChainTemplate] = Field(default_factory=list)

    def facility(self, facility_id: str) -> FacilityTemplate:
        """Look up a facility template by id."""
        for f in self.facilities:
            if f.facility_id == facility_id:
                return f
        raise KeyError(f"unknown facility template '{facility_id}'")


def load_sector(path: str | Path) -> SectorLibrary:
    """Load and validate one sector library JSON file."""
    with open(path, encoding="utf-8") as fh:
        return SectorLibrary.model_validate(json.load(fh))


def _io_rows(tech: TechnologyTemplate) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in tech.io:
        row: dict[str, Any] = {
            "technology_id": tech.technology_id,
            "target": r.target,
            "role": r.role,
            "coefficient": r.coefficient,
        }
        if r.is_product:
            row["is_product"] = True
        if r.group is not None:
            row["group"] = r.group
            row["share_min"] = r.share_min if r.share_min is not None else 0.0
            row["share_max"] = r.share_max if r.share_max is not None else 1.0
        rows.append(row)
    return rows


def _tech_row(tech: TechnologyTemplate) -> dict[str, Any]:
    return {
        "technology_id": tech.technology_id,
        "lifespan": tech.lifespan,
        "actions": "continue,replace,renew",
        "capex": tech.capex,
        "opex": tech.opex,
    }


def add_facility(
    workbook: Workbook,
    library: SectorLibrary,
    facility_id: str,
    *,
    process_id: str | None = None,
    company: str = "",
) -> Workbook:
    """Insert one facility template into ``workbook`` (pure; returns a new dict).

    Commodities are merged by id (existing rows win); a technology that already
    exists is reused (recipe/instance separation — many facilities may share an
    archetype); the process instance id is uniquified.
    """
    f = library.facility(facility_id)
    wb: Workbook = {k: list(v) for k, v in workbook.items()}
    wb.setdefault("commodities", [])
    wb.setdefault("technologies", [])
    wb.setdefault("io", [])
    wb.setdefault("processes", [])
    wb.setdefault("transitions", [])

    have_comm = {str(r.get("commodity_id")) for r in wb["commodities"]}
    referenced = {r.target for r in f.technology.io if r.role != "impact"}
    for alt in f.alternatives:
        referenced |= {r.target for r in alt.technology.io if r.role != "impact"}
    for c in library.commodities:
        if c.commodity_id in referenced and c.commodity_id not in have_comm:
            row: dict[str, Any] = {
                "commodity_id": c.commodity_id,
                "kind": c.kind,
                "unit": c.unit,
            }
            if c.price is not None:
                row["price"] = c.price
            if c.sale_price is not None:
                row["sale_price"] = c.sale_price
            wb["commodities"].append(row)
            have_comm.add(c.commodity_id)

    have_tech = {str(r.get("technology_id")) for r in wb["technologies"]}
    for tech in [f.technology, *(a.technology for a in f.alternatives)]:
        if tech.technology_id not in have_tech:
            wb["technologies"].append(_tech_row(tech))
            wb["io"].extend(_io_rows(tech))
            have_tech.add(tech.technology_id)

    have_trans = {
        (str(r.get("from_technology")), str(r.get("to_technology"))) for r in wb["transitions"]
    }
    for alt in f.alternatives:
        key = (f.technology.technology_id, alt.technology.technology_id)
        if key not in have_trans:
            wb["transitions"].append(
                {
                    "from_technology": key[0],
                    "to_technology": key[1],
                    "action": "replace",
                    "capex_per_capacity": alt.transition_capex_per_capacity,
                }
            )

    have_proc = {str(r.get("process_id")) for r in wb["processes"]}
    pid = process_id or f.label
    n = 2
    base_pid = pid
    while pid in have_proc:
        pid = f"{base_pid} {n}"
        n += 1
    wb["processes"].append(
        {
            "process_id": pid,
            "company": company,
            "baseline_technology": f.technology.technology_id,
            "capacity": f.default_capacity,
        }
    )
    return wb


def instantiate_chain(
    library: SectorLibrary,
    chain_id: str,
    *,
    company: str = "Library",
    year: int = 2025,
) -> Workbook:
    """Build a complete, runnable workbook from one chain template.

    Stages are inserted in order; consecutive-stage edges are derived from each
    stage's ``feeds`` (the routed commodity is the upstream technology's output
    that the downstream technology consumes). Demand comes from ``demand_hint``
    or defaults to half the final stage's capacity on its product output.

    Raises:
        ValueError: If a feed pair shares no commodity (a broken chain).
    """
    chain = next((c for c in library.chains if c.chain_id == chain_id), None)
    if chain is None:
        raise KeyError(f"unknown chain '{chain_id}'")

    wb: Workbook = {"periods": [{"year": year, "duration_years": 1}], "impacts": []}
    impacts: set[str] = set()
    pid_of: dict[str, str] = {}
    for stage in chain.stages:
        f = library.facility(stage.facility)
        wb = add_facility(wb, library, stage.facility, company=company)
        pid_of[stage.facility] = str(wb["processes"][-1]["process_id"])
        for tech in [f.technology, *(a.technology for a in f.alternatives)]:
            impacts |= {r.target for r in tech.io if r.role == "impact"}
    wb["impacts"] = [{"impact_id": i, "unit": "t"} for i in sorted(impacts)]

    wb.setdefault("edges", [])
    outputs_of = {
        f.facility_id: {r.target for r in f.technology.io if r.role == "output"}
        for f in library.facilities
    }
    inputs_of = {
        f.facility_id: {r.target for r in f.technology.io if r.role == "input"}
        for f in library.facilities
    }
    for stage in chain.stages:
        for feed in stage.feeds:
            shared = outputs_of.get(feed, set()) & inputs_of.get(stage.facility, set())
            if not shared:
                raise ValueError(
                    f"chain '{chain_id}': stage '{stage.facility}' feeds from "
                    f"'{feed}' but they share no commodity"
                )
            for commodity in sorted(shared):
                wb["edges"].append(
                    {
                        "from_process": pid_of[feed],
                        "to_process": pid_of[stage.facility],
                        "commodity_id": commodity,
                    }
                )

    if chain.demand_hint is not None:
        target, amount = chain.demand_hint.commodity_id, chain.demand_hint.amount
    else:
        last = library.facility(chain.stages[-1].facility)
        prods = [r.target for r in last.technology.io if r.role == "output"]
        target, amount = prods[0], last.default_capacity * 0.5
    wb["demand"] = [{"company": company, "commodity_id": target, "year": year, "amount": amount}]
    return wb
