"""The reference solver backend: build → solve (linopy + HiGHS) → extract.

The backend is sector-agnostic: it resolves the domain pack from the scenario
(or ``options["domain"]``), asks it to build the problem, solves with HiGHS, and
returns the extracted result dict.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.builder import build
from pathwise.core.solve import SolverOptions, solve
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger
from pathwise.results.extract import extract_results

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
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        problem = domain.build_problem(model, sc)
        ctx = build(problem)
        solver_opts = SolverOptions(
            time_limit_s=sc.solver.time_limit_s,
            mip_rel_gap=sc.solver.mip_gap,
            threads=sc.solver.threads,
            output_flag=bool(options.get("verbose", False)),
        )
        result = solve(ctx, solver_opts)
        return extract_results(result, terminology=domain.terminology())
