"""MACC backend: greedy marginal-cost abatement over the framework's *levers*.

A standalone optimisation *mode* — selectable alongside the MILP (``linopy``) and
``portfolio`` backends. It is a SOLVE METHOD over the same value-chain model, not
a separate data format: it reuses the front of the pipeline (validate → assemble
the :class:`~pathwise.core.problem.Problem`), then — instead of building a MILP —
reads the model's **levers** (abatement actions applied to a facility WITHOUT
changing its technology — the framework's MACC concept) and greedily deploys them
cheapest-first against the emission cap (``impact_caps``).

This reproduces the greedy annual-deployment runners common in sector
decarbonisation models (e.g. the Korean petrochemical MACC): rank levers by
$/tCO2, fill the gap to the policy target each year, carry deployment forward
irreversibly. Because deployment is irreversible, once lever potentials
saturate the residual emissions can drift above an ever-tightening target.

Distinction the framework draws: a **transition** changes a facility's technology
(decided by the MILP); a **lever** abates without a technology change (this
backend). The two are not interchangeable.

Algorithm:
    For each year ``y`` (ascending), with sector BAU ``b(y) = Σ_f e_f(y)`` (every
    facility's gross emission of the capped impact at full capacity, no levers)
    and target ``g(y)`` (the impact cap)::

        required(y) = max(0, b(y) - g(y))
        remaining   = max(0, required(y) - Σ_k d_k)          # d_k carried forward
        for lever k in ascending $/tCO2:
            add = min(remaining, P_k(y) - d_k)                # capped at potential
            d_k += add ; remaining -= add ; C += add · κ_k(y) # C = cumulative CAPEX
        actual(y) = b(y) - Σ_k d_k

    where, summing a lever's facility-instances (each block on each linked
    facility), with baseline emission ``e_f(y)`` and lifetime ``L``::

        P_k(y) = Σ_f reduction_f(y) · e_f(y)                  # abatement potential
        $/tCO2 = (Σ_f capex_f(y)/L + Σ_f opex_f(y)) / P_k(y)  # ranking key
        κ_k(y) = (Σ_f capex_f(y)) / P_k(y)                    # CAPEX booked per unit

    ASCII fallback: deploy the cheapest lever first up to its potential, carry
    deployment forward, book CAPEX in proportion to abatement added.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.entities import LeverType
from pathwise.core.extract import empty_result, macc_result
from pathwise.core.problem import Problem
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger
from pathwise.progress import ProgressFn

logger = get_logger(__name__)

_ABATING = (LeverType.EMISSION_REDUCTION, LeverType.ENVIRONMENTAL)


class MaccBackend:
    """Greedy marginal-cost abatement over the model's levers (no MILP)."""

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
                "levers": True,
                "multiPeriod": True,
                "transitions": False,
                "network": False,
                "monteCarlo": False,
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
        *,
        progress: ProgressFn | None = None,
    ) -> dict[str, Any]:
        """Validate, assemble, and greedily deploy levers against the cap.

        ``progress`` is accepted for backend-protocol uniformity (the greedy
        pass is fast and reports no incremental progress).

        Args:
            model: The in-memory workbook (a value-chain model with levers + an
                impact cap).
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: ``domain`` override and ``impact`` (the capped impact to
                chase; default: the impact that carries a cap, else the first
                declared impact — no hardcoded ``"CO2"``).

        Returns:
            pathwise's result dict with an ``outputs.macc`` block, or an
            ``invalid`` result if the model has no levers or no emission cap.
        """
        options = options or {}
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        terminology = domain.terminology()
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        report = domain.validate(model)
        if not report.ok:
            logger.warning("validation failed: %d error(s)", len(report.errors))
            return empty_result("invalid", terminology, report.as_dict())

        problem = domain.build_problem(model, sc)
        impact_id = str(options.get("impact") or _target_impact(problem))
        errors = _preflight(problem, impact_id)
        if errors:
            report_dict = report.as_dict()
            report_dict["errors"].extend(errors)
            logger.warning("MACC run invalid: %s", "; ".join(errors))
            return empty_result("invalid", terminology, report_dict)

        block = _greedy(problem, impact_id)
        logger.info(
            "MACC greedy: %d years, %d lever(s), cumulative CAPEX=%.3f",
            len(block["by_year"]),
            len(block["options"]),
            block["cumulative_capex"],
        )
        return macc_result(block, terminology, report.as_dict())


# ── Problem readers ───────────────────────────────────────────────────────────


def _target_impact(problem: Problem) -> str:
    """The capped impact to chase: the first impact with a cap, else the first
    declared impact (impact-agnostic — no hardcoded ``"CO2"``)."""
    for _company, impact, _year in problem.impact_caps:
        return impact
    return next(iter(problem.impacts), "")


def _cap(problem: Problem, impact: str, year: int) -> float | None:
    """Total emission cap for ``impact`` in ``year`` (summed over scopes), or None."""
    hits = [v for (_c, i, y), v in problem.impact_caps.items() if i == impact and y == year]
    return sum(hits) if hits else None


def _baseline_emission(problem: Problem, process: Any, impact: str, year: int) -> float:
    """A facility's gross emission of ``impact`` at full capacity in ``year``.

    Mirrors the MILP's emission expression but evaluated at the facility's
    nameplate capacity with no levers applied (the BAU contribution).
    """
    cap = process.capacity_at(year)
    tech = problem.technologies.get(process.baseline_technology)
    direct = process.direct_impact_at(impact, year)
    if tech is not None:
        direct += tech.direct_impact_at(impact, year)
    total = direct * cap
    if tech is not None:
        inputs = set(tech.input_intensity) | set(tech.input_intensity_by_year)
        for r in inputs:
            total += problem.flow_impact(r, impact, year) * cap * tech.input_intensity_at(r, year)
    return float(total)


def _preflight(problem: Problem, impact: str) -> list[str]:
    """Errors that block a greedy run (no levers / no cap for the impact).

    MACC is an abatement-only *mode*, not a cost optimiser: with no levers to
    rank and no target to chase it has nothing to compute. When that's the case
    the message points at the ``linopy`` backend — plain least-cost optimisation,
    where an emission target is OPTIONAL — so a user who just wants cost
    minimisation is steered to the right engine rather than told to invent a
    ``CO2`` target they never wanted.
    """
    abating = [m for m in problem.levers if m.lever_type in _ABATING and m.target == impact]
    capped = any(i == impact for (_c, i, _y) in problem.impact_caps)
    if abating and capped:
        return []

    missing: list[str] = []
    if not abating:
        missing.append(
            f"at least one abatement lever targeting '{impact}' "
            "(with cost-curve blocks, linked to facilities)"
        )
    if not capped:
        missing.append(f"a '{impact}' emission cap to chase (an impact_caps row)")
    return [
        f"The MACC backend is an abatement-only mode — it ranks levers by "
        f"$/{impact} and deploys them cheapest-first against a '{impact}' target, "
        "so it needs " + " and ".join(missing) + ". "
        f"If you just want least-cost optimisation (where the '{impact}' target is "
        "OPTIONAL), switch the backend to 'linopy + HiGHS' in "
        "Settings → Optimisation method — that minimises total discounted cost and "
        "is the default."
    ]


# ── The greedy deployment ─────────────────────────────────────────────────────


def _base_id(lever_id: str) -> str:
    """The shared lever id behind a per-facility instance (``"HP @ F1"`` → ``"HP"``)."""
    return lever_id.split(" @ ", 1)[0]


def _options(problem: Problem, impact: str) -> list[dict[str, Any]]:
    """Group abatement levers into curve options (one per base lever × block).

    Each option aggregates its facility-instances: per year it carries the total
    abatement potential, total CAPEX and total OPEX, plus the lever lifetime.
    """
    # base id → block index → list of (lever, block, process)
    grouped: dict[tuple[str, int], list[tuple[Any, Any, Any]]] = {}
    proc_by = {p.process_id: p for p in problem.processes}
    for m in problem.levers:
        if m.lever_type not in _ABATING or m.target != impact:
            continue
        proc = proc_by.get(m.applies_to)
        if proc is None:
            continue
        for b, blk in enumerate(m.blocks):
            grouped.setdefault((_base_id(m.lever_id), b), []).append((m, blk, proc))

    options: list[dict[str, Any]] = []
    for (base, block_idx), instances in grouped.items():
        lifetime = max(1, instances[0][0].lifetime)
        per_year: dict[int, dict[str, float]] = {}
        for y in problem.years:
            potential = capex = opex = 0.0
            for _m, blk, proc in instances:
                emit = _baseline_emission(problem, proc, impact, y)
                potential += blk.reduction_at(y) * emit
                capex += blk.capex_at(y)
                opex += blk.opex_at(y)
            rank = (capex / lifetime + opex) / potential if potential > 0 else float("inf")
            book = capex / potential if potential > 0 else 0.0
            per_year[y] = {"potential": potential, "rank": rank, "book": book}
        label = base if block_idx == 0 else f"{base} (block {block_idx})"
        options.append({"id": f"{base}#{block_idx}", "label": label, "per_year": per_year})
    return options


def _greedy(problem: Problem, impact: str) -> dict[str, Any]:
    """Run the greedy annual deployment over levers; return the result block."""
    options = _options(problem, impact)
    deployed: dict[str, float] = {o["id"]: 0.0 for o in options}
    cumulative_capex = 0.0
    by_year: list[dict[str, Any]] = []

    for year in problem.years:
        bau = sum(_baseline_emission(problem, p, impact, year) for p in problem.processes)
        target = _cap(problem, impact, year)
        target = bau if target is None else target
        required = max(0.0, bau - target)

        rows = sorted(options, key=lambda o: o["per_year"][year]["rank"])
        remaining = max(0.0, required - sum(deployed.values()))
        year_capex = 0.0
        for o in rows:
            if remaining <= 0:
                break
            info = o["per_year"][year]
            add = min(remaining, info["potential"] - deployed[o["id"]])
            if add > 0:
                deployed[o["id"]] += add
                remaining -= add
                year_capex += add * info["book"]

        cumulative_capex += year_capex
        total = sum(deployed.values())
        by_year.append(
            {
                "year": year,
                "bau": bau,
                "target": target,
                "required": required,
                "abated": total,
                "actual_emissions": bau - total,
                "shortfall": max(0.0, bau - total - target),
                "annual_capex": year_capex,
                "cumulative_capex": cumulative_capex,
                "deployed": {o["label"]: deployed[o["id"]] for o in options},
            }
        )

    return {
        "impact_id": impact,
        "by_year": by_year,
        "options": [
            {"option_id": o["id"], "label": o["label"], "deployed": deployed[o["id"]]}
            for o in options
        ],
        "cumulative_capex": cumulative_capex,
    }
