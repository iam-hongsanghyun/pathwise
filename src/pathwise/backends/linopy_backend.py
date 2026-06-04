"""The reference solver backend: build → solve (linopy + HiGHS) → extract.

The backend is sector-agnostic: it resolves the domain pack from the scenario
(or ``options["domain"]``), asks it to build the problem, solves with HiGHS, and
returns the extracted result dict.
"""

from __future__ import annotations

from typing import Any

from pathwise.config import get_settings
from pathwise.core.builder import build
from pathwise.core.solve import SolverOptions, solve
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
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build, solve, and extract one case.

        Args:
            model: The in-memory workbook.
            scenario: The run definition (a :class:`ScenarioConfig` as a dict).
            options: ``domain`` / solver overrides.

        Returns:
            pathwise's result dict.
        """
        options = options or {}
        settings = get_settings()
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
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
