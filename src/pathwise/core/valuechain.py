"""Cascade orchestrator for value-chain optimisation (cost-based, forward).

Solve each stage with the ordinary single-model pipeline
(``assemble_problem → build → solve → extract_results``) in upstream→downstream
order. After an upstream stage solves, derive a per-year **price** for each
coupled commodity and inject it — shifted by the link's time lag — into the
downstream stage's price trajectory *before* that stage is assembled and solved.
So a policy on an upstream stage (e.g. a carbon price on electricity) raises the
price the downstream stage pays, and the downstream optimiser re-chooses its
pathway accordingly.

Algorithm:
    For a link u→d on commodity c with lag L, the transferred price in year t is
    the upstream stage's average unit cost of c:

    $$ p_d(t+L) \\;=\\; \\frac{\\text{Cost}_u(t)}{\\text{Prod}_{u,c}(t)} $$

    ASCII: price_d[t+L] = upstream_cost[t] / upstream_production_of_c[t]

    where ``Cost_u(t)`` is the upstream stage's total cost in year ``t``
    (``summary.periods``) and ``Prod_{u,c}(t)`` its production of ``c``
    (``summary.commodity``). The shifted points are interpolated onto the
    downstream horizon (linear, flat-hold beyond the ends).

This is an **average-cost proxy** (exact when the upstream stage makes a single
product; an over-allocation for multi-product stages — a true marginal/transfer
price needs LP duals, a later phase). It is purely primal, so it needs no engine
change. Forward-only: downstream demand does not feed back upstream yet.

Units: price [currency / commodity-unit]; cost [currency / yr]; production
[commodity-unit / yr].
"""

from __future__ import annotations

import copy
from typing import Any

from pathwise.core.build import build
from pathwise.core.extract import extract_results
from pathwise.core.solve import solve
from pathwise.data.assemble import assemble_problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.trajectory import interpolate
from pathwise.data.valuechain import ValueChainSpec
from pathwise.data.workbook import Workbook

_EPS = 1e-9


def run_value_chain(
    spec: ValueChainSpec,
    workbooks: dict[str, Workbook],
    scenario: ScenarioConfig | None = None,
) -> dict[str, Any]:
    """Solve a value chain as a forward cascade of price-coupled stages.

    Args:
        spec: The value-chain definition (stages + coupling links).
        workbooks: ``{stage_id: workbook}`` — every stage in ``spec`` must have
            a resolved workbook (the caller does the I/O; this stays pure).
        scenario: Base run scenario; per-stage ``scenario`` overrides are
            deep-merged onto it. Defaults to ``ScenarioConfig()``.

    Returns:
        ``{"status", "stages": {id: result}, "couplings": [...]}`` — each stage's
        standard :func:`extract_results` dict plus the price trajectories that
        flowed between stages (for inspection / UI overlay).

    Raises:
        KeyError: If a stage in ``spec`` has no workbook in ``workbooks``.
    """
    base = scenario or ScenarioConfig()
    wbs: dict[str, Workbook] = {s.id: copy.deepcopy(workbooks[s.id]) for s in spec.stages}

    results: dict[str, dict[str, Any]] = {}
    couplings: list[dict[str, Any]] = []
    by_source = _links_by_source(spec)

    for sid in spec.order():
        stage = spec.stage(sid)
        sc = _stage_scenario(base, stage.scenario)
        results[sid] = extract_results(solve(build(assemble_problem(wbs[sid], sc))))

        for link in by_source.get(sid, []):
            if "price" not in link.signals:
                continue  # Phase 1 couples price only
            target_years = _years(wbs[link.to_stage])
            signal = _price_signal(results[sid], link.commodity)
            shifted = _shift(signal, link.lag_years, target_years)
            if not shifted:
                continue
            _inject_price(wbs[link.to_stage], link.commodity, shifted)
            couplings.append(
                {
                    "from_stage": sid,
                    "to_stage": link.to_stage,
                    "commodity": link.commodity,
                    "signal": "price",
                    "lag_years": link.lag_years,
                    "by_year": [{"year": y, "value": v} for y, v in sorted(shifted.items())],
                }
            )

    return {"status": _overall_status(results), "stages": results, "couplings": couplings}


# ── helpers ──────────────────────────────────────────────────────────────────


def _links_by_source(spec: ValueChainSpec) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for link in spec.active_links():
        out.setdefault(link.from_stage, []).append(link)
    return out


def _years(wb: Workbook) -> list[int]:
    return sorted(int(r["year"]) for r in wb.get("periods", []) if r.get("year") is not None)


def _price_signal(result: dict[str, Any], commodity: str) -> dict[int, float]:
    """Upstream average unit cost of ``commodity`` per year (the transfer price)."""
    summary = result.get("summary", {})
    cost = {int(r["period"]): float(r["cost"]) for r in summary.get("periods", [])}
    out: dict[int, float] = {}
    for r in summary.get("commodity", []):
        if str(r.get("commodity")) != commodity:
            continue
        y = int(r["period"])
        produced = float(r.get("produced") or 0.0)
        if produced > _EPS and y in cost:
            out[y] = cost[y] / produced
    return out


def _shift(signal: dict[int, float], lag: int, target_years: list[int]) -> dict[int, float]:
    """Shift a year→price signal forward by ``lag`` and interpolate onto target years."""
    if not signal or not target_years:
        return {}
    shifted = {y + lag: v for y, v in signal.items()}
    return interpolate(shifted, target_years)


def _inject_price(wb: Workbook, commodity: str, by_year: dict[int, float]) -> None:
    """Upsert a per-year price column for ``commodity`` into ``commodities_t__price``."""
    rows = wb.setdefault("commodities_t__price", [])
    index = {int(r["year"]): r for r in rows if r.get("year") is not None}
    for y, v in by_year.items():
        if y in index:
            index[y][commodity] = v
        else:
            row: dict[str, Any] = {"year": y, commodity: v}
            rows.append(row)
            index[y] = row


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
