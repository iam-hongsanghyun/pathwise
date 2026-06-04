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
from pathwise.core.problem import CostToggles, Problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.trajectory import interpolate
from pathwise.data.workbook import Workbook

Rows = list[dict[str, Any]]


def _rows(wb: Workbook, sheet: str) -> Rows:
    return wb.get(sheet, [])


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    return float(value)


def _int(value: Any, default: int | None = None) -> int | None:
    n = _num(value, None)
    return int(n) if n is not None else default


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


def _meta(wb: Workbook) -> dict[str, Any]:
    return {str(r.get("key")): r.get("value") for r in _rows(wb, "meta")}


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


def assemble_problem(workbook: Workbook, scenario: ScenarioConfig) -> Problem:
    """Build a :class:`Problem` from a workbook and a validated scenario.

    Args:
        workbook: The in-memory workbook (``{sheet: rows[]}``).
        scenario: The validated run definition.

    Returns:
        The assembled problem instance.
    """
    meta = _meta(workbook)
    econ = scenario.economics

    # ── Periods / horizon ────────────────────────────────────────────────────
    years = sorted(int(r["year"]) for r in _rows(workbook, "periods"))
    if scenario.horizon.start is not None:
        years = [y for y in years if y >= scenario.horizon.start]
    if scenario.horizon.end is not None:
        years = [y for y in years if y <= scenario.horizon.end]
    duration = {
        int(r["year"]): _num(r.get("duration_years"), 1.0) or 1.0
        for r in _rows(workbook, "periods")
    }
    periods = [Period(year=y, duration_years=duration.get(y, 1.0)) for y in years]
    base_year = econ.base_year or _int(meta.get("base_year")) or (years[0] if years else 0)

    # ── Commodities (+ optional price trajectory) ────────────────────────────
    price_traj: dict[str, dict[int, float]] = {}
    sale_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, "commodity_prices"):
        cid = _str(r.get("commodity_id"))
        if cid is None:
            continue
        y = int(r["year"])
        if (p := _num(r.get("price"))) is not None:
            price_traj.setdefault(cid, {})[y] = p
        if (sp := _num(r.get("sale_price"))) is not None:
            sale_traj.setdefault(cid, {})[y] = sp

    commodities: dict[str, Commodity] = {}
    for r in _rows(workbook, "commodities"):
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
        commodities[cid] = Commodity(
            commodity_id=cid,
            kind=kind,
            unit=_str(r.get("unit")) or "unit",
            price_by_year=prices,
            sale_price_by_year=sales,
            sellable=_bool(r.get("sellable"), True),
            purchasable=purchasable,
        )

    # ── Impacts (+ price trajectory) ─────────────────────────────────────────
    impact_price_traj: dict[str, dict[int, float]] = {}
    for r in _rows(workbook, "impact_prices"):
        iid = _str(r.get("impact_id"))
        if iid is not None and (p := _num(r.get("price"))) is not None:
            impact_price_traj.setdefault(iid, {})[int(r["year"])] = p
    impacts: dict[str, Impact] = {}
    for r in _rows(workbook, "impacts"):
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
    for r in _rows(workbook, "process_inputs"):
        k, c = _str(r.get("technology_id")), _str(r.get("commodity_id"))
        if k and c:
            inputs.setdefault(k, {})[c] = _num(r.get("intensity"), 0.0) or 0.0
    outputs: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, "process_outputs"):
        k, c = _str(r.get("technology_id")), _str(r.get("commodity_id"))
        if k and c:
            outputs.setdefault(k, {})[c] = _num(r.get("yield"), 0.0) or 0.0
    direct: dict[str, dict[str, float]] = {}
    for r in _rows(workbook, "tech_impacts"):
        k, i = _str(r.get("technology_id")), _str(r.get("impact_id"))
        if k and i:
            direct.setdefault(k, {})[i] = _num(r.get("factor"), 0.0) or 0.0

    commodity_impacts: dict[tuple[str, str], float] = {}
    for r in _rows(workbook, "commodity_impacts"):
        c, i = _str(r.get("commodity_id")), _str(r.get("impact_id"))
        if c and i:
            commodity_impacts[(c, i)] = _num(r.get("factor"), 0.0) or 0.0

    technologies: dict[str, Technology] = {}
    for r in _rows(workbook, "technologies"):
        k = _str(r.get("technology_id"))
        if k is None:
            continue
        capex = _num(r.get("capex"), 0.0) or 0.0
        renewal = _num(r.get("renewal"), 0.0) or 0.0
        opex = _num(r.get("opex"), 0.0) or 0.0
        technologies[k] = Technology(
            technology_id=k,
            lifespan=_int(r.get("lifespan"), 20) or 20,
            introduction_year=_int(r.get("introduction_year")),
            actions=_actions(r.get("actions")),
            capex_by_year=dict.fromkeys(years, capex),
            renewal_by_year=dict.fromkeys(years, renewal),
            opex_by_year=dict.fromkeys(years, opex),
            input_intensity=inputs.get(k, {}),
            output_yield=outputs.get(k, {}),
            direct_impact=direct.get(k, {}),
        )

    # ── Processes ────────────────────────────────────────────────────────────
    processes = [
        Process(
            process_id=str(r["process_id"]),
            company=_str(r.get("company")) or "all",
            baseline_technology=str(r["baseline_technology"]),
            capacity=_num(r.get("capacity"), 0.0) or 0.0,
            introduced_year=_int(r.get("introduced_year")),
            capex=_num(r.get("capex"), 0.0) or 0.0,
            fixed_opex=_num(r.get("fixed_opex"), 0.0) or 0.0,
            failure_rate=min(max(_num(r.get("failure_rate"), 0.0) or 0.0, 0.0), 1.0),
            replaceable=_bool(r.get("replaceable"), True),
        )
        for r in _rows(workbook, "processes")
        if _str(r.get("process_id"))
    ]

    # ── Per-company objective (cost default; profit ⇒ maximise profit) ───────
    company_objective: dict[str, ObjectiveMode] = {}
    for r in _rows(workbook, "company_config"):
        c = _str(r.get("company"))
        obj = (_str(r.get("objective")) or "cost").lower()
        if c and obj in {m.value for m in ObjectiveMode}:
            company_objective[c] = ObjectiveMode(obj)

    # ── Edges ────────────────────────────────────────────────────────────────
    edges = [
        Edge(
            from_process=str(r["from_process"]),
            to_process=str(r["to_process"]),
            commodity_id=str(r["commodity_id"]),
            max_flow=_num(r.get("max_flow")),
        )
        for r in _rows(workbook, "edges")
        if _str(r.get("from_process")) and _str(r.get("to_process")) and _str(r.get("commodity_id"))
    ]

    # ── Measures (+ blocks) ──────────────────────────────────────────────────
    blocks_by_measure: dict[str, list[tuple[int, MeasureBlock]]] = {}
    for r in _rows(workbook, "measure_blocks"):
        mid = _str(r.get("measure_id"))
        if mid is None:
            continue
        blocks_by_measure.setdefault(mid, []).append(
            (
                _int(r.get("block"), 0) or 0,
                MeasureBlock(
                    reduction=_num(r.get("reduction"), 0.0) or 0.0,
                    capex=_num(r.get("capex"), 0.0) or 0.0,
                ),
            )
        )
    measures: list[Measure] = []
    for r in _rows(workbook, "measures"):
        mid = _str(r.get("measure_id"))
        mtype_s = (_str(r.get("type")) or "energy_efficiency").lower()
        if mid is None or mtype_s not in {m.value for m in MeasureType}:
            continue
        ordered = [b for _, b in sorted(blocks_by_measure.get(mid, []), key=lambda t: t[0])]
        measures.append(
            Measure(
                measure_id=mid,
                measure_type=MeasureType(mtype_s),
                applies_to=_str(r.get("applies_to")) or "",
                target=_str(r.get("target")) or "",
                lifetime=_int(r.get("lifetime"), 15) or 15,
                blocks=ordered,
            )
        )

    # ── Transitions (replace/renew + compatibility) ──────────────────────────
    transitions: list[Transition] = []
    for r in _rows(workbook, "transitions"):
        frm, to = _str(r.get("from_technology")), _str(r.get("to_technology"))
        if not frm or not to:
            continue
        action_s = (_str(r.get("action")) or "replace").lower()
        action = (
            TransitionAction(action_s)
            if action_s in {a.value for a in TransitionAction}
            else TransitionAction.REPLACE
        )
        transitions.append(
            Transition(
                from_technology=frm,
                to_technology=to,
                action=action,
                capex_per_capacity=_num(r.get("capex_per_capacity"), 0.0) or 0.0,
                compatible=_bool(r.get("compatible"), True),
            )
        )

    # ── Storage (per-commodity inter-year stores) ────────────────────────────
    storages: list[Storage] = []
    for r in _rows(workbook, "storage"):
        sid, cid = _str(r.get("storage_id")), _str(r.get("commodity_id"))
        if not sid or not cid:
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
            )
        )

    # ── Decision controls: investment budget + minimum production ────────────
    investment_budget: dict[tuple[str, int], float] = {}
    for r in _rows(workbook, "investment_budget"):
        lim = _num(r.get("limit"))
        if lim is not None:
            investment_budget[(_str(r.get("company")) or "all", int(r["year"]))] = lim
    min_production: dict[tuple[str, str, int], float] = {}
    for r in _rows(workbook, "min_production"):
        q = _str(r.get("commodity_id"))
        if q is None:
            continue
        min_production[(_str(r.get("company")) or "all", q, int(r["year"]))] = (
            _num(r.get("amount"), 0.0) or 0.0
        )

    # ── Demand & impact caps ─────────────────────────────────────────────────
    demand: dict[tuple[str, str, int], float] = {}
    for r in _rows(workbook, "demand"):
        c, q = _str(r.get("company")) or "all", _str(r.get("commodity_id"))
        if q is None:
            continue
        demand[(c, q, int(r["year"]))] = _num(r.get("amount"), 0.0) or 0.0

    impact_caps: dict[tuple[str, str, int], float] = {}
    for r in _rows(workbook, "impact_caps"):
        c, i = _str(r.get("company")) or "all", _str(r.get("impact_id"))
        if i is None:
            continue
        impact_caps[(c, i, int(r["year"]))] = _num(r.get("limit"), 0.0) or 0.0

    toggles = CostToggles(**scenario.cost_components.model_dump())

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
        commodity_impacts=commodity_impacts,
        demand=demand,
        impact_caps=impact_caps,
        investment_budget=investment_budget,
        min_production=min_production,
        company_objective=company_objective,
        discount_rate=econ.discount_rate,
        base_year=base_year,
        capex_convention=econ.capex_convention,
        slack_penalty=scenario.slack_penalty,
        toggles=toggles,
    )
