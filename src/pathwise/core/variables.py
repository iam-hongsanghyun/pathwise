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

from pathwise.core.entities import LeverType, MarketTarget, TransitionAction
from pathwise.core.problem import Problem, green_key, leg_key


@dataclass(slots=True)
class LeverSlot:
    """A flattened ``(lever, block)`` decision slot.

    Attributes:
        key: Stable string key ``"{lever_id}#{block}"``.
        lever_id: Owning lever.
        process: Process the lever is installed on.
        lever_type: Lever kind (energy efficiency / emission / environmental).
        target: Target flow id (efficiency) or impact id (reduction/env).
        reduction: Fractional reduction at full adoption of this block [—].
        capex: Block capital cost — a one-off lump at adoption [currency].
        opex: Block fixed operating cost per year at full adoption
            [currency / yr], charged each period in proportion to adoption.
        lifetime: Economic lifetime [yr].
    """

    key: str
    lever_id: str
    process: str
    lever_type: LeverType
    target: str
    reduction: float
    capex: float
    opex: float
    lifetime: int
    #: A GROUP scope (a fleet, company, "all"…) when the lever covers a group of assets
    #: rather than one process. Empty ⇒ a plain process slot. A fleet is just a group, so
    #: a fleet MACC is a scoped slot — the deploy/capex/ordering machinery is unchanged.
    scope: str = ""
    #: Per-year overrides of the scalar block cost / reduction (empty → scalar).
    capex_by_year: dict[int, float] = field(default_factory=dict)
    opex_by_year: dict[int, float] = field(default_factory=dict)
    reduction_by_year: dict[int, float] = field(default_factory=dict)

    def capex_at(self, year: int) -> float:
        return self.capex_by_year.get(year, self.capex)

    def opex_at(self, year: int) -> float:
        return self.opex_by_year.get(year, self.opex)

    def reduction_at(self, year: int) -> float:
        return self.reduction_by_year.get(year, self.reduction)


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
    slots: list[LeverSlot]
    ref_consumption: dict[tuple[str, str], float]  # (process, flow) -> baseline use
    ref_impact: dict[tuple[str, str], float]  # (process, impact) -> baseline emission
    fleet_ref_fuel: dict[str, float] = field(default_factory=dict)  # fleet -> full-deploy fuel
    grouped_comms: list[str] = field(default_factory=list)  # flows in any blend group
    grouped_out_comms: list[str] = field(default_factory=list)  # flows in any output slate

    # Decision variables (set in build_context).
    on: Any = None  # binary: facility operates [process, period]
    u: Any = None  # binary: tech active [process, tech, period]
    x: Any = None  # throughput on tech [process, tech, period]
    fin: Any = None  # blend-group input flow [process, tech, flow, period]
    fout: Any = None  # slate-group output flow [process, tech, flow, period]
    buy: Any = None  # external purchase [process, flow, period]
    sell: Any = None  # external sale/disposal [process, flow, period]
    deliver: Any = None  # product delivered to demand [process, flow, period]
    flow: Any = None  # inter-process flow [edge, period]
    z: Any = None  # lever adoption [slot, period] (process levers — continuous 0..1)
    dfl: Any = None  # binary deploy of a scoped (fleet/group) lever slot [slot, period]
    fsaved: Any = None  # abated fuel from a scoped fleet lever [slot, period] (≤ actual fuel)
    emit: Any = None  # impact emitted [process, impact, period]
    units: Any = None  # integer ships assigned to a fleet route [process, period]
    cunits: Any = None  # integer carriers of a fleet on a physicalised connection [leg, period]
    legflow: Any = None  # cargo carried by a fleet on a physicalised connection [leg, period]
    built: Any = None  # integer carriers BUILT by the optimiser (fleet acquisition) [fleet, period]
    w: Any = None  # transition (replace) event [process, tech, period]
    ren: Any = None  # renewal (rebuild same tech, reset life) event [process, tech, period]
    cap_built: Any = None  # storage capacity built [store]
    charge: Any = None  # flow charged into a store [store, period]
    discharge: Any = None  # flow discharged from a store [store, period]
    level: Any = None  # storage inventory level [store, period]
    extbuy: Any = None  # external purchase for a stored flow [store, period]
    mbuy: Any = None  # flow-market purchase [cmarket, period]
    msell: Any = None  # flow-market sale [cmarket, period]
    abuy: Any = None  # ETS allowance bought [imarket, period]
    asell: Any = None  # ETS allowance sold [imarket, period]
    cmarkets: list[Any] = field(default_factory=list)  # flow Market entities
    imarkets: list[Any] = field(default_factory=list)  # impact (ETS) Market entities
    dispense: Any = None  # fuel a station dispenses [station, period]
    slk_dem: Any = None  # demand slack [demand_key]
    slk_cap: Any = None  # impact-cap slack [cap_key]
    slk_green: Any = None  # green-corridor intensity-cap slack [green_key]

    demand_keys: list[tuple[str, str, int]] = field(default_factory=list)
    cap_keys: list[tuple[str, str, int]] = field(default_factory=list)
    green_keys: list[str] = field(default_factory=list)


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
        # A forced switch (simulate) makes its target reachable even with no
        # transition row, so its recipe is wired into the flow balance.
        forced = problem.forced_switches.get(p.process_id)
        if forced is not None:
            techs.add(forced[0])
        out[p.process_id] = sorted(t for t in techs if t in problem.technologies)
    return out


def _lever_slots(problem: Problem) -> list[LeverSlot]:
    """Flatten levers × blocks into addressable slots."""
    slots: list[LeverSlot] = []
    for m in problem.levers:
        for b, blk in enumerate(m.blocks):
            slots.append(
                LeverSlot(
                    key=f"{m.lever_id}#{b}",
                    lever_id=m.lever_id,
                    process=m.applies_to,
                    lever_type=m.lever_type,
                    target=m.target,
                    reduction=blk.reduction,
                    capex=blk.capex,
                    opex=blk.opex,
                    lifetime=m.lifetime,
                    scope=m.scope,
                    capex_by_year=blk.capex_by_year,
                    opex_by_year=blk.opex_by_year,
                    reduction_by_year=blk.reduction_by_year,
                )
            )
    return slots


def _references(
    problem: Problem,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Precompute baseline consumption and emission references per process.

    Used to linearise MACC savings: a lever's saving is ``reduction × ref``
    (a constant), not ``reduction × throughput`` (which would be bilinear).
    Reference uses the process's full capacity on its baseline technology, with
    coefficients read at the first horizon year ``t₀`` (so a recipe whose
    intensity/emission factor is supplied only as a year trajectory still has a
    well-defined reference rather than a zero one).

    ``ref_consumption[(p, r)] = capacity_p · input_intensity[baseline, r](t₀)``.
    ``ref_impact[(p, i)] = capacity_p · direct_impact[baseline, i](t₀)
        + Σ_r flow_impacts[(r, i)] · ref_consumption[(p, r)]``.
    """
    ref_cons: dict[tuple[str, str], float] = {}
    ref_imp: dict[tuple[str, str], float] = {}
    t0 = problem.years[0] if problem.years else 0
    for p in problem.processes:
        tech = problem.technologies.get(p.baseline_technology)
        if tech is None:
            continue
        cap = p.capacity
        inputs = set(tech.input_intensity) | set(tech.input_intensity_by_year)
        for r in inputs:
            ref_cons[(p.process_id, r)] = cap * tech.input_intensity_at(r, t0)
        for i in problem.impacts:
            total = (tech.direct_impact_at(i, t0) + p.direct_impact_at(i, t0)) * cap
            for r in inputs:
                total += problem.flow_impacts.get((r, i), 0.0) * ref_cons.get(
                    (p.process_id, r), 0.0
                )
            ref_imp[(p.process_id, i)] = total
    return ref_cons, ref_imp


def _fleet_references(problem: Problem) -> dict[str, float]:
    r"""Per-fleet full-deployment annual fuel — the baseline a fleet (group of N
    transport assets) lever's saving scales against, exactly like ``ref_consumption``
    is a process's full-capacity baseline.

    A fleet's fuel is ``Σ legflow · efficiency · distance`` over its candidate
    connection-route legs. At full deployment ``legflow → cap_on(distance) ·
    max_units``, so::

        ref_fuel[f] = Σ_{legs of f} efficiency(t₀) · distance · cap_on(distance) · max_units

    with ``max_units`` falling back to the fleet's own ``count`` (then ``max_build``)
    when a leg sets no ceiling. Read at the first horizon year so a year-trajectory
    efficiency still yields a well-defined, constant reference (keeps the saving
    linear: ``reduction · z · ref``, never ``reduction · z · legflow``).
    """
    refs: dict[str, float] = {}
    t0 = problem.years[0] if problem.years else 0
    for cr in problem.connection_routes:
        if cr.distance <= 0 or not cr.legs:
            continue
        for leg in cr.legs:
            fl = problem.fleets.get(leg.fleet_id)
            if fl is None or fl.efficiency_at(t0) <= 0:
                continue
            cap = fl.capacity_on(cr.distance) or fl.capacity
            if cap <= 0:
                continue
            units = leg.max_units
            if units is None:
                units = fl.count or fl.max_build or 0.0
            if units <= 0:
                continue
            refs[fl.fleet_id] = refs.get(fl.fleet_id, 0.0) + (
                fl.efficiency_at(t0) * cr.distance * cap * units
            )
    return refs


def build_context(model: Model, problem: Problem) -> BuildContext:
    """Create all decision variables and return the populated context."""
    procs = [p.process_id for p in problem.processes]
    techs = list(problem.technologies)
    comms = list(problem.flows)
    impacts = list(problem.impacts)
    years = problem.years

    feasible = _feasible_techs(problem)
    slots = _lever_slots(problem)
    ref_cons, ref_imp = _references(problem)
    fleet_ref_fuel = _fleet_references(problem)
    grouped_comms = sorted({c for k in problem.technologies.values() for c in k.grouped_inputs()})
    grouped_out = sorted({c for k in problem.technologies.values() for c in k.grouped_outputs()})

    p_idx = pd.Index(procs, name="process")
    k_idx = pd.Index(techs, name="tech")
    r_idx = pd.Index(comms, name="flow")
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
        fleet_ref_fuel=fleet_ref_fuel,
        grouped_comms=grouped_comms,
        grouped_out_comms=grouped_out,
    )

    ctx.on = model.add_variables(binary=True, coords=[p_idx, t_idx], name="on")
    ctx.u = model.add_variables(binary=True, coords=[p_idx, k_idx, t_idx], name="u")
    ctx.x = model.add_variables(lower=0.0, coords=[p_idx, k_idx, t_idx], name="x")
    if grouped_comms:
        gc_idx = pd.Index(grouped_comms, name="flow")
        ctx.fin = model.add_variables(lower=0.0, coords=[p_idx, k_idx, gc_idx, t_idx], name="fin")
    if grouped_out:
        go_idx = pd.Index(grouped_out, name="flow")
        ctx.fout = model.add_variables(lower=0.0, coords=[p_idx, k_idx, go_idx, t_idx], name="fout")
    # Transition (replace) event: continuous in [0, 1] — w >= u_t - u_prev pins it
    # to the switch-in, and cost minimisation keeps it at the lower bound.
    ctx.w = model.add_variables(lower=0.0, upper=1.0, coords=[p_idx, k_idx, t_idx], name="w")
    # Renewal (rebuild) event: only for lifecycle-tracked models (a process
    # declares when its baseline was installed). Absent otherwise, so models
    # without install dates are byte-for-byte unchanged.
    if any(p.introduced_year is not None for p in problem.processes):
        ctx.ren = model.add_variables(
            lower=0.0, upper=1.0, coords=[p_idx, k_idx, t_idx], name="ren"
        )
    ctx.buy = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="buy")
    ctx.sell = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="sell")
    ctx.deliver = model.add_variables(lower=0.0, coords=[p_idx, r_idx, t_idx], name="deliver")
    ctx.emit = model.add_variables(coords=[p_idx, i_idx, t_idx], name="emit")

    # Fleet (Layer 1b): integer ships assigned to each fleet-managed route process.
    if problem.fleet_routes:
        fp_idx = pd.Index(list(problem.fleet_routes), name="process")
        ctx.units = model.add_variables(
            lower=0.0, integer=True, coords=[fp_idx, t_idx], name="units"
        )

    # Connection fleet (Layer 1c+): per (physicalised connection route, candidate
    # fleet) — the integer carriers assigned (cunits) and the cargo they carry
    # (legflow). The optimiser picks which candidate fleet(s) serve each route.
    leg_ids = [
        leg_key(cr.process, leg.fleet_id) for cr in problem.connection_routes for leg in cr.legs
    ]
    if leg_ids:
        lg_idx = pd.Index(leg_ids, name="leg")
        ctx.cunits = model.add_variables(
            lower=0.0, integer=True, coords=[lg_idx, t_idx], name="cunits"
        )
        ctx.legflow = model.add_variables(lower=0.0, coords=[lg_idx, t_idx], name="legflow")

    # Fleet acquisition (capex): integer carriers the optimiser BUILDS, per capex-bearing
    # fleet, per year — its pool then grows by the still-living built carriers. Gated so a
    # model with no fleet capex is byte-identical (no variable, no constraint, no term).
    build_fleets = [fid for fid, fl in problem.fleets.items() if fl.capex]
    if build_fleets:
        bf_idx = pd.Index(build_fleets, name="fleet")
        ctx.built = model.add_variables(
            lower=0.0, integer=True, coords=[bf_idx, t_idx], name="built"
        )

    if slots:
        s_idx = pd.Index([s.key for s in slots], name="slot")
        ctx.z = model.add_variables(lower=0.0, upper=1.0, coords=[s_idx, t_idx], name="z")
    # Scoped (fleet/group) slots deploy via a BINARY decision + an abated-fuel variable
    # capped at the actual legflow fuel (built in build._fleet_lever) — endogenous like a
    # process MACC, but exact for a variable transport activity (no over-abatement).
    fleet_slot_keys = [s.key for s in slots if s.scope]
    if fleet_slot_keys:
        fs_idx = pd.Index(fleet_slot_keys, name="slot")
        ctx.dfl = model.add_variables(binary=True, coords=[fs_idx, t_idx], name="dfl")
        ctx.fsaved = model.add_variables(lower=0.0, coords=[fs_idx, t_idx], name="fsaved")
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

    ctx.cmarkets = [m for m in problem.markets if m.target_kind == MarketTarget.FLOW]
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

    # Stations (refuelling): fuel dispensed per station per year.
    if problem.stations:
        st_idx = pd.Index([s.station_id for s in problem.stations], name="station")
        ctx.dispense = model.add_variables(lower=0.0, coords=[st_idx, t_idx], name="dispense")

    # Green-corridor (transport intensity-cap) slack — one per (lane·impact·year).
    ctx.green_keys = sorted(
        green_key(gc.label, gc.impact, y) for gc in problem.green_corridors for y in gc.limits
    )
    if ctx.green_keys:
        gk_idx = pd.Index(ctx.green_keys, name="gkey")
        ctx.slk_green = model.add_variables(lower=0.0, coords=[gk_idx], name="slk_green")

    return ctx
