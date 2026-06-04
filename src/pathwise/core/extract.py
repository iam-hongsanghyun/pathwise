"""Extract a JSON-serialisable result dict from a solved model."""

from __future__ import annotations

from typing import Any

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
            "measures": [],
            "flows": [],
            "trade": [],
            "demand_slack": [],
        },
        "summary": {"periods": [], "impacts": []},
    }


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
    for (p, k, t), v in _series(ctx.w).items():
        if v > _ON:
            out["outputs"]["transitions"].append(
                {"process": p, "to_technology": k, "period": int(t)}
            )
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
    out["summary"]["periods"] = [{"period": y} for y in prob.years]
    return out
