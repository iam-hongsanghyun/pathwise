"""Composite components — reusable, recursively-nested building blocks.

The authoring model: every reusable thing has a unique name and lives in a
*component library*. A **machine** component is a leaf (a technology recipe + a
capacity). A **group** component is a composite: it lists its children (each a
reference to another component, by name, with an instance *alias*) and the
**connections between those children** — so a group carries its own internal
wiring and reusing the group reuses the wiring.

Placing a component **instantiates** it: :func:`instantiate` walks the chosen
component top-down and stamps a fresh INSTANCE of every descendant into the
recursive ``nodes`` / ``machines`` / ``connections`` hierarchy (path-qualified
ids keep instances unique), so one definition can be reused in many groups, and
produces a workbook the engine (and :func:`pathwise.core.run.run_model`) consumes
directly.

This is the "vertical" (composition) and "horizontal" (connections) design,
together, as data.

:class:`ComponentLibrary` is the *component library*: the editable, SQLite-backed
catalogue of technologies, commodities, measures, and MACCs the authoring UI
builds interactively. It reuses the shared component-template models in
:mod:`pathwise.data.templates`. (The separate, importable-workbook catalogue lives
in :mod:`pathwise.data.libraries`.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from pathwise.data.sheets import (
    COMMODITIES,
    COMMODITY_PRICES,
    COMMODITY_PROPERTIES,
    CONNECTIONS,
    GROUPS,
    IMPACTS,
    IO,
    IO_T,
    MACCS,
    MACHINES,
    MEASURE_BLOCKS,
    MEASURE_BLOCKS_T,
    MEASURES,
    META,
    NODES,
    TECHNOLOGIES,
    TECHNOLOGIES_PRICES,
    TRANSITIONS,
)
from pathwise.data.templates import (
    CommodityTemplate,
    IoRow,
    MeasureBlockTemplate,
    MeasureTemplate,
    TechnologyTemplate,
    _io_rows,
    _io_t_rows,
    _measure_block_t_rows,
    _tech_row,
)
from pathwise.data.workbook import Workbook


class MachineComponent(BaseModel):
    """A real-world machine: one physical unit running one technology.

    This is the **Project** layer's core primitive. A component (technology) is
    the per-unit technical spec; a machine is a named instance of it with its
    real-world facts: an owning **company**, a physical **capacity** (size), a
    **build_year** / **close_year**, and its own **measures** (a per-machine MACC
    — the same technology's retrofits, which may differ machine-to-machine). The
    same technology appears as many differently-named machines across companies.

    Each machine is independent (a hard copy): editing one machine's measures
    never affects another. Instantiating a machine stamps each measure onto the
    resulting node, with block capex/opex scaled to the instance capacity.
    """

    name: str
    label: str = ""
    technology: str  # a technology_id defined in the library's technologies
    capacity: float = Field(default=0.0, ge=0.0)
    #: The company that owns this machine (free-text; a project groups by it).
    owner: str = ""
    #: Real-world lifecycle: the year the machine is built / retired (0 = unset).
    build_year: int = Field(default=0, ge=0)
    close_year: int = Field(default=0, ge=0)
    measures: list[MeasureTemplate] = Field(default_factory=list)


class ChildRef(BaseModel):
    """A child slot in a group: which component, under what instance alias."""

    component: str
    alias: str = ""  # instance name within the parent (defaults to the component name)

    def instance_alias(self) -> str:
        return self.alias or self.component


class ConnectionTemplate(BaseModel):
    """A connection between two sibling children of a group (by their aliases)."""

    source: str  # producer child alias
    target: str  # consumer child alias
    commodity: str
    lag_years: int = Field(default=0, ge=0)


class GroupComponent(BaseModel):
    """A composite component: named children + the connections that wire them.

    .. deprecated:: legacy / backward-compat
        The builder no longer authors :class:`GroupComponent` objects; composite
        structures are expressed directly in the ``nodes`` / ``connections``
        hierarchy via :func:`instantiate_into`.  This class is retained only to
        round-trip legacy ``groups`` sheet rows from older SQLite component
        libraries.
    """

    name: str
    label: str = ""
    level: str = ""  # the designed level this group sits at (free text)
    children: list[ChildRef] = Field(min_length=1)
    connections: list[ConnectionTemplate] = Field(default_factory=list)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""

    @model_validator(mode="after")
    def _aliases_unique_and_wired(self) -> GroupComponent:
        aliases = [c.instance_alias() for c in self.children]
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"group '{self.name}' has duplicate child aliases")
        known = set(aliases)
        for conn in self.connections:
            for end in (conn.source, conn.target):
                if end not in known:
                    raise ValueError(
                        f"group '{self.name}' connection references unknown child '{end}'"
                    )
        return self


class MaccGroup(BaseModel):
    """A MACC — a named, reusable BUNDLE of individual measures.

    The "group of measures" of the Component builder: it links a set of
    standalone, reusable :class:`MeasureTemplate`\\ s by id. A technology lists
    the MACCs that apply to it (``TechnologyTemplate.maccs``); placing that
    technology stamps every measure of those MACCs onto the resulting machine.
    """

    macc_id: str
    label: str = ""
    measures: list[str] = Field(default_factory=list)  # individual measure ids
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class ComponentLibrary(BaseModel):
    """A catalogue of the three reusable building blocks — technologies (recipes
    + their streams), streams (commodities), and measures (individual + grouped
    into MACCs). ``machines`` / ``groups`` are legacy composite components kept
    for back-compatibility; the builder no longer authors them (the Value Chain
    places a technology directly as a machine)."""

    label: str = ""
    commodities: list[CommodityTemplate] = Field(default_factory=list)
    technologies: list[TechnologyTemplate] = Field(default_factory=list)
    measures: list[MeasureTemplate] = Field(default_factory=list)
    maccs: list[MaccGroup] = Field(default_factory=list)
    machines: list[MachineComponent] = Field(default_factory=list)
    groups: list[GroupComponent] = Field(default_factory=list)
    #: Free-text notes / references keyed by DERIVED sector name. Sectors are not
    #: stored entities, so their notes live here at the library level; entity notes
    #: live on the entities themselves. Optimiser ignores all of it.
    notes_by_sector: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names_unique(self) -> ComponentLibrary:
        names = [m.name for m in self.machines] + [g.name for g in self.groups]
        if len(names) != len(set(names)):
            raise ValueError("duplicate component name across machines/groups")
        return self

    def machine(self, name: str) -> MachineComponent | None:
        return next((m for m in self.machines if m.name == name), None)

    def group(self, name: str) -> GroupComponent | None:
        return next((g for g in self.groups if g.name == name), None)

    def technology(self, tech_id: str) -> TechnologyTemplate | None:
        return next((t for t in self.technologies if t.technology_id == tech_id), None)

    def measure(self, measure_id: str) -> MeasureTemplate | None:
        return next((m for m in self.measures if m.measure_id == measure_id), None)

    def macc(self, macc_id: str) -> MaccGroup | None:
        return next((g for g in self.maccs if g.macc_id == macc_id), None)

    def technology_measures(self, tech_id: str) -> list[MeasureTemplate]:
        """Every measure reachable from a technology via its linked MACCs."""
        tech = self.technology(tech_id)
        if tech is None:
            return []
        seen: dict[str, MeasureTemplate] = {}
        for macc_id in tech.maccs:
            macc = self.macc(macc_id)
            if macc is None:
                continue
            for mid in macc.measures:
                m = self.measure(mid)
                if m is not None:
                    seen[mid] = m
        return list(seen.values())


def copy_component_into(
    dst: ComponentLibrary, src: ComponentLibrary, kind: str, component_id: str
) -> ComponentLibrary:
    """Deep-copy a component + its dependency closure from ``src`` into ``dst``.

    A *project* (a session library) is built by dragging components in from base /
    other libraries; the copy is a HARD copy so the project owns its own values.
    The closure follows references so a placed component actually works:
    technology → its io-target commodities + its MACCs (+ those MACCs' measures);
    MACC → its measures; measure → its target commodity; stream → itself. A
    dependency the destination already has (by id) is REUSED, never overwritten —
    the project keeps its own edits. Returns a NEW library (pure).
    """
    out = dst.model_copy(deep=True)
    have_c = {c.commodity_id for c in out.commodities}
    have_m = {m.measure_id for m in out.measures}
    have_g = {g.macc_id for g in out.maccs}
    have_t = {t.technology_id for t in out.technologies}

    def add_commodity(cid: str) -> None:
        if not cid or cid in have_c:
            return
        c = next((x for x in src.commodities if x.commodity_id == cid), None)
        if c is not None:
            out.commodities.append(c.model_copy(deep=True))
            have_c.add(cid)

    def add_measure(mid: str) -> None:
        if not mid or mid in have_m:
            return
        m = src.measure(mid)
        if m is not None:
            out.measures.append(m.model_copy(deep=True))
            have_m.add(mid)
            add_commodity(m.target)  # energy_efficiency targets a commodity (impacts: no-op)

    def add_macc(gid: str) -> None:
        if not gid or gid in have_g:
            return
        g = src.macc(gid)
        if g is not None:
            out.maccs.append(g.model_copy(deep=True))
            have_g.add(gid)
            for mid in g.measures:
                add_measure(mid)

    def add_tech(tid: str) -> None:
        if not tid or tid in have_t:
            return
        t = src.technology(tid)
        if t is None:
            return
        out.technologies.append(t.model_copy(deep=True))
        have_t.add(tid)
        for r in t.io:
            if r.role != "impact":
                add_commodity(r.target)
        for gid in t.maccs:
            add_macc(gid)

    if kind == "technology":
        add_tech(component_id)
    elif kind == "stream":
        add_commodity(component_id)
    elif kind == "measure":
        add_measure(component_id)
    elif kind == "macc":
        add_macc(component_id)
    return out


def load_component_library(path: str | Path) -> ComponentLibrary:
    """Load and validate a component library from a ``.sqlite`` (preferred) or
    ``.json`` file (the format is chosen by suffix)."""
    p = Path(path)
    if p.suffix in (".sqlite", ".db"):
        from pathwise.api.workbook_io import parse_sqlite

        return library_from_workbook(parse_sqlite(p.read_bytes()))
    with open(p, encoding="utf-8") as fh:
        return ComponentLibrary.model_validate(json.load(fh))


# ── Library ⇄ SQLite workbook (one table per kind, like the example workbooks) ─
# A component library is a nested document; we store it the same generic
# sheets-in-SQLite way the examples use, so libraries are inspectable with any
# SQLite tool. The cleanly-flat kinds become tables; the genuinely-nested legacy
# bits (a machine's measures, a group's children/connections) ride along as a
# JSON column so the round-trip stays lossless.


def library_to_workbook(lib: ComponentLibrary) -> Workbook:
    """Decompose a component library into a ``{sheet: rows}`` workbook (lossless).

    Per-year cost trajectories ride on separate long-format sheets
    (``commodity_prices`` / ``technologies_prices`` / ``measure_blocks_t``, keyed
    by entity id + year), emitted only when populated so a library with no
    trajectories produces the same sheets as before. Free-text notes ride as an
    extra ``notes`` column on each entity sheet (written only when non-empty); a
    derived sector's note rides in ``meta`` under a ``sector_note:<sector>`` key.
    """

    def js(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)

    def with_notes(row: dict[str, Any], notes: str) -> dict[str, Any]:
        if notes:
            row["notes"] = notes
        return row

    wb: Workbook = {
        # Sector notes are keyed by a present-or-absent dict, so (unlike entity
        # notes, where "" is the default) an explicit empty value is meaningful
        # and must be stored — never drop a present key.
        META: [{"key": "label", "value": lib.label}]
        + [{"key": f"sector_note:{k}", "value": v} for k, v in lib.notes_by_sector.items()],
        COMMODITIES: [_commodity_row(c) for c in lib.commodities],
        TECHNOLOGIES: [
            with_notes(
                {
                    "technology_id": t.technology_id,
                    "lifespan": t.lifespan,
                    "capex": t.capex,
                    "opex": t.opex,
                    "introduction_year": t.introduction_year,
                    "phase_out_year": t.phase_out_year,
                    "maccs": "|".join(t.maccs),
                },
                t.notes,
            )
            for t in lib.technologies
        ],
        IO: [
            {"technology_id": t.technology_id, **r.model_dump()}
            for t in lib.technologies
            for r in t.io
        ],
        MEASURES: [
            with_notes(
                {
                    "measure_id": m.measure_id,
                    "label": m.label,
                    "type": m.type,
                    "target": m.target,
                    "lifetime": m.lifetime,
                },
                m.notes,
            )
            for m in lib.measures
        ],
        MEASURE_BLOCKS: [
            {
                "measure_id": m.measure_id,
                "block": i,
                "reduction": b.reduction,
                "capex_per_capacity": b.capex_per_capacity,
                "opex_per_capacity": b.opex_per_capacity,
            }
            for m in lib.measures
            for i, b in enumerate(m.blocks)
        ],
        MACCS: [
            with_notes(
                {"macc_id": g.macc_id, "label": g.label, "measures": "|".join(g.measures)},
                g.notes,
            )
            for g in lib.maccs
        ],
        MACHINES: [
            {
                "name": mc.name,
                "label": mc.label,
                "technology": mc.technology,
                "capacity": mc.capacity,
                "owner": mc.owner,
                "build_year": mc.build_year,
                "close_year": mc.close_year,
                "measures_json": js([m.model_dump() for m in mc.measures]),
            }
            for mc in lib.machines
        ],
        GROUPS: [
            with_notes(
                {
                    "name": g.name,
                    "label": g.label,
                    "level": g.level,
                    "children_json": js([c.model_dump() for c in g.children]),
                    "connections_json": js([c.model_dump() for c in g.connections]),
                },
                g.notes,
            )
            for g in lib.groups
        ],
    }
    # Per-year cost trajectories — only when populated (keeps trajectory-free
    # libraries byte-identical to the legacy sheets).
    if cp := _commodity_price_rows(lib):
        wb[COMMODITY_PRICES] = cp
    if tp := _technology_price_rows(lib):
        wb[TECHNOLOGIES_PRICES] = tp
    if iot := [row for t in lib.technologies for row in _io_t_rows(t)]:
        wb[IO_T] = iot
    if mb := _measure_block_traj_rows(lib):
        wb[MEASURE_BLOCKS_T] = mb
    if props := [
        {"commodity_id": c.commodity_id, "property": k, "value": v}
        for c in lib.commodities
        for k, v in c.properties.items()
    ]:
        wb[COMMODITY_PROPERTIES] = props
    return wb


def _commodity_traj_rows(c: CommodityTemplate) -> list[dict[str, Any]]:
    """One commodity's long-format price rows (commodity_id, year, price?, sale_price?).

    Matches the ``commodity_prices`` sheet the assembler already reads, so a
    commodity's per-year prices drive the optimiser as soon as the library loads.
    """
    rows: list[dict[str, Any]] = []
    for y in sorted(set(c.price_by_year) | set(c.sale_price_by_year)):
        row: dict[str, Any] = {"commodity_id": c.commodity_id, "year": y}
        if y in c.price_by_year:
            row["price"] = c.price_by_year[y]
        if y in c.sale_price_by_year:
            row["sale_price"] = c.sale_price_by_year[y]
        rows.append(row)
    return rows


def _tech_traj_rows(t: TechnologyTemplate) -> list[dict[str, Any]]:
    """One technology's long-format cost rows (technology_id, year, capex?, opex?)."""
    rows: list[dict[str, Any]] = []
    for y in sorted(set(t.capex_by_year) | set(t.opex_by_year)):
        row: dict[str, Any] = {"technology_id": t.technology_id, "year": y}
        if y in t.capex_by_year:
            row["capex"] = t.capex_by_year[y]
        if y in t.opex_by_year:
            row["opex"] = t.opex_by_year[y]
        rows.append(row)
    return rows


def _commodity_price_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format commodity price rows across the whole library."""
    return [row for c in lib.commodities for row in _commodity_traj_rows(c)]


def _technology_price_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format technology cost rows across the whole library."""
    return [row for t in lib.technologies for row in _tech_traj_rows(t)]


def _measure_block_traj_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format measure-block trajectory rows, keyed (measure_id, block, year).

    Blocks have no own id, so the block ORDINAL (its index in the measure's
    ``blocks`` list, matching the ``measure_blocks`` sheet) completes the key.
    """
    rows: list[dict[str, Any]] = []
    for m in lib.measures:
        for i, b in enumerate(m.blocks):
            for y in sorted(set(b.capex_per_capacity_by_year) | set(b.opex_per_capacity_by_year)):
                row: dict[str, Any] = {"measure_id": m.measure_id, "block": i, "year": y}
                if y in b.capex_per_capacity_by_year:
                    row["capex_per_capacity"] = b.capex_per_capacity_by_year[y]
                if y in b.opex_per_capacity_by_year:
                    row["opex_per_capacity"] = b.opex_per_capacity_by_year[y]
                rows.append(row)
    return rows


def _read_traj(
    rows: list[dict[str, Any]], *value_cols: str
) -> dict[Any, dict[str, dict[int, float]]]:
    """Group long-format trajectory rows into ``{entity_key: {value_col: {year: v}}}``.

    Each row carries the entity key the caller injected under ``_key`` (an id, or
    an ``(id, block)`` tuple) and a ``year``. A year is kept only when its cell is
    a real number, so an explicit ``0.0`` survives but an absent / blank cell is
    skipped (it falls back to the scalar). Rows lacking a key or a year are dropped.
    """
    out: dict[Any, dict[str, dict[int, float]]] = {}
    for r in rows:
        key = r.get("_key")
        y = _year(r.get("year"))
        if key is None or y is None:
            continue
        for col in value_cols:
            v = r.get(col)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.setdefault(key, {}).setdefault(col, {})[y] = float(v)
    return out


def library_from_workbook(wb: Workbook) -> ComponentLibrary:
    """Reconstruct a component library from its ``library_to_workbook`` sheets."""
    label = next(
        (_es(r.get("value")) for r in wb.get(META, []) if _es(r.get("key")) == "label"), ""
    )
    notes_by_sector: dict[str, str] = {}
    for r in wb.get(META, []):
        key = _es(r.get("key"))
        if key.startswith("sector_note:"):
            notes_by_sector[key[len("sector_note:") :]] = _es(r.get("value"))

    # Per-year trajectories (long-format sheets; absent → empty → scalar fallback).
    comm_traj = _read_traj(
        [{**r, "_key": _es(r.get("commodity_id"))} for r in wb.get(COMMODITY_PRICES, [])],
        "price",
        "sale_price",
    )
    tech_traj = _read_traj(
        [{**r, "_key": _es(r.get("technology_id"))} for r in wb.get(TECHNOLOGIES_PRICES, [])],
        "capex",
        "opex",
    )
    block_traj = _read_traj(
        [
            {**r, "_key": (_es(r.get("measure_id")), _year(r.get("block")) or 0)}
            for r in wb.get(MEASURE_BLOCKS_T, [])
        ],
        "capex_per_capacity",
        "opex_per_capacity",
    )

    # Physical stream properties (long format: commodity_id, property, value).
    props_by: dict[str, dict[str, float]] = {}
    for r in wb.get(COMMODITY_PROPERTIES, []):
        cid, prop = _es(r.get("commodity_id")), _es(r.get("property"))
        val = r.get("value")
        if cid and prop and isinstance(val, (int, float)):
            props_by.setdefault(cid, {})[prop] = float(val)

    io_by: dict[str, list[IoRow]] = {}
    for r in wb.get(IO, []):
        tid = _es(r.get("technology_id"))
        io_by.setdefault(tid, []).append(
            IoRow(
                target=_es(r.get("target")),
                role=_es(r.get("role")) or "input",
                coefficient=_enum(r.get("coefficient")),
                unit=_es(r.get("unit")) or None,
                is_product=bool(r.get("is_product")),
                group=_es(r.get("group")) or None,
                share_min=r.get("share_min")
                if isinstance(r.get("share_min"), (int, float))
                else None,
                share_max=r.get("share_max")
                if isinstance(r.get("share_max"), (int, float))
                else None,
            )
        )

    io_t_by = _read_io_t(wb.get(IO_T, []))

    def split(v: object) -> list[str]:
        sv = _es(v)
        return sv.split("|") if sv else []

    technologies = [
        TechnologyTemplate(
            technology_id=_es(r.get("technology_id")),
            lifespan=int(_enum(r.get("lifespan"), 20)) or 20,
            capex=_enum(r.get("capex")),
            opex=_enum(r.get("opex")),
            capex_by_year=tech_traj.get(_es(r.get("technology_id")), {}).get("capex", {}),
            opex_by_year=tech_traj.get(_es(r.get("technology_id")), {}).get("opex", {}),
            introduction_year=_year(r.get("introduction_year")),
            phase_out_year=_year(r.get("phase_out_year")),
            io=io_by.get(_es(r.get("technology_id")), []),
            **_io_t_fields(io_t_by, _es(r.get("technology_id"))),
            maccs=split(r.get("maccs")),
            notes=_es(r.get("notes")),
        )
        for r in wb.get(TECHNOLOGIES, [])
    ]

    blocks_by: dict[str, list[dict[str, object]]] = {}
    for r in wb.get(MEASURE_BLOCKS, []):
        blocks_by.setdefault(_es(r.get("measure_id")), []).append(r)
    measures = [
        MeasureTemplate(
            measure_id=_es(r.get("measure_id")),
            label=_es(r.get("label")),
            type=_es(r.get("type")) or "energy_efficiency",
            target=_es(r.get("target")),
            lifetime=int(_enum(r.get("lifetime"), 15)) or 15,
            blocks=[
                MeasureBlockTemplate(
                    reduction=_enum(b.get("reduction"), 0.01),
                    capex_per_capacity=_enum(b.get("capex_per_capacity")),
                    opex_per_capacity=_enum(b.get("opex_per_capacity")),
                    capex_per_capacity_by_year=block_traj.get(
                        (_es(r.get("measure_id")), _year(b.get("block")) or 0), {}
                    ).get("capex_per_capacity", {}),
                    opex_per_capacity_by_year=block_traj.get(
                        (_es(r.get("measure_id")), _year(b.get("block")) or 0), {}
                    ).get("opex_per_capacity", {}),
                )
                for b in sorted(
                    blocks_by.get(_es(r.get("measure_id")), []), key=lambda b: _enum(b.get("block"))
                )
            ],
            notes=_es(r.get("notes")),
        )
        for r in wb.get(MEASURES, [])
    ]

    maccs = [
        MaccGroup(
            macc_id=_es(r.get("macc_id")),
            label=_es(r.get("label")),
            measures=split(r.get("measures")),
            notes=_es(r.get("notes")),
        )
        for r in wb.get(MACCS, [])
    ]
    commodities = [
        CommodityTemplate(
            commodity_id=_es(r.get("commodity_id")),
            kind=_es(r.get("kind")) or "material",
            unit=_es(r.get("unit")) or "unit",
            price=r.get("price") if isinstance(r.get("price"), (int, float)) else None,
            sale_price=r.get("sale_price")
            if isinstance(r.get("sale_price"), (int, float))
            else None,
            price_by_year=comm_traj.get(_es(r.get("commodity_id")), {}).get("price", {}),
            sale_price_by_year=comm_traj.get(_es(r.get("commodity_id")), {}).get("sale_price", {}),
            sector=_es(r.get("sector")) or None,
            notes=_es(r.get("notes")),
            properties=props_by.get(_es(r.get("commodity_id")), {}),
        )
        for r in wb.get(COMMODITIES, [])
    ]
    machines = [
        MachineComponent(
            name=_es(r.get("name")),
            label=_es(r.get("label")),
            technology=_es(r.get("technology")),
            capacity=_enum(r.get("capacity")),
            owner=_es(r.get("owner")),
            build_year=int(_enum(r.get("build_year"))),
            close_year=int(_enum(r.get("close_year"))),
            measures=[
                MeasureTemplate.model_validate(m)
                for m in json.loads(_es(r.get("measures_json")) or "[]")
            ],
        )
        for r in wb.get(MACHINES, [])
    ]
    groups = [
        GroupComponent(
            name=_es(r.get("name")),
            label=_es(r.get("label")),
            level=_es(r.get("level")),
            children=[
                ChildRef.model_validate(c) for c in json.loads(_es(r.get("children_json")) or "[]")
            ],
            connections=[
                ConnectionTemplate.model_validate(c)
                for c in json.loads(_es(r.get("connections_json")) or "[]")
            ],
            notes=_es(r.get("notes")),
        )
        for r in wb.get(GROUPS, [])
    ]
    return ComponentLibrary(
        label=label,
        commodities=commodities,
        technologies=technologies,
        measures=measures,
        maccs=maccs,
        machines=machines,
        groups=groups,
        notes_by_sector=notes_by_sector,
    )


def instantiate(
    library: ComponentLibrary, component: str, *, instance_id: str | None = None
) -> Workbook:
    """Stamp a component into a recursive hierarchy workbook (one fresh instance).

    Recursively places ``component`` and all its descendants as instance nodes
    (path-qualified ids), emitting the ``nodes`` / ``machines`` / ``connections``
    sheets plus the referenced ``technologies`` / ``io`` / ``commodities``. The
    result is a runnable workbook (add ``periods`` + ``demand`` to solve).

    Raises:
        KeyError: If ``component`` or any referenced child is not in the library.
    """
    nodes: list[dict[str, Any]] = []
    machines: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    measures: list[dict[str, Any]] = []
    measure_blocks: list[dict[str, Any]] = []
    measure_blocks_t: list[dict[str, Any]] = []

    def place(name: str, node_id: str, parent_id: str | None) -> None:
        machine = library.machine(name)
        if machine is not None:
            nodes.append(
                {
                    "node_id": node_id,
                    "parent_id": parent_id,
                    "kind": "machine",
                    "level": "machine",
                    "label": machine.label or machine.name,
                }
            )
            machines.append(
                {
                    "machine_id": node_id,
                    "baseline_technology": machine.technology,
                    "capacity": machine.capacity,
                }
            )
            # Measures come from the machine's technology's linked MACCs, plus
            # any embedded directly on the machine (legacy); deduped by id.
            applied = list(machine.measures)
            seen_ids = {m.measure_id for m in applied}
            for m in library.technology_measures(machine.technology):
                if m.measure_id not in seen_ids:
                    applied.append(m)
                    seen_ids.add(m.measure_id)
            for m in applied:
                mid = f"{node_id} · {m.measure_id}"
                measures.append(
                    {
                        "measure_id": mid,
                        "type": m.type,
                        "facility": node_id,
                        "target": m.target,
                        "lifetime": m.lifetime,
                    }
                )
                for i, blk in enumerate(m.blocks):
                    measure_blocks.append(
                        {
                            "measure_id": mid,
                            "block": i,
                            "reduction": blk.reduction,
                            "capex": round(blk.capex_per_capacity * machine.capacity, 2),
                            "opex": round(blk.opex_per_capacity * machine.capacity, 2),
                        }
                    )
                    measure_blocks_t.extend(_measure_block_t_rows(mid, i, blk, machine.capacity))
            return
        group = library.group(name)
        if group is None:
            raise KeyError(f"unknown component '{name}'")
        nodes.append(
            {
                "node_id": node_id,
                "parent_id": parent_id,
                "kind": "group",
                "level": group.level,
                "label": group.label or group.name,
            }
        )
        alias_to_id: dict[str, str] = {}
        for child in group.children:
            alias = child.instance_alias()
            child_id = f"{node_id}/{alias}"
            alias_to_id[alias] = child_id
            place(child.component, child_id, node_id)
        for conn in group.connections:
            connections.append(
                {
                    "from_node": alias_to_id[conn.source],
                    "to_node": alias_to_id[conn.target],
                    "commodity_id": conn.commodity,
                    "lag_years": conn.lag_years,
                }
            )

    root_id = instance_id or component
    place(component, root_id, None)

    technologies = [_tech_row(t) for t in library.technologies]
    io: list[dict[str, Any]] = []
    io_t: list[dict[str, Any]] = []
    impact_ids: set[str] = set()
    for t in library.technologies:
        io.extend(_io_rows(t))
        io_t.extend(_io_t_rows(t))
        impact_ids |= {r.target for r in t.io if r.role == "impact"}
    commodities: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    for c in library.commodities:
        row: dict[str, Any] = {"commodity_id": c.commodity_id, "kind": c.kind, "unit": c.unit}
        if c.price is not None:
            row["price"] = c.price
        if c.sale_price is not None:
            row["sale_price"] = c.sale_price
        if c.sector:
            row["sector"] = c.sector
        commodities.append(row)
        properties.extend(
            {"commodity_id": c.commodity_id, "property": k, "value": v}
            for k, v in c.properties.items()
        )

    out: Workbook = {
        NODES: nodes,
        MACHINES: machines,
        CONNECTIONS: connections,
        TECHNOLOGIES: technologies,
        IO: io,
        COMMODITIES: commodities,
        IMPACTS: [{"impact_id": i, "unit": "t"} for i in sorted(impact_ids)],
    }
    if io_t:
        out[IO_T] = io_t
    if properties:
        out[COMMODITY_PROPERTIES] = properties
    if measures:
        out[MEASURES] = measures
        out[MEASURE_BLOCKS] = measure_blocks
        if measure_blocks_t:
            out[MEASURE_BLOCKS_T] = measure_blocks_t
    # Per-year cost trajectories so authored per-year capex/opex/price drive the
    # optimiser once the instance is solved (assembler reads these sheets).
    if tp := _technology_price_rows(library):
        out[TECHNOLOGIES_PRICES] = tp
    cp = [row for c in library.commodities for row in _commodity_traj_rows(c)]
    if cp:
        out[COMMODITY_PRICES] = cp
    return out


def instantiate_into(
    model: Workbook,
    library: ComponentLibrary,
    component: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Drop a FRESH copy of ``component`` into ``model`` under ``parent_id``.

    The "place a facility into a company" operation of the Value-Chain builder:
    :func:`instantiate` stamps a brand-new instance (path-qualified ids, so two
    companies never share a facility), then this merges that instance into the
    existing workbook — appending ``nodes`` / ``machines`` / ``connections`` /
    ``measures`` / ``measure_blocks`` and merging the referenced
    ``technologies`` / ``io`` / ``commodities`` by id (existing rows win, recipes
    are shared). The instance's root node is re-parented to ``parent_id``.

    Pure — returns a new workbook; ``model`` is not mutated.

    Args:
        model: The session workbook to extend.
        library: The component library to instantiate from.
        component: The component name to place.
        parent_id: The node the new instance becomes a child of.
        instance_id: Root instance id; defaults to ``"{parent_id}/{component}"``
            uniquified against existing node ids.

    Raises:
        KeyError: If ``component`` (or a referenced child) is not in the library.
    """
    wb: Workbook = {k: list(v) for k, v in model.items()}
    have_nodes = {str(r.get("node_id")) for r in wb.get(NODES, [])}
    root_id = instance_id or f"{parent_id}/{component}"
    base, n = root_id, 2
    while root_id in have_nodes:
        root_id = f"{base}-{n}"
        n += 1

    fresh = instantiate(library, component, instance_id=root_id)
    for row in fresh[NODES]:
        if row["node_id"] == root_id:
            row["parent_id"] = parent_id

    # measure_blocks_t rows are per-instance (path-qualified measure ids), so
    # they append cleanly like measure_blocks.
    append_keys = (
        NODES,
        MACHINES,
        CONNECTIONS,
        MEASURES,
        MEASURE_BLOCKS,
        MEASURE_BLOCKS_T,
    )
    for key in append_keys:
        if fresh.get(key):
            wb.setdefault(key, []).extend(fresh[key])

    _merge_by(wb, fresh, TECHNOLOGIES, "technology_id")
    _merge_by(wb, fresh, COMMODITIES, "commodity_id")
    _merge_by(wb, fresh, IMPACTS, "impact_id")
    # io rows have no single id; key on (technology_id, target, role) and only
    # add rows for technologies the model did not already carry.
    have_tech = {str(r.get("technology_id")) for r in model.get(TECHNOLOGIES, [])}
    wb.setdefault(IO, [])
    for row in fresh.get(IO, []):
        if str(row.get("technology_id")) not in have_tech:
            wb[IO].append(row)
    wb.setdefault(IO_T, [])
    for row in fresh.get(IO_T, []):
        if str(row.get("technology_id")) not in have_tech:
            wb[IO_T].append(row)
    # Trajectory rows are multi-row-per-entity, so merge by entity (skip an
    # entity entirely when the model already carried it — the recipe is shared).
    have_comm = {str(r.get("commodity_id")) for r in model.get(COMMODITIES, [])}
    new_tp = [
        r
        for r in fresh.get(TECHNOLOGIES_PRICES, [])
        if str(r.get("technology_id")) not in have_tech
    ]
    if new_tp:
        wb.setdefault(TECHNOLOGIES_PRICES, []).extend(new_tp)
    new_cp = [
        r for r in fresh.get(COMMODITY_PRICES, []) if str(r.get("commodity_id")) not in have_comm
    ]
    if new_cp:
        wb.setdefault(COMMODITY_PRICES, []).extend(new_cp)
    return wb


def _merge_by(wb: Workbook, fresh: Workbook, sheet: str, id_col: str) -> None:
    """Append ``fresh[sheet]`` rows into ``wb[sheet]``, skipping existing ids."""
    have = {str(r.get(id_col)) for r in wb.get(sheet, [])}
    wb.setdefault(sheet, [])
    for row in fresh.get(sheet, []):
        if str(row.get(id_col)) not in have:
            wb[sheet].append(row)
            have.add(str(row.get(id_col)))


def _commodity_row(c: CommodityTemplate) -> dict[str, Any]:
    row: dict[str, Any] = {"commodity_id": c.commodity_id, "kind": c.kind, "unit": c.unit}
    if c.price is not None:
        row["price"] = c.price
    if c.sale_price is not None:
        row["sale_price"] = c.sale_price
    if c.sector:
        row["sector"] = c.sector
    if c.notes:
        row["notes"] = c.notes
    return row


def _merge_row(wb: Workbook, sheet: str, id_col: str, row: dict[str, Any]) -> None:
    """Append one row to ``wb[sheet]`` unless its id already exists."""
    rows = wb.setdefault(sheet, [])
    if all(str(r.get(id_col)) != str(row.get(id_col)) for r in rows):
        rows.append(row)


def _merge_tech_traj(wb: Workbook, tech: TechnologyTemplate) -> None:
    """Carry a technology's per-year capex/opex into the model's ``technologies_prices``.

    So per-year costs authored on the library template actually reach the
    assembler when the technology is placed. No-op when the technology has no
    trajectory or already has rows in the model (idempotent, recipe shared).
    """
    traj = _tech_traj_rows(tech)
    if not traj:
        return
    rows = wb.setdefault(TECHNOLOGIES_PRICES, [])
    if any(str(r.get("technology_id")) == tech.technology_id for r in rows):
        return
    rows.extend(traj)


def _merge_commodity_traj(wb: Workbook, c: CommodityTemplate) -> None:
    """Carry a commodity's per-year price/sale_price into the model's ``commodity_prices``."""
    traj = _commodity_traj_rows(c)
    if not traj:
        return
    rows = wb.setdefault(COMMODITY_PRICES, [])
    if any(str(r.get("commodity_id")) == c.commodity_id for r in rows):
        return
    rows.extend(traj)


def _merge_io_t(wb: Workbook, tech: TechnologyTemplate) -> None:
    """Carry a technology's per-year io coefficients into the model's ``io_t`` sheet.

    So a coefficient time-series authored on the library template reaches the
    assembler when the technology is placed. No-op when there is no trajectory or
    the model already carries the technology's rows (idempotent, recipe shared).
    """
    rows_new = _io_t_rows(tech)
    if not rows_new:
        return
    rows = wb.setdefault(IO_T, [])
    if any(str(r.get("technology_id")) == tech.technology_id for r in rows):
        return
    rows.extend(rows_new)


def _read_io_t(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, dict[int, float]]]]:
    """Group ``io_t`` rows into ``{technology_id: {role: {target: {year: coefficient}}}}``."""
    out: dict[str, dict[str, dict[str, dict[int, float]]]] = {}
    for r in rows:
        tid, target = _es(r.get("technology_id")), _es(r.get("target"))
        role = _es(r.get("role")) or "input"
        y, cv = _year(r.get("year")), r.get("coefficient")
        if not tid or not target or y is None:
            continue
        if isinstance(cv, (int, float)) and not isinstance(cv, bool):
            out.setdefault(tid, {}).setdefault(role, {}).setdefault(target, {})[y] = float(cv)
    return out


_ROLE_TRAJ = (
    ("input_intensity_by_year", "input"),
    ("output_yield_by_year", "output"),
    ("direct_impact_by_year", "impact"),
)


def _io_t_fields(
    io_t_by: dict[str, dict[str, dict[str, dict[int, float]]]], tid: str
) -> dict[str, Any]:
    """The three ``*_by_year`` kwargs for a ``TechnologyTemplate`` from grouped io_t."""
    by_role = io_t_by.get(tid, {})
    return {field: by_role.get(role, {}) for field, role in _ROLE_TRAJ}


def place_technology(
    model: Workbook,
    library: ComponentLibrary,
    technology_id: str,
    *,
    parent_id: str,
    capacity: float = 0.0,
    instance_id: str | None = None,
) -> Workbook:
    """Place a technology as a fresh MACHINE node under ``parent_id``.

    The Value-Chain builder's "add component": a technology becomes one machine
    node (a process); its recipe (``technologies`` / ``io``) + referenced streams
    + impacts are merged in, and every measure of the technology's linked MACCs is
    stamped onto the machine (block cost scaled to ``capacity``). Pure — returns a
    new workbook.

    Raises:
        KeyError: If ``technology_id`` is not in the library.
    """
    tech = library.technology(technology_id)
    if tech is None:
        raise KeyError(f"unknown technology '{technology_id}'")

    wb: Workbook = {k: list(v) for k, v in model.items()}
    have_nodes = {str(r.get("node_id")) for r in wb.get(NODES, [])}
    node_id = instance_id or f"{parent_id}/{technology_id}"
    base, n = node_id, 2
    while node_id in have_nodes:
        node_id = f"{base}-{n}"
        n += 1

    wb.setdefault(NODES, []).append(
        {
            "node_id": node_id,
            "parent_id": parent_id,
            "kind": "machine",
            "level": "machine",
            "label": technology_id,
        }
    )
    wb.setdefault(MACHINES, []).append(
        {"machine_id": node_id, "baseline_technology": technology_id, "capacity": capacity}
    )

    _merge_row(wb, TECHNOLOGIES, "technology_id", _tech_row(tech))
    _merge_tech_traj(wb, tech)
    if all(str(r.get("technology_id")) != technology_id for r in model.get(IO, [])):
        wb.setdefault(IO, []).extend(_io_rows(tech))
    _merge_io_t(wb, tech)
    inputs_outputs = {r.target for r in tech.io if r.role != "impact"}
    for c in library.commodities:
        if c.commodity_id in inputs_outputs:
            _merge_row(wb, COMMODITIES, "commodity_id", _commodity_row(c))
            _merge_commodity_traj(wb, c)
    for imp in sorted({r.target for r in tech.io if r.role == "impact"}):
        _merge_row(wb, IMPACTS, "impact_id", {"impact_id": imp, "unit": "t"})

    measures = wb.setdefault(MEASURES, [])
    blocks = wb.setdefault(MEASURE_BLOCKS, [])
    for m in library.technology_measures(technology_id):
        mid = f"{node_id} · {m.measure_id}"
        measures.append(
            {
                "measure_id": mid,
                "type": m.type,
                "facility": node_id,
                "target": m.target,
                "lifetime": m.lifetime,
            }
        )
        for i, blk in enumerate(m.blocks):
            blocks.append(
                {
                    "measure_id": mid,
                    "block": i,
                    "reduction": blk.reduction,
                    "capex": round(blk.capex_per_capacity * capacity, 2),
                    "opex": round(blk.opex_per_capacity * capacity, 2),
                }
            )
            if t_rows := _measure_block_t_rows(mid, i, blk, capacity):
                wb.setdefault(MEASURE_BLOCKS_T, []).extend(t_rows)
    return wb


def add_alternative(
    model: Workbook,
    library: ComponentLibrary,
    technology_id: str,
    *,
    from_technology: str,
    capex_per_capacity: float = 0.0,
) -> Workbook:
    """Make ``technology_id`` an ALTERNATIVE the optimiser may switch to from
    ``from_technology`` — used to offer alternatives on a machine in the value
    chain WITHOUT baking them into the Component library.

    Merges the alternative's recipe (``technologies`` / ``io`` + referenced
    ``commodities`` / ``impacts``) into the model and adds a ``transitions`` row
    ``from_technology → technology_id`` (any facility running ``from_technology``
    may switch). Idempotent on the transition. Pure — returns a new workbook.

    Raises:
        KeyError: If ``technology_id`` is not in the library.
    """
    tech = library.technology(technology_id)
    if tech is None:
        raise KeyError(f"unknown technology '{technology_id}'")

    wb: Workbook = {k: list(v) for k, v in model.items()}
    _merge_row(wb, TECHNOLOGIES, "technology_id", _tech_row(tech))
    _merge_tech_traj(wb, tech)
    if all(str(r.get("technology_id")) != technology_id for r in model.get(IO, [])):
        wb.setdefault(IO, []).extend(_io_rows(tech))
    _merge_io_t(wb, tech)
    inputs_outputs = {r.target for r in tech.io if r.role != "impact"}
    for c in library.commodities:
        if c.commodity_id in inputs_outputs:
            _merge_row(wb, COMMODITIES, "commodity_id", _commodity_row(c))
            _merge_commodity_traj(wb, c)
    for imp in sorted({r.target for r in tech.io if r.role == "impact"}):
        _merge_row(wb, IMPACTS, "impact_id", {"impact_id": imp, "unit": "t"})

    transitions = wb.setdefault(TRANSITIONS, [])
    exists = any(
        str(r.get("from_technology")) == from_technology
        and str(r.get("to_technology")) == technology_id
        for r in transitions
    )
    if not exists:
        transitions.append(
            {
                "from_technology": from_technology,
                "to_technology": technology_id,
                "action": "replace",
                "capex_per_capacity": capex_per_capacity,
            }
        )
    return wb


def _es(v: object) -> str:
    return "" if v is None else str(v)


def _enum(v: object, default: float = 0.0) -> float:
    if v is None or v == "":
        return default
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _year(v: object) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(float(v))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def extract_library_from_workbook(workbook: Workbook, *, label: str = "") -> ComponentLibrary:
    """Recover a component library (the *details*) from an assembled workbook.

    The near-inverse of :func:`instantiate`: an imported scenario carries its
    component DEFINITIONS (streams, technology recipes, measures) interleaved with
    its value-chain STRUCTURE (nodes/machines/connections). This pulls the
    definitions back out into a :class:`ComponentLibrary` so the Component view can
    show the scenario's components, leaving the structure to the Value-chain view.

    Best-effort: ``io`` is grouped back under its technology, and per-facility
    measures (``"<node> · <measure>"``) are de-duplicated to reusable templates.
    The MACC *bundles* and technology→MACC links are not present in an assembled
    workbook, so they are omitted (the individual measures are still recovered).
    """
    commodities: list[CommodityTemplate] = []
    seen_c: set[str] = set()
    for r in workbook.get(COMMODITIES, []):
        cid = _es(r.get("commodity_id"))
        if not cid or cid in seen_c:
            continue
        seen_c.add(cid)
        kind = _es(r.get("kind")) or "material"
        commodities.append(
            CommodityTemplate(
                commodity_id=cid,
                kind=kind
                if kind in ("energy", "material", "indirect", "product", "byproduct")
                else "material",
                unit=_es(r.get("unit")) or "unit",
                price=r.get("price") if isinstance(r.get("price"), (int, float)) else None,
                sale_price=r.get("sale_price")
                if isinstance(r.get("sale_price"), (int, float))
                else None,
                sector=_es(r.get("sector")) or None,
            )
        )

    io_by_tech: dict[str, list[IoRow]] = {}
    for r in workbook.get(IO, []):
        tid = _es(r.get("technology_id"))
        role = _es(r.get("role")) or "input"
        if not tid or role not in ("input", "output", "impact"):
            continue
        io_by_tech.setdefault(tid, []).append(
            IoRow(
                target=_es(r.get("target")),
                role=role,
                coefficient=_enum(r.get("coefficient")),
                unit=_es(r.get("unit")) or None,
                is_product=bool(r.get("is_product")),
                group=_es(r.get("group")) or None,
                share_min=r.get("share_min")
                if isinstance(r.get("share_min"), (int, float))
                else None,
                share_max=r.get("share_max")
                if isinstance(r.get("share_max"), (int, float))
                else None,
            )
        )

    io_t_by = _read_io_t(workbook.get(IO_T, []))
    technologies: list[TechnologyTemplate] = []
    seen_t: set[str] = set()
    for r in workbook.get(TECHNOLOGIES, []):
        tid = _es(r.get("technology_id"))
        if not tid or tid in seen_t or not io_by_tech.get(tid):
            continue  # a technology with no recoverable io can't be represented
        seen_t.add(tid)
        technologies.append(
            TechnologyTemplate(
                technology_id=tid,
                lifespan=int(_enum(r.get("lifespan"), 20)) or 20,
                capex=_enum(r.get("capex")),
                opex=_enum(r.get("opex")),
                introduction_year=_year(r.get("introduction_year")),
                phase_out_year=_year(r.get("phase_out_year")),
                io=io_by_tech[tid],
                **_io_t_fields(io_t_by, tid),
                maccs=[],
            )
        )

    blocks_by_m: dict[str, list[dict[str, object]]] = {}
    for r in workbook.get(MEASURE_BLOCKS, []):
        blocks_by_m.setdefault(_es(r.get("measure_id")), []).append(r)
    measures: list[MeasureTemplate] = []
    seen_m: set[str] = set()
    for r in workbook.get(MEASURES, []):
        mid = _es(r.get("measure_id"))
        base = mid.split(" · ")[-1]  # de-instantiate the per-facility prefix
        if not base or base in seen_m:
            continue
        blks = sorted(blocks_by_m.get(mid, []), key=lambda b: _enum(b.get("block")))
        templates = [
            MeasureBlockTemplate(
                reduction=min(max(_enum(b.get("reduction"), 0.01), 1e-6), 1.0),
                capex_per_capacity=max(_enum(b.get("capex")), 0.0),
                opex_per_capacity=max(_enum(b.get("opex")), 0.0),
            )
            for b in blks
        ]
        if not templates:
            continue  # a measure needs at least one block
        seen_m.add(base)
        mtype = _es(r.get("type")) or "energy_efficiency"
        measures.append(
            MeasureTemplate(
                measure_id=base,
                label="",
                type=mtype
                if mtype in ("energy_efficiency", "emission_reduction", "environmental")
                else "energy_efficiency",
                target=_es(r.get("target")),
                lifetime=int(_enum(r.get("lifetime"), 15)) or 15,
                blocks=templates,
            )
        )

    return ComponentLibrary(
        label=label, commodities=commodities, technologies=technologies, measures=measures
    )
