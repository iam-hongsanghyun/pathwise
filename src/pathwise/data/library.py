"""Facility-template library — the format contract and chain instantiation.

The library is a set of static JSON files (one per named collection, served to
the frontend like the example workbooks) holding **prebuilt facility archetypes**
(inputs, outputs incl. slates, costs, emission factors, alternatives) and
**process chains** (ordered stages wired by intermediate streams). Users insert
them into a model instead of authoring cross-referenced tables by hand. The
templates are generic process recipes — pathwise is a general process-network
tool, so a library is just a reusable bundle, not a hard-coded industry.

Every facility and chain **must carry a reference** (``source.url``): values are
only as credible as their citation, so an uncited entry is a validation error,
not a style issue. These pydantic models are the single source of truth for the
format — the CI test validates every shipped JSON file against them, and
:func:`instantiate_chain` proves each chain assembles into a solvable workbook.

.. note:: **Two distinct "library" concepts exist in pathwise.**

   This module defines :class:`Library` — the *facility-template library*: a
   curated, read-only catalogue of prebuilt facility archetypes and process
   chains (static JSON assets on disk) that users insert wholesale into a model.

   A separate concept is the *component library*
   (:class:`pathwise.data.components.ComponentLibrary`), which is the editable,
   SQLite-backed catalogue of technologies, commodities,
   measures, and MACCs that the authoring UI builds interactively.  The two
   libraries operate at different layers and serve different purposes; neither is
   a subset of the other.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from pathwise.data.sheets import (
    COMMODITIES,
    DEMAND,
    EDGES,
    IMPACTS,
    IO,
    MEASURE_BLOCKS,
    MEASURE_BLOCKS_T,
    MEASURES,
    NODE_LAYOUT,
    PERIODS,
    PROCESSES,
    TECHNOLOGIES,
    TRANSITIONS,
)
from pathwise.data.workbook import Workbook


def _current_year() -> int:
    """The current calendar year — the default start for a fresh instantiation."""
    return datetime.date.today().year


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
    """A technology recipe: costs + per-unit-throughput coefficients.

    ``maccs`` lists the ids of the MACC bundles that apply to this technology
    (Component-library authoring); placing the technology stamps their measures
    onto the machine. Empty for the facility-library format.
    """

    technology_id: str
    lifespan: int = Field(default=20, ge=1)
    capex: float = 0.0  # replacement capex [currency / unit capacity]
    opex: float = 0.0  # fixed O&M [currency / unit throughput]
    #: Per-year cost trajectories. When non-empty they override the scalar
    #: ``capex`` / ``opex`` for the years given (sparse points are interpolated
    #: onto the horizon by the assembler); empty = use the scalar everywhere. Keys
    #: are calendar years, values share the scalar's units.
    capex_by_year: dict[int, float] = Field(default_factory=dict)
    opex_by_year: dict[int, float] = Field(default_factory=dict)
    #: Years the technology is AVAILABLE to adopt: first year (introduction) and
    #: last year (phase-out). None = always available. The optimiser only lets a
    #: facility run / switch to the technology within this window.
    introduction_year: int | None = None
    phase_out_year: int | None = None
    io: list[IoRow] = Field(min_length=1)
    maccs: list[str] = Field(default_factory=list)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class Alternative(BaseModel):
    """A lower-carbon technology the facility may transition to."""

    technology: TechnologyTemplate
    transition_capex_per_capacity: float = 0.0


class CommodityTemplate(BaseModel):
    """A stream the library's facilities consume or produce."""

    commodity_id: str
    kind: str = Field(pattern="^(energy|material|indirect|product|byproduct)$")
    unit: str = "unit"
    price: float | None = None
    sale_price: float | None = None
    #: Per-year price trajectories overriding the scalar ``price`` / ``sale_price``
    #: for the years given (interpolated onto the horizon); empty = scalar.
    price_by_year: dict[int, float] = Field(default_factory=dict)
    sale_price_by_year: dict[int, float] = Field(default_factory=dict)
    #: Free-form physical properties of the stream (temperature, voltage,
    #: pressure, calorific value, …), keyed by name → value. Carried as metadata
    #: through to the workbook's ``commodity_properties`` sheet.
    properties: dict[str, float] = Field(default_factory=dict)
    #: Owning sector — the sector that PRODUCES this stream (electricity belongs to
    #: "power", not "steel"). Blank/None = a general, industry-agnostic stream.
    #: Purely organisational (groups streams in the Component builder); the
    #: optimiser ignores it.
    sector: str | None = None
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class MeasureBlockTemplate(BaseModel):
    """One piecewise step of a measure's cost curve.

    ``capex_per_capacity`` (and ``opex_per_capacity``) scale with the facility
    instance the block is stamped onto (block cost = value × instance capacity),
    so one template serves plants of any size.
    """

    reduction: float = Field(gt=0.0, le=1.0)
    capex_per_capacity: float = Field(ge=0.0)
    opex_per_capacity: float = Field(default=0.0, ge=0.0)
    #: Per-year overrides of ``capex_per_capacity`` / ``opex_per_capacity`` for the
    #: years given (interpolated onto the horizon); empty = use the scalar.
    capex_per_capacity_by_year: dict[int, float] = Field(default_factory=dict)
    opex_per_capacity_by_year: dict[int, float] = Field(default_factory=dict)


class MeasureTemplate(BaseModel):
    """A measure template: a small retrofit of the SAME system (no tech switch).

    The other decarbonisation lever next to ``alternatives`` (full technology
    transitions): efficiency or abatement upgrades applied to the facility's
    existing technology, with a piecewise cost curve the optimiser may adopt
    fractionally and cumulatively.
    """

    measure_id: str
    label: str = ""
    type: str = Field(pattern="^(energy_efficiency|emission_reduction|environmental)$")
    target: str  # commodity id (energy_efficiency) or impact id (otherwise)
    lifetime: int = Field(default=15, ge=1)
    blocks: list[MeasureBlockTemplate] = Field(min_length=1)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class FacilityTemplate(BaseModel):
    """A prebuilt facility archetype: baseline technology + alternatives."""

    facility_id: str
    label: str
    description: str = ""
    technology: TechnologyTemplate
    alternatives: list[Alternative] = Field(default_factory=list)
    measures: list[MeasureTemplate] = Field(default_factory=list)
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
    """A predefined multi-stage route through the library's facilities."""

    chain_id: str
    label: str
    description: str = ""
    stages: list[ChainStage] = Field(min_length=1)
    demand_hint: DemandHint | None = None
    source: SourceRef


class Library(BaseModel):
    """One named library: all templates in a single collection."""

    id: str
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


def load_library(path: str | Path) -> Library:
    """Load and validate one library JSON file."""
    with open(path, encoding="utf-8") as fh:
        return Library.model_validate(json.load(fh))


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
    row: dict[str, Any] = {
        "technology_id": tech.technology_id,
        "lifespan": tech.lifespan,
        "actions": "continue,replace,renew",
        "capex": tech.capex,
        "opex": tech.opex,
    }
    if tech.introduction_year is not None:
        row["introduction_year"] = tech.introduction_year
    if tech.phase_out_year is not None:
        row["phase_out_year"] = tech.phase_out_year
    return row


def _measure_block_t_rows(
    measure_id: str, block_index: int, blk: MeasureBlockTemplate, capacity: float
) -> list[dict[str, Any]]:
    """Per-year absolute block-cost rows (× capacity) for a model's ``measure_blocks_t``.

    The per-year analogue of the scalar ``measure_blocks`` row a placement stamps:
    block cost = per-capacity value × the instance capacity, one row per year the
    block overrides. Empty when the block has no per-year cost.
    """
    rows: list[dict[str, Any]] = []
    for y in sorted(set(blk.capex_per_capacity_by_year) | set(blk.opex_per_capacity_by_year)):
        row: dict[str, Any] = {"measure_id": measure_id, "block": block_index, "year": y}
        if y in blk.capex_per_capacity_by_year:
            row["capex"] = round(blk.capex_per_capacity_by_year[y] * capacity, 2)
        if y in blk.opex_per_capacity_by_year:
            row["opex"] = round(blk.opex_per_capacity_by_year[y] * capacity, 2)
        rows.append(row)
    return rows


def add_facility(
    workbook: Workbook,
    library: Library,
    facility_id: str,
    *,
    process_id: str | None = None,
    company: str = "",
) -> Workbook:
    """Insert one facility template into ``workbook`` (pure; returns a new dict).

    Commodities are merged by id (existing rows win); a technology that already
    exists is reused (recipe/instance separation — many facilities may share an
    archetype); the process instance id is uniquified. Measure templates
    are stamped onto the created instance (``facility`` = the new process id;
    block capex scales with the instance capacity).
    """
    f = library.facility(facility_id)
    wb: Workbook = {k: list(v) for k, v in workbook.items()}
    wb.setdefault(COMMODITIES, [])
    wb.setdefault(TECHNOLOGIES, [])
    wb.setdefault(IO, [])
    wb.setdefault(PROCESSES, [])
    wb.setdefault(TRANSITIONS, [])
    if f.measures:
        wb.setdefault(MEASURES, [])
        wb.setdefault(MEASURE_BLOCKS, [])

    have_comm = {str(r.get("commodity_id")) for r in wb[COMMODITIES]}
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
            wb[COMMODITIES].append(row)
            have_comm.add(c.commodity_id)

    have_tech = {str(r.get("technology_id")) for r in wb[TECHNOLOGIES]}
    for tech in [f.technology, *(a.technology for a in f.alternatives)]:
        if tech.technology_id not in have_tech:
            wb[TECHNOLOGIES].append(_tech_row(tech))
            wb[IO].extend(_io_rows(tech))
            have_tech.add(tech.technology_id)

    have_trans = {
        (str(r.get("from_technology")), str(r.get("to_technology"))) for r in wb[TRANSITIONS]
    }
    for alt in f.alternatives:
        key = (f.technology.technology_id, alt.technology.technology_id)
        if key not in have_trans:
            wb[TRANSITIONS].append(
                {
                    "from_technology": key[0],
                    "to_technology": key[1],
                    "action": "replace",
                    "capex_per_capacity": alt.transition_capex_per_capacity,
                }
            )

    have_proc = {str(r.get("process_id")) for r in wb[PROCESSES]}
    pid = process_id or f.label
    n = 2
    base_pid = pid
    while pid in have_proc:
        pid = f"{base_pid} {n}"
        n += 1
    wb[PROCESSES].append(
        {
            "process_id": pid,
            "company": company,
            "baseline_technology": f.technology.technology_id,
            "capacity": f.default_capacity,
        }
    )

    # Measures: small retrofits of the SAME system, stamped per instance.
    for m in f.measures:
        mid = f"{pid} · {m.measure_id}"
        wb[MEASURES].append(
            {
                "measure_id": mid,
                "type": m.type,
                "facility": pid,
                "target": m.target,
                "lifetime": m.lifetime,
            }
        )
        for i, blk in enumerate(m.blocks):
            wb[MEASURE_BLOCKS].append(
                {
                    "measure_id": mid,
                    "block": i,
                    "reduction": blk.reduction,
                    "capex": blk.capex_per_capacity * f.default_capacity,
                    "opex": blk.opex_per_capacity * f.default_capacity,
                }
            )
            if t_rows := _measure_block_t_rows(mid, i, blk, f.default_capacity):
                wb.setdefault(MEASURE_BLOCKS_T, []).extend(t_rows)
    return wb


def add_replacement(
    workbook: Workbook,
    library: Library,
    facility_id: str,
    replace_process: str,
    *,
    transition_capex: float | None = None,
) -> Workbook:
    """Add a template's technology as a TRANSITION OPTION of an existing facility.

    The mirror of :func:`add_facility` for the *future* system: instead of
    creating a new (initial) facility instance, the template's baseline
    technology is merged in (commodities + technology + io) and registered as a
    transition target of ``replace_process``'s baseline technology.

    Because transitions are TECHNOLOGY-level (``from_technology`` →
    ``to_technology``), the option automatically becomes available to **every**
    facility sharing that baseline — replacing "a part of the chain" is just
    adding a replacement per stage.

    Args:
        workbook: The model to extend (pure; returns a new dict).
        library: The library.
        facility_id: The template whose baseline technology becomes the option.
        replace_process: The facility whose baseline it may replace, or a
            technology id directly (same effect — transitions are
            technology-level).
        transition_capex: Switch cost [currency / unit capacity]; defaults to
            the template technology's replacement ``capex``.

    Raises:
        KeyError: Unknown template or process.
    """
    f = library.facility(facility_id)
    wb: Workbook = {k: list(v) for k, v in workbook.items()}
    wb.setdefault(COMMODITIES, [])
    wb.setdefault(TECHNOLOGIES, [])
    wb.setdefault(IO, [])
    wb.setdefault(TRANSITIONS, [])

    # The replace target may be a FACILITY (→ its baseline technology) or a
    # TECHNOLOGY id directly — transitions are technology-level either way,
    # so the option covers every facility running that baseline.
    proc = next(
        (r for r in wb.get(PROCESSES, []) if str(r.get("process_id")) == replace_process),
        None,
    )
    if proc is not None:
        from_tech = str(proc.get("baseline_technology") or "")
    elif any(str(r.get("technology_id")) == replace_process for r in wb.get(TECHNOLOGIES, [])):
        from_tech = replace_process
    else:
        raise KeyError(f"unknown facility '{replace_process}'")

    have_comm = {str(r.get("commodity_id")) for r in wb[COMMODITIES]}
    referenced = {r.target for r in f.technology.io if r.role != "impact"}
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
            wb[COMMODITIES].append(row)
            have_comm.add(c.commodity_id)

    have_tech = {str(r.get("technology_id")) for r in wb[TECHNOLOGIES]}
    if f.technology.technology_id not in have_tech:
        wb[TECHNOLOGIES].append(_tech_row(f.technology))
        wb[IO].extend(_io_rows(f.technology))

    key = (from_tech, f.technology.technology_id)
    have_trans = {
        (str(r.get("from_technology")), str(r.get("to_technology"))) for r in wb[TRANSITIONS]
    }
    if key not in have_trans and key[0] != key[1]:
        wb[TRANSITIONS].append(
            {
                "from_technology": key[0],
                "to_technology": key[1],
                "action": "replace",
                "capex_per_capacity": (
                    transition_capex if transition_capex is not None else f.technology.capex
                ),
            }
        )
    return wb


def add_chain(
    workbook: Workbook,
    library: Library,
    chain_id: str,
    *,
    company: str = "",
) -> Workbook:
    """Merge one chain template into an existing workbook (pure).

    Inserts every stage via :func:`add_facility`, derives ``edges`` from each
    stage's ``feeds`` (the commodity the upstream produces and the downstream
    consumes), places the stages left→right in ``node_layout``, ensures the
    referenced impacts and at least one period exist, and seeds demand from the
    chain's ``demand_hint`` for every horizon year.

    Raises:
        ValueError: If a feed pair shares no commodity (a broken chain).
    """
    chain = next((c for c in library.chains if c.chain_id == chain_id), None)
    if chain is None:
        raise KeyError(f"unknown chain '{chain_id}'")

    wb: Workbook = {k: list(v) for k, v in workbook.items()}
    wb.setdefault(PERIODS, [])
    wb.setdefault(IMPACTS, [])
    wb.setdefault(EDGES, [])
    wb.setdefault(DEMAND, [])
    wb.setdefault(NODE_LAYOUT, [])
    if not wb[PERIODS]:
        wb[PERIODS] = [{"year": _current_year(), "duration_years": 1}]

    base_y = 60 + len(wb.get(PROCESSES, [])) * 40
    pid_of: dict[str, str] = {}
    impacts: set[str] = set()
    for i, stage in enumerate(chain.stages):
        f = library.facility(stage.facility)
        wb = add_facility(wb, library, stage.facility, company=company)
        pid = str(wb[PROCESSES][-1]["process_id"])
        pid_of[stage.facility] = pid
        wb[NODE_LAYOUT] = [r for r in wb[NODE_LAYOUT] if str(r.get("id")) != f"process:{pid}"] + [
            {"id": f"process:{pid}", "x": 260 + i * 440, "y": base_y}
        ]
        for tech in [f.technology, *(a.technology for a in f.alternatives)]:
            impacts |= {r.target for r in tech.io if r.role == "impact"}
    have_imp = {str(r.get("impact_id")) for r in wb[IMPACTS]}
    wb[IMPACTS] += [{"impact_id": i, "unit": "t"} for i in sorted(impacts - have_imp)]

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
                wb[EDGES].append(
                    {
                        "from_process": pid_of[feed],
                        "to_process": pid_of[stage.facility],
                        "commodity_id": commodity,
                    }
                )

    if chain.demand_hint is not None:
        years = [int(p["year"]) for p in wb[PERIODS] if p.get("year") is not None]
        for y in years:
            exists = any(
                str(d.get("commodity_id")) == chain.demand_hint.commodity_id
                and int(d.get("year") or 0) == y
                for d in wb[DEMAND]
            )
            if not exists:
                wb[DEMAND].append(
                    {
                        "company": company,
                        "commodity_id": chain.demand_hint.commodity_id,
                        "year": y,
                        "amount": chain.demand_hint.amount,
                    }
                )
    return wb


def instantiate_chain(
    library: Library,
    chain_id: str,
    *,
    company: str = "Library",
    year: int | None = None,
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

    year = year or _current_year()
    wb: Workbook = {PERIODS: [{"year": year, "duration_years": 1}], IMPACTS: []}
    impacts: set[str] = set()
    pid_of: dict[str, str] = {}
    for stage in chain.stages:
        f = library.facility(stage.facility)
        wb = add_facility(wb, library, stage.facility, company=company)
        pid_of[stage.facility] = str(wb[PROCESSES][-1]["process_id"])
        for tech in [f.technology, *(a.technology for a in f.alternatives)]:
            impacts |= {r.target for r in tech.io if r.role == "impact"}
    wb[IMPACTS] = [{"impact_id": i, "unit": "t"} for i in sorted(impacts)]

    wb.setdefault(EDGES, [])
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
                wb[EDGES].append(
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
    wb[DEMAND] = [{"company": company, "commodity_id": target, "year": year, "amount": amount}]
    return wb
