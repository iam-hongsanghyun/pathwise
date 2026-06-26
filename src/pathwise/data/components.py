"""Composite components — reusable, recursively-nested building blocks.

The authoring model: every reusable thing has a unique name and lives in a
*component library*. A **asset** component is a leaf (a technology recipe + a
capacity). A **group** component is a composite: it lists its children (each a
reference to another component, by name, with an instance *alias*) and the
**links between those children** — so a group carries its own internal
wiring and reusing the group reuses the wiring.

Placing a component **instantiates** it: :func:`instantiate` walks the chosen
component top-down and stamps a fresh INSTANCE of every descendant into the
recursive ``nodes`` / ``assets`` / ``links`` hierarchy (path-qualified
ids keep instances unique), so one definition can be reused in many groups, and
produces a workbook the engine (and :func:`pathwise.core.run.run_model`) consumes
directly.

This is the "vertical" (composition) and "horizontal" (links) design,
together, as data.

:class:`ComponentLibrary` is the *component library*: the editable, SQLite-backed
catalogue of technologies, flows, measures, and MACCs the authoring UI
builds interactively. It reuses the shared component-template models in
:mod:`pathwise.data.templates`. (The separate, importable-workbook catalogue lives
in :mod:`pathwise.data.libraries`.)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, model_validator

from pathwise.data.aliases import normalize_workbook
from pathwise.data.sheets import (
    ASSETS,
    FLOW_PRICES,
    FLOW_PROPERTIES,
    FLOWS,
    GROUPS,
    IMPACTS,
    IO,
    IO_T,
    LEVER_BLOCKS,
    LEVER_BLOCKS_T,
    LEVERS,
    LINKS,
    MACCS,
    META,
    NODES,
    STATIONS,
    STORAGE,
    TECHNOLOGIES,
    TECHNOLOGIES_PRICES,
    TRANSITIONS,
)
from pathwise.data.templates import (
    FlowTemplate,
    IoRow,
    LeverBlockTemplate,
    LeverTemplate,
    StationTemplate,
    StorageTemplate,
    TechnologyTemplate,
    _io_rows,
    _io_t_rows,
    _lever_block_t_rows,
    _station_row,
    _storage_row,
    _tech_row,
)
from pathwise.data.workbook import Workbook


class AssetComponent(BaseModel):
    """A real-world asset: one physical unit running one technology.

    This is the **Project** layer's core primitive. A component (technology) is
    the per-unit technical spec; a asset is a named instance of it with its
    real-world facts: an owning **company**, a physical **capacity** (size), a
    **build_year** / **close_year**, and its own **levers** (a per-asset MACC
    — the same technology's retrofits, which may differ asset-to-asset). The
    same technology appears as many differently-named assets across companies.

    Each asset is independent (a hard copy): editing one asset's levers
    never affects another. Instantiating a asset stamps each lever onto the
    resulting node, with block capex/opex scaled to the instance capacity.
    """

    name: str
    label: str = ""
    technology: str  # a technology_id defined in the library's technologies
    capacity: float = Field(default=0.0, ge=0.0)
    #: The company that owns this asset (free-text; a project groups by it).
    owner: str = ""
    #: Real-world lifecycle: the year the asset is built / retired (0 = unset).
    build_year: int = Field(default=0, ge=0)
    close_year: int = Field(default=0, ge=0)
    measures: list[LeverTemplate] = Field(default_factory=list)


class ChildRef(BaseModel):
    """A child slot in a group: which component, under what instance alias."""

    component: str
    alias: str = ""  # instance name within the parent (defaults to the component name)

    def instance_alias(self) -> str:
        return self.alias or self.component


class LinkTemplate(BaseModel):
    """A connection between two sibling children of a group (by their aliases)."""

    source: str  # producer child alias
    target: str  # consumer child alias
    # ``commodity`` is the pre-rename input key (component libraries saved before
    # commodity→flow); accept it so old ``links_json`` / ``connections_json`` blobs load.
    flow: str = Field(validation_alias=AliasChoices("flow", "commodity"))
    lag_years: int = Field(default=0, ge=0)


class GroupComponent(BaseModel):
    """A composite component: named children + the links that wire them.

    .. deprecated:: legacy / backward-compat
        The builder no longer authors :class:`GroupComponent` objects; composite
        structures are expressed directly in the ``nodes`` / ``links``
        hierarchy via :func:`instantiate_into`.  This class is retained only to
        round-trip legacy ``groups`` sheet rows from older SQLite component
        libraries.
    """

    name: str
    label: str = ""
    level: str = ""  # the designed level this group sits at (free text)
    children: list[ChildRef] = Field(min_length=1)
    links: list[LinkTemplate] = Field(default_factory=list)
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""

    @model_validator(mode="after")
    def _aliases_unique_and_wired(self) -> GroupComponent:
        aliases = [c.instance_alias() for c in self.children]
        if len(aliases) != len(set(aliases)):
            raise ValueError(f"group '{self.name}' has duplicate child aliases")
        known = set(aliases)
        for conn in self.links:
            for end in (conn.source, conn.target):
                if end not in known:
                    raise ValueError(f"group '{self.name}' link references unknown child '{end}'")
        return self


class MaccGroup(BaseModel):
    """A MACC — a named, reusable BUNDLE of individual levers.

    The "group of levers" of the Component builder: it links a set of
    standalone, reusable :class:`LeverTemplate`\\ s by id. A technology lists
    the MACCs that apply to it (``TechnologyTemplate.maccs``); placing that
    technology stamps every lever of those MACCs onto the resulting asset.
    """

    macc_id: str
    label: str = ""
    measures: list[str] = Field(default_factory=list)  # individual lever ids
    #: Free-text notes / references for the authoring UI (optimiser ignores it).
    notes: str = ""


class ComponentLibrary(BaseModel):
    """A catalogue of the three reusable building blocks — technologies (recipes
    + their streams), streams (flows), and measures (individual + grouped
    into MACCs). ``assets`` / ``groups`` are legacy composite components kept
    for back-compatibility; the builder no longer authors them (the Network
    places a technology directly as a asset)."""

    label: str = ""
    flows: list[FlowTemplate] = Field(default_factory=list)
    technologies: list[TechnologyTemplate] = Field(default_factory=list)
    #: Storage + station component kinds (alongside technologies). Each is placed as an
    #: asset NODE (like a technology), plus a ``storage`` / ``stations`` row keyed by it.
    storages: list[StorageTemplate] = Field(default_factory=list)
    stations: list[StationTemplate] = Field(default_factory=list)
    measures: list[LeverTemplate] = Field(default_factory=list)
    maccs: list[MaccGroup] = Field(default_factory=list)
    assets: list[AssetComponent] = Field(default_factory=list)
    groups: list[GroupComponent] = Field(default_factory=list)
    #: Free-text notes / references keyed by DERIVED sector name. Sectors are not
    #: stored entities, so their notes live here at the library level; entity notes
    #: live on the entities themselves. Optimiser ignores all of it.
    notes_by_sector: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names_unique(self) -> ComponentLibrary:
        names = [m.name for m in self.assets] + [g.name for g in self.groups]
        if len(names) != len(set(names)):
            raise ValueError("duplicate component name across assets/groups")
        return self

    def asset(self, name: str) -> AssetComponent | None:
        return next((m for m in self.assets if m.name == name), None)

    def group(self, name: str) -> GroupComponent | None:
        return next((g for g in self.groups if g.name == name), None)

    def technology(self, tech_id: str) -> TechnologyTemplate | None:
        return next((t for t in self.technologies if t.technology_id == tech_id), None)

    def storage(self, storage_id: str) -> StorageTemplate | None:
        return next((s for s in self.storages if s.storage_id == storage_id), None)

    def station(self, station_id: str) -> StationTemplate | None:
        return next((s for s in self.stations if s.station_id == station_id), None)

    def lever(self, lever_id: str) -> LeverTemplate | None:
        return next((m for m in self.measures if m.lever_id == lever_id), None)

    def macc(self, macc_id: str) -> MaccGroup | None:
        return next((g for g in self.maccs if g.macc_id == macc_id), None)

    def technology_measures(self, tech_id: str) -> list[LeverTemplate]:
        """Every lever reachable from a technology via its linked MACCs."""
        tech = self.technology(tech_id)
        if tech is None:
            return []
        seen: dict[str, LeverTemplate] = {}
        for macc_id in tech.maccs:
            macc = self.macc(macc_id)
            if macc is None:
                continue
            for mid in macc.measures:
                m = self.lever(mid)
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
    technology → its io-target flows + its MACCs (+ those MACCs' levers);
    MACC → its levers; lever → its target flow; stream → itself. A
    dependency the destination already has (by id) is REUSED, never overwritten —
    the project keeps its own edits. Returns a NEW library (pure).
    """
    out = dst.model_copy(deep=True)
    have_c = {c.flow_id for c in out.flows}
    have_m = {m.lever_id for m in out.measures}
    have_g = {g.macc_id for g in out.maccs}
    have_t = {t.technology_id for t in out.technologies}
    have_s = {s.storage_id for s in out.storages}
    have_st = {s.station_id for s in out.stations}

    def add_flow(cid: str) -> None:
        if not cid or cid in have_c:
            return
        c = next((x for x in src.flows if x.flow_id == cid), None)
        if c is not None:
            out.flows.append(c.model_copy(deep=True))
            have_c.add(cid)

    def add_measure(mid: str) -> None:
        if not mid or mid in have_m:
            return
        m = src.lever(mid)
        if m is not None:
            out.measures.append(m.model_copy(deep=True))
            have_m.add(mid)
            add_flow(m.target)  # energy_efficiency targets a flow (impacts: no-op)

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
                add_flow(r.target)
        for gid in t.maccs:
            add_macc(gid)

    def add_storage(sid: str) -> None:
        if not sid or sid in have_s:
            return
        s = src.storage(sid)
        if s is not None:
            out.storages.append(s.model_copy(deep=True))
            have_s.add(sid)
            add_flow(s.flow_id)
            if s.energy_flow:
                add_flow(s.energy_flow)

    def add_station(sid: str) -> None:
        if not sid or sid in have_st:
            return
        s = src.station(sid)
        if s is not None:
            out.stations.append(s.model_copy(deep=True))
            have_st.add(sid)
            add_flow(s.refuel_flow)

    if kind == "technology":
        add_tech(component_id)
    elif kind == "storage":
        add_storage(component_id)
    elif kind == "station":
        add_station(component_id)
    elif kind == "stream":
        add_flow(component_id)
    elif kind == "lever":
        add_measure(component_id)
    elif kind == "macc":
        add_macc(component_id)
    return out


# ── Project bundle (a self-contained, portable project) ───────────────────────

#: Discriminator stamped on an exported project so import can reject other JSON.
PROJECT_BUNDLE_FORMAT = "pathwise.project"


class ProjectBundle(BaseModel):
    """A self-contained, portable **project** — a named workspace bundling its
    Facility + Network model with every component it needs to re-open and
    re-edit on any asset.

    Maps onto the three-layer model:

    - ``model``: the shared Facility + Network workbook
      (nodes / assets / links / … + the ``project`` sheet that carries the
      name). The engine runs off this alone — placed recipes are already inlined.
    - ``session_libraries``: the project's OWN (project-specific) component
      libraries, kept verbatim. They live only with the project, never in the base
      catalogue.
    - ``base_libraries``: every BASE component the model references, sliced to the
      dependency closure actually used, so the Library tab and component pickers
      resolve after import even on a host that lacks those base libraries.
    """

    format: str = PROJECT_BUNDLE_FORMAT
    version: int = 1
    name: str = ""
    model: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    session_libraries: dict[str, ComponentLibrary] = Field(default_factory=dict)
    base_libraries: dict[str, ComponentLibrary] = Field(default_factory=dict)


def referenced_technology_ids(model: dict[str, list[dict[str, Any]]]) -> set[str]:
    """Every technology id a model uses: each asset's baseline technology plus
    both endpoints of every transition.

    Used to slice base libraries down to the components a project actually needs
    (the recipe rows themselves already live inline in the model).

    Args:
        model: A session workbook (reads its ``assets`` + ``transitions`` sheets).

    Returns:
        The set of referenced ``technology_id`` strings (falsy ids dropped).
    """
    out: set[str] = set()
    for row in model.get("assets", []):
        tid = str(row.get("baseline_technology") or "")
        if tid:
            out.add(tid)
    for row in model.get("transitions", []):
        for key in ("from_technology", "to_technology"):
            tid = str(row.get(key) or "")
            if tid:
                out.add(tid)
    return out


def slice_library_to_technologies(src: ComponentLibrary, tech_ids: set[str]) -> ComponentLibrary:
    """A minimal closed sub-library of ``src`` holding only the technologies in
    ``tech_ids`` that ``src`` actually defines, plus their dependency closure
    (io-target flows, linked MACCs and their measures).

    Args:
        src: The source (base) library to slice — not mutated.
        tech_ids: Technology ids to keep (typically :func:`referenced_technology_ids`).

    Returns:
        A NEW :class:`ComponentLibrary` (empty if ``src`` defines none of ``tech_ids``).
    """
    out = ComponentLibrary(label=src.label)
    for tid in sorted(tech_ids):
        if src.technology(tid) is not None:
            out = copy_component_into(out, src, "technology", tid)
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
# bits (a asset's measures, a group's children/links) ride along as a
# JSON column so the round-trip stays lossless.


def library_to_workbook(lib: ComponentLibrary) -> Workbook:
    """Decompose a component library into a ``{sheet: rows}`` workbook (lossless).

    Per-year cost trajectories ride on separate long-format sheets
    (``flow_prices`` / ``technologies_prices`` / ``measure_blocks_t``, keyed
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
        FLOWS: [_flow_row(c) for c in lib.flows],
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
        LEVERS: [
            with_notes(
                {
                    "lever_id": m.lever_id,
                    "label": m.label,
                    "type": m.type,
                    "target": m.target,
                    "lifetime": m.lifetime,
                },
                m.notes,
            )
            for m in lib.measures
        ],
        LEVER_BLOCKS: [
            {
                "lever_id": m.lever_id,
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
        STORAGE: [_storage_row(s) for s in lib.storages],
        STATIONS: [_station_row(s) for s in lib.stations],
        ASSETS: [
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
            for mc in lib.assets
        ],
        GROUPS: [
            with_notes(
                {
                    "name": g.name,
                    "label": g.label,
                    "level": g.level,
                    "children_json": js([c.model_dump() for c in g.children]),
                    "links_json": js([c.model_dump() for c in g.links]),
                },
                g.notes,
            )
            for g in lib.groups
        ],
    }
    # Per-year cost trajectories — only when populated (keeps trajectory-free
    # libraries byte-identical to the legacy sheets).
    if cp := _flow_price_rows(lib):
        wb[FLOW_PRICES] = cp
    if tp := _technology_price_rows(lib):
        wb[TECHNOLOGIES_PRICES] = tp
    if iot := [row for t in lib.technologies for row in _io_t_rows(t)]:
        wb[IO_T] = iot
    if mb := _lever_block_traj_rows(lib):
        wb[LEVER_BLOCKS_T] = mb
    if props := [
        {"flow_id": c.flow_id, "property": k, "value": v}
        for c in lib.flows
        for k, v in c.properties.items()
    ]:
        wb[FLOW_PROPERTIES] = props
    return wb


def _flow_traj_rows(c: FlowTemplate) -> list[dict[str, Any]]:
    """One flow's long-format price rows (flow_id, year, price?, sale_price?).

    Matches the ``flow_prices`` sheet the assembler already reads, so a
    flow's per-year prices drive the optimiser as soon as the library loads.
    """
    rows: list[dict[str, Any]] = []
    for y in sorted(set(c.price_by_year) | set(c.sale_price_by_year)):
        row: dict[str, Any] = {"flow_id": c.flow_id, "year": y}
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


def _flow_price_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format flow price rows across the whole library."""
    return [row for c in lib.flows for row in _flow_traj_rows(c)]


def _technology_price_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format technology cost rows across the whole library."""
    return [row for t in lib.technologies for row in _tech_traj_rows(t)]


def _lever_block_traj_rows(lib: ComponentLibrary) -> list[dict[str, Any]]:
    """Long-format lever-block trajectory rows, keyed (lever_id, block, year).

    Blocks have no own id, so the block ORDINAL (its index in the lever's
    ``blocks`` list, matching the ``lever_blocks`` sheet) completes the key.
    """
    rows: list[dict[str, Any]] = []
    for m in lib.measures:
        for i, b in enumerate(m.blocks):
            for y in sorted(set(b.capex_per_capacity_by_year) | set(b.opex_per_capacity_by_year)):
                row: dict[str, Any] = {"lever_id": m.lever_id, "block": i, "year": y}
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
    # Bundled seeds + libraries saved before the rename carry OLD sheet/column names
    # (``commodities``/``commodity_prices`` …); normalise to the current vocabulary.
    wb = normalize_workbook(wb)
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
        [{**r, "_key": _es(r.get("flow_id"))} for r in wb.get(FLOW_PRICES, [])],
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
            {**r, "_key": (_es(r.get("lever_id")), _year(r.get("block")) or 0)}
            for r in wb.get(LEVER_BLOCKS_T, [])
        ],
        "capex_per_capacity",
        "opex_per_capacity",
    )

    # Physical stream properties (long format: flow_id, property, value).
    props_by: dict[str, dict[str, float]] = {}
    for r in wb.get(FLOW_PROPERTIES, []):
        cid, prop = _es(r.get("flow_id")), _es(r.get("property"))
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
    for r in wb.get(LEVER_BLOCKS, []):
        blocks_by.setdefault(_es(r.get("lever_id")), []).append(r)
    measures = [
        LeverTemplate(
            lever_id=_es(r.get("lever_id")),
            label=_es(r.get("label")),
            type=_es(r.get("type")) or "energy_efficiency",
            target=_es(r.get("target")),
            lifetime=int(_enum(r.get("lifetime"), 15)) or 15,
            blocks=[
                LeverBlockTemplate(
                    reduction=_enum(b.get("reduction"), 0.01),
                    capex_per_capacity=_enum(b.get("capex_per_capacity")),
                    opex_per_capacity=_enum(b.get("opex_per_capacity")),
                    capex_per_capacity_by_year=block_traj.get(
                        (_es(r.get("lever_id")), _year(b.get("block")) or 0), {}
                    ).get("capex_per_capacity", {}),
                    opex_per_capacity_by_year=block_traj.get(
                        (_es(r.get("lever_id")), _year(b.get("block")) or 0), {}
                    ).get("opex_per_capacity", {}),
                )
                for b in sorted(
                    blocks_by.get(_es(r.get("lever_id")), []), key=lambda b: _enum(b.get("block"))
                )
            ],
            notes=_es(r.get("notes")),
        )
        for r in wb.get(LEVERS, [])
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
    storages = [
        StorageTemplate(
            storage_id=_es(r.get("storage_id")),
            flow_id=_es(r.get("flow_id")),
            max_capacity=_enum(r.get("max_capacity")),
            capex_per_capacity=_enum(r.get("capex_per_capacity")),
            fixed_opex_per_capacity=_enum(r.get("fixed_opex_per_capacity")),
            charge_efficiency=_enum(r.get("charge_efficiency"), 1.0),
            discharge_efficiency=_enum(r.get("discharge_efficiency"), 1.0),
            standing_loss=_enum(r.get("standing_loss")),
            initial_level=_enum(r.get("initial_level")),
            energy_flow=_es(r.get("energy_flow")) or None,
            energy_per_throughput=_enum(r.get("energy_per_throughput")),
            notes=_es(r.get("notes")),
        )
        for r in wb.get(STORAGE, [])
        if _es(r.get("storage_id"))
    ]
    stations = [
        StationTemplate(
            station_id=_es(r.get("station_id")),
            refuel_flow=_es(r.get("refuel_flow")),
            refuel_capacity=_enum(r.get("refuel_capacity")),
            refuel_fee=_enum(r.get("refuel_fee")),
            capex=_enum(r.get("capex")),
            fixed_opex=_enum(r.get("fixed_opex")),
            notes=_es(r.get("notes")),
        )
        for r in wb.get(STATIONS, [])
        if _es(r.get("station_id"))
    ]
    flows = [
        FlowTemplate(
            flow_id=_es(r.get("flow_id")),
            kind=_es(r.get("kind")) or "material",
            unit=_es(r.get("unit")) or "unit",
            price=r.get("price") if isinstance(r.get("price"), (int, float)) else None,
            sale_price=r.get("sale_price")
            if isinstance(r.get("sale_price"), (int, float))
            else None,
            price_by_year=comm_traj.get(_es(r.get("flow_id")), {}).get("price", {}),
            sale_price_by_year=comm_traj.get(_es(r.get("flow_id")), {}).get("sale_price", {}),
            sector=_es(r.get("sector")) or None,
            notes=_es(r.get("notes")),
            properties=props_by.get(_es(r.get("flow_id")), {}),
        )
        for r in wb.get(FLOWS, [])
    ]
    assets = [
        AssetComponent(
            name=_es(r.get("name")),
            label=_es(r.get("label")),
            technology=_es(r.get("technology")),
            capacity=_enum(r.get("capacity")),
            owner=_es(r.get("owner")),
            build_year=int(_enum(r.get("build_year"))),
            close_year=int(_enum(r.get("close_year"))),
            measures=[
                LeverTemplate.model_validate(m)
                for m in json.loads(_es(r.get("measures_json")) or "[]")
            ],
        )
        for r in wb.get(ASSETS, [])
    ]
    groups = [
        GroupComponent(
            name=_es(r.get("name")),
            label=_es(r.get("label")),
            level=_es(r.get("level")),
            children=[
                ChildRef.model_validate(c) for c in json.loads(_es(r.get("children_json")) or "[]")
            ],
            links=[
                LinkTemplate.model_validate(c)
                # ``connections_json`` is the pre-rename column name — read it as a
                # fallback so component libraries saved before connection→link load.
                for c in json.loads(
                    _es(r.get("links_json")) or _es(r.get("connections_json")) or "[]"
                )
            ],
            notes=_es(r.get("notes")),
        )
        for r in wb.get(GROUPS, [])
    ]
    return ComponentLibrary(
        label=label,
        flows=flows,
        technologies=technologies,
        storages=storages,
        stations=stations,
        measures=measures,
        maccs=maccs,
        assets=assets,
        groups=groups,
        notes_by_sector=notes_by_sector,
    )


def instantiate(
    library: ComponentLibrary, component: str, *, instance_id: str | None = None
) -> Workbook:
    """Stamp a component into a recursive hierarchy workbook (one fresh instance).

    Recursively places ``component`` and all its descendants as instance nodes
    (path-qualified ids), emitting the ``nodes`` / ``assets`` / ``links``
    sheets plus the referenced ``technologies`` / ``io`` / ``flows``. The
    result is a runnable workbook (add ``periods`` + ``demand`` to solve).

    Raises:
        KeyError: If ``component`` or any referenced child is not in the library.
    """
    nodes: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    levers: list[dict[str, Any]] = []
    lever_blocks: list[dict[str, Any]] = []
    lever_blocks_t: list[dict[str, Any]] = []

    def place(name: str, node_id: str, parent_id: str | None) -> None:
        asset = library.asset(name)
        if asset is not None:
            nodes.append(
                {
                    "node_id": node_id,
                    "parent_id": parent_id,
                    "kind": "asset",
                    "level": "asset",
                    "label": asset.label or asset.name,
                }
            )
            m_row: dict[str, Any] = {
                "asset_id": node_id,
                "baseline_technology": asset.technology,
                "capacity": asset.capacity,
            }
            # Carry the asset's lifecycle years under the canonical column names
            # the engine reads (0 = unset for the legacy build_year/close_year).
            if asset.build_year:
                m_row["introduced_year"] = asset.build_year
            if asset.close_year:
                m_row["decommission_year"] = asset.close_year
            assets.append(m_row)
            # Levers come from the asset's technology's linked MACCs, plus
            # any embedded directly on the asset (legacy); deduped by id.
            applied = list(asset.measures)
            seen_ids = {m.lever_id for m in applied}
            for m in library.technology_measures(asset.technology):
                if m.lever_id not in seen_ids:
                    applied.append(m)
                    seen_ids.add(m.lever_id)
            for m in applied:
                mid = f"{node_id} · {m.lever_id}"
                levers.append(
                    {
                        "lever_id": mid,
                        "type": m.type,
                        "facility": node_id,
                        "target": m.target,
                        "lifetime": m.lifetime,
                    }
                )
                for i, blk in enumerate(m.blocks):
                    lever_blocks.append(
                        {
                            "lever_id": mid,
                            "block": i,
                            "reduction": blk.reduction,
                            "capex": round(blk.capex_per_capacity * asset.capacity, 2),
                            "opex": round(blk.opex_per_capacity * asset.capacity, 2),
                        }
                    )
                    lever_blocks_t.extend(_lever_block_t_rows(mid, i, blk, asset.capacity))
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
        for conn in group.links:
            links.append(
                {
                    "from_node": alias_to_id[conn.source],
                    "to_node": alias_to_id[conn.target],
                    "flow_id": conn.flow,
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
    flows: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    for c in library.flows:
        row: dict[str, Any] = {"flow_id": c.flow_id, "kind": c.kind, "unit": c.unit}
        if c.price is not None:
            row["price"] = c.price
        if c.sale_price is not None:
            row["sale_price"] = c.sale_price
        if c.sector:
            row["sector"] = c.sector
        flows.append(row)
        properties.extend(
            {"flow_id": c.flow_id, "property": k, "value": v} for k, v in c.properties.items()
        )

    out: Workbook = {
        NODES: nodes,
        ASSETS: assets,
        LINKS: links,
        TECHNOLOGIES: technologies,
        IO: io,
        FLOWS: flows,
        IMPACTS: [{"impact_id": i, "unit": "t"} for i in sorted(impact_ids)],
    }
    if io_t:
        out[IO_T] = io_t
    if properties:
        out[FLOW_PROPERTIES] = properties
    if levers:
        out[LEVERS] = levers
        out[LEVER_BLOCKS] = lever_blocks
        if lever_blocks_t:
            out[LEVER_BLOCKS_T] = lever_blocks_t
    # Per-year cost trajectories so authored per-year capex/opex/price drive the
    # optimiser once the instance is solved (assembler reads these sheets).
    if tp := _technology_price_rows(library):
        out[TECHNOLOGIES_PRICES] = tp
    cp = [row for c in library.flows for row in _flow_traj_rows(c)]
    if cp:
        out[FLOW_PRICES] = cp
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

    The "place a facility into a company" operation of the Network builder:
    :func:`instantiate` stamps a brand-new instance (path-qualified ids, so two
    companies never share a facility), then this merges that instance into the
    existing workbook — appending ``nodes`` / ``assets`` / ``links`` /
    ``levers`` / ``lever_blocks`` and merging the referenced
    ``technologies`` / ``io`` / ``flows`` by id (existing rows win, recipes
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

    # lever_blocks_t rows are per-instance (path-qualified lever ids), so
    # they append cleanly like lever_blocks.
    append_keys = (
        NODES,
        ASSETS,
        LINKS,
        LEVERS,
        LEVER_BLOCKS,
        LEVER_BLOCKS_T,
    )
    for key in append_keys:
        if fresh.get(key):
            wb.setdefault(key, []).extend(fresh[key])

    _merge_by(wb, fresh, TECHNOLOGIES, "technology_id")
    _merge_by(wb, fresh, FLOWS, "flow_id")
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
    have_comm = {str(r.get("flow_id")) for r in model.get(FLOWS, [])}
    new_tp = [
        r
        for r in fresh.get(TECHNOLOGIES_PRICES, [])
        if str(r.get("technology_id")) not in have_tech
    ]
    if new_tp:
        wb.setdefault(TECHNOLOGIES_PRICES, []).extend(new_tp)
    new_cp = [r for r in fresh.get(FLOW_PRICES, []) if str(r.get("flow_id")) not in have_comm]
    if new_cp:
        wb.setdefault(FLOW_PRICES, []).extend(new_cp)
    return wb


def _merge_by(wb: Workbook, fresh: Workbook, sheet: str, id_col: str) -> None:
    """Append ``fresh[sheet]`` rows into ``wb[sheet]``, skipping existing ids."""
    have = {str(r.get(id_col)) for r in wb.get(sheet, [])}
    wb.setdefault(sheet, [])
    for row in fresh.get(sheet, []):
        if str(row.get(id_col)) not in have:
            wb[sheet].append(row)
            have.add(str(row.get(id_col)))


def _flow_row(c: FlowTemplate) -> dict[str, Any]:
    row: dict[str, Any] = {"flow_id": c.flow_id, "kind": c.kind, "unit": c.unit}
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


def _merge_flow_traj(wb: Workbook, c: FlowTemplate) -> None:
    """Carry a flow's per-year price/sale_price into the model's ``flow_prices``."""
    traj = _flow_traj_rows(c)
    if not traj:
        return
    rows = wb.setdefault(FLOW_PRICES, [])
    if any(str(r.get("flow_id")) == c.flow_id for r in rows):
        return
    rows.extend(traj)


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


def _instance_into(wb: Workbook, tech: TechnologyTemplate, iid: str, source: str) -> None:
    """Copy a technology template into ``wb`` under a unique instance id ``iid``.

    Rekeys the technology / io / cost-trajectory / io-trajectory rows to ``iid``
    so a placed asset owns a **private, independently-editable copy** of the
    technology; ``source_technology`` records the component it was stamped from.
    Two assets stamped from the same component therefore get distinct instances
    and can be edited apart.
    """

    if any(str(r.get("technology_id")) == iid for r in wb.get(TECHNOLOGIES, [])):
        return  # already stamped this instance (idempotent)

    def _rekey(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in rows:
            r["technology_id"] = iid
        return rows

    trow = _tech_row(tech)
    trow["technology_id"] = iid
    trow["source_technology"] = source
    _merge_row(wb, TECHNOLOGIES, "technology_id", trow)  # iid is unique → always added
    wb.setdefault(IO, []).extend(_rekey(_io_rows(tech)))
    if traj := _rekey(_tech_traj_rows(tech)):
        wb.setdefault(TECHNOLOGIES_PRICES, []).extend(traj)
    if iot := _rekey(_io_t_rows(tech)):
        wb.setdefault(IO_T, []).extend(iot)


def place_technology(
    model: Workbook,
    library: ComponentLibrary,
    technology_id: str,
    *,
    parent_id: str,
    capacity: float = 0.0,
    instance_id: str | None = None,
) -> Workbook:
    """Place a technology as a fresh ASSET node under ``parent_id``.

    The Network builder's "add component": a technology becomes one asset
    node (a process); its recipe (``technologies`` / ``io``) + referenced streams
    + impacts are merged in, and every lever of the technology's linked MACCs is
    stamped onto the asset (block cost scaled to ``capacity``). Pure — returns a
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
            "kind": "asset",
            "level": "asset",
            "label": technology_id,
        }
    )
    # The asset runs its OWN instance of the technology (a private copy), so the
    # same component placed on two assets can be edited independently.
    iid = f"{technology_id}@{node_id}"
    wb.setdefault(ASSETS, []).append(
        {
            "asset_id": node_id,
            "baseline_technology": iid,
            "capacity": capacity,
            "source_technology": technology_id,
        }
    )
    _instance_into(wb, tech, iid, technology_id)
    inputs_outputs = {r.target for r in tech.io if r.role != "impact"}
    for c in library.flows:
        if c.flow_id in inputs_outputs:
            _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
            _merge_flow_traj(wb, c)
    for imp in sorted({r.target for r in tech.io if r.role == "impact"}):
        _merge_row(wb, IMPACTS, "impact_id", {"impact_id": imp, "unit": "t"})

    levers_out = wb.setdefault(LEVERS, [])
    blocks = wb.setdefault(LEVER_BLOCKS, [])
    for m in library.technology_measures(technology_id):
        mid = f"{node_id} · {m.lever_id}"
        levers_out.append(
            {
                "lever_id": mid,
                "type": m.type,
                "facility": node_id,
                "target": m.target,
                "lifetime": m.lifetime,
            }
        )
        for i, blk in enumerate(m.blocks):
            blocks.append(
                {
                    "lever_id": mid,
                    "block": i,
                    "reduction": blk.reduction,
                    "capex": round(blk.capex_per_capacity * capacity, 2),
                    "opex": round(blk.opex_per_capacity * capacity, 2),
                }
            )
            if t_rows := _lever_block_t_rows(mid, i, blk, capacity):
                wb.setdefault(LEVER_BLOCKS_T, []).extend(t_rows)
    return wb


def _unique_id(rows: list[dict[str, Any]], id_col: str, wanted: str) -> str:
    """``wanted`` if free in ``rows[id_col]``, else ``wanted-2``, ``-3`` … unused."""
    have = {str(r.get(id_col)) for r in rows}
    if wanted not in have:
        return wanted
    n = 2
    while f"{wanted}-{n}" in have:
        n += 1
    return f"{wanted}-{n}"


def _scope_group(wb: Workbook, parent_id: str) -> str:
    """The abstract group a node placed under ``parent_id`` belongs to. If ``parent_id``
    is a kind-group node (Storage / Stations / Technology … wrapper), step up to its
    parent so the engine scopes on the real group, not the kind wrapper. Group *types*
    are arbitrary user labels — this only unwraps the kind grouping, nothing hardcoded."""
    for r in wb.get(NODES, []):
        if str(r.get("node_id")) == parent_id:
            return str(r.get("parent_id") or "") or parent_id
    return parent_id


def _place_node(
    wb: Workbook,
    parent_id: str,
    label: str,
    level: str,
    instance_id: str | None,
    component: str | None = None,
) -> str:
    """Add a fresh asset NODE under ``parent_id`` (kind=asset, given ``level``) and
    return its unique node id. EVERY component kind is a real node in the hierarchy —
    they show + group like a technology (``parent_id`` is just their abstract place, not
    a scope). ``component`` records the model-row id this node represents, when that id
    differs from the node id (flow / lever / macc reference a shared row by its own id)."""
    have = {str(r.get("node_id")) for r in wb.get(NODES, [])}
    node_id = instance_id or f"{parent_id}/{label}"
    base, n = node_id, 2
    while node_id in have:
        node_id = f"{base}-{n}"
        n += 1
    row: dict[str, Any] = {
        "node_id": node_id,
        "parent_id": parent_id,
        "kind": "asset",
        "level": level,
        "label": label,
    }
    if component is not None:
        row["component"] = component
    wb.setdefault(NODES, []).append(row)
    return node_id


def _copy_lever_def(wb: Workbook, library: ComponentLibrary, lever_id: str) -> None:
    """Copy a lever DEFINITION (row + cost-curve blocks + its target flow) from the
    library into the model — the System's hard copy. Idempotent by lever id; blocks store
    per-capacity values (a later facility link scales them). The model is the System copy;
    the Library is untouched."""
    m = library.lever(lever_id)
    if m is None:
        return
    _merge_row(
        wb,
        LEVERS,
        "lever_id",
        {
            "lever_id": m.lever_id,
            "label": m.label,
            "type": m.type,
            "target": m.target,
            "lifetime": m.lifetime,
        },
    )
    if not any(str(r.get("lever_id")) == lever_id for r in wb.get(LEVER_BLOCKS, [])):
        for i, b in enumerate(m.blocks):
            wb.setdefault(LEVER_BLOCKS, []).append(
                {
                    "lever_id": lever_id,
                    "block": i,
                    "reduction": b.reduction,
                    "capex": b.capex_per_capacity,
                    "opex": b.opex_per_capacity,
                }
            )
    c = next((x for x in library.flows if x.flow_id == m.target), None)
    if c is not None:
        _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
        _merge_flow_traj(wb, c)


def place_flow(
    model: Workbook,
    library: ComponentLibrary,
    flow_id: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Place a flow component as an asset NODE + the flow's hard copy in the model.

    Same pipeline as every other kind: a node in the System hierarchy, plus the flow's
    definition copied into the model's ``flows`` (its real-world price etc. are then edited
    in the System, never the Library). The node's ``component`` links to the flow row.
    """
    c = next((x for x in library.flows if x.flow_id == flow_id), None)
    if c is None:
        raise KeyError(f"unknown flow '{flow_id}'")
    wb: Workbook = {k: list(v) for k, v in model.items()}
    _place_node(wb, parent_id, flow_id, "flow", instance_id, component=flow_id)
    _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
    _merge_flow_traj(wb, c)
    return wb


def place_lever(
    model: Workbook,
    library: ComponentLibrary,
    lever_id: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Place a lever component as an asset NODE + the lever's hard copy in the model."""
    if library.lever(lever_id) is None:
        raise KeyError(f"unknown lever '{lever_id}'")
    wb: Workbook = {k: list(v) for k, v in model.items()}
    _place_node(wb, parent_id, lever_id, "lever", instance_id, component=lever_id)
    _copy_lever_def(wb, library, lever_id)
    return wb


def place_macc(
    model: Workbook,
    library: ComponentLibrary,
    macc_id: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Place a MACC component as an asset NODE + the MACC's hard copy (and its levers)."""
    g = library.macc(macc_id)
    if g is None:
        raise KeyError(f"unknown macc '{macc_id}'")
    wb: Workbook = {k: list(v) for k, v in model.items()}
    _place_node(wb, parent_id, macc_id, "macc", instance_id, component=macc_id)
    _merge_row(
        wb,
        MACCS,
        "macc_id",
        {"macc_id": g.macc_id, "label": g.label, "measures": "|".join(g.measures)},
    )
    for mid in g.measures:
        _copy_lever_def(wb, library, mid)
    return wb


def place_component(
    model: Workbook,
    library: ComponentLibrary,
    kind: str,
    component_id: str,
    *,
    parent_id: str,
    capacity: float = 0.0,
    instance_id: str | None = None,
) -> Workbook:
    """Place ANY component kind into the System through ONE uniform pipeline: a node in the
    hierarchy + the component's definition hard-copied into the model, so the instance is
    edited in the System (never the Library). Dispatches to the per-kind placer — the
    pipeline is identical; only the copied fields differ by kind.

    Raises:
        KeyError: If ``kind`` is unknown or ``component_id`` is not in the library.
    """
    if kind == "technology":
        return place_technology(
            model,
            library,
            component_id,
            parent_id=parent_id,
            capacity=capacity,
            instance_id=instance_id,
        )
    if kind == "storage":
        return place_storage(
            model, library, component_id, parent_id=parent_id, instance_id=instance_id
        )
    if kind == "station":
        return place_station(
            model, library, component_id, parent_id=parent_id, instance_id=instance_id
        )
    if kind == "flow":
        return place_flow(
            model, library, component_id, parent_id=parent_id, instance_id=instance_id
        )
    if kind == "lever":
        return place_lever(
            model, library, component_id, parent_id=parent_id, instance_id=instance_id
        )
    if kind == "macc":
        return place_macc(
            model, library, component_id, parent_id=parent_id, instance_id=instance_id
        )
    raise KeyError(f"unknown component kind '{kind}'")


def place_storage(
    model: Workbook,
    library: ComponentLibrary,
    storage_id: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Place a storage component as an asset NODE under ``parent_id``.

    Storage is a component like any other — it becomes a node in the hierarchy (so it
    shows in the structure, groups + moves like a technology), plus a ``storage`` row
    keyed by that node id carrying its physics + economics. ``company`` records the
    node's parent purely as the abstract group it sits in (not a scope the user sets).
    Merges the stored flow (+ any running-energy flow). Pure — returns a new workbook.

    Raises:
        KeyError: If ``storage_id`` is not in the library.
    """
    s = library.storage(storage_id)
    if s is None:
        raise KeyError(f"unknown storage '{storage_id}'")
    wb: Workbook = {k: list(v) for k, v in model.items()}
    group = _scope_group(wb, parent_id)
    node_id = _place_node(wb, parent_id, storage_id, "storage", instance_id)
    wb.setdefault(STORAGE, []).append(_storage_row(s, storage_id=node_id, company=group))
    for cid in (s.flow_id, s.energy_flow):
        c = next((x for x in library.flows if x.flow_id == cid), None)
        if c is not None:
            _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
            _merge_flow_traj(wb, c)
    return wb


def place_station(
    model: Workbook,
    library: ComponentLibrary,
    station_id: str,
    *,
    parent_id: str,
    instance_id: str | None = None,
) -> Workbook:
    """Place a station component as an asset NODE under ``parent_id``.

    Like :func:`place_storage`: a station is a node in the hierarchy plus a ``stations``
    row keyed by that node id. ``company`` records the parent group (abstract place).
    Merges its dispensed fuel flow into ``flows``. Pure — returns a new workbook.

    Raises:
        KeyError: If ``station_id`` is not in the library.
    """
    s = library.station(station_id)
    if s is None:
        raise KeyError(f"unknown station '{station_id}'")
    wb: Workbook = {k: list(v) for k, v in model.items()}
    group = _scope_group(wb, parent_id)
    node_id = _place_node(wb, parent_id, station_id, "station", instance_id)
    wb.setdefault(STATIONS, []).append(_station_row(s, station_id=node_id, company=group))
    c = next((x for x in library.flows if x.flow_id == s.refuel_flow), None)
    if c is not None:
        _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
        _merge_flow_traj(wb, c)
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
    ``from_technology`` — used to offer alternatives on a asset in the value
    chain WITHOUT baking them into the Component library.

    Merges the alternative's recipe (``technologies`` / ``io`` + referenced
    ``flows`` / ``impacts``) into the model and adds a ``transitions`` row
    ``from_technology → technology_id`` (any facility running ``from_technology``
    may switch). Idempotent on the transition. Pure — returns a new workbook.

    Raises:
        KeyError: If ``technology_id`` is not in the library.
    """
    tech = library.technology(technology_id)
    if tech is None:
        raise KeyError(f"unknown technology '{technology_id}'")

    wb: Workbook = {k: list(v) for k, v in model.items()}
    # Per-asset alternative: stamp a PRIVATE instance of the alternative
    # technology for the asset whose baseline is ``from_technology`` (itself an
    # instance id), so the switch option is editable independently per asset.
    node = from_technology.split("@", 1)[1] if "@" in from_technology else from_technology
    alt_iid = f"{technology_id}@{node}"
    _instance_into(wb, tech, alt_iid, technology_id)
    inputs_outputs = {r.target for r in tech.io if r.role != "impact"}
    for c in library.flows:
        if c.flow_id in inputs_outputs:
            _merge_row(wb, FLOWS, "flow_id", _flow_row(c))
            _merge_flow_traj(wb, c)
    for imp in sorted({r.target for r in tech.io if r.role == "impact"}):
        _merge_row(wb, IMPACTS, "impact_id", {"impact_id": imp, "unit": "t"})

    transitions = wb.setdefault(TRANSITIONS, [])
    exists = any(
        str(r.get("from_technology")) == from_technology and str(r.get("to_technology")) == alt_iid
        for r in transitions
    )
    if not exists:
        transitions.append(
            {
                "from_technology": from_technology,
                "to_technology": alt_iid,
                "action": "replace",
                "capex_per_capacity": capex_per_capacity,
                "source_technology": technology_id,
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
    component DEFINITIONS (streams, technology recipes, levers) interleaved with
    its network STRUCTURE (nodes/assets/links). This pulls the
    definitions back out into a :class:`ComponentLibrary` so the Component view can
    show the scenario's components, leaving the structure to the Network view.

    Best-effort: ``io`` is grouped back under its technology, and per-facility
    levers (``"<node> · <lever>"``) are de-duplicated to reusable templates.
    The MACC *bundles* and technology→MACC links are not present in an assembled
    workbook, so they are omitted (the individual levers are still recovered).
    """
    # Bundled seeds + libraries saved before the rename carry OLD sheet/column names
    # (``commodities``/``commodity_id`` …); normalise to the current vocabulary first.
    workbook = normalize_workbook(workbook)
    flows: list[FlowTemplate] = []
    seen_c: set[str] = set()
    for r in workbook.get(FLOWS, []):
        cid = _es(r.get("flow_id"))
        if not cid or cid in seen_c:
            continue
        seen_c.add(cid)
        kind = _es(r.get("kind")) or "material"
        flows.append(
            FlowTemplate(
                flow_id=cid,
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
    for r in workbook.get(LEVER_BLOCKS, []):
        blocks_by_m.setdefault(_es(r.get("lever_id")), []).append(r)
    measures: list[LeverTemplate] = []
    seen_m: set[str] = set()
    for r in workbook.get(LEVERS, []):
        mid = _es(r.get("lever_id"))
        base = mid.split(" · ")[-1]  # de-instantiate the per-facility prefix
        if not base or base in seen_m:
            continue
        blks = sorted(blocks_by_m.get(mid, []), key=lambda b: _enum(b.get("block")))
        templates = [
            LeverBlockTemplate(
                reduction=min(max(_enum(b.get("reduction"), 0.01), 1e-6), 1.0),
                capex_per_capacity=max(_enum(b.get("capex")), 0.0),
                opex_per_capacity=max(_enum(b.get("opex")), 0.0),
            )
            for b in blks
        ]
        if not templates:
            continue  # a lever needs at least one block
        seen_m.add(base)
        mtype = _es(r.get("type")) or "energy_efficiency"
        measures.append(
            LeverTemplate(
                lever_id=base,
                label="",
                type=mtype
                if mtype in ("energy_efficiency", "emission_reduction", "environmental")
                else "energy_efficiency",
                target=_es(r.get("target")),
                lifetime=int(_enum(r.get("lifetime"), 15)) or 15,
                blocks=templates,
            )
        )

    return ComponentLibrary(label=label, flows=flows, technologies=technologies, measures=measures)
