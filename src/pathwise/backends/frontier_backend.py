"""Frontier backend: the cost–impact trade-off curve (ε-constraint Pareto front).

A different SOLVE METHOD over the same model: repeatedly run the least-cost
optimiser (``linopy``) with a tightening **cap on a characterised impact category**
(e.g. GWP) and record the resulting `(cap, cost, achieved impact)`. The locus of
points is the cost-vs-impact Pareto frontier — the decision-grade output of "how
much does each extra tonne avoided cost?". Reuses the existing optimise path and
the characterisation layer (the capped target may be any impact or category).
"""

from __future__ import annotations

from typing import Any

from pathwise.core.extract import empty_result
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook, default_impact
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger
from pathwise.progress import ProgressFn

logger = get_logger(__name__)


class FrontierBackend:
    """Trace the cost–impact Pareto frontier by sweeping an ε-constraint cap."""

    name = "frontier"
    label = "Cost–impact frontier (ε-constraint)"

    def capabilities(self) -> dict[str, Any]:
        """Backend capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "kind": "frontier",
            "features": {"frontier": True, "epsilonConstraint": True},
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
        *,
        progress: ProgressFn | None = None,
    ) -> dict[str, Any]:
        """Sweep a cap on ``scenario.frontier.impact`` and record cost vs impact.

        ``scenario.frontier`` = ``{impact, from, to, step}`` (the category to trade
        off and the cap range). Each point fixes a hard cap, runs least-cost
        ``linopy``, and records the achieved cost and impact. Infeasible points
        (cap below the achievable minimum) are recorded with their status.
        """
        from pathwise.backends.registry import get_backend  # lazy: avoid import cycle

        options = options or {}
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        report = domain.validate(model)
        if not report.ok:
            return empty_result("invalid", domain.terminology(), report.as_dict())

        fr = (scenario or {}).get("frontier") or {}
        impact = str(fr.get("impact") or default_impact(model))
        caps = _cap_points(
            float(fr.get("from") or 0.0), float(fr.get("to") or 0.0), float(fr.get("step") or 0.0)
        )
        if not fr or len(caps) < 2:
            rep = report.as_dict()
            rep["errors"].append(
                "frontier backend needs scenario.frontier = {impact, from, to, step} "
                "spanning at least two cap points"
            )
            return empty_result("invalid", domain.terminology(), rep)

        linopy = get_backend("linopy")
        # ε-constraint: REPLACE any pre-existing caps on the swept impact with our single
        # hard cap; keep caps on OTHER impacts. Appending instead would (a) sum with the
        # model's own caps under system-scope pooling and (b) — if the model carries a soft
        # cap on this impact — soften ours too, leaving the frontier cap non-binding (every
        # point collapses to the baseline). Other impacts' soft caps no longer contaminate
        # this one (assemble pools soft/penalty per impact).
        other_caps = [c for c in model.get("impact_caps", []) if str(c.get("impact_id")) != impact]
        # Drop the frontier block; the optimiser solves plain least-cost per point.
        run_scenario = {k: v for k, v in (scenario or {}).items() if k != "frontier"}

        points: list[dict[str, Any]] = []
        n_caps = len(caps)
        for i, cap in enumerate(caps):
            capped: Workbook = {
                **model,
                # A year-less HARD cap applies to every year, system-wide ("all").
                "impact_caps": [
                    *other_caps,
                    {"company": "all", "impact_id": impact, "limit": cap, "soft": 0},
                ],
            }
            res = linopy.run(capped, run_scenario, options)
            if res.get("status") != "optimal":
                points.append({"cap": cap, "status": res.get("status")})
            else:
                achieved = sum(
                    float(r["total"])
                    for r in res["summary"]["impacts"]
                    if str(r["impact"]) == impact
                )
                points.append(
                    {"cap": cap, "cost": res["objective"], "impact": achieved, "status": "optimal"}
                )
            # One full least-cost solve per cap point: report live completed/total
            # so the client can show "12 / 40 runs" as the sweep proceeds.
            if progress is not None:
                progress(i + 1, n_caps, f"{impact} cap {cap:g}")

        logger.info(
            "frontier: %d point(s) on %s, %d feasible",
            len(points),
            impact,
            sum(1 for p in points if p.get("status") == "optimal"),
        )
        out = empty_result("optimal", domain.terminology(), report.as_dict())
        out["outputs"]["frontier"] = {"impact": impact, "points": points}
        return out


def _cap_points(lo: float, hi: float, step: float, *, cap: int = 200) -> list[float]:
    """Inclusive ``[lo, hi]`` grid at ``step`` (single point if ``step <= 0``)."""
    if step <= 0 or hi <= lo:
        return [lo]
    n = min(cap, int((hi - lo) / step) + 1)
    pts = [lo + i * step for i in range(n)]
    if pts[-1] < hi - 1e-9:
        pts.append(hi)
    return pts
