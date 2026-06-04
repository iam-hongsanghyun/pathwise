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

from linopy import Model

from pathwise.core.entities import CommodityKind, MeasureType
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
    _flow_balance(ctx)
    _impacts(ctx)
    _macc(ctx)
    _objective(ctx)
    return ctx


def _prev(years: list[int]) -> dict[int, int | None]:
    return {y: (years[i - 1] if i > 0 else None) for i, y in enumerate(years)}


def _technology(ctx: BuildContext) -> None:
    """One active technology per process; capacity link; baseline lock; events."""
    m, prob = ctx.model, ctx.problem
    prev = _prev(ctx.years)
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}

    for p in ctx.procs:
        feas = ctx.feasible[p]
        infeasible = [k for k in ctx.techs if k not in feas]
        for t in ctx.years:
            # Exactly one feasible technology is active each period.
            active = _lin_sum([ctx.u.sel(process=p, tech=k, period=t) for k in feas])
            m.add_constraints(active == 1, name=f"one_tech[{p},{t}]")
            for k in feas:
                # Throughput only on the active technology, bounded by capacity.
                m.add_constraints(
                    ctx.x.sel(process=p, tech=k, period=t)
                    <= cap[p] * ctx.u.sel(process=p, tech=k, period=t),
                    name=f"cap[{p},{k},{t}]",
                )
            # Forbid infeasible technologies entirely.
            for k in infeasible:
                m.add_constraints(
                    ctx.u.sel(process=p, tech=k, period=t) == 0, name=f"nofeas_u[{p},{k},{t}]"
                )
                m.add_constraints(
                    ctx.x.sel(process=p, tech=k, period=t) == 0, name=f"nofeas_x[{p},{k},{t}]"
                )
        # Baseline locked in the first period.
        t0 = ctx.years[0]
        m.add_constraints(
            ctx.u.sel(process=p, tech=baseline[p], period=t0) == 1, name=f"baseline[{p}]"
        )
        # Transition (replace) event detection: w >= u_t - u_prev.
        for k in feas:
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
        for k in [k for k in ctx.techs if k not in feas]:
            for t in ctx.years:
                m.add_constraints(
                    ctx.w.sel(process=p, tech=k, period=t) == 0, name=f"wnofeas[{p},{k},{t}]"
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
    """Gross input of commodity ``r`` at ``p`` (before efficiency savings)."""
    terms = [
        ctx.problem.technologies[k].input_intensity.get(r, 0.0)
        * ctx.x.sel(process=p, tech=k, period=t)
        for k in ctx.feasible[p]
        if ctx.problem.technologies[k].input_intensity.get(r, 0.0) != 0.0
    ]
    return _lin_sum(terms)


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

    def _purchasable(r: str) -> bool:
        c = prob.commodities[r]
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
                if not comm.sellable:
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

    # Demand (slack-softened): Σ deliver over company processes + slack >= demand.
    for c, q, y in ctx.demand_keys:
        procs = [p.process_id for p in prob.processes if c == "all" or p.company == c]
        delivered = _lin_sum([ctx.deliver.sel(process=p, commodity=q, period=y) for p in procs])
        key = f"{c}|{q}|{y}"
        slack = ctx.slk_dem.sel(dkey=key)
        rhs = prob.demand[(c, q, y)]
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


def _objective(ctx: BuildContext) -> None:
    """Discounted total system cost + slack penalties (minimise)."""
    m, prob = ctx.model, ctx.problem
    tog = prob.toggles
    prev = _prev(ctx.years)
    dur = {p.year: p.duration_years for p in prob.periods}
    cap = {p.process_id: p.capacity for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}

    # Replacement capex per (process, target tech) = capacity × transition cost.
    trans_cost: dict[tuple[str, str], float] = {}
    for tr in prob.transitions:
        for proc in prob.processes:
            if tr.from_technology == proc.baseline_technology:
                trans_cost[(proc.process_id, tr.to_technology)] = (
                    tr.capex_per_capacity * proc.capacity
                )

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
            if tog.commodity_cost:
                for r in ctx.comms:
                    price = prob.commodities[r].price(t)
                    sale = prob.commodities[r].sale_price(t)
                    if price:
                        terms.append((w * price) * ctx.buy.sel(process=p, commodity=r, period=t))
                    if sale:
                        terms.append((-w * sale) * ctx.sell.sel(process=p, commodity=r, period=t))
            if tog.impact_price:
                for i in ctx.impacts:
                    pr = prob.impacts[i].price(t)
                    if pr:
                        terms.append((w * pr) * ctx.emit.sel(process=p, impact=i, period=t))
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

    # Slack penalties (keep the model well-posed and diagnosable).
    if ctx.demand_keys:
        terms.append(prob.slack_penalty * ctx.slk_dem.sum())
    if ctx.cap_keys:
        terms.append(prob.slack_penalty * ctx.slk_cap.sum())

    obj = _lin_sum(terms)
    if obj is not None:
        m.add_objective(obj)
