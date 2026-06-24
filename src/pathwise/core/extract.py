"""Extract a JSON-serialisable result dict from a solved model."""

from __future__ import annotations

from typing import Any

from pathwise.core.entities import Transition
from pathwise.core.problem import leg_key
from pathwise.core.solve import SolveResult

_ON = 0.5
_EPS = 1e-6
#: Backstop on the per-ship disaggregation (huge fleets would otherwise flood the
#: result); realistic models are far smaller. Beyond this, ``vessels`` is truncated.
_MAX_VESSELS = 5000


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
            "fleet": [],
            "vessels": [],
            "transitions": [],
            "renewals": [],
            "measures": [],
            "flows": [],
            "transport": [],
            "trade": [],
            "consumption": [],
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


def macc_result(
    macc: dict[str, Any],
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Result dict for a greedy-MACC backend run.

    Emits the full :func:`empty_result` skeleton (so generic result consumers
    keep working) plus an ``outputs["macc"]`` block and, for charts that read the
    standard summary, the residual emission path under ``summary["impacts"]`` and
    the cumulative-CAPEX path under ``summary["periods"]``. ``objective`` is the
    final-year cumulative CAPEX (total programme cost).

    Args:
        macc: The MACC block (per-year deployment, totals, options).
        terminology: Domain label overrides.
        validation: Validation report.

    Returns:
        pathwise's result dict with ``status="optimal"``.
    """
    out = empty_result("optimal", terminology, validation)
    by_year = macc.get("by_year", [])
    out["objective"] = by_year[-1]["cumulative_capex"] if by_year else None
    out["outputs"]["macc"] = macc
    impact = macc.get("impact_id", "")  # the MACC backend always sets the target impact
    out["summary"]["impacts"] = [
        {"period": r["year"], "impact": impact, "total": r["actual_emissions"]} for r in by_year
    ]
    out["summary"]["periods"] = [
        {"period": r["year"], "cost": r["cumulative_capex"]} for r in by_year
    ]
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
    # Fleet (Layer 1b/1c): carriers assigned to each route, by year, enriched with
    # the route's geography (from/to/mode/distance), the fleet + its fuel, and the
    # fuel burned on it (efficiency × distance × throughput) — "ship operation + fuel
    # by route by company". Fuel/emissions themselves stay plain trade/impact outputs.
    if ctx.units is not None:
        company_of = {p.process_id: p.company for p in prob.processes}
        thru: dict[tuple[str, int], float] = {}
        for (p, _k, t), v in _series(ctx.x).items():
            thru[(p, int(t))] = thru.get((p, int(t)), 0.0) + v
        for (p, t), v in _series(ctx.units).items():
            if v <= _EPS:
                continue
            t = int(t)
            fr = prob.fleet_routes.get(p)
            rt = prob.routes.get(p)
            fl = prob.fleets.get(fr.fleet_id) if fr else None
            row: dict[str, Any] = {
                "process": p,
                "period": t,
                "ships": round(v),
                "company": company_of.get(p),
                "throughput": thru.get((p, t), 0.0),
            }
            if fr:
                row["fleet"] = fr.fleet_id
            if fl and fl.fuel:
                row["fuel"] = fl.fuel
            if rt:
                row["from"] = rt.from_node
                row["to"] = rt.to_node
                row["mode"] = rt.mode
                row["distance"] = rt.distance
                if fl and fl.efficiency > 0:
                    row["fuel_used"] = fl.efficiency * rt.distance * thru.get((p, t), 0.0)
            out["outputs"]["fleet"].append(row)

            # Per-ship disaggregation (Layer 2): split the integer carrier count on
            # this route into named vessels and load them greedily, so the marginal
            # ship's under-utilisation is visible (a deterministic post-solve view —
            # not a stochastic/discrete-event sim, which stays out of scope). Capacity
            # per ship is the route's resolved share, else the fleet's flat capacity.
            cap = fr.share if (fr and fr.share is not None) else (fl.capacity if fl else 0.0)
            n_ships = round(v)
            if cap > 0 and n_ships > 0 and len(out["outputs"]["vessels"]) < _MAX_VESSELS:
                load_total = thru.get((p, t), 0.0)
                full = int(load_total // cap)
                remainder = load_total - full * cap
                for k in range(n_ships):
                    if k < full:
                        load, util = cap, 1.0
                    elif k == full and remainder > _EPS:
                        load, util = remainder, remainder / cap
                    else:
                        load, util = 0.0, 0.0
                    out["outputs"]["vessels"].append(
                        {
                            "vessel": f"{fr.fleet_id if fr else p}#{k + 1}",
                            "fleet": fr.fleet_id if fr else None,
                            "process": p,
                            "period": t,
                            "company": company_of.get(p),
                            "load": load,
                            "capacity": cap,
                            "utilization": util,
                        }
                    )
    # Connection-fleet (Layer 1c+): the carriers the optimiser CHOSE for each
    # physicalised value-chain connection — which candidate fleet won the lane, the
    # cargo it carried and the fuel it burned. Reported into the same fleet table.
    if ctx.cunits is not None:
        cargo = {
            leg_key(cr.process, leg.fleet_id): (cr, leg)
            for cr in prob.connection_routes
            for leg in cr.legs
        }
        legflow = _series(ctx.legflow) if ctx.legflow is not None else {}
        for (lk, t), v in _series(ctx.cunits).items():
            if v <= _EPS or lk not in cargo:
                continue
            cr, leg = cargo[lk]
            fl = prob.fleets.get(leg.fleet_id)
            carried = legflow.get((lk, t), 0.0)
            if carried <= _EPS:
                continue  # idle carriers (degenerate when a fleet has no O&M) — not chosen
            crow: dict[str, Any] = {
                "process": cr.process,
                "period": int(t),
                "ships": round(v),
                "fleet": leg.fleet_id,
                "commodity": cr.commodity,
                "throughput": carried,
                "distance": cr.distance,
            }
            if fl and fl.fuel:
                crow["fuel"] = fl.fuel
                if fl.efficiency > 0:
                    crow["fuel_used"] = fl.efficiency * cr.distance * carried
            out["outputs"]["fleet"].append(crow)

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
            # Transport physics on a tagged edge: freight cost / per-impact emissions
            # / energy borne by the flow (untagged edges are skipped). Emissions are
            # impact-agnostic — a {impact_id: amount} map, no privileged impact.
            if edge.cost or edge.emissions or edge.energy:
                out["outputs"]["transport"].append(
                    {
                        "from": edge.from_process,
                        "to": edge.to_process,
                        "commodity": edge.commodity_id,
                        "period": int(t),
                        "flow": v,
                        "cost": edge.cost * v,
                        "emissions": {i: fac * v for i, fac in edge.emissions.items()},
                        "energy": edge.energy * v,
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
    # Transport-route fuel emissions (fuel_used × commodity_impacts — never hardcoded)
    # join the same totals so reported impacts span the value chain + its transport.
    if ctx.legflow is not None and prob.connection_routes:
        legmap = {
            leg_key(cr.process, leg.fleet_id): (cr, leg)
            for cr in prob.connection_routes
            for leg in cr.legs
        }
        for (lk, t), v in _series(ctx.legflow).items():
            pair = legmap.get(lk)
            if pair is None or v <= _EPS:
                continue
            cr, leg = pair
            fl = prob.fleets.get(leg.fleet_id)
            if fl is None or not fl.fuel:
                continue
            fuel_used = v * fl.efficiency * cr.distance
            for (comm, imp), fac in prob.commodity_impacts.items():
                if comm == fl.fuel and fac:
                    by_period_impact[(int(t), imp)] = (
                        by_period_impact.get((int(t), imp), 0.0) + fuel_used * fac
                    )
    out["summary"]["impacts"] = [
        {"period": t, "impact": i, "total": val} for (t, i), val in sorted(by_period_impact.items())
    ]
    out["summary"]["periods"] = [
        {"period": y, "cost": cost} for y, cost in _period_costs(ctx).items()
    ]
    out["outputs"]["consumption"] = _consumption_detail(ctx)
    out["summary"]["commodity"] = _commodity_summary(ctx)
    return out


def _consumption_detail(ctx: Any) -> list[dict[str, Any]]:
    """Per (process, commodity, year) input consumption — the facility-level
    counterpart of :func:`_commodity_summary` (which aggregates over facilities).

    Consumption is ``Σ_tech throughput · input_intensity`` plus any blend-group
    mix flow, matching how the gross input is formed in the build.
    """
    prob = ctx.problem
    cons: dict[tuple[str, str, int], float] = {}
    for (p, k, t), v in _series(ctx.x).items():
        tech = prob.technologies[k]
        yr = int(t)
        grouped = tech.grouped_inputs()
        for r in set(tech.input_intensity) | set(tech.input_intensity_by_year):
            if r in grouped:
                continue  # blend members counted from the mix flow `fin` below
            cons[(p, r, yr)] = cons.get((p, r, yr), 0.0) + tech.input_intensity_at(r, yr) * v
    if ctx.fin is not None:
        for (p, _k, r, t), v in _series(ctx.fin).items():
            cons[(p, r, int(t))] = cons.get((p, r, int(t)), 0.0) + v
    return [
        {"process": p, "commodity": r, "period": t, "value": val}
        for (p, r, t), val in sorted(cons.items())
        if val > _EPS
    ]


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
    # Freight: per-edge transport cost + the (per-impact) cost of freight emissions on
    # the flow, each priced at its own impact (mirrors the objective so the reported
    # per-year cost reconciles). Impact-agnostic — no hardcoded CO2.
    if any(e.cost or e.emissions for e in prob.edges):
        for (e, t), v in _series(ctx.flow).items():
            edge = prob.edges[int(e)]
            cost[int(t)] += edge.cost * v
            if tog.impact_price:
                for i, fac in edge.emissions.items():
                    if i in prob.impacts:
                        cost[int(t)] += prob.impacts[i].price(int(t)) * fac * v
    if tog.capex:
        for (p, k, t), v in w.items():
            if k != baseline[p] and v > _EPS:
                cost[int(t)] += _repl_capex(p, k, int(t)) * v
        for s in prob.storages:
            cb = cap_built.get(s.storage_id, 0.0)
            cost[years[0]] += s.capex_per_capacity_at(years[0]) * cb
            for t in years:
                cost[t] += s.fixed_opex_per_capacity_at(t) * cb
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
