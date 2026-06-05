"""Assemble the ``linopy`` model: variables → constraints → objective.

Loop-based construction over the (small-to-moderate) process/period sets, kept
deliberately explicit so each constraint maps one-to-one to ALGORITHM.md. The
genuinely model-specific pieces are the per-commodity **node balance** (with
inter-process edges, external buy/sell, and demand delivery) and the LP-safe
**MACC** savings (proportional to a fixed baseline reference, not throughput).
"""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import xarray as xr
from linopy import Model

from pathwise.core.entities import CommodityKind, MeasureType, ObjectiveMode
from pathwise.core.problem import Problem
from pathwise.core.variables import BuildContext, build_context
from pathwise.logger import get_logger

logger = get_logger(__name__)


def _lin_sum(terms: list[Any]) -> Any:
    """Sum a list of ``linopy`` expressions (``None`` if empty)."""
    if not terms:
        return None
    acc = terms[0]
    for t in terms[1:]:
        acc = acc + t
    return acc


def build(problem: Problem) -> BuildContext:
    """Build the full ``linopy`` model for ``problem`` and return its context."""
    model = Model()
    ctx = build_context(model, problem)
    logger.info(
        "model built: %d processes, %d techs, %d commodities, %d impacts, %d periods, "
        "%d edges, %d measure-slots",
        len(ctx.procs),
        len(ctx.techs),
        len(ctx.comms),
        len(ctx.impacts),
        len(ctx.years),
        len(problem.edges),
        len(ctx.slots),
    )
    _technology(ctx)
    _blend(ctx)
    _flow_balance(ctx)
    _storage(ctx)
    _markets(ctx)
    _impacts(ctx)
    _macc(ctx)
    _controls(ctx)
    _objective(ctx)
    return ctx


def _prev(years: list[int]) -> dict[int, int | None]:
    return {y: (years[i - 1] if i > 0 else None) for i, y in enumerate(years)}


def _technology(ctx: BuildContext) -> None:
    """One active technology per process; capacity link; baseline lock; events."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    # Available throughput = (possibly temporal) capacity derated by failure rate.
    avail = {p.process_id: p for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}

    # Infeasible (process, technology) pairs are forbidden in a single vectorised
    # constraint each — NOT a per-pair Python loop — so the model scales to many
    # technologies (e.g. one specific technology per facility).
    feas_arr = np.array(
        [
            [[1.0 if k in ctx.feasible[p] else 0.0 for _t in ctx.years] for k in ctx.techs]
            for p in ctx.procs
        ]
    )
    feas = xr.DataArray(
        feas_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    big = (max((p.capacity for p in prob.processes), default=1.0) or 1.0) * 1.0e3 + 1.0e6
    m.add_constraints(ctx.u <= feas, name="ufeas")
    m.add_constraints(ctx.w <= feas, name="wfeas")
    m.add_constraints(ctx.x <= big * feas, name="xfeas")

    for p in ctx.procs:
        feas_p = ctx.feasible[p]
        for t in ctx.years:
            # One technology active iff the facility operates (`on`). If off, the
            # facility runs nothing — its output is sourced elsewhere (outsourced).
            active = _lin_sum([ctx.u.sel(process=p, tech=k, period=t) for k in feas_p])
            m.add_constraints(active == ctx.on.sel(process=p, period=t), name=f"one_tech[{p},{t}]")
            cap_pt = avail[p].available(t)
            for k in feas_p:
                # Throughput only on the active technology, bounded by capacity.
                m.add_constraints(
                    ctx.x.sel(process=p, tech=k, period=t)
                    <= cap_pt * ctx.u.sel(process=p, tech=k, period=t),
                    name=f"cap[{p},{k},{t}]",
                )
                # Must-run floor: when active, throughput ≥ min_cf × capacity.
                min_cf = prob.technologies[k].min_capacity_factor
                if min_cf > 0.0:
                    m.add_constraints(
                        ctx.x.sel(process=p, tech=k, period=t)
                        >= min_cf * cap_pt * ctx.u.sel(process=p, tech=k, period=t),
                        name=f"mincf[{p},{k},{t}]",
                    )
        # If operating in the first period, it runs the baseline (no prior switch).
        t0 = ctx.years[0]
        m.add_constraints(
            ctx.u.sel(process=p, tech=baseline[p], period=t0) == ctx.on.sel(process=p, period=t0),
            name=f"baseline[{p}]",
        )
        # Transition (replace) event detection: w >= u_t - u_prev (feasible techs).
        for k in feas_p:
            for t in ctx.years:
                pt = prev[t]
                if pt is None:
                    m.add_constraints(
                        ctx.w.sel(process=p, tech=k, period=t) == 0, name=f"w0[{p},{k},{t}]"
                    )
                else:
                    m.add_constraints(
                        ctx.w.sel(process=p, tech=k, period=t)
                        >= ctx.u.sel(process=p, tech=k, period=t)
                        - ctx.u.sel(process=p, tech=k, period=pt),
                        name=f"event[{p},{k},{t}]",
                    )


def _produced(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """Output of commodity ``r`` at process ``p`` in ``t`` (expression or None)."""
    terms = [
        ctx.problem.technologies[k].output_yield.get(r, 0.0)
        * ctx.x.sel(process=p, tech=k, period=t)
        for k in ctx.feasible[p]
        if ctx.problem.technologies[k].output_yield.get(r, 0.0) != 0.0
    ]
    return _lin_sum(terms)


def _gross_consumed(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """Gross input of commodity ``r`` at ``p`` (before efficiency savings).

    A commodity that is part of a technology's blend group is consumed via the
    mix flow variable ``fin`` (so the optimiser picks the share); other inputs
    keep the fixed form ``intensity · throughput``.
    """
    terms = []
    for k in ctx.feasible[p]:
        tech = ctx.problem.technologies[k]
        if r in tech.grouped_inputs():
            terms.append(ctx.fin.sel(process=p, tech=k, commodity=r, period=t))
        else:
            coef = tech.input_intensity.get(r, 0.0)
            if coef != 0.0:
                terms.append(coef * ctx.x.sel(process=p, tech=k, period=t))
    return _lin_sum(terms)


def _blend(ctx: BuildContext) -> None:
    """Blend-group mix: members sum to the group requirement; shares bounded.

    For each technology blend group ``g`` (members ``C_g``, requirement
    ``R_g = Σ intensity_c``) and throughput ``x``::

        Σ_{c∈C_g} fin_c = R_g · x ;   s_min_c·R_g·x ≤ fin_c ≤ s_max_c·R_g·x

    Grouped commodities not used by a technology are pinned to zero.
    """
    if not ctx.grouped_comms:
        return
    m, prob = ctx.model, ctx.problem
    for p in ctx.procs:
        for k in ctx.techs:
            tech = prob.technologies[k]
            members_all = tech.grouped_inputs()
            for t in ctx.years:
                xpkt = ctx.x.sel(process=p, tech=k, period=t)
                for g, members in tech.share_groups.items():
                    req = tech.group_requirement(g)
                    m.add_constraints(
                        _lin_sum(
                            [ctx.fin.sel(process=p, tech=k, commodity=c, period=t) for c in members]
                        )
                        == req * xpkt,
                        name=f"mix[{p},{k},{g},{t}]",
                    )
                    for c, (lo, hi) in members.items():
                        f = ctx.fin.sel(process=p, tech=k, commodity=c, period=t)
                        if lo > 0.0:
                            m.add_constraints(f >= lo * req * xpkt, name=f"mixlo[{p},{k},{c},{t}]")
                        if hi < 1.0:
                            m.add_constraints(f <= hi * req * xpkt, name=f"mixhi[{p},{k},{c},{t}]")
                for c in ctx.grouped_comms:
                    if c not in members_all:
                        m.add_constraints(
                            ctx.fin.sel(process=p, tech=k, commodity=c, period=t) == 0,
                            name=f"mix0[{p},{k},{c},{t}]",
                        )


def _efficiency_savings(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """MACC energy-efficiency savings on commodity ``r`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction * ctx.ref_consumption.get((p, r), 0.0) * ctx.z.sel(slot=s.key, period=t)
        for s in ctx.slots
        if s.measure_type == MeasureType.ENERGY_EFFICIENCY and s.process == p and s.target == r
    ]
    return _lin_sum(terms)


def _edges_in(ctx: BuildContext, p: str, r: str) -> list[int]:
    return [i for i, e in enumerate(ctx.problem.edges) if e.to_process == p and e.commodity_id == r]


def _edges_out(ctx: BuildContext, p: str, r: str) -> list[int]:
    return [
        i for i, e in enumerate(ctx.problem.edges) if e.from_process == p and e.commodity_id == r
    ]


def _flow_balance(ctx: BuildContext) -> None:
    """Per-commodity node balance + edge caps + demand delivery (slack-softened)."""
    m, prob = ctx.model, ctx.problem
    products = {r for r, c in prob.commodities.items() if c.kind == CommodityKind.PRODUCT}
    produced_anywhere = {
        r for k in prob.technologies.values() for r, y in k.output_yield.items() if y != 0.0
    }
    raw_kinds = {CommodityKind.ENERGY, CommodityKind.MATERIAL, CommodityKind.INDIRECT}
    # A commodity with a market can be bought even if it is produced internally —
    # this is what lets the model outsource an upstream process (buy its output).
    market_commodities = {mk.target for mk in ctx.cmarkets}

    def _purchasable(r: str) -> bool:
        c = prob.commodities[r]
        if r in market_commodities:
            return True
        if c.purchasable is not None:
            return c.purchasable
        return c.kind in raw_kinds and r not in produced_anywhere

    for p in ctx.procs:
        for r in ctx.comms:
            comm = prob.commodities[r]
            for t in ctx.years:
                produced = _produced(ctx, p, r, t)
                gross = _gross_consumed(ctx, p, r, t)
                savings = _efficiency_savings(ctx, p, r, t)
                consumed = gross
                if savings is not None:
                    consumed = (gross - savings) if gross is not None else (-1.0) * savings
                in_edges = _edges_in(ctx, p, r)
                out_edges = _edges_out(ctx, p, r)
                inflow = _lin_sum([ctx.flow.sel(edge=i, period=t) for i in in_edges])
                outflow = _lin_sum([ctx.flow.sel(edge=i, period=t) for i in out_edges])

                # in == out :  produced + buy + inflow == consumed + outflow + sell + deliver
                lhs_terms = [ctx.buy.sel(process=p, commodity=r, period=t)]
                if produced is not None:
                    lhs_terms.append(produced)
                if inflow is not None:
                    lhs_terms.append(inflow)
                rhs_terms = [
                    ctx.sell.sel(process=p, commodity=r, period=t),
                    ctx.deliver.sel(process=p, commodity=r, period=t),
                ]
                if consumed is not None:
                    rhs_terms.append(consumed)
                if outflow is not None:
                    rhs_terms.append(outflow)
                m.add_constraints(
                    _lin_sum(lhs_terms) == _lin_sum(rhs_terms), name=f"bal[{p},{r},{t}]"
                )

                # Non-products cannot be delivered; non-sellable cannot be sold;
                # only raw inputs may be bought externally.
                if r not in products:
                    m.add_constraints(
                        ctx.deliver.sel(process=p, commodity=r, period=t) == 0,
                        name=f"nodeliver[{p},{r},{t}]",
                    )
                # Products leave only via `deliver` (to demand/market); the
                # generic `sell` is for by-products / surplus raw streams.
                if r in products or not comm.sellable:
                    m.add_constraints(
                        ctx.sell.sel(process=p, commodity=r, period=t) == 0,
                        name=f"nosell[{p},{r},{t}]",
                    )
                if not _purchasable(r):
                    m.add_constraints(
                        ctx.buy.sel(process=p, commodity=r, period=t) == 0,
                        name=f"nobuy[{p},{r},{t}]",
                    )

    # Edge capacities.
    for i, e in enumerate(prob.edges):
        if e.max_flow is not None:
            for t in ctx.years:
                m.add_constraints(
                    ctx.flow.sel(edge=i, period=t) <= e.max_flow, name=f"emax[{i},{t}]"
                )

    # Demand: cost companies must meet it (slack-softened); profit companies may
    # sell UP TO it (producing less is allowed — revenue handled in the objective).
    for c, q, y in ctx.demand_keys:
        procs = [p.process_id for p in prob.processes if c == "all" or p.company == c]
        delivered = _lin_sum([ctx.deliver.sel(process=p, commodity=q, period=y) for p in procs])
        key = f"{c}|{q}|{y}"
        rhs = prob.demand[(c, q, y)]
        if prob.objective_of(c) == ObjectiveMode.PROFIT:
            if delivered is not None:
                m.add_constraints(delivered <= rhs, name=f"sellcap[{key}]")
        else:
            slack = ctx.slk_dem.sel(dkey=key)
            if delivered is None:
                m.add_constraints(slack >= rhs, name=f"demand[{key}]")
            else:
                m.add_constraints(delivered + slack >= rhs, name=f"demand[{key}]")


def _abatement(ctx: BuildContext, p: str, i: str, t: int) -> Any:
    """MACC emission/environmental abatement of impact ``i`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction * ctx.ref_impact.get((p, i), 0.0) * ctx.z.sel(slot=s.key, period=t)
        for s in ctx.slots
        if s.measure_type in (MeasureType.EMISSION_REDUCTION, MeasureType.ENVIRONMENTAL)
        and s.process == p
        and s.target == i
    ]
    return _lin_sum(terms)


def _impacts(ctx: BuildContext) -> None:
    """Define ``emit`` per (process, impact, period) and apply caps (slack-softened)."""
    m, prob = ctx.model, ctx.problem
    for p in ctx.procs:
        for i in ctx.impacts:
            for t in ctx.years:
                terms = []
                for r in ctx.comms:
                    factor = prob.commodity_impacts.get((r, i), 0.0)
                    if factor == 0.0:
                        continue
                    cons = _gross_consumed(ctx, p, r, t)
                    sav = _efficiency_savings(ctx, p, r, t)
                    if cons is not None:
                        terms.append(factor * cons)
                    if sav is not None:
                        terms.append((-factor) * sav)
                for k in ctx.feasible[p]:
                    df = prob.technologies[k].direct_impact.get(i, 0.0)
                    if df != 0.0:
                        terms.append(df * ctx.x.sel(process=p, tech=k, period=t))
                abate = _abatement(ctx, p, i, t)
                if abate is not None:
                    terms.append((-1.0) * abate)
                gross = _lin_sum(terms)
                rhs = gross if gross is not None else 0.0
                m.add_constraints(
                    ctx.emit.sel(process=p, impact=i, period=t) == rhs, name=f"emit[{p},{i},{t}]"
                )
                m.add_constraints(
                    ctx.emit.sel(process=p, impact=i, period=t) >= 0, name=f"emitpos[{p},{i},{t}]"
                )

    for c, i, y in ctx.cap_keys:
        procs = [p.process_id for p in prob.processes if c == "all" or p.company == c]
        total = _lin_sum([ctx.emit.sel(process=p, impact=i, period=y) for p in procs])
        key = f"{c}|{i}|{y}"
        slack = ctx.slk_cap.sel(ckey=key)
        rhs = prob.impact_caps[(c, i, y)]
        # A hard cap forbids exceedance (slack pinned to zero); a soft cap allows
        # it at the cap's penalty (applied in the objective). Default: soft.
        soft = prob.impact_cap_soft.get((c, i), True)
        if not soft:
            m.add_constraints(slack == 0, name=f"caphard[{key}]")
        if total is not None:
            m.add_constraints(total - slack <= rhs, name=f"cap[{key}]")


def _macc(ctx: BuildContext) -> None:
    """MACC adoption: cumulative blocks + persistence across periods."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    by_measure: dict[str, list[str]] = {}
    for s in ctx.slots:
        by_measure.setdefault(s.measure_id, []).append(s.key)
    for keys in by_measure.values():
        for a, b in itertools.pairwise(keys):  # block a adopted before b
            for t in ctx.years:
                m.add_constraints(
                    ctx.z.sel(slot=a, period=t) >= ctx.z.sel(slot=b, period=t),
                    name=f"mono[{a},{b},{t}]",
                )
    for s in ctx.slots:
        for t in ctx.years:
            pt = prev[t]
            if pt is not None:
                m.add_constraints(
                    ctx.z.sel(slot=s.key, period=t) >= ctx.z.sel(slot=s.key, period=pt),
                    name=f"persist[{s.key},{t}]",
                )
    _ = prob  # referenced for symmetry; measures already flattened into slots


def _scope_processes(ctx: BuildContext, company: str) -> list[str]:
    """Process ids in ``company`` (``"all"`` ⇒ every process)."""
    return [p.process_id for p in ctx.problem.processes if company == "all" or p.company == company]


def _transition_costs(ctx: BuildContext) -> dict[tuple[str, str], float]:
    """Nominal replacement capex per ``(process, target tech)`` = capacity × cost."""
    prob = ctx.problem
    out: dict[tuple[str, str], float] = {}
    for tr in prob.transitions:
        for proc in prob.processes:
            if tr.from_technology == proc.baseline_technology:
                out[(proc.process_id, tr.to_technology)] = tr.capex_per_capacity * proc.capacity
    return out


def _storage(ctx: BuildContext) -> None:
    """Inter-year inventory dynamics + market linkage for each store.

    Algorithm (per store ``s`` of commodity ``r``, year ``t``):
        level_t = (1−loss)·level_{t-1} + η_c·charge_t − discharge_t/η_d
        extbuy_t = Σ_{p∈scope} buy_{p,r,t} + charge_t − discharge_t   (≥ 0)
        0 ≤ level_t, charge_t, discharge_t ≤ cap_built ≤ max_capacity

    ``charge`` draws commodity from the market (raises external purchase),
    ``discharge`` returns it (lowers external purchase). Only the external
    purchase ``extbuy`` is priced — process ``buy`` of a stored commodity is the
    internal draw (repriced in the objective).
    """
    m, prob = ctx.model, ctx.problem
    if not prob.storages:
        return
    prev = _prev(ctx.years)
    for s in prob.storages:
        sid = s.storage_id
        m.add_constraints(ctx.cap_built.sel(store=sid) <= s.max_capacity, name=f"scap[{sid}]")
        scope = _scope_processes(ctx, s.company)
        for t in ctx.years:
            charge_t = ctx.charge.sel(store=sid, period=t)
            dis_t = ctx.discharge.sel(store=sid, period=t)
            lvl_t = ctx.level.sel(store=sid, period=t)
            pt = prev[t]
            decay = 1.0 - s.standing_loss
            gain = s.charge_efficiency * charge_t - (1.0 / s.discharge_efficiency) * dis_t
            prior = decay * ctx.level.sel(store=sid, period=pt) if pt is not None else None
            rhs = (gain + prior) if prior is not None else (gain + decay * s.initial_level)
            m.add_constraints(lvl_t == rhs, name=f"slevel[{sid},{t}]")
            m.add_constraints(lvl_t <= ctx.cap_built.sel(store=sid), name=f"slcap[{sid},{t}]")
            m.add_constraints(charge_t <= ctx.cap_built.sel(store=sid), name=f"schg[{sid},{t}]")
            m.add_constraints(dis_t <= ctx.cap_built.sel(store=sid), name=f"sdis[{sid},{t}]")
            buys = _lin_sum(
                [ctx.buy.sel(process=p, commodity=s.commodity_id, period=t) for p in scope]
            )
            link = charge_t - dis_t
            if buys is not None:
                link = link + buys
            m.add_constraints(ctx.extbuy.sel(store=sid, period=t) == link, name=f"smkt[{sid},{t}]")


def _markets(ctx: BuildContext) -> None:
    """Commodity-market clearing (least-cost mixture) + tradable ETS balance.

    Commodity markets supply a stream's external need (process draw, or the
    store's external purchase if storable):
        Σ_m (mbuy_{m,t} − msell_{m,t}) = external_need_{r,t}
    ETS markets cover emissions with allowances (deficit bought, surplus sold):
        allocation_t + abuy_{m,t} − asell_{m,t} = Σ_{p∈scope} emit_{p,i,t}
    """
    m, prob = ctx.model, ctx.problem

    # ── Commodity markets ────────────────────────────────────────────────────
    by_commodity: dict[str, list[Any]] = {}
    for mk in ctx.cmarkets:
        by_commodity.setdefault(mk.target, []).append(mk)
    storages_of: dict[str, list[Any]] = {}
    for st in prob.storages:
        storages_of.setdefault(st.commodity_id, []).append(st)

    for r, mkts in by_commodity.items():
        scope_companies = {mk.company for mk in mkts}
        procs = (
            ctx.procs
            if "all" in scope_companies
            else [p.process_id for p in prob.processes if p.company in scope_companies]
        )
        for t in ctx.years:
            net = _lin_sum(
                [ctx.mbuy.sel(cmarket=mk.market_id, period=t) for mk in mkts]
                + [(-1.0) * ctx.msell.sel(cmarket=mk.market_id, period=t) for mk in mkts]
            )
            if r in storages_of:
                target = _lin_sum(
                    [ctx.extbuy.sel(store=s.storage_id, period=t) for s in storages_of[r]]
                )
            else:
                target = _lin_sum([ctx.buy.sel(process=p, commodity=r, period=t) for p in procs])
            rhs = target if target is not None else 0.0
            m.add_constraints(net == rhs, name=f"mclear[{r},{t}]")
        for mk in mkts:
            for t in ctx.years:
                if mk.max_buy is not None:
                    m.add_constraints(
                        ctx.mbuy.sel(cmarket=mk.market_id, period=t) <= mk.max_buy,
                        name=f"mmaxbuy[{mk.market_id},{t}]",
                    )
                if mk.max_sell is not None:
                    m.add_constraints(
                        ctx.msell.sel(cmarket=mk.market_id, period=t) <= mk.max_sell,
                        name=f"mmaxsell[{mk.market_id},{t}]",
                    )

    # ── ETS allowance markets ─────────────────────────────────────────────────
    for mk in ctx.imarkets:
        scope = _scope_processes(ctx, mk.company)
        for t in ctx.years:
            emit = _lin_sum([ctx.emit.sel(process=p, impact=mk.target, period=t) for p in scope])
            held = ctx.abuy.sel(imarket=mk.market_id, period=t) - ctx.asell.sel(
                imarket=mk.market_id, period=t
            )
            lhs = held if emit is None else (held - emit)
            m.add_constraints(lhs == -mk.allocation(t), name=f"ets[{mk.market_id},{t}]")
            if mk.max_buy is not None:
                m.add_constraints(
                    ctx.abuy.sel(imarket=mk.market_id, period=t) <= mk.max_buy,
                    name=f"etsmaxbuy[{mk.market_id},{t}]",
                )
            if mk.max_sell is not None:
                m.add_constraints(
                    ctx.asell.sel(imarket=mk.market_id, period=t) <= mk.max_sell,
                    name=f"etsmaxsell[{mk.market_id},{t}]",
                )


def _controls(ctx: BuildContext) -> None:
    """Company decision controls: investment budget cap + minimum production."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    company_of = {p.process_id: p.company for p in prob.processes}
    trans_cost = _transition_costs(ctx)
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    slot_company = {s.key: company_of.get(s.process, "all") for s in ctx.slots}

    def _in_scope(company: str, target: str) -> bool:
        return company == "all" or target == company

    # Investment-budget cap (nominal capex per company-year).
    for (c, y), limit in prob.investment_budget.items():
        terms: list[Any] = []
        for p in ctx.procs:
            if not _in_scope(c, company_of[p]):
                continue
            for k in ctx.feasible[p]:
                if k == baseline[p]:
                    continue
                cost = trans_cost.get((p, k), prob.technologies[k].capex(y) * cap[p])
                if cost:
                    terms.append(cost * ctx.w.sel(process=p, tech=k, period=y))
        for s in ctx.slots:
            if not _in_scope(c, slot_company[s.key]) or not s.capex:
                continue
            inc = ctx.z.sel(slot=s.key, period=y)
            pt = prev[y]
            if pt is not None:
                inc = inc - ctx.z.sel(slot=s.key, period=pt)
            terms.append(s.capex * inc)
        if y == ctx.years[0]:
            for st in prob.storages:
                if _in_scope(c, st.company) and st.capex_per_capacity:
                    terms.append(st.capex_per_capacity * ctx.cap_built.sel(store=st.storage_id))
        total = _lin_sum(terms)
        if total is not None:
            m.add_constraints(total <= limit, name=f"budget[{c},{y}]")

    # Minimum annual production (hard floor on delivered product).
    for (c, q, y), amount in prob.min_production.items():
        delivered = _lin_sum(
            [ctx.deliver.sel(process=p, commodity=q, period=y) for p in _scope_processes(ctx, c)]
        )
        if delivered is not None:
            m.add_constraints(delivered >= amount, name=f"minprod[{c},{q},{y}]")


def _objective(ctx: BuildContext) -> None:
    """Discounted total system cost + slack penalties (minimise)."""
    m, prob = ctx.model, ctx.problem
    tog = prob.toggles
    prev = _prev(ctx.years)
    dur = {p.year: p.duration_years for p in prob.periods}
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    fixed_opex = {p.process_id: p.fixed_opex for p in prob.processes}
    trans_cost = _transition_costs(ctx)

    # Stored commodities are priced via the store's external purchase, not the
    # process buy (which becomes the internal draw) — avoids double counting.
    stored = {s.commodity_id for s in prob.storages}
    # Market-covered streams/impacts are priced via the market (mbuy/msell,
    # abuy/asell), not via the flat commodity/impact price.
    market_comms = {mk.target for mk in ctx.cmarkets}
    ets_impacts = {mk.target for mk in ctx.imarkets}

    terms: list[Any] = []
    for t in ctx.years:
        df = prob.discount_factor(t)
        w = df * dur[t]
        # Operational: opex + commodity purchases − sales + impact prices.
        for p in ctx.procs:
            if tog.opex:
                for k in ctx.feasible[p]:
                    ox = prob.technologies[k].opex(t)
                    if ox:
                        terms.append((w * ox) * ctx.x.sel(process=p, tech=k, period=t))
                # Facility fixed annual O&M — only while operating (`on`).
                if fixed_opex[p]:
                    terms.append((w * fixed_opex[p]) * ctx.on.sel(process=p, period=t))
            if tog.commodity_cost:
                for r in ctx.comms:
                    if r in stored or r in market_comms:
                        continue  # priced via storage / market below
                    price = prob.commodities[r].price(t)
                    sale = prob.commodities[r].sale_price(t)
                    if price:
                        terms.append((w * price) * ctx.buy.sel(process=p, commodity=r, period=t))
                    if sale:
                        terms.append((-w * sale) * ctx.sell.sel(process=p, commodity=r, period=t))
            if tog.impact_price:
                for i in ctx.impacts:
                    if i in ets_impacts:
                        continue  # priced via the ETS allowance market below
                    pr = prob.impacts[i].price(t)
                    if pr:
                        terms.append((w * pr) * ctx.emit.sel(process=p, impact=i, period=t))
        # Storage: external purchase priced (unless a market prices the stream)
        # + fixed O&M on built capacity.
        if tog.commodity_cost:
            for st in prob.storages:
                if st.commodity_id not in market_comms:
                    price = prob.commodities[st.commodity_id].price(t)
                    if price:
                        terms.append((w * price) * ctx.extbuy.sel(store=st.storage_id, period=t))
                if st.fixed_opex_per_capacity:
                    terms.append(
                        (w * st.fixed_opex_per_capacity) * ctx.cap_built.sel(store=st.storage_id)
                    )
        # Markets: commodity buy/sell + tradable ETS allowance buy/sell.
        if tog.commodity_cost:
            for mk in ctx.cmarkets:
                if mk.price(t):
                    terms.append((w * mk.price(t)) * ctx.mbuy.sel(cmarket=mk.market_id, period=t))
                if mk.sell_price(t):
                    terms.append(
                        (-w * mk.sell_price(t)) * ctx.msell.sel(cmarket=mk.market_id, period=t)
                    )
        if tog.impact_price:
            for mk in ctx.imarkets:
                if mk.price(t):
                    terms.append((w * mk.price(t)) * ctx.abuy.sel(imarket=mk.market_id, period=t))
                if mk.sell_price(t):
                    terms.append(
                        (-w * mk.sell_price(t)) * ctx.asell.sel(imarket=mk.market_id, period=t)
                    )
        # Replacement capex (discounted lump at the event year).
        if tog.capex:
            for p in ctx.procs:
                for k in ctx.feasible[p]:
                    if k == baseline[p]:
                        continue
                    c = trans_cost.get((p, k))
                    if c is None:
                        c = prob.technologies[k].capex(t) * cap[p]
                    if c:
                        terms.append((df * c) * ctx.w.sel(process=p, tech=k, period=t))
        # Measure capex on adoption increments (discounted lump).
        if tog.measure_capex and ctx.slots:
            for s in ctx.slots:
                pt = prev[t]
                inc = ctx.z.sel(slot=s.key, period=t)
                if pt is not None:
                    inc = inc - ctx.z.sel(slot=s.key, period=pt)
                if s.capex:
                    terms.append((df * s.capex) * inc)

    # Product sale revenue for profit companies (negative cost ⇒ maximise profit):
    # revenue = sale_price · delivered, summed over the company's processes.
    for comp, q, y in ctx.demand_keys:
        if prob.objective_of(comp) != ObjectiveMode.PROFIT:
            continue
        price = prob.commodities[q].sale_price(y)
        if not price:
            continue
        scope = _scope_processes(ctx, comp)
        delivered = _lin_sum([ctx.deliver.sel(process=p, commodity=q, period=y) for p in scope])
        if delivered is not None:
            terms.append((-(prob.discount_factor(y) * dur[y] * price)) * delivered)

    # Storage build capex — one-time, discounted at the first year.
    if tog.capex and prob.storages:
        df0 = prob.discount_factor(ctx.years[0])
        for st in prob.storages:
            if st.capex_per_capacity:
                terms.append((df0 * st.capex_per_capacity) * ctx.cap_built.sel(store=st.storage_id))

    # Slack penalties (keep the model well-posed and diagnosable).
    if ctx.demand_keys:
        terms.append(prob.slack_penalty * ctx.slk_dem.sum())
    if ctx.cap_keys:
        # Soft caps are penalised at their own penalty (default slack_penalty);
        # hard caps have slack pinned to zero so their coefficient is irrelevant.
        for cap_c, cap_i, cap_y in ctx.cap_keys:
            pen = prob.impact_cap_penalty.get((cap_c, cap_i), prob.slack_penalty)
            terms.append(pen * ctx.slk_cap.sel(ckey=f"{cap_c}|{cap_i}|{cap_y}"))

    obj = _lin_sum(terms)
    if obj is not None:
        m.add_objective(obj)
