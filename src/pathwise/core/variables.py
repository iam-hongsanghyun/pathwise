"""Build context: declare the ``linopy`` variables and precompute references.

Holds the model, the problem, coordinate lists, the decision variables, and the
constant reference quantities used to keep the MACC terms linear (savings are
proportional to a *fixed* baseline consumption, not the variable throughput).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from linopy import Model

from pathwise.core.entities import MarketTarget, MeasureType, TransitionAction
from pathwise.core.problem import Problem


@dataclass(slots=True)
class MeasureSlot:
    """A flattened ``(measure, block)`` decision slot.

    Attributes:
        key: Stable string key ``"{measure_id}#{block}"``.
        measure_id: Owning measure.
        process: Process the measure is installed on.
        measure_type: Lever (energy efficiency / emission / environmental).
        target: Target commodity id (efficiency) or impact id (reduction/env).
        reduction: Fractional reduction at full adoption of this block [—].
        capex: Block capital cost [currency].
        lifetime: Economic lifetime [yr].
    """

    key: str
    measure_id: str
    process: str
    measure_type: MeasureType
    target: str
    reduction: float
    capex: float
    lifetime: int


@dataclass(slots=True)
class BuildContext:
    """Everything :mod:`pathwise.core.build` and :mod:`extract` need.

    Coordinate lists mirror the problem sets; the variables are ``linopy``
    variables over named dims.
    """

    model: Model
    problem: Problem

    procs: list[str]
    techs: list[str]
    comms: list[str]
    impacts: list[str]
    years: list[int]

    feasible: dict[str, list[str]]  # process -> feasible technologies
    slots: list[MeasureSlot]
    ref_consumption: dict[tuple[str, str], float]  # (process, commodity) -> baseline use
    ref_impact: dict[tuple[str, str], float]  # (process, impact) -> baseline emission
    grouped_comms: list[str] = field(default_factory=list)  # commodities in any blend group

    # Decision variables (set in build_context).
    on: Any = None  # binary: facility operates [process, period]
    u: Any = None  # binary: tech active [process, tech, period]
    x: Any = None  # throughput on tech [process, tech, period]
    fin: Any = None  # blend-group input flow [process, tech, commodity, period]
    buy: Any = None  # external purchase [process, commodity, period]
    sell: Any = None  # external sale/disposal [process, commodity, period]
    deliver: Any = None  # product delivered to demand [process, commodity, period]
    flow: Any = None  # inter-process flow [edge, period]
    z: Any = None  # measure adoption [slot, period]
    emit: Any = None  # impact emitted [process, impact, period]
    w: Any = None  # transition (replace) event [process, tech, period]
    cap_built: Any = None  # storage capacity built [store]
    charge: Any = None  # commodity charged into a store [store, period]
    discharge: Any = None  # commodity discharged from a store [store, period]
    level: Any = None  # storage inventory level [store, period]
    extbuy: Any = None  # external purchase for a stored commodity [store, period]
    mbuy: Any = None  # commodity-market purchase [cmarket, period]
    msell: Any = None  # commodity-market sale [cmarket, period]
    abuy: Any = None  # ETS allowance bought [imarket, period]
    asell: Any = None  # ETS allowance sold [imarket, period]
    cmarkets: list[Any] = field(default_factory=list)  # commodity Market entities
    imarkets: list[Any] = field(default_factory=list)  # impact (ETS) Market entities
    slk_dem: Any = None  # demand slack [demand_key]
    slk_cap: Any = None  # impact-cap slack [cap_key]

    demand_keys: list[tuple[str, str, int]] = field(default_factory=list)
    cap_keys: list[tuple[str, str, int]] = field(default_factory=list)


def _feasible_techs(problem: Problem) -> dict[str, list[str]]:
    """Technologies each process may run: baseline + one-step transition targets.

    A non-replaceable facility is locked to its baseline technology.
    """
    by_from: dict[str, set[str]] = {}
    for tr in problem.transitions:
        if tr.action in (TransitionAction.REPLACE, TransitionAction.RENEW):
            by_from.setdefault(tr.from_technology, set()).add(tr.to_technology)
    out: dict[str, list[str]] = {}
    for p in problem.processes:
        techs = {p.baseline_technology}
        if p.replaceable:
            techs |= by_from.get(p.baseline_technology, set())
        out[p.process_id] = sorted(t for t in techs if t in problem.technologies)
    return out


def _measure_slots(problem: Problem) -> list[MeasureSlot]:
    """Flatten measures × blocks into addressable slots."""
    slots: list[MeasureSlot] = []
    for m in problem.measures:
        for b, blk in enumerate(m.blocks):
            slots.append(
                MeasureSlot(
                    key=f"{m.measure_id}#{b}",
                    measure_id=m.measure_id,
                    process=m.applies_to,
                    measure_type=m.measure_type,
                    target=m.target,
                    reduction=blk.reduction,
                    capex=blk.capex,
                    lifetime=m.lifetime,
                )
            )
    return slots


def _references(
    problem: Problem,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Precompute baseline consumption and emission references per process.

    Used to linearise MACC savings: a measure's saving is ``reduction × ref``
    (a constant), not ``reduction × throughput`` (which would be bilinear).
    Reference uses the process's full capacity on its baseline technology.

    ``ref_consumption[(p, r)] = capacity_p · input_intensity[baseline, r]``.
    ``ref_impact[(p, i)] = capacity_p · direct_impact[baseline, i]
        + Σ_r commodity_impacts[(r, i)] · ref_consumption[(p, r)]``.
    """
    ref_cons: dict[tuple[str, str], float] = {}
    ref_imp: dict[tuple[str, str], float] = {}
    for p in problem.processes:
        tech = problem.technologies.get(p.baseline_technology)
        if tech is None:
            continue
        cap = p.capacity
        for r, intensity in tech.input_intensity.items():
            ref_cons[(p.process_id, r)] = cap * intensity
        for i in problem.impacts:
            total = tech.direct_impact.get(i, 0.0) * cap
            for r in tech.input_intensity:
                total += problem.commodity_impacts.get((r, i), 0.0) * ref_cons.get(
                    (p.process_id, r), 0.0
                )
            ref_imp[(p.process_id, i)] = total
    return ref_cons, ref_imp


def build_context(model: Model, problem: Problem) -> BuildContext:
    """Create all decision variables and return the populated context."""
    procs = [p.process_id for p in problem.processes]
    techs = list(problem.technologies)
    comms = list(problem.commodities)
    impacts = list(problem.impacts)
    years = problem.years

    feasible = _feasible_techs(problem)
    slots = _measure_slots(problem)
    ref_cons, ref_imp = _references(problem)
    grouped_comms = sorted({c for k in problem.technologies.values() for c in k.grouped_inputs()})

    p_idx = pd.Index(procs, name="process")
    k_idx = pd.Index(techs, name="tech")
    r_idx = pd.Index(comms, name="commodity")
    i_idx = pd.Index(impacts, name="impact")
    t_idx = pd.Index(years, name="period")

    ctx = BuildContext(
        model=model,
        problem=problem,
        procs=procs,
        techs=techs,
        comms=comms,
        impacts=impacts,
        years=years,
        feasible=feasible,
        slots=slots,
        ref_consumption=ref_cons,
        ref_impact=ref_imp,
        grouped_comms=grouped_comms,
    )

    ctx.on = model.add_variables(binary=True, coords=[p_idx, t_idx], name="on")
    ctx.u = model.add_variables(binary=True, coords=[p_idx, k_idx, t_idx], name="u")
    ctx.x = model.add_variables(lower=0.0, coords=[p_idx, k_idx, t_idx], name="x")
    if grouped_comms:
        gc_idx = pd.Index(grouped_comms, name="commodity")
        ctx.fin = model.add_variables(lower=0.0, coords=[p_idx, k_idx, gc_idx, t_idx], name="fin")
    # Transition (replace) event: continuous in [0, 1] — w >= u_t - u_prev pins it
    # to the switch-in, and cost minimisation keeps it at the lower bound.
    ctx.w = model.add_variables(lower=0.0, upper=1.0, coords=[p_idx, k_idx, t_idx], name="w")
    ctx.buy = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="buy")
    ctx.sell = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="sell")
    ctx.deliver = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="deliver")
    ctx.emit = model.add_variables(coords=[p_idx, i_idx, t_idx], name="emit")

    if slots:
        s_idx = pd.Index([s.key for s in slots], name="slot")
        ctx.z = model.add_variables(lower=0.0, upper=1.0, coords=[s_idx, t_idx], name="z")
    if problem.edges:
        e_idx = pd.Index(list(range(len(problem.edges))), name="edge")
        ctx.flow = model.add_variables(lower=0.0, coords=[e_idx, t_idx], name="flow")
    if problem.storages:
        st_idx = pd.Index([s.storage_id for s in problem.storages], name="store")
        ctx.cap_built = model.add_variables(lower=0.0, coords=[st_idx], name="cap_built")
        ctx.charge = model.add_variables(lower=0.0, coords=[st_idx, t_idx], name="charge")
        ctx.discharge = model.add_variables(lower=0.0, coords=[st_idx, t_idx], name="discharge")
        ctx.level = model.add_variables(lower=0.0, coords=[st_idx, t_idx], name="level")
        ctx.extbuy = model.add_variables(lower=0.0, coords=[st_idx, t_idx], name="extbuy")

    ctx.cmarkets = [m for m in problem.markets if m.target_kind == MarketTarget.COMMODITY]
    ctx.imarkets = [m for m in problem.markets if m.target_kind == MarketTarget.IMPACT]
    if ctx.cmarkets:
        cm_idx = pd.Index([m.market_id for m in ctx.cmarkets], name="cmarket")
        ctx.mbuy = model.add_variables(lower=0.0, coords=[cm_idx, t_idx], name="mbuy")
        ctx.msell = model.add_variables(lower=0.0, coords=[cm_idx, t_idx], name="msell")
    if ctx.imarkets:
        im_idx = pd.Index([m.market_id for m in ctx.imarkets], name="imarket")
        ctx.abuy = model.add_variables(lower=0.0, coords=[im_idx, t_idx], name="abuy")
        ctx.asell = model.add_variables(lower=0.0, coords=[im_idx, t_idx], name="asell")

    ctx.demand_keys = sorted(problem.demand)
    if ctx.demand_keys:
        d_idx = pd.Index([f"{c}|{q}|{y}" for (c, q, y) in ctx.demand_keys], name="dkey")
        ctx.slk_dem = model.add_variables(lower=0.0, coords=[d_idx], name="slk_dem")
    ctx.cap_keys = sorted(problem.impact_caps)
    if ctx.cap_keys:
        ck_idx = pd.Index([f"{c}|{i}|{y}" for (c, i, y) in ctx.cap_keys], name="ckey")
        ctx.slk_cap = model.add_variables(lower=0.0, coords=[ck_idx], name="slk_cap")

    return ctx
