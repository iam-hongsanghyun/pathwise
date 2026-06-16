"""The reference solver backend: build → solve (linopy + HiGHS) → extract."""

from __future__ import annotations

from typing import Any

from pathwise.config import get_settings
from pathwise.core.build import build
from pathwise.core.extract import empty_result, extract_results
from pathwise.core.run import run_model
from pathwise.core.solve import SolverOptions, solve
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger

logger = get_logger(__name__)


class LinopyBackend:
    """Builds and solves the process-network model with ``linopy`` + HiGHS."""

    name = "linopy"
    label = "linopy + HiGHS"

    def capabilities(self) -> dict[str, Any]:
        """Backend capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "solver": "HiGHS",
            "features": {
                "multiPeriod": True,
                "network": True,
                "multiImpact": True,
                "transitions": True,
                "macc": True,
                "carbonPrice": True,
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate, build, solve, and extract one case.

        Args:
            model: The in-memory workbook.
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: ``domain`` / verbosity overrides.

        Returns:
            pathwise's result dict (validation folded in).
        """
        options = options or {}
        settings = get_settings()
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        report = domain.validate(model)
        if not report.ok:
            logger.warning("validation failed: %d error(s)", len(report.errors))
            return empty_result("invalid", domain.terminology(), report.as_dict())

        # A node hierarchy is solved through the unified front door: a joint solve
        # at the root/``system`` level, or a per-level partitioned cascade
        # (``optimisation_scope`` = a designed level). Flat models keep the
        # direct build→solve path below.
        if model.get("nodes"):
            logger.info("hierarchy model → run_model(scope=%s)", sc.optimisation_scope)
            return run_model(model, sc, terminology=domain.terminology(), report=report.as_dict())

        problem = domain.build_problem(model, sc)
        ctx = build(problem)
        time_limit = min(sc.solver.time_limit_s, float(settings.max_solver_time_limit_s))
        # HiGHS log streams to the server terminal so the optimisation is visible;
        # `verbose: false` in options (or PATHWISE_SOLVER_VERBOSE=false) silences it.
        verbose = bool(options.get("verbose", settings.solver_verbose))
        opts = SolverOptions(
            solver_name=settings.solver_name,
            time_limit_s=time_limit,
            mip_rel_gap=sc.solver.mip_gap,
            threads=settings.solver_threads,
            output_flag=verbose,
            user_bound_scale=settings.highs_user_bound_scale,
            user_objective_scale=settings.highs_user_objective_scale,
        )
        logger.info(
            "solving: %d facilities × %d techs × %d periods (HiGHS%s)",
            len(ctx.procs),
            len(ctx.techs),
            len(ctx.years),
            ", log on" if verbose else "",
        )
        result = solve(ctx, opts)
        return extract_results(result, domain.terminology(), report.as_dict())
