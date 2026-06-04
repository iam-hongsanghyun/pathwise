"""Extract a JSON-serialisable result dict from a solved model.

Reads the ``linopy`` variable solutions off the :class:`BuildContext` and turns
them into plain lists/dicts the API and Excel exporter consume. Also recomputes
per-period energy and emissions from the solution and the problem parameters so
the summary is self-contained.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.solve import SolveResult
from pathwise.core.variables import G_PER_TONNE

_BINARY_ON = 0.5
_EPS = 1e-6


def _series(var: Any) -> dict[tuple, float]:
    """Return a ``{index_tuple: value}`` dict for a solved variable (NaN dropped)."""
    if var is None:
        return {}
    s = var.solution.to_series().dropna()
    return {idx: float(v) for idx, v in s.items()}


def empty_result(
    status: str,
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Return a result dict with no decisions (e.g. an ``invalid`` run)."""
    return {
        "status": status,
        "termination": status,
        "objective": None,
        "terminology": terminology or {},
        "validation": validation or {"errors": [], "warnings": []},
        "outputs": {
            "chosen_technology": [],
            "carrier_energy": [],
            "transitions": [],
            "new_builds": [],
            "measures": [],
            "slack": [],
        },
        "summary": {"periods": []},
    }


def extract_results(
    result: SolveResult,
    terminology: dict[str, str] | None = None,
    validation: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build the result dict from a :class:`SolveResult`.

    Args:
        result: The solve outcome (carries the build context with solutions).
        terminology: Optional sector label overrides to echo back to the UI.
        validation: Optional validation report (errors/warnings) to include.

    Returns:
        A JSON-serialisable result dict with ``status``, ``objective``,
        ``validation``, ``outputs`` (decisions), and ``summary``
        (per-period energy/emissions).
    """
    ctx = result.context
    problem = ctx.problem
    out: dict[str, Any] = {
        "status": result.status.value,
        "termination": result.termination,
        "objective": result.objective,
        "terminology": terminology or {},
        "validation": validation or {"errors": [], "warnings": []},
        "outputs": {
            "chosen_technology": [],
            "carrier_energy": [],
            "transitions": [],
            "new_builds": [],
            "measures": [],
            "slack": [],
        },
        "summary": {"periods": []},
    }
    if not result.ok:
        return out

    # Chosen technology per asset/period.
    for (asset, tech, period), val in _series(ctx.u).items():
        if val > _BINARY_ON:
            out["outputs"]["chosen_technology"].append(
                {"asset": asset, "technology": tech, "period": int(period)}
            )

    # Carrier energy [MJ] per asset/technology/carrier/period.
    ec = _series(ctx.ec)
    for (asset, tech, carrier, period), val in ec.items():
        if val > _EPS:
            out["outputs"]["carrier_energy"].append(
                {
                    "asset": asset,
                    "technology": tech,
                    "carrier": carrier,
                    "period": int(period),
                    "energy_mj": val,
                }
            )

    # Retrofit events.
    for (asset, tech, period), val in _series(ctx.w).items():
        if val > _BINARY_ON:
            out["outputs"]["transitions"].append(
                {"asset": asset, "to_technology": tech, "period": int(period)}
            )

    # New-build commissioning.
    for (asset, period), val in _series(ctx.build).items():
        if val > _BINARY_ON:
            out["outputs"]["new_builds"].append({"asset": asset, "period": int(period)})

    # Measure adoption.
    for (asset, measure, block, period), val in _series(ctx.z).items():
        if val > _EPS:
            out["outputs"]["measures"].append(
                {
                    "asset": asset,
                    "measure": measure,
                    "block": int(block),
                    "period": int(period),
                    "adoption": val,
                }
            )

    # Slack (demand + target), only where positive.
    for (group, period), val in _series(ctx.slk_dem).items():
        if val > _EPS:
            out["outputs"]["slack"].append(
                {"kind": "demand", "group": group, "period": int(period), "value": val}
            )
    for (group, period), val in _series(ctx.slk_tgt).items():
        if val > _EPS:
            out["outputs"]["slack"].append(
                {"kind": "target", "group": group, "period": int(period), "value": val}
            )

    # ── Per-period summary: energy [MJ] and emissions [tCO2e] ─────────────────
    carrier_by_id = {c.carrier_id: c for c in problem.carriers}
    energy_by_year: dict[int, float] = dict.fromkeys(problem.years, 0.0)
    gross_g_by_year: dict[int, float] = dict.fromkeys(problem.years, 0.0)
    for (_asset, _tech, carrier, period), mj in ec.items():
        y = int(period)
        energy_by_year[y] += mj
        gross_g_by_year[y] += mj * carrier_by_id[carrier].intensity(y)

    abate_g_by_year: dict[int, float] = dict.fromkeys(problem.years, 0.0)
    if ctx.has_measures:
        measure_by_id = {m.measure_id: m for m in problem.measures}
        for (_asset, measure, block, period), z in _series(ctx.z).items():
            blk = int(block)
            blocks = measure_by_id[measure].blocks
            if blk < len(blocks):
                abate_g_by_year[int(period)] += z * blocks[blk].abatement * G_PER_TONNE

    for y in problem.years:
        net_t = (gross_g_by_year[y] - abate_g_by_year[y]) / G_PER_TONNE
        energy = energy_by_year[y]
        out["summary"]["periods"].append(
            {
                "period": y,
                "energy_mj": energy,
                "emissions_tco2e": net_t,
                "intensity_gco2e_per_mj": (gross_g_by_year[y] / energy) if energy else 0.0,
            }
        )
    return out
