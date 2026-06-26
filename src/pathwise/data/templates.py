"""Component-template models — the format contract for authored components.

These pydantic models are the single source of truth for a component's shape: a
technology recipe (costs + per-unit-throughput I/O coefficients), the streams it
consumes/produces, and lever cost-curves. The editable, SQLite-backed component
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
    (Component-library authoring); placing the technology stamps their levers
    onto the asset.
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
    #: Recipe rows. May be EMPTY: a half-authored technology (no flows yet) is a valid
    #: DRAFT the library saves, so partial work persists. The model-level validator
    #: still requires io before a model is solvable — authoring and solving differ.
    io: list[IoRow] = Field(default_factory=list)
    #: Per-year overrides of an io coefficient, keyed ``target -> {year: value}`` —
    #: a recipe whose intensity / yield / emission factor improves over the horizon.
    #: Empty = use the scalar ``io`` coefficient every year (sparse points are
    #: interpolated by the assembler). Values share the static row's authored unit.
    #: Round-trips through the ``io_t`` sheet (mirrors ``capex_by_year`` ↔ prices).
    input_intensity_by_year: dict[str, dict[int, float]] = Field(default_factory=dict)
    output_yield_by_year: dict[str, dict[int, float]] = Field(default_factory=dict)
    direct_impact_by_year: dict[str, dict[int, float]] = Field(default_factory=dict)
    maccs: list[str] = Field(default_factory=list)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class FlowTemplate(BaseModel):
    """A stream a component's technologies consume or produce."""

    flow_id: str
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
    #: through to the workbook's ``flow_properties`` sheet.
    properties: dict[str, float] = Field(default_factory=dict)
    #: Owning sector — the sector that PRODUCES this stream (electricity belongs to
    #: "power", not "steel"). Blank/None = a general, industry-agnostic stream.
    #: Purely organisational (groups streams in the Component builder); the
    #: optimiser ignores it.
    sector: str | None = None
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class LeverBlockTemplate(BaseModel):
    """One piecewise step of a lever's cost curve.

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


class LeverTemplate(BaseModel):
    """A lever template: a small retrofit of the SAME system (no tech switch).

    Efficiency or abatement upgrades applied to a facility's existing technology,
    with a piecewise cost curve the optimiser may adopt fractionally and
    cumulatively.
    """

    lever_id: str
    label: str = ""
    type: str = Field(pattern="^(energy_efficiency|emission_reduction|environmental)$")
    target: str  # flow id (energy_efficiency) or impact id (otherwise)
    lifetime: int = Field(default=15, ge=1)
    #: Cost-curve steps. May be EMPTY — a half-authored lever saves as a draft (same
    #: rationale as a technology's io); the optimiser simply ignores a lever with no blocks.
    blocks: list[LeverBlockTemplate] = Field(default_factory=list)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class StorageTemplate(BaseModel):
    """A storage component: store an amount of a flow, with round-trip efficiency.

    Maps 1:1 onto the engine's ``storage`` sheet (charge/discharge/level/built
    capacity is solved; these are the per-unit economics + physics). Placing it
    stamps a ``storage`` row scoped to the chosen company. ``energy_flow`` +
    ``energy_per_throughput`` give the optional running-energy draw per unit moved.
    """

    storage_id: str
    flow_id: str  # the stored flow
    max_capacity: float = Field(default=0.0, ge=0.0)
    capex_per_capacity: float = Field(default=0.0, ge=0.0)
    fixed_opex_per_capacity: float = Field(default=0.0, ge=0.0)
    charge_efficiency: float = Field(default=1.0, ge=0.0, le=1.0)
    discharge_efficiency: float = Field(default=1.0, ge=0.0, le=1.0)
    standing_loss: float = Field(default=0.0, ge=0.0, le=1.0)
    initial_level: float = Field(default=0.0, ge=0.0)
    #: Optional running-energy: a flow drawn per unit of throughput moved.
    energy_flow: str | None = None
    energy_per_throughput: float = Field(default=0.0, ge=0.0)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class StationTemplate(BaseModel):
    """A refuelling station: supplies a fuel flow to fleets/modes at its location.

    Maps 1:1 onto the engine's ``stations`` sheet. Placing it stamps a ``stations``
    row scoped to the chosen company; the fleets in that scope draw their fuel
    through it, capped at ``refuel_capacity`` and priced at ``refuel_fee`` on top of
    the fuel price.
    """

    station_id: str
    refuel_flow: str = ""  # the fuel flow dispensed (empty ⇒ a pure transfer hub)
    refuel_capacity: float = Field(default=0.0, ge=0.0)
    refuel_fee: float = Field(default=0.0, ge=0.0)
    capex: float = Field(default=0.0, ge=0.0)
    fixed_opex: float = Field(default=0.0, ge=0.0)
    #: Transfer-hub fields: a tonnage ceiling on cargo passing through + a per-unit
    #: handling fee — what makes a station a port/hub beyond refuelling.
    throughput_capacity: float = Field(default=0.0, ge=0.0)
    handling_fee: float = Field(default=0.0, ge=0.0)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


def _storage_row(
    s: StorageTemplate, *, storage_id: str | None = None, company: str | None = None
) -> dict[str, Any]:
    """A :class:`StorageTemplate` projected to a ``storage`` sheet row.

    ``storage_id`` / ``company`` override the template id + bind the placed
    instance to a scope (omitted for the library catalogue, set on placement).
    """
    row: dict[str, Any] = {
        "storage_id": storage_id or s.storage_id,
        "flow_id": s.flow_id,
        "max_capacity": s.max_capacity,
        "capex_per_capacity": s.capex_per_capacity,
        "fixed_opex_per_capacity": s.fixed_opex_per_capacity,
        "charge_efficiency": s.charge_efficiency,
        "discharge_efficiency": s.discharge_efficiency,
        "standing_loss": s.standing_loss,
        "initial_level": s.initial_level,
    }
    if s.energy_flow:
        row["energy_flow"] = s.energy_flow
        row["energy_per_throughput"] = s.energy_per_throughput
    if company is not None:
        row["company"] = company
    if s.notes:
        row["notes"] = s.notes
    return row


def _station_row(
    s: StationTemplate, *, station_id: str | None = None, company: str | None = None
) -> dict[str, Any]:
    """A :class:`StationTemplate` projected to a ``stations`` sheet row."""
    row: dict[str, Any] = {
        "station_id": station_id or s.station_id,
        "refuel_flow": s.refuel_flow,
        "refuel_capacity": s.refuel_capacity,
        "refuel_fee": s.refuel_fee,
        "capex": s.capex,
        "fixed_opex": s.fixed_opex,
        "throughput_capacity": s.throughput_capacity,
        "handling_fee": s.handling_fee,
    }
    if company is not None:
        row["company"] = company
    if s.notes:
        row["notes"] = s.notes
    return row


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


def _io_t_rows(tech: TechnologyTemplate) -> list[dict[str, Any]]:
    """A technology's per-year io coefficients (technology_id, target, role, year, coefficient).

    Mirrors :func:`_io_rows` for the time-varying ``io_t`` sheet; empty trajectories
    emit nothing, so a technology with only scalar coefficients adds no rows.
    """
    rows: list[dict[str, Any]] = []
    for role, traj_by_target in (
        ("input", tech.input_intensity_by_year),
        ("output", tech.output_yield_by_year),
        ("impact", tech.direct_impact_by_year),
    ):
        for target, traj in traj_by_target.items():
            for y in sorted(traj):
                rows.append(
                    {
                        "technology_id": tech.technology_id,
                        "target": target,
                        "role": role,
                        "year": y,
                        "coefficient": traj[y],
                    }
                )
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


def _lever_block_t_rows(
    lever_id: str, block_index: int, blk: LeverBlockTemplate, capacity: float
) -> list[dict[str, Any]]:
    """Per-year absolute block-cost rows (× capacity) for a model's ``lever_blocks_t``.

    The per-year analogue of the scalar ``lever_blocks`` row a placement stamps:
    block cost = per-capacity value × the instance capacity, one row per year the
    block overrides. Empty when the block has no per-year cost.
    """
    rows: list[dict[str, Any]] = []
    for y in sorted(set(blk.capex_per_capacity_by_year) | set(blk.opex_per_capacity_by_year)):
        row: dict[str, Any] = {"lever_id": lever_id, "block": block_index, "year": y}
        if y in blk.capex_per_capacity_by_year:
            row["capex"] = round(blk.capex_per_capacity_by_year[y] * capacity, 2)
        if y in blk.opex_per_capacity_by_year:
            row["opex"] = round(blk.opex_per_capacity_by_year[y] * capacity, 2)
        rows.append(row)
    return rows
