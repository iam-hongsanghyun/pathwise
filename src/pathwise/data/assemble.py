"""Translate a workbook + scenario into a core :class:`Problem`.

Pure parsing/normalisation: read the ``{sheet: rows[]}`` workbook, coerce types,
densify year-keyed trajectories, and build the entity collections. No solver
objects and no I/O.
"""

from __future__ import annotations

import math
from typing import Any

from pathwise.core.entities import (
    Commodity,
    CommodityKind,
    Edge,
    Impact,
    Market,
    MarketTarget,
    Measure,
    MeasureBlock,
    MeasureType,
    ObjectiveMode,
    Period,
    Process,
    Storage,
    Technology,
    Transition,
    TransitionAction,
)
from pathwise.core.problem import CostToggles, Fleet, FleetRoute, Problem, Route
from pathwise.data.hierarchy import Hierarchy, load_hierarchy
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.sheets import (
    CHARACTERISATION,
    COMMODITIES,
    COMMODITIES_T_MAX_PURCHASE,
    COMMODITIES_T_PRICE,
    COMMODITIES_T_SALE_PRICE,
    COMMODITY_IMPACTS,
    COMMODITY_IMPACTS_T,
    COMMODITY_PRICES,
    COMMODITY_PROPERTIES,
    COMPANY_CONFIG,
    DEMAND,
    DEMAND_T_AMOUNT,
    EDGE_IMPACTS,
    EDGES,
    EDGES_T,
    FLEET,
    FLEET_ROUTES,
    IMPACT_CAPS,
    IMPACT_CAPS_T_LIMIT,
    IMPACT_PRICES,
    IMPACTS,
    IMPACTS_T_PRICE,
    INVESTMENT_BUDGET,
    INVESTMENT_BUDGET_T_LIMIT,
    IO,
    IO_T,
    MACC_LINKS,
    MACCS,
    MACHINES,
    MARKET_PRICES,
    MARKETS,
    MARKETS_T_ALLOCATION,
    MARKETS_T_MAX_BUY,
    MARKETS_T_MAX_SELL,
    MARKETS_T_PRICE,
    MARKETS_T_SELL_PRICE,
    MAX_CONSUMPTION,
    MAX_CONSUMPTION_T_AMOUNT,
    MAX_PRODUCTION,
    MAX_PRODUCTION_T_AMOUNT,
    MEASURE_BLOCKS,
    MEASURE_BLOCKS_T,
    MEASURE_LINKS,
    MEASURES,
    META,
    MIN_CONSUMPTION,
    MIN_CONSUMPTION_T_AMOUNT,
    MIN_PRODUCTION,
    MIN_PRODUCTION_T_AMOUNT,
    NODE_LAYOUT,
    NODES,
    PERIODS,
    PROCESS_IMPACTS,
    PROCESS_IMPACTS_T,
    PROCESS_INPUTS,
    PROCESS_OUTPUTS,
    PROCESSES,
    PROCESSES_T_CAPACITY,
    PROCESSES_T_FAILURE_RATE,
    PROCESSES_T_FIXED_OPEX,
    PROCESSES_T_MAX_CF,
    ROUTES,
    STORAGE,
    STORAGE_T_CAPEX,
    STORAGE_T_CHARGE_EFFICIENCY,
    STORAGE_T_DISCHARGE_EFFICIENCY,
    STORAGE_T_FIXED_OPEX,
    STORAGE_T_STANDING_LOSS,
    TECH_IMPACTS,
    TECHNOLOGIES,
    TECHNOLOGIES_PRICES,
    TECHNOLOGIES_T_CAPEX,
    TECHNOLOGIES_T_MIN_CF,
    TECHNOLOGIES_T_OPEX,
    TECHNOLOGIES_T_RENEWAL,
    TECHNOLOGY_CAPS,
    TRANSITIONS,
    TRANSITIONS_T,
    UNITS,
)
from pathwise.data.trajectory import interpolate
from pathwise.data.workbook import Workbook
from pathwise.routing import Point, route_distance_km
from pathwise.units import CoefficientConverter, load_units_config

Rows = list[dict[str, Any]]


def _rows(wb: Workbook, sheet: str) -> Rows:
    return wb.get(sheet, [])


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, str) and value.strip() == "":
        return default  # empty cell from an xlsx round-trip
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return default if (math.isnan(f) or math.isinf(f)) else f  # reject NaN/inf cells


def _int(value: Any, default: int | None = None) -> int | None:
    n = _num(value, None)
    return int(n) if n is not None else default


def _numd(value: Any, default: float) -> float:
    """Parse ``value`` to float, falling back to ``default`` only when absent.

    Unlike the ``_num(x, d) or d`` idiom this preserves an explicitly authored
    ``0.0`` (the ``or`` form silently replaces a falsy 0.0 with the default).
    """
    v = _num(value)
    return default if v is None else v


def _str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return str(value).strip()


def _bool(value: Any, default: bool = False) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "t"}
    return bool(value)


def _enabled(r: dict[str, Any]) -> bool:
    """Whether a component row is included in the model.

    Components are included by default; a row is excluded only when its
    ``enabled`` cell is explicitly falsy (the left-rail checkbox). An excluded
    technology / facility / market / store is dropped from the optimisation
    entirely (a checked-but-unplaced item stays in as an available alternative).
    """
    v = r.get("enabled")
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return True
    return _bool(v, True)


def _meta(wb: Workbook) -> dict[str, Any]:
    return {str(r.get("key")): r.get("value") for r in _rows(wb, META)}


def _model_unit_overrides(wb: Workbook, scenario_overrides: Any) -> list[Any]:
    """Pint ``custom_units`` from the model's ``units`` registry sheet + the scenario.

    Each base-anchored row ``(unit, dimension, factor_to_base)`` becomes a pint
    definition ``"<unit> = <factor> * <base>"``, where ``<base>`` is the
    dimension's canonical base from the global ``units.yaml``. Base rows
    (``unit == base``) are skipped — the base is defined globally. Scenario-level
    overrides are appended last so they win (``merged_custom_units`` redefines in
    place). Returns a flat definition list suitable as ``unit_overrides``.
    """
    dims = load_units_config().get("dimensions", {})
    defs: list[str] = []
    for r in _rows(wb, UNITS):
        unit, dim = _str(r.get("unit")), _str(r.get("dimension"))
        factor = _num(r.get("factor_to_base"))
        if not unit or not dim or factor is None or factor <= 0.0:
            continue
        base = dims.get(dim, {}).get("base")
        if base and unit != str(base):
            # Exact float repr, but drop a trailing ".0" so whole factors read cleanly.
            fstr = repr(float(factor))
            defs.append(f"{unit} = {fstr[:-2] if fstr.endswith('.0') else fstr} * {base}")
    if isinstance(scenario_overrides, dict):
        extra = list(scenario_overrides.get("custom_units", []))
    elif isinstance(scenario_overrides, list):
        extra = list(scenario_overrides)
    else:
        extra = []
    return defs + extra


def _wide_temporal(wb: Workbook, sheet: str) -> dict[str, dict[int, float]]:
    """Parse a PyPSA-style wide temporal sheet → ``{item_name: {year: value}}``.

    Rows are snapshots (a ``year`` column); every other column is named by a
    static item (commodity / market / impact id), linking temporal to static
    data by name. Blank cells are skipped (the static default applies).
    """
    out: dict[str, dict[int, float]] = {}
    for r in _rows(wb, sheet):
        y = _int(r.get("year"))
        if y is None:
            continue
        for col, val in r.items():
            if col == "year":
                continue
            v = _num(val)
            if v is not None:
                out.setdefault(str(col), {})[y] = v
    return out


def _temporal_dict(
    wb: Workbook,
    sheet: str,
    temporal_sheet: str,
    id_col: str,
    key_cols: list[str],
    value_col: str,
    base_years: list[int] | None = None,
) -> dict[tuple[Any, ...], float]:
    """Aggregate a relational sheet into ``{(*key, year): value}``.

    Accepts both the legacy long format (a ``year`` + ``value_col`` on each row)
    and the PyPSA-style named-component form (a static row identified by
    ``id_col`` whose values live in the wide ``temporal_sheet``, columns = names).
    Multiple rows mapping to the same key/year are summed.

    When ``base_years`` is given, a row carrying a value but NO ``year`` (and no
    named-component id) is a **base** that applies to every one of those years; a
    year-specific row for the same key overrides the base for that year. This lets
    a single annual cap (e.g. a per-machine max output) hold across the whole run
    without authoring one row per period.
    """
    wide = _wide_temporal(wb, temporal_sheet)
    out: dict[tuple[Any, ...], float] = {}
    base: dict[tuple[Any, ...], float] = {}
    for r in _rows(wb, sheet):
        key = tuple(_str(r.get(c)) or "all" for c in key_cols)
        yr, val = _num(r.get("year")), _num(r.get(value_col))
        if yr is not None and val is not None:  # legacy long row
            out[(*key, int(yr))] = out.get((*key, int(yr)), 0.0) + val
        elif (name := _str(r.get(id_col))) is not None:  # named component
            for y, v in wide.get(name, {}).items():
                out[(*key, y)] = out.get((*key, y), 0.0) + v
        elif val is not None and base_years is not None:  # year-less base → all years
            base[key] = base.get(key, 0.0) + val
    for key, v in base.items():
        for y in base_years or ():
            out.setdefault((*key, y), v)  # a year-specific value already set wins
    return out


def _actions(value: Any) -> frozenset[TransitionAction]:
    """Parse a comma-separated availability string into actions (default: all)."""
    s = _str(value)
    if not s:
        return frozenset(TransitionAction)
    out = set()
    for tok in s.split(","):
        tok = tok.strip().lower()
        if tok in {a.value for a in TransitionAction}:
            out.add(TransitionAction(tok))
    return frozenset(out) if out else frozenset(TransitionAction)


def _expand_hierarchy(workbook: Workbook, h: Hierarchy) -> Workbook:
    """Synthesize flat ``processes`` + ``edges`` from a node hierarchy.

    Each machine becomes one ``Process`` — so a facility is the *sum of its
    machines* and can run **multiple technologies in parallel** — and
    machine↔machine connections become edges. ``company`` is set to the machine's
    top-level subdivision (the child of the root, e.g. the company/sector) and
    ``group`` to its parent (the facility), so the existing facility/company/
    machine scope still resolves for the canonical depth; arbitrary mid-levels are
    handled by the hierarchy-aware scope added later.
    """
    roots = set(h.roots())

    def company_of(mid: str) -> str:
        for a in h.ancestors(mid):
            if h.nodes[a].parent_id in roots:
                return a
        return h.nodes[mid].parent_id or mid

    procs: list[dict[str, Any]] = []
    for mid, m in h.machines.items():
        node = h.nodes.get(mid)
        if node is None:
            continue
        row: dict[str, Any] = {
            "process_id": mid,
            "company": company_of(mid),
            "group": node.parent_id or company_of(mid),
            # Every designed level the machine sits under, so a market / demand /
            # cap scoped to ANY ancestor (sector, company, facility…) resolves.
            "scopes": [mid, *h.ancestors(mid), "all"],
            "baseline_technology": m.baseline_technology,
            "capacity": m.capacity,
            "max_capacity_factor": m.max_capacity_factor,
        }
        if m.introduced_year is not None:
            row["introduced_year"] = m.introduced_year
        if m.decommission_year is not None:
            row["decommission_year"] = m.decommission_year
        if m.max_renewals is not None:
            row["max_renewals"] = m.max_renewals
        procs.append(row)

    # Connections (machine↔machine or group↔group) become machine edges: the
    # producers of the commodity in the source subtree → its consumers in the
    # destination subtree (resolved via each machine's technology I/O).
    io_out: dict[str, set[str]] = {}
    io_in: dict[str, set[str]] = {}
    for r in workbook.get(IO, []):
        tech, role, tgt = _str(r.get("technology_id")), _str(r.get("role")), _str(r.get("target"))
        coef = _num(r.get("coefficient")) or 0.0
        if not tech or not tgt:
            continue
        if role == "output" and coef != 0.0:
            io_out.setdefault(tech, set()).add(tgt)
        elif role == "input" and coef > 0.0:
            io_in.setdefault(tech, set()).add(tgt)
    machine_tech = {mid: m.baseline_technology for mid, m in h.machines.items()}

    def producers(node: str, commodity: str) -> list[str]:
        return [
            m
            for m in h.leaf_machines(node)
            if commodity in io_out.get(machine_tech.get(m, ""), set())
        ]

    def consumers(node: str, commodity: str) -> list[str]:
        return [
            m
            for m in h.leaf_machines(node)
            if commodity in io_in.get(machine_tech.get(m, ""), set())
        ]

    edges = list(workbook.get(EDGES, []))
    edges_t = list(workbook.get(EDGES_T, []))
    edge_impacts = list(workbook.get(EDGE_IMPACTS, []))
    # Seed with any pre-authored machine→machine edge (e.g. a per-provider bound set
    # in the machine popup): the fan-out then skips that triple, so the authored row
    # — carrying its bounds — IS the edge, rather than a duplicate parallel channel.
    seen_edges: set[tuple[str, str, str]] = {
        (f, t, ci)
        for e in edges
        if (f := _str(e.get("from_process")))
        and (t := _str(e.get("to_process")))
        and (ci := _str(e.get("commodity_id")))
    }
    for c in h.connections:
        for s in producers(c.from_node, c.commodity_id):
            for d in consumers(c.to_node, c.commodity_id):
                if s == d or (s, d, c.commodity_id) in seen_edges:
                    continue
                seen_edges.add((s, d, c.commodity_id))
                edge: dict[str, Any] = {
                    "from_process": s,
                    "to_process": d,
                    "commodity_id": c.commodity_id,
                }
                if c.max_flow is not None:
                    edge["max_flow"] = c.max_flow
                if c.min_flow is not None:
                    edge["min_flow"] = c.min_flow
                if c.lag_years:
                    edge["lag_years"] = c.lag_years  # delivery lag (recycling / use-phase return)
                # Per-unit transport physics, carried onto every fanned edge: scalar
                # cost/energy as columns, per-impact freight emissions as edge_impacts.
                if c.cost:
                    edge["freight_cost"] = c.cost
                if c.energy:
                    edge["freight_energy"] = c.energy
                for imp, fac in c.emissions.items():
                    edge_impacts.append(
                        {
                            "from_process": s,
                            "to_process": d,
                            "commodity_id": c.commodity_id,
                            "impact_id": imp,
                            "factor": fac,
                        }
                    )
                edges.append(edge)
                # Carry per-year bounds (node-space → process-space): one edges_t
                # row per year, the connection's series applied to every fanned edge.
                for yr in sorted({*c.min_flow_by_year, *c.max_flow_by_year}):
                    et_row: dict[str, Any] = {
                        "from_process": s,
                        "to_process": d,
                        "commodity_id": c.commodity_id,
                        "year": yr,
                    }
                    if yr in c.max_flow_by_year:
                        et_row["max_flow"] = c.max_flow_by_year[yr]
                    if yr in c.min_flow_by_year:
                        et_row["min_flow"] = c.min_flow_by_year[yr]
                    edges_t.append(et_row)

    return {
        **workbook,
        PROCESSES: procs,
        EDGES: edges,
        EDGES_T: edges_t,
        EDGE_IMPACTS: edge_impacts,
    }


def assemble_problem(workbook: Workbook, scenario: ScenarioConfig) -> Problem:
    """Build a :class:`Problem` from a workbook and a validated scenario.

    Args:
        workbook: The in-memory workbook (``{sheet: rows[]}``).
        scenario: The validated run definition.

    Returns:
        The assembled problem instance.
    """
    # A node hierarchy (optional) expands to flat processes/edges first, so the
    # rest of assembly is unchanged; absent ⇒ the model stays flat.
    hierarchy = load_hierarchy(workbook)
    if hierarchy is not None:
        workbook = _expand_hierarchy(workbook, hierarchy)

    meta = _meta(workbook)
    econ = scenario.economics

    # ── Periods / horizon ────────────────────────────────────────────────────
    years = sorted(y for r in _rows(workbook, PERIODS) if (y := _int(r.get("year"))) is not None)
    if scenario.horizon.start is not None:
        years = [y for y in years if y >= scenario.horizon.start]
    if scenario.horizon.end is not None:
        years = [y for y in years if y <= scenario.horizon.end]
    duration = {
        y: (_num(r.get("duration_years"), 1.0) or 1.0)
        for r in _rows(workbook, PERIODS)
        if (y := _int(r.get("year"))) is not None
    }
    periods = [Period(year=y, duration_years=duration.get(y, 1.0)) for y in years]
    base_year = econ.base_year or _int(meta.get("base_year")) or (years[0] if years else 0)
    # Discount: an explicit scenario value wins; else the model's own
    # ``meta.discount_rate`` (the Project-tab setting); else the engine default.
    discount_rate = (
        econ.discount_rate
        if econ.discount_rate is not None
        else _numd(meta.get("discount_rate"), 0.08)
    )

    # ── Commodities (+ optional price trajectory) ────────────────────────────
    price_traj: dict[str, dict[int, float]] = {}
    sale_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, COMMODITY_PRICES):
        cid = _str(r.get("commodity_id"))
        if cid is None:
            continue
        y = _int(r.get("year"))
        if y is None:
            continue
        if (p := _num(r.get("price"))) is not None:
            price_traj.setdefault(cid, {})[y] = p
        if (sp := _num(r.get("sale_price"))) is not None:
            sale_traj.setdefault(cid, {})[y] = sp
    # PyPSA-style wide temporal tables override the legacy long-format.
    price_traj.update(_wide_temporal(workbook, COMMODITIES_T_PRICE))
    sale_traj.update(_wide_temporal(workbook, COMMODITIES_T_SALE_PRICE))
    # Per-year external-purchase volume cap (used by value-chain ``volume`` links).
    maxbuy_traj: dict[str, dict[int, float]] = _wide_temporal(workbook, COMMODITIES_T_MAX_PURCHASE)
    # Free-form physical stream properties (long format: commodity_id, property, value).
    props_by_commodity: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, COMMODITY_PROPERTIES):
        cid_p, prop = _str(r.get("commodity_id")), _str(r.get("property"))
        val = _num(r.get("value"))
        if cid_p and prop and val is not None:
            props_by_commodity.setdefault(cid_p, {})[prop] = val

    commodities: dict[str, Commodity] = {}
    for r in _rows(workbook, COMMODITIES):
        cid = _str(r.get("commodity_id"))
        if cid is None:
            continue
        kind_s = (_str(r.get("kind")) or "material").lower()
        kind = (
            CommodityKind(kind_s)
            if kind_s in {k.value for k in CommodityKind}
            else CommodityKind.MATERIAL
        )
        base_price = _num(r.get("price"), 0.0) or 0.0
        base_sale = _num(r.get("sale_price"), 0.0) or 0.0
        prices = (
            interpolate(price_traj[cid], years)
            if cid in price_traj
            else dict.fromkeys(years, base_price)
        )
        sales = (
            interpolate(sale_traj[cid], years)
            if cid in sale_traj
            else dict.fromkeys(years, base_sale)
        )
        purchasable = None if r.get("purchasable") is None else _bool(r.get("purchasable"), True)
        # Volume cap: a temporal table wins, else a scalar column applied flat.
        base_cap = _num(r.get("max_purchase"))
        if cid in maxbuy_traj:
            max_purchase = interpolate(maxbuy_traj[cid], years)
        elif base_cap is not None:
            max_purchase = dict.fromkeys(years, base_cap)
        else:
            max_purchase = {}
        commodities[cid] = Commodity(
            commodity_id=cid,
            kind=kind,
            unit=_str(r.get("unit")) or "unit",
            price_by_year=prices,
            sale_price_by_year=sales,
            sellable=_bool(r.get("sellable"), True),
            purchasable=purchasable,
            available_from=_int(r.get("available_from")),
            available_to=_int(r.get("available_to")),
            max_purchase_by_year=max_purchase,
            properties=props_by_commodity.get(cid, {}),
        )

    # ── Impacts (+ price trajectory) ─────────────────────────────────────────
    impact_price_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, IMPACT_PRICES):
        iid = _str(r.get("impact_id"))
        if (
            iid is not None
            and (p := _num(r.get("price"))) is not None
            and (y := _int(r.get("year"))) is not None
        ):
            impact_price_traj.setdefault(iid, {})[y] = p
    impact_price_traj.update(_wide_temporal(workbook, IMPACTS_T_PRICE))
    impacts: dict[str, Impact] = {}
    for r in _rows(workbook, IMPACTS):
        iid = _str(r.get("impact_id"))
        if iid is None:
            continue
        prices = interpolate(impact_price_traj[iid], years) if iid in impact_price_traj else {}
        impacts[iid] = Impact(
            impact_id=iid, unit=_str(r.get("unit")) or "unit", price_by_year=prices
        )
    # Impacts referenced only via prices still count.
    for iid, traj in impact_price_traj.items():
        if iid not in impacts:
            impacts[iid] = Impact(impact_id=iid, price_by_year=interpolate(traj, years))

    # ── Technologies (+ per-tech inputs/outputs/direct impacts) ──────────────
    inputs: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, PROCESS_INPUTS):
        k, c = _str(r.get("technology_id")), _str(r.get("commodity_id"))
        if k and c:
            inputs.setdefault(k, {})[c] = _num(r.get("intensity"), 0.0) or 0.0
    outputs: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, PROCESS_OUTPUTS):
        k, c = _str(r.get("technology_id")), _str(r.get("commodity_id"))
        if k and c:
            outputs.setdefault(k, {})[c] = _num(r.get("yield"), 0.0) or 0.0
    direct: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, TECH_IMPACTS):
        k, i = _str(r.get("technology_id")), _str(r.get("impact_id"))
        if k and i:
            direct.setdefault(k, {})[i] = _num(r.get("factor"), 0.0) or 0.0

    # Unified I/O table (preferred): one row per (technology, target, role).
    # role ∈ {input, output, impact}; augments/overrides the legacy sheets.
    # Input rows may carry a blend `group` + `share_min`/`share_max` (the mix the
    # optimiser may pick within); output rows may carry the same columns to form
    # an output SLATE (co-product shares the optimiser picks within bounds).
    # `coefficient` is then the member's baseline use / yield.
    share_groups: dict[str, dict[str, dict[str, tuple[float, float]]]] = {}
    output_share_groups: dict[str, dict[str, dict[str, tuple[float, float]]]] = {}

    def _share_bounds(r: dict[str, Any]) -> tuple[float, float]:
        lo_raw = _num(r.get("share_min"), 0.0)
        hi_raw = _num(r.get("share_max"), 1.0)
        lo = min(max(float(lo_raw if lo_raw is not None else 0.0), 0.0), 1.0)
        hi = min(max(float(hi_raw if hi_raw is not None else 1.0), 0.0), 1.0)
        return lo, max(lo, hi)

    # Per-recipe-row units: an io coefficient authored in a `unit` that differs from
    # its target stream's canonical unit is converted to that unit here, so the
    # matrix stays in one unit per commodity (linking technologies needs none).
    # Absent/blank unit ⇒ factor 1, so a library with no declared units is unchanged.
    converter = CoefficientConverter(
        commodity_units={cid: c.unit for cid, c in commodities.items()},
        commodity_props=props_by_commodity,
        impact_units={iid: imp.unit for iid, imp in impacts.items()},
        unit_overrides=_model_unit_overrides(workbook, scenario.unit_overrides),
    )
    # The unit each static io row declares per (tech, target, role); io_t rows carry
    # no unit of their own and inherit it, so the trajectory never kinks at a unit.
    io_unit_by_key: dict[tuple[str, str, str], str | None] = {}

    for r in _rows(workbook, IO):
        k, target = _str(r.get("technology_id")), _str(r.get("target"))
        role = (_str(r.get("role")) or "input").lower()
        if not k or not target:
            continue
        unit = _str(r.get("unit"))
        io_unit_by_key[(k, target, role)] = unit
        coef = converter.to_canonical(_num(r.get("coefficient"), 0.0) or 0.0, unit, target, role)
        if role == "output":
            outputs.setdefault(k, {})[target] = coef
            if (g := _str(r.get("group"))) is not None:
                output_share_groups.setdefault(k, {}).setdefault(g, {})[target] = _share_bounds(r)
        elif role == "impact":
            direct.setdefault(k, {})[target] = coef
        else:
            inputs.setdefault(k, {})[target] = coef
            if (g := _str(r.get("group"))) is not None:
                share_groups.setdefault(k, {}).setdefault(g, {})[target] = _share_bounds(r)

    # Optional year-varying I/O coefficients (long format: technology_id, target,
    # role, year, coefficient) — a recipe whose intensity / yield / emission
    # factor improves over the horizon. Sparse points interpolate onto the years.
    io_t_points: dict[tuple[str, str, str], dict[int, float]] = {}
    # Year-varying share bounds, captured per (tech, target, role) as separate
    # min/max year-series (a row may carry share_min/share_max with or without a
    # coefficient). Member-to-group is resolved from the static share groups.
    io_t_share_lo: dict[tuple[str, str, str], dict[int, float]] = {}
    io_t_share_hi: dict[tuple[str, str, str], dict[int, float]] = {}
    for r in _rows(workbook, IO_T):
        k, target = _str(r.get("technology_id")), _str(r.get("target"))
        role = (_str(r.get("role")) or "input").lower()
        yv, cv = _int(r.get("year")), _num(r.get("coefficient"))
        if k is None or target is None or yv is None:
            continue
        if cv is not None:
            cv = converter.to_canonical(cv, io_unit_by_key.get((k, target, role)), target, role)
            io_t_points.setdefault((k, target, role), {})[yv] = cv
        smin, smax = _num(r.get("share_min")), _num(r.get("share_max"))
        if smin is not None:
            io_t_share_lo.setdefault((k, target, role), {})[yv] = min(max(smin, 0.0), 1.0)
        if smax is not None:
            io_t_share_hi.setdefault((k, target, role), {})[yv] = min(max(smax, 0.0), 1.0)

    def _io_by_year(
        tech_id: str,
    ) -> tuple[
        dict[str, dict[int, float]], dict[str, dict[int, float]], dict[str, dict[int, float]]
    ]:
        inp: dict[str, dict[int, float]] = {}
        out: dict[str, dict[int, float]] = {}
        imp: dict[str, dict[int, float]] = {}
        for (kk, target, role), pts in io_t_points.items():
            if kk != tech_id:
                continue
            traj = interpolate(pts, years)
            if role == "output":
                out[target] = traj
            elif role == "impact":
                imp[target] = traj
            else:
                inp[target] = traj
        return inp, out, imp

    def _share_by_year(
        tech_id: str, groups: dict[str, dict[str, dict[str, tuple[float, float]]]], role: str
    ) -> dict[str, dict[str, dict[int, tuple[float, float]]]]:
        """Year-varying ``{group: {member: {year: (lo, hi)}}}`` for one technology.

        The member→group mapping comes from the static ``share_groups`` /
        ``output_share_groups``; min and max year-series are interpolated
        independently and zipped, falling back to the static bound for an unset end.
        """
        out: dict[str, dict[str, dict[int, tuple[float, float]]]] = {}
        for g, members in groups.get(tech_id, {}).items():
            for c, (base_lo, base_hi) in members.items():
                lo_pts = io_t_share_lo.get((tech_id, c, role))
                hi_pts = io_t_share_hi.get((tech_id, c, role))
                if not lo_pts and not hi_pts:
                    continue
                lo_y = interpolate(lo_pts, years) if lo_pts else dict.fromkeys(years, base_lo)
                hi_y = interpolate(hi_pts, years) if hi_pts else dict.fromkeys(years, base_hi)
                out.setdefault(g, {})[c] = {y: (lo_y[y], max(lo_y[y], hi_y[y])) for y in years}
        return out

    commodity_impacts: dict[tuple[str, str], float] = {}
    for r in _rows(workbook, COMMODITY_IMPACTS):
        c, i = _str(r.get("commodity_id")), _str(r.get("impact_id"))
        if c and i:
            commodity_impacts[(c, i)] = _num(r.get("factor"), 0.0) or 0.0

    # Optional year-varying carbon intensity (long format: commodity_id, impact_id,
    # year, factor) — e.g. a greening grid, or an upstream value-chain stage's
    # pathway. Sparse points are interpolated onto the horizon (flat-hold ends).
    ci_points: dict[tuple[str, str], dict[int, float]] = {}
    for r in _rows(workbook, COMMODITY_IMPACTS_T):
        c, i = _str(r.get("commodity_id")), _str(r.get("impact_id"))
        yr, fac = _int(r.get("year")), _num(r.get("factor"))
        if c and i and yr is not None and fac is not None:
            ci_points.setdefault((c, i), {})[yr] = fac
    commodity_impacts_by_year = {k: interpolate(v, years) for k, v in ci_points.items()}

    # LCIA characterisation: map a base elementary-flow impact to a category with a
    # factor (e.g. CO2/CH4/N2O → GWP). The engine derives the category emission as
    # Σ_flow factor · emit[flow]; pricing/caps/inventory then treat it like any impact.
    characterisation: dict[tuple[str, str], float] = {}
    for r in _rows(workbook, CHARACTERISATION):
        flow, cat = _str(r.get("flow_impact_id")), _str(r.get("category_id"))
        fac = _num(r.get("factor"))
        if flow and cat and fac is not None:
            characterisation[(flow, cat)] = fac

    # Per-year technology costs. Two input conventions, like commodity prices:
    # the long-format `technologies_prices` sheet (technology_id, year, capex,
    # opex, renewal — what the component library emits), overridden by the
    # PyPSA-wide `technologies_t__<attr>` tables when both are present.
    tech_capex_t: dict[str, dict[int, float]] = {}
    tech_opex_t: dict[str, dict[int, float]] = {}
    tech_renewal_t: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, TECHNOLOGIES_PRICES):
        tid = _str(r.get("technology_id"))
        yr = _int(r.get("year"))
        if tid is None or yr is None:
            continue
        if (cap_v := _num(r.get("capex"))) is not None:
            tech_capex_t.setdefault(tid, {})[yr] = cap_v
        if (opx_v := _num(r.get("opex"))) is not None:
            tech_opex_t.setdefault(tid, {})[yr] = opx_v
        if (ren_v := _num(r.get("renewal"))) is not None:
            tech_renewal_t.setdefault(tid, {})[yr] = ren_v
    tech_capex_t.update(_wide_temporal(workbook, TECHNOLOGIES_T_CAPEX))
    tech_renewal_t.update(_wide_temporal(workbook, TECHNOLOGIES_T_RENEWAL))
    tech_opex_t.update(_wide_temporal(workbook, TECHNOLOGIES_T_OPEX))
    tech_mincf_t = _wide_temporal(workbook, TECHNOLOGIES_T_MIN_CF)

    def _attr_by_year(
        name: str, base: float, wide: dict[str, dict[int, float]]
    ) -> dict[int, float]:
        return interpolate(wide[name], years) if name in wide else dict.fromkeys(years, base)

    technologies: dict[str, Technology] = {}
    for r in _rows(workbook, TECHNOLOGIES):
        k = _str(r.get("technology_id"))
        if k is None or not _enabled(r):
            continue
        in_t, out_t, imp_t = _io_by_year(k)
        technologies[k] = Technology(
            technology_id=k,
            lifespan=_int(r.get("lifespan"), 20) or 20,
            introduction_year=_int(r.get("introduction_year")),
            phase_out_year=_int(r.get("phase_out_year")),
            actions=_actions(r.get("actions")),
            capex_by_year=_attr_by_year(k, _num(r.get("capex"), 0.0) or 0.0, tech_capex_t),
            renewal_by_year=_attr_by_year(k, _num(r.get("renewal"), 0.0) or 0.0, tech_renewal_t),
            opex_by_year=_attr_by_year(k, _num(r.get("opex"), 0.0) or 0.0, tech_opex_t),
            input_intensity=inputs.get(k, {}),
            output_yield=outputs.get(k, {}),
            direct_impact=direct.get(k, {}),
            input_intensity_by_year=in_t,
            output_yield_by_year=out_t,
            direct_impact_by_year=imp_t,
            min_capacity_factor=min(max(_num(r.get("min_capacity_factor"), 0.0) or 0.0, 0.0), 1.0),
            min_capacity_factor_by_year=(
                interpolate(tech_mincf_t[k], years) if k in tech_mincf_t else {}
            ),
            share_groups=share_groups.get(k, {}),
            output_share_groups=output_share_groups.get(k, {}),
            share_groups_by_year=_share_by_year(k, share_groups, "input"),
            output_share_groups_by_year=_share_by_year(k, output_share_groups, "output"),
        )

    # ── Processes (4-stage inclusion via `enabled` × placement in node_layout) ─
    # Placement (a node in `node_layout`) means "in the initial topology":
    #   checked + placed   → initial, active (baseline runs from the start)
    #   checked + unplaced → available (in the optimisation, not initial)
    #   unchecked + placed → fixed (kept but locked to baseline; replaceable=False)
    #   unchecked + unplaced → excluded from the optimisation
    cap_t = _wide_temporal(workbook, PROCESSES_T_CAPACITY)
    fopex_t = _wide_temporal(workbook, PROCESSES_T_FIXED_OPEX)
    frate_t = _wide_temporal(workbook, PROCESSES_T_FAILURE_RATE)
    maxcf_t = _wide_temporal(workbook, PROCESSES_T_MAX_CF)

    # Per-facility direct emissions (static + year-varying) — added on top of the
    # baseline technology's own direct impact.
    proc_direct: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, PROCESS_IMPACTS):
        pid, imp = _str(r.get("process_id")), _str(r.get("impact_id"))
        if pid and imp:
            proc_direct.setdefault(pid, {})[imp] = _num(r.get("factor"), 0.0) or 0.0
    proc_direct_raw: dict[str, dict[str, dict[int, float]]] = {}
    for r in _rows(workbook, PROCESS_IMPACTS_T):
        pid, imp, yr = _str(r.get("process_id")), _str(r.get("impact_id")), _int(r.get("year"))
        if pid and imp and yr is not None:
            proc_direct_raw.setdefault(pid, {}).setdefault(imp, {})[yr] = (
                _num(r.get("factor"), 0.0) or 0.0
            )
    proc_direct_t: dict[str, dict[str, dict[int, float]]] = {
        pid: {imp: interpolate(traj, years) for imp, traj in by_imp.items()}
        for pid, by_imp in proc_direct_raw.items()
    }

    placed_nodes = {_str(r.get("id")) for r in _rows(workbook, NODE_LAYOUT)}
    processes = []
    for r in _rows(workbook, PROCESSES):
        pid = _str(r.get("process_id"))
        if not pid:
            continue
        enabled = _enabled(r)
        placed = f"process:{pid}" in placed_nodes
        if not enabled and not placed:
            continue  # stage 3: excluded
        fixed = not enabled  # stage 4: unchecked but placed → locked to baseline
        processes.append(
            Process(
                process_id=pid,
                company=_str(r.get("company")) or "all",
                baseline_technology=str(r["baseline_technology"]),
                capacity=_num(r.get("capacity"), 0.0) or 0.0,
                introduced_year=_int(r.get("introduced_year")),
                max_renewals=_int(r.get("max_renewals")),
                capex=_num(r.get("capex"), 0.0) or 0.0,
                fixed_opex=_num(r.get("fixed_opex"), 0.0) or 0.0,
                failure_rate=min(max(_num(r.get("failure_rate"), 0.0) or 0.0, 0.0), 1.0),
                max_capacity_factor=min(max(_numd(r.get("max_capacity_factor"), 1.0), 0.0), 1.0),
                replaceable=False if fixed else _bool(r.get("replaceable"), True),
                decommission_year=_int(r.get("decommission_year")),
                group=_str(r.get("group")) or "",
                scopes=frozenset(str(s) for s in (r.get("scopes") or ())),
                capacity_by_year=interpolate(cap_t[pid], years) if pid in cap_t else {},
                fixed_opex_by_year=interpolate(fopex_t[pid], years) if pid in fopex_t else {},
                failure_rate_by_year=interpolate(frate_t[pid], years) if pid in frate_t else {},
                max_capacity_factor_by_year=interpolate(maxcf_t[pid], years)
                if pid in maxcf_t
                else {},
                direct_impact=proc_direct.get(pid, {}),
                direct_impact_by_year=proc_direct_t.get(pid, {}),
            )
        )

    # ── Per-company objective (cost default; profit ⇒ maximise profit) ───────
    company_objective: dict[str, ObjectiveMode] = {}
    for r in _rows(workbook, COMPANY_CONFIG):
        c = _str(r.get("company"))
        obj = (_str(r.get("objective")) or "cost").lower()
        if c and obj in {m.value for m in ObjectiveMode}:
            company_objective[c] = ObjectiveMode(obj)

    # ── Edges (+ optional per-year bounds: edges_t, min and max) ─────────────
    edge_maxflow_t: dict[tuple[str, str, str], dict[int, float]] = {}
    edge_minflow_t: dict[tuple[str, str, str], dict[int, float]] = {}
    for r in _rows(workbook, EDGES_T):
        frm, to, cid = (
            _str(r.get("from_process")),
            _str(r.get("to_process")),
            _str(r.get("commodity_id")),
        )
        yr = _int(r.get("year"))
        if not (frm and to and cid) or yr is None:
            continue
        ek = (frm, to, cid)
        if (mf := _num(r.get("max_flow"))) is not None:
            edge_maxflow_t.setdefault(ek, {})[yr] = mf
        if (nf := _num(r.get("min_flow"))) is not None:
            edge_minflow_t.setdefault(ek, {})[yr] = nf
    # Per-impact freight emissions per edge (impact-agnostic), keyed by (from,to,comm).
    edge_emissions: dict[tuple[str, str, str], dict[str, float]] = {}
    for r in _rows(workbook, EDGE_IMPACTS):
        frm, to, cid = (
            _str(r.get("from_process")),
            _str(r.get("to_process")),
            _str(r.get("commodity_id")),
        )
        imp, fac = _str(r.get("impact_id")), _num(r.get("factor"))
        if frm and to and cid and imp and fac:
            edge_emissions.setdefault((frm, to, cid), {})[imp] = fac
    edges = []
    for r in _rows(workbook, EDGES):
        frm, to, cid = (
            _str(r.get("from_process")),
            _str(r.get("to_process")),
            _str(r.get("commodity_id")),
        )
        if not frm or not to or not cid:
            continue
        ek = (frm, to, cid)
        edges.append(
            Edge(
                from_process=frm,
                to_process=to,
                commodity_id=cid,
                max_flow=_num(r.get("max_flow")),
                max_flow_by_year=(
                    interpolate(edge_maxflow_t[ek], years) if ek in edge_maxflow_t else {}
                ),
                min_flow=_num(r.get("min_flow")),
                min_flow_by_year=(
                    interpolate(edge_minflow_t[ek], years) if ek in edge_minflow_t else {}
                ),
                available_from=_int(r.get("available_from")),
                available_to=_int(r.get("available_to")),
                lag_years=_int(r.get("lag_years")) or 0,
                cost=_num(r.get("freight_cost"), 0.0) or 0.0,
                emissions=edge_emissions.get(ek, {}),
                energy=_num(r.get("freight_energy"), 0.0) or 0.0,
            )
        )

    # ── Measures (+ blocks, + optional per-year block cost) ──────────────────
    # Long-format measure_blocks_t (measure_id, block, year, capex, opex —
    # absolute, already scaled to the instance, matching measure_blocks).
    block_traj: dict[tuple[str, int], dict[str, dict[int, float]]] = {}
    for r in _rows(workbook, MEASURE_BLOCKS_T):
        mid = _str(r.get("measure_id"))
        yr = _int(r.get("year"))
        if mid is None or yr is None:
            continue
        bi = _int(r.get("block"), 0) or 0
        if (cx := _num(r.get("capex"))) is not None:
            block_traj.setdefault((mid, bi), {}).setdefault("capex", {})[yr] = cx
        if (ox := _num(r.get("opex"))) is not None:
            block_traj.setdefault((mid, bi), {}).setdefault("opex", {})[yr] = ox
        if (rx := _num(r.get("reduction"))) is not None:
            block_traj.setdefault((mid, bi), {}).setdefault("reduction", {})[yr] = rx

    blocks_by_measure: dict[str, list[tuple[int, MeasureBlock]]] = {}
    for r in _rows(workbook, MEASURE_BLOCKS):
        mid = _str(r.get("measure_id"))
        if mid is None:
            continue
        bi = _int(r.get("block"), 0) or 0
        bt = block_traj.get((mid, bi), {})
        blocks_by_measure.setdefault(mid, []).append(
            (
                bi,
                MeasureBlock(
                    reduction=_num(r.get("reduction"), 0.0) or 0.0,
                    capex=_num(r.get("capex"), 0.0) or 0.0,
                    opex=_num(r.get("opex"), 0.0) or 0.0,
                    capex_by_year=interpolate(bt["capex"], years) if "capex" in bt else {},
                    opex_by_year=interpolate(bt["opex"], years) if "opex" in bt else {},
                    reduction_by_year=(
                        interpolate(bt["reduction"], years) if "reduction" in bt else {}
                    ),
                ),
            )
        )
    # Measures are a CATALOGUE of individual retrofits. A measure reaches
    # facilities three ways, all optional and combinable:
    #   1. direct `facility` (that one plant) / `technology` (every facility
    #      whose baseline runs it) columns on the measure row;
    #   2. membership in a named MACC (`maccs` rows {macc, measure_id} — the
    #      same measure may sit in several MACCs) deployed via `macc_links`
    #      rows {macc, facility|technology|commodity|storage} — a commodity
    #      (stream) reaches every facility whose baseline technology consumes
    #      it; a storage reaches the consumers of its stored stream;
    #   3. legacy `applies_to` / `set` + `measure_links` columns (older files).
    # Every (measure, facility) pair becomes its OWN independent Measure
    # instance — adoption is per facility, never grouped.
    links_by_set: dict[str, list[str]] = {}
    for r in _rows(workbook, MEASURE_LINKS):  # legacy sheet
        set_id, target = _str(r.get("set")), _str(r.get("applies_to"))
        if set_id and target:
            links_by_set.setdefault(set_id, []).append(target)

    maccs_by_measure: dict[str, list[str]] = {}
    for r in _rows(workbook, MACCS):
        macc, member = _str(r.get("macc")), _str(r.get("measure_id"))
        if macc and member:
            maccs_by_measure.setdefault(member, []).append(macc)

    macc_targets: dict[str, list[tuple[str, str]]] = {}  # macc → [(kind, name)]
    for r in _rows(workbook, MACC_LINKS):
        macc = _str(r.get("macc"))
        if not macc:
            continue
        for link_kind in ("facility", "technology", "commodity", "storage"):
            if target := _str(r.get(link_kind)):
                macc_targets.setdefault(macc, []).append((link_kind, target))

    proc_ids = {proc.process_id for proc in processes}
    by_baseline: dict[str, list[str]] = {}
    for proc in processes:
        by_baseline.setdefault(proc.baseline_technology, []).append(proc.process_id)

    def _resolve(target: str) -> list[str]:
        """A link target → the facility ids it covers (facility OR technology)."""
        if target in proc_ids:
            return [target]
        return by_baseline.get(target, [])

    storage_commodity: dict[str, str] = {}
    for r in _rows(workbook, STORAGE):
        sid, cid = _str(r.get("storage_id")), _str(r.get("commodity_id"))
        if sid and cid:
            storage_commodity[sid] = cid

    def _consumers(commodity: str) -> list[str]:
        """Facilities whose baseline technology consumes the stream."""
        return [
            p.process_id for p in processes if commodity in inputs.get(p.baseline_technology, {})
        ]

    def _resolve_link(kind: str, target: str) -> list[str]:
        """A typed macc_links target → the facility ids it deploys on."""
        if kind == "commodity":
            return _consumers(target)
        if kind == "storage":
            stored = storage_commodity.get(target)
            return _consumers(stored) if stored else []
        return _resolve(target)

    measures: list[Measure] = []
    for r in _rows(workbook, MEASURES):
        mid = _str(r.get("measure_id"))
        mtype_s = (_str(r.get("type")) or "energy_efficiency").lower()
        if mid is None or mtype_s not in {m.value for m in MeasureType}:
            continue
        ordered = [b for _, b in sorted(blocks_by_measure.get(mid, []), key=lambda t: t[0])]
        targets: list[str] = []
        if direct_fac := _str(r.get("facility")):
            targets.extend(_resolve(direct_fac))
        if direct_tech := _str(r.get("technology")):
            targets.extend(_resolve(direct_tech))
        for macc in maccs_by_measure.get(mid, []):
            for link_kind, link in macc_targets.get(macc, []):
                targets.extend(_resolve_link(link_kind, link))
        if direct_link := _str(r.get("applies_to")):  # legacy column
            targets.extend(_resolve(direct_link))
        if set_id := _str(r.get("set")):  # legacy named set
            for link in links_by_set.get(set_id, []):
                targets.extend(_resolve(link))
        unique = list(dict.fromkeys(targets))
        for pid in unique:
            measures.append(
                Measure(
                    # Keep the plain id for the simple 1:1 case (backwards
                    # compatible); suffix with the facility when expanded.
                    measure_id=mid if len(unique) == 1 else f"{mid} @ {pid}",
                    measure_type=MeasureType(mtype_s),
                    applies_to=pid,
                    target=_str(r.get("target")) or "",
                    lifetime=_int(r.get("lifetime"), 15) or 15,
                    blocks=ordered,
                )
            )

    # ── Transitions (replace/renew + compatibility) ──────────────────────────
    # Fleet-wide adoption caps (technology_id, max_count): at most N processes may
    # run the technology in any year.
    technology_caps: dict[str, int] = {}
    for r in _rows(workbook, TECHNOLOGY_CAPS):
        tid, cap = _str(r.get("technology_id")), _int(r.get("max_count"))
        if tid is not None and cap is not None:
            technology_caps[tid] = cap

    # Fleet (Layer 1b): a carrier asset class (cargo, capacity, lifecycle) and the
    # routes (transport processes) it serves. A class is one row with ``count`` +
    # lifecycle; the legacy per-year form (one row per (id, year, available)) is
    # still accepted. ``fleet_id`` is canonical; ``archetype`` is its old alias.
    _CLASS_COLS = ("company", "mode", "fuel", "cargo", "efficiency", "capacity", "count")
    fleets: dict[str, Fleet] = {}
    fleet_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, FLEET):
        fid = _str(r.get("fleet_id")) or _str(r.get("archetype"))
        if fid is None:
            continue
        y, avail = _int(r.get("year")), _num(r.get("available"))
        if y is not None and avail is not None:  # legacy per-year availability row
            fleet_traj.setdefault(fid, {})[y] = avail
        if r.get("count") is not None or any(r.get(c) is not None for c in _CLASS_COLS):
            fleets[fid] = Fleet(
                fleet_id=fid,
                company=_str(r.get("company")) or "all",
                mode=_str(r.get("mode")) or "",
                fuel=_str(r.get("fuel")) or "",
                cargo=_str(r.get("cargo")) or "",
                efficiency=_numd(r.get("efficiency"), 0.0),
                capacity=_numd(r.get("capacity"), 0.0),
                count=_numd(r.get("count"), 0.0),
                build_year=_int(r.get("build_year")),
                close_year=_int(r.get("close_year")),
                lifespan=_int(r.get("lifespan")),
                ship_size=_numd(r.get("ship_size"), 0.0),
                speed=_numd(r.get("speed"), 0.0),
                turnaround_days=_numd(r.get("turnaround_days"), 0.0),
                operating_days=_numd(r.get("operating_days"), 350.0),
            )
    fleet_available: dict[tuple[str, int], float] = {
        (fid, y): n for fid, traj in fleet_traj.items() for y, n in interpolate(traj, years).items()
    }
    # Lifecycle pool: a class fleet is available at its ``count`` while in service.
    for fid, fl in fleets.items():
        for y in years:
            fleet_available[(fid, y)] = fl.available_at(y)

    # Physical routes (Layer 1c): a transport process's endpoints/mode/length. Any
    # node may carry lon/lat; a route's distance is authored or derived from the
    # endpoints via the routing providers (sea = searoute, land = great-circle).
    coords: dict[str, Point] = {}
    for sheet, idcol in ((NODES, "node_id"), (MACHINES, "machine_id"), (PROCESSES, "process_id")):
        for r in _rows(workbook, sheet):
            nid = _str(r.get(idcol))
            lon, lat = _num(r.get("lon")), _num(r.get("lat"))
            if nid is not None and lon is not None and lat is not None:
                coords[nid] = (lon, lat)
    routes: dict[str, Route] = {}
    for r in _rows(workbook, ROUTES):
        rt_proc = _str(r.get("process"))
        if rt_proc is None:
            continue
        frm, to = _str(r.get("from_node")) or "", _str(r.get("to_node")) or ""
        mode = _str(r.get("mode")) or ""
        dist = _num(r.get("distance"))
        if dist is None and frm in coords and to in coords:
            dist = route_distance_km(coords[frm], coords[to], mode)
        routes[rt_proc] = Route(
            process=rt_proc, from_node=frm, to_node=to, mode=mode, distance=dist or 0.0
        )

    fleet_routes: dict[str, FleetRoute] = {}
    for r in _rows(workbook, FLEET_ROUTES):
        route_proc = _str(r.get("process"))
        fid = _str(r.get("fleet_id")) or _str(r.get("archetype"))
        if route_proc is None or fid is None:
            continue
        # Per-carrier throughput: explicit ``share`` wins; else the fleet's
        # distance-derived capacity on this route; else its flat capacity (in build).
        share = _num(r.get("share"))
        if share is None:
            rt_geo, rt_fleet = routes.get(route_proc), fleets.get(fid)
            if rt_geo is not None and rt_fleet is not None:
                share = rt_fleet.capacity_on(rt_geo.distance)
        fleet_routes[route_proc] = FleetRoute(
            process=route_proc,
            fleet_id=fid,
            share=share,
            min_units=_numd(r.get("min_units"), 0.0),
            max_units=_num(r.get("max_units")),
        )

    # Optional year-varying transition capex (long format: from_technology,
    # to_technology, year, capex_per_capacity).
    trans_capex_t: dict[tuple[str, str], dict[int, float]] = {}
    for r in _rows(workbook, TRANSITIONS_T):
        frm, to = _str(r.get("from_technology")), _str(r.get("to_technology"))
        yr, cx = _int(r.get("year")), _num(r.get("capex_per_capacity"))
        if frm and to and yr is not None and cx is not None:
            trans_capex_t.setdefault((frm, to), {})[yr] = cx
    transitions: list[Transition] = []
    for r in _rows(workbook, TRANSITIONS):
        frm, to = _str(r.get("from_technology")), _str(r.get("to_technology"))
        if not frm or not to:
            continue
        # Drop transitions whose endpoints were excluded (unchecked technology).
        if frm not in technologies or to not in technologies:
            continue
        action_s = (_str(r.get("action")) or "replace").lower()
        action = (
            TransitionAction(action_s)
            if action_s in {a.value for a in TransitionAction}
            else TransitionAction.REPLACE
        )
        cx_t = trans_capex_t.get((frm, to))
        transitions.append(
            Transition(
                from_technology=frm,
                to_technology=to,
                action=action,
                capex_per_capacity=_num(r.get("capex_per_capacity"), 0.0) or 0.0,
                capex_per_capacity_by_year=interpolate(cx_t, years) if cx_t else {},
                compatible=_bool(r.get("compatible"), True),
            )
        )

    # ── Storage (per-commodity inter-year stores) ────────────────────────────
    sto_capex_t = _wide_temporal(workbook, STORAGE_T_CAPEX)
    sto_fopex_t = _wide_temporal(workbook, STORAGE_T_FIXED_OPEX)
    sto_chg_t = _wide_temporal(workbook, STORAGE_T_CHARGE_EFFICIENCY)
    sto_dis_t = _wide_temporal(workbook, STORAGE_T_DISCHARGE_EFFICIENCY)
    sto_loss_t = _wide_temporal(workbook, STORAGE_T_STANDING_LOSS)

    def _sto_by_year(sid: str, wide: dict[str, dict[int, float]]) -> dict[int, float]:
        return interpolate(wide[sid], years) if sid in wide else {}

    storages: list[Storage] = []
    for r in _rows(workbook, STORAGE):
        sid, cid = _str(r.get("storage_id")), _str(r.get("commodity_id"))
        if not sid or not cid or not _enabled(r):
            continue
        storages.append(
            Storage(
                storage_id=sid,
                commodity_id=cid,
                company=_str(r.get("company")) or "all",
                max_capacity=_num(r.get("max_capacity"), 0.0) or 0.0,
                capex_per_capacity=_num(r.get("capex_per_capacity"), 0.0) or 0.0,
                fixed_opex_per_capacity=_num(r.get("fixed_opex_per_capacity"), 0.0) or 0.0,
                charge_efficiency=_num(r.get("charge_efficiency"), 1.0) or 1.0,
                discharge_efficiency=_num(r.get("discharge_efficiency"), 1.0) or 1.0,
                standing_loss=_num(r.get("standing_loss"), 0.0) or 0.0,
                initial_level=_num(r.get("initial_level"), 0.0) or 0.0,
                capex_per_capacity_by_year=_sto_by_year(sid, sto_capex_t),
                fixed_opex_per_capacity_by_year=_sto_by_year(sid, sto_fopex_t),
                charge_efficiency_by_year=_sto_by_year(sid, sto_chg_t),
                discharge_efficiency_by_year=_sto_by_year(sid, sto_dis_t),
                standing_loss_by_year=_sto_by_year(sid, sto_loss_t),
            )
        )

    # ── Markets (commodity supply / tradable ETS) ───────────────────────────
    mkt_price: dict[str, dict[int, float]] = {}
    mkt_sell: dict[str, dict[int, float]] = {}
    mkt_alloc: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, MARKET_PRICES):
        mid = _str(r.get("market_id"))
        if mid is None:
            continue
        y = _int(r.get("year"))
        if y is None:
            continue
        if (v := _num(r.get("price"))) is not None:
            mkt_price.setdefault(mid, {})[y] = v
        if (v := _num(r.get("sell_price"))) is not None:
            mkt_sell.setdefault(mid, {})[y] = v
        if (v := _num(r.get("allocation"))) is not None:
            mkt_alloc.setdefault(mid, {})[y] = v
    mkt_price.update(_wide_temporal(workbook, MARKETS_T_PRICE))
    mkt_sell.update(_wide_temporal(workbook, MARKETS_T_SELL_PRICE))
    mkt_alloc.update(_wide_temporal(workbook, MARKETS_T_ALLOCATION))
    mkt_maxbuy = _wide_temporal(workbook, MARKETS_T_MAX_BUY)
    mkt_maxsell = _wide_temporal(workbook, MARKETS_T_MAX_SELL)
    markets: list[Market] = []
    for r in _rows(workbook, MARKETS):
        mid, target = _str(r.get("market_id")), _str(r.get("target"))
        if not mid or not target or not _enabled(r):
            continue
        # Kind is auto-inferred from the target: if it names an impact it is a
        # tradable-allowance (ETS) market, otherwise a commodity market. An
        # explicit ``target_kind`` still wins for backward compatibility.
        kind_s = (_str(r.get("target_kind")) or "").lower()
        if kind_s in {k.value for k in MarketTarget}:
            mkind = MarketTarget(kind_s)
        elif target in impacts:
            mkind = MarketTarget.IMPACT
        else:
            mkind = MarketTarget.COMMODITY
        base_p = _num(r.get("price"))
        base_s = _num(r.get("sell_price"))
        base_a = _num(r.get("allocation"))
        prices = mkt_price.get(mid) or ({} if base_p is None else dict.fromkeys(years, base_p))
        sells = mkt_sell.get(mid) or ({} if base_s is None else dict.fromkeys(years, base_s))
        allocs = mkt_alloc.get(mid) or ({} if base_a is None else dict.fromkeys(years, base_a))
        markets.append(
            Market(
                market_id=mid,
                target=target,
                target_kind=mkind,
                company=_str(r.get("company")) or "all",
                price_by_year=interpolate(prices, years) if prices else {},
                sell_price_by_year=interpolate(sells, years) if sells else {},
                max_buy=_num(r.get("max_buy")),
                max_sell=_num(r.get("max_sell")),
                max_buy_by_year=interpolate(mkt_maxbuy[mid], years) if mid in mkt_maxbuy else {},
                max_sell_by_year=interpolate(mkt_maxsell[mid], years) if mid in mkt_maxsell else {},
                available_from=_int(r.get("available_from")),
                available_to=_int(r.get("available_to")),
                allocation_by_year=interpolate(allocs, years) if allocs else {},
                tag=_str(r.get("tag")),
            )
        )

    # ── Relational data: legacy long format OR named component + wide temporal ─
    investment_budget = _temporal_dict(
        workbook,
        INVESTMENT_BUDGET,
        INVESTMENT_BUDGET_T_LIMIT,
        "budget_id",
        ["company"],
        "limit",
        base_years=years,  # a year-less (static) budget cap holds every year
    )
    min_production = _temporal_dict(
        workbook,
        MIN_PRODUCTION,
        MIN_PRODUCTION_T_AMOUNT,
        "min_id",
        ["company", "commodity_id"],
        "amount",
        base_years=years,  # a year-less floor (per-machine min output) holds every year
    )
    max_production = _temporal_dict(
        workbook,
        MAX_PRODUCTION,
        MAX_PRODUCTION_T_AMOUNT,
        "max_id",
        ["company", "commodity_id"],
        "amount",
        base_years=years,  # a year-less cap (per-machine / per-stream) holds every year
    )
    min_consumption = _temporal_dict(
        workbook,
        MIN_CONSUMPTION,
        MIN_CONSUMPTION_T_AMOUNT,
        "min_cons_id",
        ["company", "commodity_id"],
        "amount",
        base_years=years,  # a year-less required offtake (per-machine intake floor) holds every year
    )
    max_consumption = _temporal_dict(
        workbook,
        MAX_CONSUMPTION,
        MAX_CONSUMPTION_T_AMOUNT,
        "max_cons_id",
        ["company", "commodity_id"],
        "amount",
        base_years=years,  # a year-less max purchase (per-machine intake cap) holds every year
    )
    demand = _temporal_dict(
        workbook,
        DEMAND,
        DEMAND_T_AMOUNT,
        "demand_id",
        ["company", "commodity_id"],
        "amount",
        base_years=years,  # a year-less (static) demand/target holds every year
    )
    impact_caps = _temporal_dict(
        workbook,
        IMPACT_CAPS,
        IMPACT_CAPS_T_LIMIT,
        "cap_id",
        ["company", "impact_id"],
        "limit",
        base_years=years,  # a year-less (static) emission cap holds every year
    )
    # Hard/soft per (company, impact): a cap row may set `soft` (default true) and
    # a `penalty` (per unit exceedance); a hard cap must hold exactly.
    impact_cap_soft: dict[tuple[str, str], bool] = {}
    impact_cap_penalty: dict[tuple[str, str], float] = {}
    impact_cap_intensity: dict[tuple[str, str], bool] = {}
    for r in _rows(workbook, IMPACT_CAPS):
        ckey = (_str(r.get("company")) or "all", _str(r.get("impact_id")) or "")
        if r.get("soft") is not None:
            impact_cap_soft[ckey] = _bool(r.get("soft"), True)
        if (pen := _num(r.get("penalty"))) is not None:
            impact_cap_penalty[ckey] = pen
        if r.get("intensity") is not None:
            impact_cap_intensity[ckey] = _bool(r.get("intensity"), False)

    # Optimisation scope: "system" pools every emission target for an (impact,
    # year) into a single economy-wide cap (companies trade off → minimise the
    # whole economy's cost); "company"/"facility" keep targets as authored (each
    # entity independent → minimise its own cost).
    if scenario.optimisation_scope == "system":
        intensity_imps = {imp for (_s, imp), on in impact_cap_intensity.items() if on}
        pooled: dict[tuple[str, str, int], float] = {}
        for (_scope, imp, yr), limit in impact_caps.items():
            key = ("all", imp, yr)
            # Absolute caps add up; an intensity target is shared (take the max).
            pooled[key] = (
                max(pooled.get(key, 0.0), limit)
                if imp in intensity_imps
                else pooled.get(key, 0.0) + limit
            )
        impact_caps = pooled
        # Pool soft/penalty PER IMPACT, not globally: the pooled cap on impact X is
        # soft iff some source cap on X was soft (none specified → default soft), with
        # penalty = the max over X's source caps. (Previously a single soft cap on ANY
        # impact softened EVERY impact's pooled cap, silently defeating a hard cap set
        # on a different impact — e.g. the frontier backend's ε-constraint.)
        pooled_imps = {imp for (_s, imp, _y) in pooled}
        new_soft: dict[tuple[str, str], bool] = {}
        new_penalty: dict[tuple[str, str], float] = {}
        for imp in pooled_imps:
            softs = [v for (_s, i), v in impact_cap_soft.items() if i == imp]
            pens = [v for (_s, i), v in impact_cap_penalty.items() if i == imp]
            new_soft[("all", imp)] = (not softs) or any(softs)
            new_penalty[("all", imp)] = max(pens, default=scenario.slack_penalty)
        impact_cap_soft = new_soft
        impact_cap_penalty = new_penalty
        impact_cap_intensity = {("all", imp): imp in intensity_imps for (_s, imp, _y) in pooled}

    toggles = CostToggles(**scenario.cost_components.model_dump())
    vintage_timing = _bool(_meta(workbook).get("vintage_timing"))

    return Problem(
        periods=periods,
        processes=processes,
        technologies=technologies,
        commodities=commodities,
        impacts=impacts,
        measures=measures,
        edges=edges,
        transitions=transitions,
        storages=storages,
        markets=markets,
        commodity_impacts=commodity_impacts,
        commodity_impacts_by_year=commodity_impacts_by_year,
        characterisation=characterisation,
        demand=demand,
        impact_caps=impact_caps,
        impact_cap_soft=impact_cap_soft,
        impact_cap_penalty=impact_cap_penalty,
        impact_cap_intensity=impact_cap_intensity,
        investment_budget=investment_budget,
        min_production=min_production,
        max_production=max_production,
        min_consumption=min_consumption,
        max_consumption=max_consumption,
        technology_caps=technology_caps,
        fleets=fleets,
        fleet_available=fleet_available,
        fleet_routes=fleet_routes,
        routes=routes,
        company_objective=company_objective,
        default_objective=ObjectiveMode(scenario.objective),
        objective_impact=scenario.objective_impact,
        impact_weight=scenario.impact_weight,
        cost_weight=scenario.cost_weight,
        vintage_timing=vintage_timing,
        discount_rate=discount_rate,
        base_year=base_year,
        capex_convention=econ.capex_convention,
        slack_penalty=scenario.slack_penalty,
        toggles=toggles,
    )
