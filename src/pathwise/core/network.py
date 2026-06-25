"""Cascade orchestrator for network optimisation (cost-based, forward).

Solve each stage with the ordinary single-model pipeline
(``assemble_problem → build → solve → extract_results``) in upstream→downstream
order. After an upstream stage solves, derive a per-year **price** for each
coupled flow and inject it — shifted by the link's time lag — into the
downstream stage's price trajectory *before* that stage is assembled and solved.
So a policy on an upstream stage (e.g. a carbon price on electricity) raises the
price the downstream stage pays, and the downstream optimiser re-chooses its
pathway accordingly.

Algorithm:
    For a link u→d on flow c with lag L, the transferred price in year t is
    the upstream stage's average unit cost of c:

    $$ p_d(t+L) \\;=\\; \\frac{\\text{Cost}_u(t)}{\\text{Prod}_{u,c}(t)} $$

    ASCII: price_d[t+L] = upstream_cost[t] / upstream_production_of_c[t]

    where ``Cost_u(t)`` is the upstream stage's total cost in year ``t``
    (``summary.periods``) and ``Prod_{u,c}(t)`` its production of ``c``
    (``summary.flow``). The shifted points are interpolated onto the
    downstream horizon (linear, flat-hold beyond the ends).

This is an **average-cost proxy** (exact when the upstream stage makes a single
product; an over-allocation for multi-product stages — a true marginal/transfer
price needs LP duals, a later phase). It is purely primal, so it needs no engine
change. Forward-only: downstream demand does not feed back upstream yet.

Units: price [currency / flow-unit]; cost [currency / yr]; production
[flow-unit / yr].
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from pathwise.core.build import build
from pathwise.core.extract import extract_results
from pathwise.core.solve import options_from_scenario, solve
from pathwise.data.assemble import assemble_problem
from pathwise.data.network import NetworkSpec
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.sheets import (
    DEMAND,
    FLOW_IMPACTS_T,
    FLOWS_T_MAX_PURCHASE,
    FLOWS_T_PRICE,
)
from pathwise.data.trajectory import interpolate
from pathwise.data.workbook import Workbook, default_impact

_EPS = 1e-9
_TOL = 1e-3  # relative convergence tolerance for the feedback fixed point


def run_network(
    spec: NetworkSpec,
    workbooks: dict[str, Workbook],
    scenario: ScenarioConfig | None = None,
    iterations: int = 1,
    damping: float = 0.5,
    forced_switches: dict[str, tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Solve a network as a cascade of coupled stages.

    A forward pass solves each stage upstream→downstream, injecting the upstream
    price / carbon-intensity signals (lagged) into the downstream inputs. With
    ``iterations > 1`` and ``feedback`` links present, downstream consumption of
    the coupled flow is fed back as the upstream stage's demand and the pass
    repeats (Gauss–Seidel) until the feedback demand converges — damped to avoid
    oscillation.

    Args:
        spec: The network definition (stages + coupling links).
        workbooks: ``{stage_id: workbook}`` — every stage in ``spec`` must have
            a resolved workbook (the caller does the I/O; this stays pure).
        scenario: Base run scenario; per-stage ``scenario`` overrides are
            deep-merged onto it. Defaults to ``ScenarioConfig()``.
        iterations: Max forward passes. ``1`` = forward-only (no feedback).
        damping: Relaxation on the fed-back demand, ``0 < damping ≤ 1`` — a new
            demand is ``(1-damping)·old + damping·observed``.

    Returns:
        ``{"status", "stages": {id: result}, "couplings": [...], "iterations": n}``
        — each stage's standard :func:`extract_results` dict plus the trajectories
        that flowed between stages (for inspection / UI overlay).

    Raises:
        KeyError: If a stage in ``spec`` has no workbook in ``workbooks``.
    """
    base = scenario or ScenarioConfig()
    wbs: dict[str, Workbook] = {s.id: copy.deepcopy(workbooks[s.id]) for s in spec.stages}
    feedback = [link for link in spec.active_links() if link.feedback]

    results: dict[str, dict[str, Any]] = {}
    couplings: list[dict[str, Any]] = []
    prev: dict[tuple[str, str, int], float] = {}
    passes = 0
    for it in range(max(1, iterations)):
        results, couplings = _forward_pass(spec, wbs, base, forced_switches)
        passes = it + 1
        if not feedback:
            break
        observed = _feedback_demands(spec, wbs, results, feedback)
        damped = {k: (1 - damping) * prev.get(k, v) + damping * v for k, v in observed.items()}
        change = max(
            (abs(damped[k] - prev.get(k, 0.0)) / max(abs(damped[k]), 1.0) for k in damped),
            default=0.0,
        )
        _apply_feedback_demands(spec, wbs, damped)
        prev = damped
        if it >= 1 and change < _TOL:
            break

    out: dict[str, Any] = {
        "status": _overall_status(results),
        "stages": results,
        "couplings": couplings,
    }
    if feedback:
        out["iterations"] = passes
    return out


def sweep_value_chain(
    spec: NetworkSpec,
    draws: list[dict[str, Workbook]],
    scenario: ScenarioConfig | None = None,
    *,
    iterations: int = 1,
    damping: float = 0.5,
) -> dict[str, Any]:
    """Run the network over an ensemble of workbook draws (uncertainty).

    Each draw is a full ``{stage_id: workbook}`` variant — e.g. the same chain
    with a different upstream carbon-price trajectory — so the caller expresses
    whatever uncertainty matters (policy, prices, demand). The result holds every
    run plus, per stage, the distribution (min / mean / max / p10 / p90) of total
    cost and total CO2 across the draws — i.e. how upstream uncertainty spreads
    into each stage's outcomes.

    Args:
        spec: The network definition.
        draws: One ``{stage_id: workbook}`` per ensemble member.
        scenario: Base scenario applied to every draw.
        iterations: Forward passes per run (feedback fixed point).
        damping: Feedback relaxation per run.

    Returns:
        ``{"runs": [...], "distribution": {stage: {"cost": {...}, "co2": {...}}}}``.
    """
    runs = [
        run_network(spec, wbs, scenario, iterations=iterations, damping=damping) for wbs in draws
    ]
    return {"runs": runs, "distribution": _distribution(spec, runs)}


def _distribution(spec: NetworkSpec, runs: list[dict[str, Any]]) -> dict[str, Any]:
    # The chain's headline impact (impact-agnostic): the first coupling link that
    # names one, else the first impact any run reports — never a hardcoded CO2.
    primary = next((lnk.impact for lnk in spec.links if lnk.impact), "")
    if not primary:
        primary = next(
            (
                str(r["impact"])
                for run in runs
                for st in run.get("stages", {}).values()
                for r in st.get("summary", {}).get("impacts", [])
                if r.get("impact")
            ),
            "",
        )
    out: dict[str, Any] = {}
    for sid in (s.id for s in spec.stages):
        present = [run for run in runs if sid in run.get("stages", {})]
        costs = [
            sum(float(r["cost"]) for r in run["stages"][sid].get("summary", {}).get("periods", []))
            for run in present
        ]
        emissions = [
            sum(
                float(r.get("total") or 0.0)
                for r in run["stages"][sid].get("summary", {}).get("impacts", [])
                if str(r.get("impact")) == primary
            )
            for run in present
        ]
        out[sid] = {"cost": _stats(costs), "impact": primary, "emissions": _stats(emissions)}
    return out


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    arr = np.asarray(values, dtype=float)
    return {
        "min": float(arr.min()),
        "mean": float(arr.mean()),
        "max": float(arr.max()),
        "p10": float(np.percentile(arr, 10)),
        "p90": float(np.percentile(arr, 90)),
    }


def _forward_pass(
    spec: NetworkSpec,
    wbs: dict[str, Workbook],
    base: ScenarioConfig,
    forced: dict[str, tuple[str, int]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """One upstream→downstream solve, injecting price/CI signals as it goes.

    ``forced`` pins technology switches (``{process: (to_tech, year)}``, a selected
    variant) on every stage's problem — keys for processes not in a stage are simply
    inert, so a model-wide pin reaches whichever stage owns each asset.
    """
    results: dict[str, dict[str, Any]] = {}
    couplings: list[dict[str, Any]] = []
    by_source = _links_by_source(spec)
    for sid in spec.order():
        sc = _stage_scenario(base, spec.stage(sid).scenario)
        prob = assemble_problem(wbs[sid], sc)
        if forced:
            prob.forced_switches = dict(forced)
        results[sid] = extract_results(solve(build(prob), options_from_scenario(sc)))
        for link in by_source.get(sid, []):
            target_years = _years(wbs[link.to_stage])
            # marginal_price (finite-difference) takes precedence over the
            # average-cost price proxy when both are requested.
            if "marginal_price" in link.signals:
                sc = _stage_scenario(base, spec.stage(sid).scenario)
                mp = marginal_price(wbs[sid], sc, link.flow)
                shifted = _shift(mp, link.lag_years, target_years)
                if shifted:
                    _inject_price(wbs[link.to_stage], link.flow, shifted)
                    couplings.append(_record(sid, link, "marginal_price", shifted))
            elif "price" in link.signals:
                shifted = _shift(
                    _price_signal(results[sid], link.flow), link.lag_years, target_years
                )
                if shifted:
                    _inject_price(wbs[link.to_stage], link.flow, shifted)
                    couplings.append(_record(sid, link, "price", shifted))
            if "carbon_intensity" in link.signals:
                # Impact-agnostic: an unset link impact resolves to the upstream
                # model's first declared impact (never a hardcoded CO2).
                imp = link.impact or default_impact(wbs[sid])
                shifted = _shift(
                    _ci_signal(results[sid], link.flow, imp),
                    link.lag_years,
                    target_years,
                )
                if shifted:
                    _inject_ci(wbs[link.to_stage], link.flow, imp, shifted)
                    couplings.append(_record(sid, link, "carbon_intensity", shifted, imp))
            if "volume" in link.signals:
                shifted = _shift(
                    _volume_signal(results[sid], link.flow), link.lag_years, target_years
                )
                if shifted:
                    _inject_volume(wbs[link.to_stage], link.flow, shifted)
                    couplings.append(_record(sid, link, "volume", shifted))
    return results, couplings


# ── helpers ──────────────────────────────────────────────────────────────────


def _links_by_source(spec: NetworkSpec) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for link in spec.active_links():
        out.setdefault(link.from_stage, []).append(link)
    return out


def _years(wb: Workbook) -> list[int]:
    return sorted(int(r["year"]) for r in wb.get("periods", []) if r.get("year") is not None)


def _record(
    from_stage: str, link: Any, signal: str, by_year: dict[int, float], impact: str = ""
) -> dict[str, Any]:
    rec = {
        "from_stage": from_stage,
        "to_stage": link.to_stage,
        "flow": link.flow,
        "signal": signal,
        "lag_years": link.lag_years,
        "by_year": [{"year": y, "value": v} for y, v in sorted(by_year.items())],
    }
    if signal == "carbon_intensity":
        rec["impact"] = impact or link.impact
    return rec


def _price_signal(result: dict[str, Any], flow: str) -> dict[int, float]:
    """Upstream average unit cost of ``flow`` per year (the transfer price)."""
    summary = result.get("summary", {})
    cost = {int(r["period"]): float(r["cost"]) for r in summary.get("periods", [])}
    out: dict[int, float] = {}
    for r in summary.get("flow", []):
        if str(r.get("flow")) != flow:
            continue
        y = int(r["period"])
        produced = float(r.get("produced") or 0.0)
        if produced > _EPS and y in cost:
            out[y] = cost[y] / produced
    return out


def marginal_price(wb: Workbook, scenario: ScenarioConfig, flow: str) -> dict[int, float]:
    """True marginal cost of one more unit of ``flow`` per year (transfer price).

    Re-solves the stage with its demand for ``flow`` bumped by a small ε in
    each year; ``Δobjective / ε`` (un-discounted) is the marginal cost of delivery
    that year — unlike the average-cost proxy it reflects scarcity / binding
    capacity. Costs O(years) extra solves. Returns ``{}`` if the flow has no
    demand row to perturb or a solve is non-optimal.
    """
    prob = assemble_problem(wb, scenario)
    opts = options_from_scenario(scenario)
    base = solve(build(prob), opts)
    if base.objective is None:
        return {}
    duration = {p.year: p.duration_years for p in prob.periods}
    company = _upstream_company(wb, flow)
    rows = wb.get("demand", [])
    present = {
        y
        for y in prob.years
        if any(
            str(r.get("company")) == company
            and str(r.get("flow_id")) == flow
            and _as_int(r.get("year")) == y
            for r in rows
        )
    }
    out: dict[int, float] = {}
    eps = 1.0
    for y in sorted(present):
        weight = prob.discount_factor(y) * (duration.get(y, 1.0) or 1.0)
        if weight <= 0:
            continue
        wb2 = copy.deepcopy(wb)
        for r in wb2["demand"]:
            if (
                str(r.get("company")) == company
                and str(r.get("flow_id")) == flow
                and _as_int(r.get("year")) == y
            ):
                r["amount"] = float(r.get("amount") or 0.0) + eps
        bumped = solve(build(assemble_problem(wb2, scenario)), opts)
        if bumped.objective is None:
            continue
        out[y] = (bumped.objective - base.objective) / eps / weight
    return out


def _ci_signal(result: dict[str, Any], flow: str, impact: str) -> dict[int, float]:
    """Upstream carbon intensity of ``flow`` per year = emissions / production.

    Emissions attributable to the flow are taken as the stage's total of
    ``impact`` that year (exact when the stage makes a single product; an
    over-allocation for multi-product stages — documented).
    """
    summary = result.get("summary", {})
    total = {
        int(r["period"]): float(r.get("total") or 0.0)
        for r in summary.get("impacts", [])
        if str(r.get("impact")) == impact
    }
    out: dict[int, float] = {}
    for r in summary.get("flow", []):
        if str(r.get("flow")) != flow:
            continue
        y = int(r["period"])
        produced = float(r.get("produced") or 0.0)
        if produced > _EPS and y in total:
            out[y] = total[y] / produced
    return out


def _volume_signal(result: dict[str, Any], flow: str) -> dict[int, float]:
    """Upstream production volume of ``flow`` per year [unit / yr].

    The volume an upstream stage actually produces is the supply available to a
    downstream stage; injected as a per-year cap on the downstream stage's
    external purchase of the flow.
    """
    out: dict[int, float] = {}
    for r in result.get("summary", {}).get("flow", []):
        if str(r.get("flow")) != flow:
            continue
        out[int(r["period"])] = float(r.get("produced") or 0.0)
    return out


def _shift(signal: dict[int, float], lag: int, target_years: list[int]) -> dict[int, float]:
    """Shift a year→price signal forward by ``lag`` and interpolate onto target years."""
    if not signal or not target_years:
        return {}
    shifted = {y + lag: v for y, v in signal.items()}
    return interpolate(shifted, target_years)


def _inject_price(wb: Workbook, flow: str, by_year: dict[int, float]) -> None:
    """Upsert a per-year price column for ``flow`` into ``flows_t__price``."""
    rows = wb.setdefault(FLOWS_T_PRICE, [])
    index = {int(r["year"]): r for r in rows if r.get("year") is not None}
    for y, v in by_year.items():
        if y in index:
            index[y][flow] = v
        else:
            row: dict[str, Any] = {"year": y, flow: v}
            rows.append(row)
            index[y] = row


def _inject_volume(wb: Workbook, flow: str, by_year: dict[int, float]) -> None:
    """Upsert a per-year purchase cap for ``flow`` into ``flows_t__max_purchase``."""
    rows = wb.setdefault(FLOWS_T_MAX_PURCHASE, [])
    index = {int(r["year"]): r for r in rows if r.get("year") is not None}
    for y, v in by_year.items():
        if y in index:
            index[y][flow] = v
        else:
            row: dict[str, Any] = {"year": y, flow: v}
            rows.append(row)
            index[y] = row


def _feedback_demands(
    spec: NetworkSpec,
    wbs: dict[str, Workbook],
    results: dict[str, dict[str, Any]],
    feedback_links: list[Any],
) -> dict[tuple[str, str, int], float]:
    """Downstream consumption of each fed-back flow → upstream demand target."""
    out: dict[tuple[str, str, int], float] = {}
    for link in feedback_links:
        for r in results.get(link.to_stage, {}).get("summary", {}).get("flow", []):
            if str(r.get("flow")) != link.flow:
                continue
            key = (link.from_stage, link.flow, int(r["period"]))
            out[key] = out.get(key, 0.0) + float(r.get("consumed") or 0.0)
    return out


def _apply_feedback_demands(
    spec: NetworkSpec, wbs: dict[str, Workbook], demands: dict[tuple[str, str, int], float]
) -> None:
    """Upsert fed-back demand onto the upstream stages' demand sheets."""
    for (stage_id, flow, year), amount in demands.items():
        wb = wbs[stage_id]
        company = _upstream_company(wb, flow)
        rows = wb.setdefault(DEMAND, [])
        for r in rows:
            if (
                str(r.get("company")) == company
                and str(r.get("flow_id")) == flow
                and _as_int(r.get("year")) == year
            ):
                r["amount"] = amount
                break
        else:
            rows.append({"company": company, "flow_id": flow, "year": year, "amount": amount})


def _upstream_company(wb: Workbook, flow: str) -> str:
    """The company whose demand for ``flow`` the feedback should drive."""
    for r in wb.get("demand", []):
        if str(r.get("flow_id")) == flow:
            return str(r.get("company"))
    producers = {
        str(r.get("technology_id"))
        for r in wb.get("io", [])
        if str(r.get("target")) == flow and str(r.get("role")) == "output"
    }
    for p in wb.get("processes", []):
        if str(p.get("baseline_technology")) in producers:
            return str(p.get("company"))
    procs = wb.get("processes", [])
    return str(procs[0].get("company")) if procs else "all"


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _inject_ci(wb: Workbook, flow: str, impact: str, by_year: dict[int, float]) -> None:
    """Upsert per-year carbon-intensity rows for ``flow`` into ``flow_impacts_t``."""
    rows = wb.setdefault(FLOW_IMPACTS_T, [])
    index = {
        (str(r.get("flow_id")), str(r.get("impact_id")), int(r["year"])): r
        for r in rows
        if r.get("year") is not None
    }
    for y, v in by_year.items():
        key = (flow, impact, y)
        if key in index:
            index[key]["factor"] = v
        else:
            rows.append({"flow_id": flow, "impact_id": impact, "year": y, "factor": v})


def _stage_scenario(base: ScenarioConfig, overrides: dict[str, Any]) -> ScenarioConfig:
    if not overrides:
        return base
    return ScenarioConfig.from_dict(_deep_merge(base.model_dump(), overrides))


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _overall_status(results: dict[str, dict[str, Any]]) -> str:
    statuses = [r.get("status", "error") for r in results.values()]
    if not statuses:
        return "error"
    return next((s for s in statuses if s != "optimal"), "optimal")
