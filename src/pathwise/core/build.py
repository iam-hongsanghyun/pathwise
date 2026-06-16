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

from pathwise.core.entities import (
    CommodityKind,
    MeasureType,
    ObjectiveMode,
    Transition,
    TransitionAction,
)
from pathwise.core.problem import Problem
from pathwise.core.variables import BuildContext, build_context
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Big-M for the indicator/throughput links: a value safely above any feasible
#: throughput. Scaled off the largest nameplate capacity plus a floor so it stays
#: valid even when every capacity is tiny.
_BIG_M_CAPACITY_SCALE = 1.0e3
_BIG_M_FLOOR = 1.0e6


def _big_m(problem: Problem) -> float:
    """A Big-M safely above any feasible throughput in ``problem``."""
    peak = max((p.capacity for p in problem.processes), default=1.0) or 1.0
    return peak * _BIG_M_CAPACITY_SCALE + _BIG_M_FLOOR


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
    _lifecycle(ctx)
    _blend(ctx)
    _output_blend(ctx)
    _flow_balance(ctx)
    _purchase_caps(ctx)
    _storage(ctx)
    _markets(ctx)
    _impacts(ctx)
    _macc(ctx)
    _controls(ctx)
    _adoption_caps(ctx)
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

    # Infeasible (process, technology, period) triples are forbidden in a single
    # vectorised constraint each — NOT a per-pair Python loop — so the model
    # scales to many technologies. A transition target additionally respects its
    # `introduction_year` (not adoptable before it); the BASELINE is exempt —
    # it is already installed regardless of when the technology became available.
    def _feas(p: str, k: str, t: int) -> float:
        if k not in ctx.feasible[p]:
            return 0.0
        if k != baseline[p]:
            intro = prob.technologies[k].introduction_year
            if intro is not None and t < intro:
                return 0.0
        # Phase-out binds EVERY technology, the installed baseline included —
        # after it the facility must transition or switch off.
        out = prob.technologies[k].phase_out_year
        if out is not None and t > out:
            return 0.0
        return 1.0

    feas_arr = np.array(
        [[[_feas(p, k, t) for t in ctx.years] for k in ctx.techs] for p in ctx.procs]
    )
    feas = xr.DataArray(
        feas_arr,
        coords={"process": ctx.procs, "tech": ctx.techs, "period": ctx.years},
        dims=["process", "tech", "period"],
    )
    big = _big_m(prob)
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
                min_cf = prob.technologies[k].min_cf_at(t)
                if min_cf > 0.0:
                    m.add_constraints(
                        ctx.x.sel(process=p, tech=k, period=t)
                        >= min_cf * cap_pt * ctx.u.sel(process=p, tech=k, period=t),
                        name=f"mincf[{p},{k},{t}]",
                    )
        # Decommission: the facility may not operate past its last year.
        dec = avail[p].decommission_year
        if dec is not None:
            for t in ctx.years:
                if t > dec:
                    m.add_constraints(ctx.on.sel(process=p, period=t) == 0, name=f"decomm[{p},{t}]")
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


def _lifecycle(ctx: BuildContext) -> None:
    r"""Asset end-of-life: force a renewal or replacement when a vintage expires.

    A technology may be active in year ``t`` only if a *live vintage* covers it:
    the original baseline install (while ``t < introduced_year + lifespan``), a
    replacement switch-in (``w``), or a renewal rebuild (``ren``) that happened
    within the trailing ``lifespan`` window. Once the window lapses the facility
    must renew the same technology, replace it, or switch off — capturing the
    capital wear-out the engine previously ignored.

    Algorithm:
        For process ``p``, technology ``k`` of life ``L`` and year ``t``::

            u[p,k,t] <= live0[p,k,t]
                        + Σ_{t' in years, t-L < t' <= t} refresh[p,k,t']

        refresh = ren                  (k is the baseline — a rebuild)
                = w + ren              (k reached by replacement — switch-in or rebuild)
        live0   = 1 if k is baseline and t < introduced_year + L, else 0

    Only processes that declare ``introduced_year`` are lifecycle-tracked; every
    other process (and every model with no install dates) is left untouched, so
    existing scenarios are unchanged. A renewal is permitted only for a
    technology whose ``actions`` include :attr:`TransitionAction.RENEW` and only
    while it is the active technology.
    """
    if ctx.ren is None:
        return
    m, prob = ctx.model, ctx.problem
    tracked = [p for p in prob.processes if p.introduced_year is not None]
    if not tracked:
        return
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    for p in tracked:
        pid = p.process_id
        inst = p.introduced_year or ctx.years[0]
        for k in ctx.feasible[pid]:
            tech = prob.technologies[k]
            life = max(int(tech.lifespan), 1)
            can_renew = TransitionAction.RENEW in tech.actions
            is_base = k == baseline[pid]
            for t in ctx.years:
                ren_kt = ctx.ren.sel(process=pid, tech=k, period=t)
                # A renewal rebuilds the active technology; forbid it where the
                # technology does not allow renewal, else tie it to operation.
                if can_renew:
                    m.add_constraints(
                        ren_kt <= ctx.u.sel(process=pid, tech=k, period=t),
                        name=f"renact[{pid},{k},{t}]",
                    )
                else:
                    m.add_constraints(ren_kt == 0, name=f"renfeas[{pid},{k},{t}]")
                # Live-vintage window.
                refresh = [
                    ctx.ren.sel(process=pid, tech=k, period=tp)
                    for tp in ctx.years
                    if t - life < tp <= t
                ]
                if not is_base:
                    refresh += [
                        ctx.w.sel(process=pid, tech=k, period=tp)
                        for tp in ctx.years
                        if t - life < tp <= t
                    ]
                live0 = 1.0 if (is_base and t < inst + life) else 0.0
                u_kt = ctx.u.sel(process=pid, tech=k, period=t)
                cover = _lin_sum(refresh)
                rhs = live0 if cover is None else live0 + cover
                m.add_constraints(u_kt <= rhs, name=f"life[{pid},{k},{t}]")


def _produced(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """Output of commodity ``r`` at process ``p`` in ``t`` (expression or None).

    A commodity in a technology's output slate group is produced via the slate
    flow variable ``fout`` (so the optimiser picks its share within bounds);
    other outputs keep the fixed form ``yield · throughput``.
    """
    terms = []
    for k in ctx.feasible[p]:
        tech = ctx.problem.technologies[k]
        if r in tech.grouped_outputs():
            terms.append(ctx.fout.sel(process=p, tech=k, commodity=r, period=t))
        else:
            coef = tech.output_yield_at(r, t)
            if coef != 0.0:
                terms.append(coef * ctx.x.sel(process=p, tech=k, period=t))
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
            coef = tech.input_intensity_at(r, t)
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
    gc = ctx.grouped_comms
    # The mix flow is non-zero only for (process, feasible tech, member commodity);
    # everything else is killed by ONE vectorised bound — not a per-cell Python
    # loop — so blend models scale to many facilities/technologies.
    member = np.zeros((len(ctx.procs), len(ctx.techs), len(gc)))
    for i, p in enumerate(ctx.procs):
        fset = set(ctx.feasible[p])
        for j, k in enumerate(ctx.techs):
            if k not in fset:
                continue
            member_set = prob.technologies[k].grouped_inputs()
            for li, c in enumerate(gc):
                if c in member_set:
                    member[i, j, li] = 1.0
    big = _big_m(prob)
    member_da = xr.DataArray(
        member,
        coords={"process": ctx.procs, "tech": ctx.techs, "commodity": gc},
        dims=["process", "tech", "commodity"],
    )
    m.add_constraints(ctx.fin <= big * member_da, name="finmask")

    # Group sum + share bounds — only over feasible (process, technology) pairs
    # that actually carry a blend group.
    for p in ctx.procs:
        for k in ctx.feasible[p]:
            tech = prob.technologies[k]
            if not tech.share_groups:
                continue
            for t in ctx.years:
                xpkt = ctx.x.sel(process=p, tech=k, period=t)
                for g, members in tech.share_groups.items():
                    req = tech.group_requirement_at(g, t)
                    m.add_constraints(
                        _lin_sum(
                            [ctx.fin.sel(process=p, tech=k, commodity=c, period=t) for c in members]
                        )
                        == req * xpkt,
                        name=f"mix[{p},{k},{g},{t}]",
                    )
                    for c in members:
                        lo, hi = tech.input_share_at(g, c, t)
                        f = ctx.fin.sel(process=p, tech=k, commodity=c, period=t)
                        if lo > 0.0:
                            m.add_constraints(f >= lo * req * xpkt, name=f"mixlo[{p},{k},{c},{t}]")
                        if hi < 1.0:
                            m.add_constraints(f <= hi * req * xpkt, name=f"mixhi[{p},{k},{c},{t}]")


def _output_blend(ctx: BuildContext) -> None:
    """Output slate mix: members sum to the slate requirement; shares bounded.

    The production-side mirror of :func:`_blend`. For each technology output
    slate group ``G`` (members, requirement ``R_G = Σ yield_c``) and throughput
    ``x``::

        Σ_{c∈G} fout_c = R_G · x ;   s_min_c·R_G·x ≤ fout_c ≤ s_max_c·R_G·x

    so a multi-product unit (e.g. a naphtha cracker) can shift its co-product
    slate toward the most valuable mix within its physical flexibility. Slate
    commodities not produced by a technology are pinned to zero.
    """
    if not ctx.grouped_out_comms:
        return
    m, prob = ctx.model, ctx.problem
    go = ctx.grouped_out_comms
    # The slate flow is non-zero only for (process, feasible tech, member
    # commodity); everything else is killed by ONE vectorised bound.
    member = np.zeros((len(ctx.procs), len(ctx.techs), len(go)))
    for i, p in enumerate(ctx.procs):
        fset = set(ctx.feasible[p])
        for j, k in enumerate(ctx.techs):
            if k not in fset:
                continue
            member_set = prob.technologies[k].grouped_outputs()
            for li, c in enumerate(go):
                if c in member_set:
                    member[i, j, li] = 1.0
    big = _big_m(prob)
    member_da = xr.DataArray(
        member,
        coords={"process": ctx.procs, "tech": ctx.techs, "commodity": go},
        dims=["process", "tech", "commodity"],
    )
    m.add_constraints(ctx.fout <= big * member_da, name="foutmask")

    for p in ctx.procs:
        for k in ctx.feasible[p]:
            tech = prob.technologies[k]
            if not tech.output_share_groups:
                continue
            for t in ctx.years:
                xpkt = ctx.x.sel(process=p, tech=k, period=t)
                for g, members in tech.output_share_groups.items():
                    req = tech.output_group_requirement_at(g, t)
                    m.add_constraints(
                        _lin_sum(
                            [
                                ctx.fout.sel(process=p, tech=k, commodity=c, period=t)
                                for c in members
                            ]
                        )
                        == req * xpkt,
                        name=f"slate[{p},{k},{g},{t}]",
                    )
                    for c in members:
                        lo, hi = tech.output_share_at(g, c, t)
                        f = ctx.fout.sel(process=p, tech=k, commodity=c, period=t)
                        if lo > 0.0:
                            m.add_constraints(
                                f >= lo * req * xpkt, name=f"slatelo[{p},{k},{c},{t}]"
                            )
                        if hi < 1.0:
                            m.add_constraints(
                                f <= hi * req * xpkt, name=f"slatehi[{p},{k},{c},{t}]"
                            )


def _efficiency_savings(ctx: BuildContext, p: str, r: str, t: int) -> Any:
    """MACC energy-efficiency savings on commodity ``r`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction_at(t) * ctx.ref_consumption.get((p, r), 0.0) * ctx.z.sel(slot=s.key, period=t)
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
                if not _purchasable(r) or not comm.available(t):
                    # Not purchasable, or outside the stream's availability
                    # window (available_from/available_to).
                    m.add_constraints(
                        ctx.buy.sel(process=p, commodity=r, period=t) == 0,
                        name=f"nobuy[{p},{r},{t}]",
                    )

    # Edge capacities (per-year cap when given).
    for i, e in enumerate(prob.edges):
        for t in ctx.years:
            mf = e.max_flow_at(t)
            if mf is not None:
                m.add_constraints(ctx.flow.sel(edge=i, period=t) <= mf, name=f"emax[{i},{t}]")

    # Demand: cost companies must meet it (slack-softened); profit companies may
    # sell UP TO it (producing less is allowed — revenue handled in the objective).
    for c, q, y in ctx.demand_keys:
        # Demand scope (``c``) may target a facility, a company, a group, or
        # "all" — so demand can be set at any level (facility- vs company-level).
        procs = [p.process_id for p in prob.processes if p.in_scope(c)]
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


def _purchase_caps(ctx: BuildContext) -> None:
    r"""Per-year ceiling on a commodity's total external purchase (volume cap).

    When :attr:`Commodity.max_purchase_by_year` is set for a stream, the total
    bought across every process (or, for a stored stream, the store's external
    purchase) in that year is bounded::

        Σ_p buy[p, r, t] <= max_purchase_r(t)

    Unset commodities/years are unconstrained, so this is inert unless a model
    (or a value-chain ``volume`` link) supplies a cap.
    """
    m, prob = ctx.model, ctx.problem
    stored = {s.commodity_id: s for s in prob.storages}
    stores_of: dict[str, list[Any]] = {}
    for st in prob.storages:
        stores_of.setdefault(st.commodity_id, []).append(st)
    for r in ctx.comms:
        comm = prob.commodities[r]
        if not comm.max_purchase_by_year:
            continue
        for t in ctx.years:
            cap = comm.max_purchase(t)
            if cap is None:
                continue
            if r in stored:
                total = _lin_sum(
                    [ctx.extbuy.sel(store=st.storage_id, period=t) for st in stores_of[r]]
                )
            else:
                total = _lin_sum([ctx.buy.sel(process=p, commodity=r, period=t) for p in ctx.procs])
            if total is not None:
                m.add_constraints(total <= cap, name=f"buycap[{r},{t}]")


def _abatement(ctx: BuildContext, p: str, i: str, t: int) -> Any:
    """MACC emission/environmental abatement of impact ``i`` at ``p`` (LP-safe)."""
    terms = [
        s.reduction_at(t) * ctx.ref_impact.get((p, i), 0.0) * ctx.z.sel(slot=s.key, period=t)
        for s in ctx.slots
        if s.measure_type in (MeasureType.EMISSION_REDUCTION, MeasureType.ENVIRONMENTAL)
        and s.process == p
        and s.target == i
    ]
    return _lin_sum(terms)


def _impacts(ctx: BuildContext) -> None:
    """Define ``emit`` per (process, impact, period) and apply caps (slack-softened)."""
    m, prob = ctx.model, ctx.problem
    proc_by = {p.process_id: p for p in prob.processes}
    for p in ctx.procs:
        for i in ctx.impacts:
            for t in ctx.years:
                terms = []
                for r in ctx.comms:
                    factor = prob.commodity_impact(r, i, t)
                    if factor == 0.0:
                        continue
                    cons = _gross_consumed(ctx, p, r, t)
                    sav = _efficiency_savings(ctx, p, r, t)
                    if cons is not None:
                        terms.append(factor * cons)
                    if sav is not None:
                        terms.append((-factor) * sav)
                # Facility-level direct emission (added on top of the technology's
                # own direct_impact): scales with the facility's throughput across
                # whichever technology it runs.
                dfp = proc_by[p].direct_impact_at(i, t) if p in proc_by else 0.0
                for k in ctx.feasible[p]:
                    df = prob.technologies[k].direct_impact_at(i, t) + dfp
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

    products = {r for r, comm in prob.commodities.items() if comm.kind == CommodityKind.PRODUCT}
    for c, i, y in ctx.cap_keys:
        # A cap scope (``c``) may target a facility id, a company, a group, or
        # "all" — so emissions can be capped at any level.
        procs = [p.process_id for p in prob.processes if p.in_scope(c)]
        total = _lin_sum([ctx.emit.sel(process=p, impact=i, period=y) for p in procs])
        key = f"{c}|{i}|{y}"
        slack = ctx.slk_cap.sel(ckey=key)
        limit = prob.impact_caps[(c, i, y)]
        # An intensity cap is impact per unit product: emit ≤ limit · production.
        # An absolute cap is emit ≤ limit. Production = product output in scope.
        if prob.impact_cap_intensity.get((c, i), False):
            prod_terms = [_produced(ctx, p, r, y) for p in procs for r in products]
            production = _lin_sum([t for t in prod_terms if t is not None])
            cap_rhs: Any = limit * production if production is not None else 0.0
        else:
            cap_rhs = limit
        # A hard cap forbids exceedance (slack pinned to zero); a soft cap allows
        # it at the cap's penalty (applied in the objective). Default: soft.
        soft = prob.impact_cap_soft.get((c, i), True)
        if not soft:
            m.add_constraints(slack == 0, name=f"caphard[{key}]")
        if total is not None:
            m.add_constraints(total - slack <= cap_rhs, name=f"cap[{key}]")


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


def _scope_processes(ctx: BuildContext, scope: str) -> list[str]:
    """Process ids matched by ``scope`` (facility / company / group / ``"all"``)."""
    return [p.process_id for p in ctx.problem.processes if p.in_scope(scope)]


def _transition_index(prob: Problem) -> dict[tuple[str, str], Transition]:
    """Map ``(process_id, target tech)`` → the Transition that enables the switch."""
    out: dict[tuple[str, str], Transition] = {}
    for tr in prob.transitions:
        for proc in prob.processes:
            if tr.from_technology == proc.baseline_technology:
                out[(proc.process_id, tr.to_technology)] = tr
    return out


def _replacement_capex(
    prob: Problem,
    trans_idx: dict[tuple[str, str], Transition],
    process_id: str,
    tech: str,
    capacity: float,
    year: int,
) -> float:
    """Nominal capital cost of switching ``process`` to ``tech`` in ``year``.

    Uses the transition row's (possibly year-varying) ``capex_per_capacity`` when
    one defines the switch, otherwise the target technology's own year-varying
    ``capex``. Nominal (capacity × per-capacity cost); the convention/discount is
    applied by the caller via :meth:`Problem.capex_charge`.
    """
    tr = trans_idx.get((process_id, tech))
    per_cap = tr.capex_at(year) if tr is not None else prob.technologies[tech].capex(year)
    return per_cap * capacity


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
            decay = 1.0 - s.standing_loss_at(t)
            gain = (
                s.charge_efficiency_at(t) * charge_t - (1.0 / s.discharge_efficiency_at(t)) * dis_t
            )
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
            else [
                p.process_id for p in prob.processes if any(p.in_scope(c) for c in scope_companies)
            ]
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
                if not mk.available_in(t):
                    m.add_constraints(
                        ctx.mbuy.sel(cmarket=mk.market_id, period=t) == 0,
                        name=f"mclosedb[{mk.market_id},{t}]",
                    )
                    m.add_constraints(
                        ctx.msell.sel(cmarket=mk.market_id, period=t) == 0,
                        name=f"mcloseds[{mk.market_id},{t}]",
                    )
                    continue
                mb = mk.max_buy_at(t)
                if mb is not None:
                    m.add_constraints(
                        ctx.mbuy.sel(cmarket=mk.market_id, period=t) <= mb,
                        name=f"mmaxbuy[{mk.market_id},{t}]",
                    )
                ms = mk.max_sell_at(t)
                if ms is not None:
                    m.add_constraints(
                        ctx.msell.sel(cmarket=mk.market_id, period=t) <= ms,
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
            mb = mk.max_buy_at(t)
            if mb is not None:
                m.add_constraints(
                    ctx.abuy.sel(imarket=mk.market_id, period=t) <= mb,
                    name=f"etsmaxbuy[{mk.market_id},{t}]",
                )
            ms = mk.max_sell_at(t)
            if ms is not None:
                m.add_constraints(
                    ctx.asell.sel(imarket=mk.market_id, period=t) <= ms,
                    name=f"etsmaxsell[{mk.market_id},{t}]",
                )


def _controls(ctx: BuildContext) -> None:
    """Company decision controls: investment budget cap + minimum production."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    company_of = {p.process_id: p.company for p in prob.processes}
    trans_idx = _transition_index(prob)
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
                cost = _replacement_capex(prob, trans_idx, p, k, cap[p], y)
                if cost:
                    terms.append(cost * ctx.w.sel(process=p, tech=k, period=y))
        for s in ctx.slots:
            if not _in_scope(c, slot_company[s.key]) or not s.capex_at(y):
                continue
            inc = ctx.z.sel(slot=s.key, period=y)
            pt = prev[y]
            if pt is not None:
                inc = inc - ctx.z.sel(slot=s.key, period=pt)
            terms.append(s.capex_at(y) * inc)
        if y == ctx.years[0]:
            for st in prob.storages:
                build_cost = st.capex_per_capacity_at(y)
                if _in_scope(c, st.company) and build_cost:
                    terms.append(build_cost * ctx.cap_built.sel(store=st.storage_id))
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


def _adoption_caps(ctx: BuildContext) -> None:
    r"""Fleet-wide cap on the number of processes running a technology each year.

    For a technology ``k`` with cap ``N_k`` (``Problem.technology_caps``)::

        Σ_p u[p, k, t] ≤ N_k   ∀ t

    i.e. at most ``N_k`` facilities may have ``k`` active in any year — e.g. a
    limited number of greenfield plants of a new route. Inert unless caps are set.
    """
    if not ctx.problem.technology_caps:
        return
    m, prob = ctx.model, ctx.problem
    for k, cap in prob.technology_caps.items():
        if k not in ctx.techs:
            continue
        for t in ctx.years:
            total = _lin_sum(
                [ctx.u.sel(process=p, tech=k, period=t) for p in ctx.procs if k in ctx.feasible[p]]
            )
            if total is not None:
                m.add_constraints(total <= cap, name=f"techcap[{k},{t}]")


def _objective(ctx: BuildContext) -> None:
    """Discounted total system cost + slack penalties (minimise)."""
    m, prob = ctx.model, ctx.problem
    tog = prob.toggles
    prev = _prev(ctx.years)
    dur = {p.year: p.duration_years for p in prob.periods}
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    proc_by_id = {p.process_id: p for p in prob.processes}
    trans_idx = _transition_index(prob)

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
                fox = proc_by_id[p].fixed_opex_at(t)
                if fox:
                    terms.append((w * fox) * ctx.on.sel(process=p, period=t))
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
                st_fox = st.fixed_opex_per_capacity_at(t)
                if st_fox:
                    terms.append((w * st_fox) * ctx.cap_built.sel(store=st.storage_id))
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
        # Replacement capex, charged on the switch-in event under the chosen
        # capex convention (NPV lump by default; annuity over the asset life).
        if tog.capex:
            for p in ctx.procs:
                for k in ctx.feasible[p]:
                    if k == baseline[p]:
                        continue
                    c = _replacement_capex(prob, trans_idx, p, k, cap[p], t)
                    if c:
                        charge = prob.capex_charge(t, prob.technologies[k].lifespan)
                        terms.append((charge * c) * ctx.w.sel(process=p, tech=k, period=t))
        # Renewal capex: rebuilding the active technology at end of life resets
        # its vintage (lifecycle-tracked processes only — ``ren`` is otherwise
        # absent). Charged under the same capex convention as a replacement.
        if tog.renewal and ctx.ren is not None:
            for p in ctx.procs:
                for k in ctx.feasible[p]:
                    rc = prob.technologies[k].renewal(t) * cap[p]
                    if rc:
                        charge = prob.capex_charge(t, prob.technologies[k].lifespan)
                        terms.append((charge * rc) * ctx.ren.sel(process=p, tech=k, period=t))
        # Measure capex on adoption increments (discounted lump).
        if tog.measure_capex and ctx.slots:
            for s in ctx.slots:
                pt = prev[t]
                inc = ctx.z.sel(slot=s.key, period=t)
                if pt is not None:
                    inc = inc - ctx.z.sel(slot=s.key, period=pt)
                if s.capex_at(t):
                    terms.append((df * s.capex_at(t)) * inc)
        # Measure opex while adopted — a recurring O&M cost (discounted ×
        # duration), proportional to the adoption level z, like fixed O&M.
        if tog.opex and ctx.slots:
            for s in ctx.slots:
                if s.opex_at(t):
                    terms.append((w * s.opex_at(t)) * ctx.z.sel(slot=s.key, period=t))

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

    # Storage build capex — one-time, discounted at the first year (year-0 value).
    if tog.capex and prob.storages:
        y0 = ctx.years[0]
        df0 = prob.discount_factor(y0)
        for st in prob.storages:
            build_cost = st.capex_per_capacity_at(y0)
            if build_cost:
                terms.append((df0 * build_cost) * ctx.cap_built.sel(store=st.storage_id))

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
