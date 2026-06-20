"""Component-template models — the format contract for authored components.

These pydantic models are the single source of truth for a component's shape: a
technology recipe (costs + per-unit-throughput I/O coefficients), the streams it
consumes/produces, and measure cost-curves. The editable, SQLite-backed component
library (:mod:`pathwise.data.components`) builds on these models and reuses the
``_*_row`` helpers below to project a template into workbook sheet rows.

(Formerly ``data/library.py``, which also held a separate *facility-template
library* — a read-only catalogue of prebuilt facility archetypes + process chains
that users inserted wholesale. That system was retired in favour of the importable
libraries (:mod:`pathwise.data.libraries`) + component authoring; only the shared
template models live on here.)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


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
    #: Authored unit of ``coefficient`` (e.g. ``"MWh"``, ``"t"``). None/absent means
    #: the coefficient is already in the target stream's canonical unit. The assembler
    #: converts a differing unit → the stream's unit (see :mod:`pathwise.units`); the
    #: value is stored AS AUTHORED so the editor/preview show the original number.
    unit: str | None = None
    is_product: bool = False
    group: str | None = None  # blend group (inputs) or slate group (outputs)
    share_min: float | None = Field(default=None, ge=0.0, le=1.0)
    share_max: float | None = Field(default=None, ge=0.0, le=1.0)


class TechnologyTemplate(BaseModel):
    """A technology recipe: costs + per-unit-throughput coefficients.

    ``maccs`` lists the ids of the MACC bundles that apply to this technology
    (Component-library authoring); placing the technology stamps their measures
    onto the machine.
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


class CommodityTemplate(BaseModel):
    """A stream a component's technologies consume or produce."""

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

    Efficiency or abatement upgrades applied to a facility's existing technology,
    with a piecewise cost curve the optimiser may adopt fractionally and
    cumulatively.
    """

    measure_id: str
    label: str = ""
    type: str = Field(pattern="^(energy_efficiency|emission_reduction|environmental)$")
    target: str  # commodity id (energy_efficiency) or impact id (otherwise)
    lifetime: int = Field(default=15, ge=1)
    blocks: list[MeasureBlockTemplate] = Field(min_length=1)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


def _io_rows(tech: TechnologyTemplate) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for r in tech.io:
        row: dict[str, Any] = {
            "technology_id": tech.technology_id,
            "target": r.target,
            "role": r.role,
            "coefficient": r.coefficient,
        }
        if r.unit is not None:
            row["unit"] = r.unit
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
