"""The reference solver backend: build → solve (linopy + HiGHS) → extract.

The backend is sector-agnostic: it resolves the domain pack from the scenario
(or ``options["domain"]``), asks it to build the problem, solves with HiGHS, and
returns the extracted result dict.

When the scenario enables :class:`~pathwise.data.scenario.OuterSearch`, the
single solve becomes the *inner* level of a bilevel run: an outer search
(simulated annealing or a deterministic sweep) chooses a sector-wide emission
pathway, scoring each candidate by the inner solve's total discounted cost. The
chosen pathway and the search trace are attached to the result under
``pathway_search``.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from pathwise.config import get_settings
from pathwise.core.builder import build
from pathwise.core.outer import INFEASIBLE_COST, anneal, sweep
from pathwise.core.solve import SolverOptions, solve
from pathwise.data.pathway import apply_pathway, derive_upper_bounds, sector_groups
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger
from pathwise.results.extract import empty_result, extract_results

logger = get_logger(__name__)


class LinopyBackend:
    """Builds and solves the generic model with ``linopy`` + HiGHS."""

    name = "linopy"
    label = "linopy + HiGHS"

    def capabilities(self) -> dict[str, Any]:
        """Return the backend capability descriptor for ``GET /api/backends``."""
        return {
            "name": self.name,
            "label": self.label,
            "solver": "HiGHS",
            "features": {
                "multiPeriod": True,
                "transitions": True,
                "measures": True,
                "newBuild": True,
                "intensityTargets": True,
                "absoluteTargets": True,
                "carbonPrice": True,
                "capexAnnuity": True,
                "bilevelPathway": True,
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one case — single-level, or bilevel when ``scenario.outer.enabled``.

        Args:
            model: The in-memory workbook.
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: ``domain`` / solver overrides.

        Returns:
            pathwise's result dict (with a ``pathway_search`` block for bilevel runs).
        """
        options = options or {}
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        if sc.outer.enabled:
            return self._run_outer(model, sc, domain, options)
        return self._run_single(model, sc, domain, options)

    def _run_single(
        self,
        model: Workbook,
        sc: ScenarioConfig,
        domain: Any,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate → build → solve → extract a single case."""
        settings = get_settings()
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        # Validation is part of the result — no separate round-trip.
        report = domain.validate(model)
        if not report.ok:
            logger.warning("validation failed: %d error(s)", len(report.errors))
            return empty_result("invalid", domain.terminology(), report.as_dict())

        problem = domain.build_problem(model, sc)
        ctx = build(problem)
        # Solver resource limits are server-controlled: clamp the user's time
        # limit and use the server's thread count; honour the user's MIP gap.
        time_limit = min(sc.solver.time_limit_s, float(settings.max_solver_time_limit_s))
        solver_opts = SolverOptions(
            time_limit_s=time_limit,
            mip_rel_gap=sc.solver.mip_gap,
            threads=settings.solver_threads,
            output_flag=bool(options.get("verbose", False)),
        )
        result = solve(ctx, solver_opts)
        return extract_results(result, domain.terminology(), report.as_dict())

    def _run_outer(
        self,
        model: Workbook,
        sc: ScenarioConfig,
        domain: Any,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        """Bilevel run: outer pathway search over the inner single solve."""
        settings = get_settings()
        outer = sc.outer

        # Modelled years (honour the horizon) and the sector's groups.
        years = sorted({int(r["year"]) for r in model.get("periods", [])})
        if sc.horizon.start is not None:
            years = [y for y in years if y >= sc.horizon.start]
        if sc.horizon.end is not None:
            years = [y for y in years if y <= sc.horizon.end]
        groups = sector_groups(model)

        try:
            upper_by_year = derive_upper_bounds(model, sc.selection.target_set, years)
        except ValueError as exc:
            logger.warning("outer search aborted: %s", exc)
            return empty_result(
                "invalid", domain.terminology(), {"errors": [str(exc)], "warnings": []}
            )

        upper = [upper_by_year[y] for y in years]
        floor = [outer.floor_fraction * u for u in upper]

        def evaluate(x: list[float]) -> float:
            pathway = dict(zip(years, x, strict=True))
            wb = apply_pathway(model, sc.selection.target_set, groups, pathway)
            res = self._run_single(wb, sc, domain, options)
            obj = res.get("objective")
            if res.get("status") != "optimal" or obj is None:
                return INFEASIBLE_COST
            return float(obj)

        if outer.method == "sweep":
            search = sweep(evaluate, upper, floor, steps=outer.sweep_steps)
        else:
            max_iter = min(outer.max_iterations, settings.max_outer_iterations)
            rng = np.random.default_rng(outer.seed)
            search = anneal(
                evaluate,
                x0=upper,
                lower=floor,
                upper=upper,
                max_iter=max_iter,
                t0=outer.initial_temp,
                t_min=outer.min_temp,
                cooling=outer.cooling_rate,
                rng=rng,
            )

        # Re-solve on the winning pathway to return its full decisions/outputs.
        best_pathway = dict(zip(years, search.best_x, strict=True))
        wb_best = apply_pathway(model, sc.selection.target_set, groups, best_pathway)
        result = self._run_single(wb_best, sc, domain, options)

        result["pathway_search"] = {
            "enabled": True,
            "method": search.method,
            "objective": None if math.isinf(search.best_cost) else search.best_cost,
            "groups": groups,
            "evaluations": search.n_evals,
            "pathway": [{"year": y, "limit": best_pathway[y]} for y in years],
            "bounds": {
                "upper": [{"year": y, "limit": u} for y, u in zip(years, upper, strict=True)],
                "floor": [{"year": y, "limit": f} for y, f in zip(years, floor, strict=True)],
            },
            "frontier": search.history,
        }
        return result
