"""MACC backend: greedy marginal-cost abatement against an emission target.

A standalone optimisation *mode* — selectable alongside the MILP (``linopy``) and
``portfolio`` backends. It does **not** build or solve a MILP. Instead it reads a
precomputed marginal-abatement-cost (MACC) curve and an emission-target line, and
each year deploys abatement options cheapest-first until the year's required
abatement is met (or the curve is exhausted). Deployment is irreversible —
capacity built in one year carries forward — so once option potentials saturate,
residual emissions can drift above the (ever-tightening) target in later years.

This reproduces the greedy annual-deployment runner used by marginal-cost
sector models (e.g. the Korean petrochemical MACC), which rank abatement levers
by $/tCO2 and fill the gap to a policy target rather than co-optimising a fleet.

The backend is **sector-agnostic**: all the sector-specific cost/potential maths
live in the authoring script that produces the three input sheets
(:data:`~pathwise.data.sheets.MACC_TARGET`,
:data:`~pathwise.data.sheets.MACC_CURVE`,
:data:`~pathwise.data.sheets.MACC_OPTIONS`). The backend just runs the greedy.

Algorithm:
    For each year ``y`` (ascending), with BAU ``b(y)`` and target ``g(y)``::

        $$ \\text{required}(y) = \\max(0,\\; b(y) - g(y)) $$
        $$ \\text{remaining} = \\max\\!\\Big(0,\\; \\text{required}(y) -
           \\textstyle\\sum_k d_k\\Big) $$

    Then, visiting options ``k`` in ascending cost order while ``remaining > 0``::

        $$ a_k = \\min\\big(\\text{remaining},\\; P_k(y) - d_k\\big),\\quad a_k \\ge 0 $$
        $$ d_k \\mathrel{+}= a_k,\\quad \\text{remaining} \\mathrel{-}= a_k,\\quad
           C \\mathrel{+}= a_k \\cdot \\kappa_k(y) $$

    where ``d_k`` is option ``k``'s carried-forward deployment, ``P_k(y)`` its
    potential, ``κ_k(y)`` its CAPEX booked per unit abated, and ``C`` the running
    cumulative CAPEX. Residual emissions are ``b(y) - \\sum_k d_k``.

    ASCII fallback::

        required = max(0, bau - target)
        remaining = max(0, required - sum(deployed))   # carry-forward
        for option in sorted_by_cost_ascending:
            add = min(remaining, potential[option] - deployed[option])  # >= 0
            deployed[option] += add; remaining -= add
            cumulative_capex += add * capex[option]
        actual_emissions = bau - sum(deployed)

    Symbols: emissions/potential in the model's emission unit (e.g. MtCO2/yr);
    ``cost`` in currency per unit abated (ranking only); ``capex``/``C`` in the
    currency the authoring script booked (e.g. MUSD).
"""

from __future__ import annotations

from typing import Any

from pathwise.core.extract import empty_result, macc_result
from pathwise.data import sheets
from pathwise.data.workbook import Workbook
from pathwise.logger import get_logger

logger = get_logger(__name__)


class MaccBackend:
    """Greedy marginal-cost abatement runner (no MILP)."""

    name = "macc"
    label = "MACC (greedy abatement)"

    def capabilities(self) -> dict[str, Any]:
        """Backend capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "solver": "greedy",
            "features": {
                "macc": True,
                "multiPeriod": True,
                "transitions": False,
                "network": False,
                "monteCarlo": False,
                # The three sheets this mode consumes — surfaced so the UI can
                # gate the option on their presence.
                "requires": [sheets.MACC_TARGET, sheets.MACC_CURVE],
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read the curve + target sheets and run the greedy deployment.

        Args:
            model: The in-memory workbook (must carry ``macc_target`` and
                ``macc_curve`` sheets).
            scenario: The run definition (unused beyond carrying domain labels).
            options: Optional overrides — ``impact`` names the emission label
                echoed into the result summary (default ``"CO2"``).

        Returns:
            pathwise's result dict with an ``outputs.macc`` block, or an
            ``invalid`` result if the required sheets are missing/empty.
        """
        options = options or {}
        impact_id = str(options.get("impact") or "CO2")

        target_rows = model.get(sheets.MACC_TARGET) or []
        curve_rows = model.get(sheets.MACC_CURVE) or []
        errors = _validate(target_rows, curve_rows)
        if errors:
            logger.warning("MACC run invalid: %s", "; ".join(errors))
            return empty_result("invalid", {}, {"errors": errors, "warnings": []})

        targets = _targets(target_rows)
        curve = _curve(curve_rows)
        available_from = _available_from(model.get(sheets.MACC_OPTIONS) or [])
        labels = _labels(model.get(sheets.MACC_OPTIONS) or [])

        block = _greedy(targets, curve, available_from, labels, impact_id)
        logger.info(
            "MACC greedy: %d years, %d options, cumulative CAPEX=%.3f",
            len(block["by_year"]),
            len(block["options"]),
            block["by_year"][-1]["cumulative_capex"] if block["by_year"] else 0.0,
        )
        return macc_result(block, {}, {"errors": [], "warnings": []})


# ── Parsing helpers ───────────────────────────────────────────────────────────


def _validate(target_rows: list[dict[str, Any]], curve_rows: list[dict[str, Any]]) -> list[str]:
    """Return human-readable errors that block a run (empty list = ok)."""
    errors: list[str] = []
    if not target_rows:
        errors.append(
            f"The MACC backend needs a '{sheets.MACC_TARGET}' sheet "
            "(year, bau, target). None was found."
        )
    if not curve_rows:
        errors.append(
            f"The MACC backend needs a '{sheets.MACC_CURVE}' sheet "
            "(option_id, year, potential, cost, capex). None was found."
        )
    return errors


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce a cell to float, treating blanks/None as ``default``."""
    if value is None or value == "":
        return default
    return float(value)


def _targets(rows: list[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    """``{year: (bau, target)}`` from the target sheet."""
    out: dict[int, tuple[float, float]] = {}
    for r in rows:
        if r.get("year") in (None, ""):
            continue
        out[int(r["year"])] = (_num(r.get("bau")), _num(r.get("target")))
    return out


def _curve(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """``{year: [{option_id, potential, cost, capex}, …]}`` from the curve sheet."""
    out: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        if r.get("year") in (None, "") or not r.get("option_id"):
            continue
        out.setdefault(int(r["year"]), []).append(
            {
                "option_id": str(r["option_id"]),
                "potential": _num(r.get("potential")),
                "cost": _num(r.get("cost")),
                "capex": _num(r.get("capex")),
            }
        )
    return out


def _available_from(rows: list[dict[str, Any]]) -> dict[str, int]:
    """``{option_id: first usable year}`` (only options that set one)."""
    out: dict[str, int] = {}
    for r in rows:
        if r.get("option_id") and r.get("available_from") not in (None, ""):
            out[str(r["option_id"])] = int(r["available_from"])
    return out


def _labels(rows: list[dict[str, Any]]) -> dict[str, str]:
    """``{option_id: display label}`` (falls back to the id elsewhere)."""
    return {
        str(r["option_id"]): str(r.get("label") or r["option_id"])
        for r in rows
        if r.get("option_id")
    }


# ── The greedy deployment ───────────────────────────────────────────────────


def _greedy(
    targets: dict[int, tuple[float, float]],
    curve: dict[int, list[dict[str, Any]]],
    available_from: dict[str, int],
    labels: dict[str, str],
    impact_id: str,
) -> dict[str, Any]:
    """Run the greedy annual deployment; return the JSON-serialisable block.

    See the module Algorithm section. Deployment is carried forward across years
    (irreversible) and capped at each option's per-year potential.
    """
    deployed: dict[str, float] = {}
    cumulative_capex = 0.0
    by_year: list[dict[str, Any]] = []

    for year in sorted(targets):
        bau, target = targets[year]
        required = max(0.0, bau - target)
        rows = [
            r
            for r in curve.get(year, [])
            if r["potential"] > 0 and year >= available_from.get(r["option_id"], year)
        ]
        rows.sort(key=lambda r: r["cost"])  # cheapest $/unit abated first

        remaining = max(0.0, required - sum(deployed.values()))
        year_capex = 0.0
        for r in rows:
            if remaining <= 0:
                break
            option = r["option_id"]
            add = min(remaining, r["potential"] - deployed.get(option, 0.0))
            if add > 0:
                deployed[option] = deployed.get(option, 0.0) + add
                remaining -= add
                year_capex += add * r["capex"]

        cumulative_capex += year_capex
        total_deployed = sum(deployed.values())
        by_year.append(
            {
                "year": year,
                "bau": bau,
                "target": target,
                "required": required,
                "abated": total_deployed,
                "actual_emissions": bau - total_deployed,
                "shortfall": max(0.0, bau - total_deployed - target),
                "annual_capex": year_capex,
                "cumulative_capex": cumulative_capex,
                "deployed": dict(sorted(deployed.items())),
            }
        )

    options = [
        {"option_id": k, "label": labels.get(k, k), "deployed": deployed[k]}
        for k in sorted(deployed)
    ]
    return {
        "impact_id": impact_id,
        "by_year": by_year,
        "options": options,
        "cumulative_capex": cumulative_capex,
    }
