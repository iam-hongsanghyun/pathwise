"""Extract a JSON-serialisable result dict from a solved model."""

from __future__ import annotations

from typing import Any

from pathwise.core.entities import Transition
from pathwise.core.solve import SolveResult

_ON = 0.5
_EPS = 1e-6


def _series(var: Any) -> dict[Any, float]:
    """Return ``{index: value}`` for a solved variable (NaN dropped)."""
    if var is None:
        return {}
    s = var.solution.to_series().dropna()
    return {idx: float(v) for idx, v in s.items()}


def empty_result(
    status: str,
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Result dict with no decisions (e.g. an ``invalid`` run)."""
    return {
        "status": status,
        "termination": status,
        "objective": None,
        "terminology": terminology or {},
        "validation": validation or {"errors": [], "warnings": []},
        "outputs": {
            "technology": [],
            "throughput": [],
            "transitions": [],
            "renewals": [],
            "measures": [],
            "flows": [],
            "trade": [],
            "storage": [],
            "markets": [],
            "ets": [],
            "demand_slack": [],
        },
        "summary": {"periods": [], "impacts": [], "commodity": []},
    }


def portfolio_result(
    portfolio: dict[str, Any],
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Result dict for a portfolio-backend run.

    Emits the full :func:`empty_result` skeleton (so result consumers that read
    ``outputs.throughput`` etc. never break) plus an ``outputs["portfolio"]``
    block and the chosen risk-adjusted score as ``objective``.

    Args:
        portfolio: The portfolio block (weights, frontier, distribution, …).
        terminology: Domain label overrides.
        validation: Validation report.

    Returns:
        pathwise's result dict with ``status="optimal"``.
    """
    out = empty_result("optimal", terminology, validation)
    out["objective"] = portfolio.get("objective")
    out["outputs"]["portfolio"] = portfolio
    return out


def extract_results(
    result: SolveResult,
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build the result dict from a :class:`SolveResult`."""
    out = empty_result(result.status.value, terminology, validation)
    out["termination"] = result.termination
    out["objective"] = result.objective
    if not result.ok:
        return out

    ctx = result.context
    prob = ctx.problem

    for (p, k, t), v in _series(ctx.u).items():
        if v > _ON:
            out["outputs"]["technology"].append({"process": p, "technology": k, "period": int(t)})
    for (p, k, t), v in _series(ctx.x).items():
        if v > _EPS:
            out["outputs"]["throughput"].append(
                {"process": p, "technology": k, "period": int(t), "value": v}
            )
    # A real transition is a switch INTO a non-baseline technology; the event
    # variable on a facility's own baseline carries no cost, so the solver may
    # leave it at 1 — exclude those.
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    for (p, k, t), v in _series(ctx.w).items():
        if v > _ON and k != baseline.get(p):
            out["outputs"]["transitions"].append(
                {"process": p, "to_technology": k, "period": int(t)}
            )
    # Renewals: rebuilding the active technology at end of life (lifecycle models).
    for (p, k, t), v in _series(ctx.ren).items():
        if v > _ON:
            out["outputs"]["renewals"].append({"process": p, "technology": k, "period": int(t)})
    slot_by_key = {s.key: s for s in ctx.slots}
    for (key, t), v in _series(ctx.z).items():
        if v > _EPS:
            s = slot_by_key.get(key)
            out["outputs"]["measures"].append(
                {
                    "process": s.process if s else None,
                    "measure": s.measure_id if s else key,
                    "type": s.measure_type.value if s else None,
                    "period": int(t),
                    "adoption": v,
                }
            )
    for (e, t), v in _series(ctx.flow).items():
        if v > _EPS:
            edge = prob.edges[int(e)]
            out["outputs"]["flows"].append(
                {
                    "from": edge.from_process,
                    "to": edge.to_process,
                    "commodity": edge.commodity_id,
                    "period": int(t),
                    "value": v,
                }
            )
    for (p, r, t), v in _series(ctx.buy).items():
        if v > _EPS:
            out["outputs"]["trade"].append(
                {"process": p, "commodity": r, "period": int(t), "kind": "buy", "value": v}
            )
    for (p, r, t), v in _series(ctx.sell).items():
        if v > _EPS:
            out["outputs"]["trade"].append(
                {"process": p, "commodity": r, "period": int(t), "kind": "sell", "value": v}
            )
    # Storage: built capacity + per-period level/charge/discharge.
    built = _series(ctx.cap_built)
    level = _series(ctx.level)
    charge = _series(ctx.charge)
    discharge = _series(ctx.discharge)
    commodity_of = {s.storage_id: s.commodity_id for s in prob.storages}
    for sid, capv in built.items():
        if capv <= _EPS:
            continue
        out["outputs"]["storage"].append(
            {
                "storage": str(sid),
                "commodity": commodity_of.get(str(sid)),
                "capacity": capv,
                "by_period": [
                    {
                        "period": int(t),
                        "level": level.get((sid, t), 0.0),
                        "charge": charge.get((sid, t), 0.0),
                        "discharge": discharge.get((sid, t), 0.0),
                    }
                    for t in prob.years
                ],
            }
        )

    # Commodity markets: buy/sell per period.
    mbuy, msell = _series(ctx.mbuy), _series(ctx.msell)
    for mk in ctx.cmarkets:
        rows = [
            {
                "period": int(t),
                "buy": mbuy.get((mk.market_id, t), 0.0),
                "sell": msell.get((mk.market_id, t), 0.0),
            }
            for t in prob.years
        ]
        if any(r["buy"] > _EPS or r["sell"] > _EPS for r in rows):
            out["outputs"]["markets"].append(
                {"market": mk.market_id, "commodity": mk.target, "tag": mk.tag, "by_period": rows}
            )

    # ETS allowance markets: bought (deficit) / sold (surplus) per period.
    abuy, asell = _series(ctx.abuy), _series(ctx.asell)
    for mk in ctx.imarkets:
        rows = [
            {
                "period": int(t),
                "bought": abuy.get((mk.market_id, t), 0.0),
                "sold": asell.get((mk.market_id, t), 0.0),
            }
            for t in prob.years
        ]
        out["outputs"]["ets"].append(
            {"market": mk.market_id, "impact": mk.target, "by_period": rows}
        )

    for key, v in _series(ctx.slk_dem).items():
        if v > _EPS:
            out["outputs"]["demand_slack"].append({"key": str(key), "value": v})

    # Per-period impact totals.
    emit = _series(ctx.emit)
    by_period_impact: dict[tuple[int, str], float] = {}
    for (_p, i, t), v in emit.items():
        by_period_impact[(int(t), i)] = by_period_impact.get((int(t), i), 0.0) + v
    out["summary"]["impacts"] = [
        {"period": t, "impact": i, "total": val} for (t, i), val in sorted(by_period_impact.items())
    ]
    out["summary"]["periods"] = [
        {"period": y, "cost": cost} for y, cost in _period_costs(ctx).items()
    ]
    out["summary"]["commodity"] = _commodity_summary(ctx)
    return out


def _period_costs(ctx: Any) -> dict[int, float]:
    """Nominal cost per year (operational + that year's capex) for time-series."""
    prob = ctx.problem
    tog = prob.toggles
    years = prob.years
    prev = {y: (years[i - 1] if i > 0 else None) for i, y in enumerate(years)}
    cost: dict[int, float] = dict.fromkeys(years, 0.0)

    x, buy, sell, emit, on = (
        _series(ctx.x),
        _series(ctx.buy),
        _series(ctx.sell),
        _series(ctx.emit),
        _series(ctx.on),
    )
    w, z, ren = _series(ctx.w), _series(ctx.z), _series(ctx.ren)
    mbuy, msell, abuy, asell = (
        _series(ctx.mbuy),
        _series(ctx.msell),
        _series(ctx.abuy),
        _series(ctx.asell),
    )
    cap_built, extbuy = _series(ctx.cap_built), _series(ctx.extbuy)
    stored = {s.commodity_id for s in prob.storages}
    market_comms = {m.target for m in ctx.cmarkets}
    ets_impacts = {m.target for m in ctx.imarkets}
    proc_by_id = {p.process_id: p for p in prob.processes}
    baseline = {p.process_id: p.baseline_technology for p in prob.processes}
    cap = {p.process_id: p.capacity for p in prob.processes}
    smap = {s.storage_id: s for s in prob.storages}
    cmap = {m.market_id: m for m in ctx.cmarkets}
    imap = {m.market_id: m for m in ctx.imarkets}
    # (process, target tech) → its enabling transition, for year-varying capex.
    trans_idx: dict[tuple[str, str], Transition] = {}
    for tr in prob.transitions:
        for pr in prob.processes:
            if tr.from_technology == pr.baseline_technology:
                trans_idx[(pr.process_id, tr.to_technology)] = tr

    def _repl_capex(p: str, k: str, year: int) -> float:
        tr = trans_idx.get((p, k))
        per_cap = tr.capex_at(year) if tr is not None else prob.technologies[k].capex(year)
        return float(per_cap * cap[p])

    if tog.opex:
        for (_p, k, t), v in x.items():
            cost[int(t)] += prob.technologies[k].opex(int(t)) * v
        for (p, t), v in on.items():
            fox = proc_by_id[p].fixed_opex_at(int(t))
            if fox:
                cost[int(t)] += fox * v
    if tog.commodity_cost:
        for (_p, r, t), v in buy.items():
            if r not in stored and r not in market_comms:
                cost[int(t)] += prob.commodities[r].price(int(t)) * v
        for (_p, r, t), v in sell.items():
            if r not in stored and r not in market_comms:
                cost[int(t)] -= prob.commodities[r].sale_price(int(t)) * v
        for (sid, t), v in extbuy.items():
            s = smap[sid]
            if s.commodity_id not in market_comms:
                cost[int(t)] += prob.commodities[s.commodity_id].price(int(t)) * v
        for (mid, t), v in mbuy.items():
            cost[int(t)] += cmap[mid].price(int(t)) * v
        for (mid, t), v in msell.items():
            cost[int(t)] -= cmap[mid].sell_price(int(t)) * v
    if tog.impact_price:
        for (_p, i, t), v in emit.items():
            if i not in ets_impacts:
                cost[int(t)] += prob.impacts[i].price(int(t)) * v
        for (mid, t), v in abuy.items():
            cost[int(t)] += imap[mid].price(int(t)) * v
        for (mid, t), v in asell.items():
            cost[int(t)] -= imap[mid].sell_price(int(t)) * v
    if tog.capex:
        for (p, k, t), v in w.items():
            if k != baseline[p] and v > _EPS:
                cost[int(t)] += _repl_capex(p, k, int(t)) * v
        for s in prob.storages:
            cb = cap_built.get(s.storage_id, 0.0)
            cost[years[0]] += s.capex_per_capacity * cb
            for t in years:
                cost[t] += s.fixed_opex_per_capacity * cb
    if tog.renewal and ren:
        for (p, k, t), v in ren.items():
            if v > _EPS:
                cost[int(t)] += prob.technologies[k].renewal(int(t)) * cap[p] * v
    if tog.measure_capex:
        slot_by_key = {sl.key: sl for sl in ctx.slots}
        for (key, t), v in z.items():
            sl = slot_by_key.get(key)
            if sl is None or not sl.capex_at(int(t)):
                continue
            pt = prev[int(t)]
            inc = v - (z.get((key, pt), 0.0) if pt is not None else 0.0)
            cost[int(t)] += sl.capex_at(int(t)) * inc
    if tog.opex and ctx.slots:
        slot_by_key = {sl.key: sl for sl in ctx.slots}
        for (key, t), v in z.items():
            sl = slot_by_key.get(key)
            if sl is not None and sl.opex_at(int(t)):
                cost[int(t)] += sl.opex_at(int(t)) * v
    return cost


def _commodity_summary(ctx: Any) -> list[dict[str, Any]]:
    """Per (commodity, year) gross consumed and produced — for the line chart."""
    prob = ctx.problem
    x = _series(ctx.x)
    cons: dict[tuple[str, int], float] = {}
    prod: dict[tuple[str, int], float] = {}
    for (_p, k, t), v in x.items():
        tech = prob.technologies[k]
        yr = int(t)
        grouped = tech.grouped_inputs()
        grouped_out = tech.grouped_outputs()
        # Union of scalar + year-varying ids, evaluated at the period (handles a
        # coefficient supplied only as a trajectory).
        for r in set(tech.input_intensity) | set(tech.input_intensity_by_year):
            if r in grouped:
                continue  # blend members counted from the mix flow `fin` below
            cons[(r, yr)] = cons.get((r, yr), 0.0) + tech.input_intensity_at(r, yr) * v
        for r in set(tech.output_yield) | set(tech.output_yield_by_year):
            if r in grouped_out:
                continue  # slate members counted from the slate flow `fout` below
            prod[(r, yr)] = prod.get((r, yr), 0.0) + tech.output_yield_at(r, yr) * v
    if ctx.fin is not None:
        for (_p, _k, r, t), v in _series(ctx.fin).items():
            cons[(r, int(t))] = cons.get((r, int(t)), 0.0) + v
    if ctx.fout is not None:
        for (_p, _k, r, t), v in _series(ctx.fout).items():
            prod[(r, int(t))] = prod.get((r, int(t)), 0.0) + v
    keys = sorted(set(cons) | set(prod))
    return [
        {
            "commodity": r,
            "period": t,
            "consumed": cons.get((r, t), 0.0),
            "produced": prod.get((r, t), 0.0),
        }
        for (r, t) in keys
    ]
