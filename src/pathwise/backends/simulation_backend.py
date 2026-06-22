"""Simulation backend: evaluate a FIXED configuration's lifecycle inventory.

Not an optimiser — a *what-if / LCA* lens over the **same** value-chain model
(``Workbook`` → ``Problem``), in the spirit of the ``macc`` backend: a different
SOLVE METHOD, not a new data format. Where ``linopy`` *chooses* technologies,
transitions, and measures to minimise cost, this backend **evaluates a pinned
configuration** and reports its lifecycle emission inventory and cost.

P1 (this module) evaluates the **as-is** configuration — the current plant with
no technology switching and no auto-adopted abatement (the *free-choice* sheets
``transitions`` / ``measures`` are stripped) — and returns, under
``outputs.lca``:

* ``by_impact``  — total emissions per impact (the engine's own totals), per
  functional unit;
* ``by_stage``   — those emissions decomposed across value-chain **stages**
  (company nodes = lifecycle stages), from ``throughput × impact factor``;
* ``cost``       — total system cost and the carbon cost (Σ emissions × price).

P2 will add baseline-vs-variant comparison (abatement, $/tCO2, break-even carbon
price); P3 a policy sweep. See ``docs/proposals/simulation-backend.md``.
"""

from __future__ import annotations

from typing import Any

from pathwise.core.extract import empty_result
from pathwise.core.run import run_model
from pathwise.data.scenario import ScenarioConfig
from pathwise.data.workbook import Workbook
from pathwise.domains.base import get_domain
from pathwise.logger import get_logger

logger = get_logger(__name__)

#: Sheets that hand the optimiser a *choice*. Stripping them pins each machine to
#: its baseline technology with no auto-adopted abatement — the "current" config.
_FREE_CHOICE_SHEETS = ("transitions", "measures", "measure_blocks", "measure_blocks_t")


class SimulationBackend:
    """Evaluate a pinned configuration and report its lifecycle inventory."""

    name = "simulate"
    label = "Scenario simulator (LCA what-if)"

    def capabilities(self) -> dict[str, Any]:
        """Backend capability descriptor for the handshake."""
        return {
            "name": self.name,
            "label": self.label,
            "kind": "simulation",
            "features": {
                "lca": True,
                "carbonPrice": True,
                "comparison": False,  # P2
                "policySweep": False,  # P3
            },
        }

    def run(
        self,
        model: Workbook,
        scenario: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Evaluate the configuration and fold a lifecycle inventory into the result.

        Args:
            model: The in-memory workbook.
            scenario: Run definition (a :class:`ScenarioConfig` dict); an optional
                ``simulate`` block selects the baseline / functional unit.
            options: ``domain`` / verbosity overrides.

        Returns:
            pathwise's result dict with an added ``outputs.lca`` block.
        """
        options = options or {}
        sc = ScenarioConfig.from_dict(scenario)
        domain = get_domain(options.get("domain") or sc.domain)
        logger.info("running domain=%s backend=%s", domain.name, self.name)

        report = domain.validate(model)
        if not report.ok:
            logger.warning("validation failed: %d error(s)", len(report.errors))
            return empty_result("invalid", domain.terminology(), report.as_dict())

        sim = (scenario or {}).get("simulate") or {}
        plan = (sim.get("baseline") or {}).get("plan", "as-is")
        eval_model = _as_is(model) if plan == "as-is" else model

        # One consistent joint (system-scope) evaluation of the pinned config.
        scope_scenario = {**(scenario or {}), "optimisation_scope": "system"}
        result = run_model(
            eval_model,
            ScenarioConfig.from_dict(scope_scenario),
            terminology=domain.terminology(),
            report=report.as_dict(),
        )
        if result.get("status") != "optimal":
            return result

        result["outputs"]["lca"] = _lifecycle_inventory(result, model, sim)
        return result


def _as_is(model: Workbook) -> Workbook:
    """A view of ``model`` with the free-choice sheets removed (shallow — the kept
    sheets are shared, not copied, and never mutated)."""
    return {k: v for k, v in model.items() if k not in _FREE_CHOICE_SHEETS}


def _stage_map(model: Workbook) -> dict[str, str]:
    """Map each machine ``process_id`` to its value-chain **stage** — the nearest
    ancestor node with ``level == "company"`` (a lifecycle stage in a value-chain
    model). Falls back to the machine id when no company ancestor exists."""
    nodes = model.get("nodes", [])
    parent = {
        str(n.get("node_id")): (str(n["parent_id"]) if n.get("parent_id") else None) for n in nodes
    }
    level = {str(n.get("node_id")): str(n.get("level") or "") for n in nodes}

    def company(nid: str) -> str:
        cur: str | None = nid
        while cur is not None:
            if level.get(cur) == "company":
                return cur
            cur = parent.get(cur)
        return nid

    return {
        str(n.get("node_id")): company(str(n.get("node_id")))
        for n in nodes
        if str(n.get("kind")) == "machine"
    }


def _impact_factors(model: Workbook) -> dict[str, dict[str, float]]:
    """``technology_id -> {impact: factor}`` from the static ``io`` impact rows.

    (Per-year ``io_t`` factors are ignored in the P1 decomposition; the engine's
    authoritative per-impact totals still come from ``summary.impacts``.)"""
    factors: dict[str, dict[str, float]] = {}
    for r in model.get("io", []):
        if str(r.get("role")) != "impact":
            continue
        tech, imp = str(r.get("technology_id")), str(r.get("target"))
        coef = float(r.get("coefficient") or 0.0)
        if tech and imp and coef:
            factors.setdefault(tech, {})[imp] = coef
    return factors


def _functional_unit(
    model: Workbook, sim: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """The studied product + its total demanded amount over the horizon.

    Uses ``simulate.functional_unit`` when given, else the demanded commodity with
    the largest total amount (the natural product of the chain)."""
    demand = model.get("demand", [])
    fu = sim.get("functional_unit") or {}
    commodity = fu.get("commodity")
    if commodity is None:
        totals: dict[str, float] = {}
        for r in demand:
            totals[str(r.get("commodity_id"))] = totals.get(
                str(r.get("commodity_id")), 0.0
            ) + float(r.get("amount") or 0.0)
        commodity = max(totals, key=lambda k: totals[k]) if totals else None
    amount = sum(
        float(r.get("amount") or 0.0)
        for r in demand
        if str(r.get("commodity_id")) == commodity
        and (fu.get("company") is None or str(r.get("company")) == fu.get("company"))
    )
    return {"commodity": commodity, "amount": amount}


def _carbon_cost(result: dict[str, Any], model: Workbook) -> float:
    """Σ emissions × carbon price over (impact, period) from ``impact_prices``."""
    price: dict[tuple[str, int], float] = {}
    for r in model.get("impact_prices", []):
        price[(str(r.get("impact_id")), int(r.get("year") or 0))] = float(r.get("price") or 0.0)
    return sum(
        float(row["total"]) * price.get((str(row["impact"]), int(row["period"])), 0.0)
        for row in result["summary"]["impacts"]
    )


def _lifecycle_inventory(
    result: dict[str, Any], model: Workbook, sim: dict[str, Any]
) -> dict[str, Any]:
    """Decompose the solved configuration into a lifecycle inventory + cost."""
    out = result["outputs"]
    factors = _impact_factors(model)
    stage_of = _stage_map(model)

    # Per (stage, impact) emissions from throughput × static impact factor.
    by_stage: dict[tuple[str, str], float] = {}
    for row in out.get("throughput", []):
        tech, proc, val = str(row["technology"]), str(row["process"]), float(row["value"])
        stage = stage_of.get(proc, proc)
        for imp, coef in factors.get(tech, {}).items():
            by_stage[(stage, imp)] = by_stage.get((stage, imp), 0.0) + val * coef

    # Engine's authoritative per-impact totals.
    by_impact: dict[str, float] = {}
    for row in result["summary"]["impacts"]:
        by_impact[str(row["impact"])] = by_impact.get(str(row["impact"]), 0.0) + float(row["total"])

    fu = _functional_unit(model, sim, result)
    unit = fu["amount"] or 1.0
    total_cost = sum(float(p["cost"]) for p in result["summary"]["periods"])
    carbon_cost = _carbon_cost(result, model)

    return {
        "functional_unit": fu,
        "by_impact": [
            {"impact": i, "total": t, "per_unit": t / unit} for i, t in sorted(by_impact.items())
        ],
        "by_stage": [
            {"stage": s, "impact": i, "total": t, "per_unit": t / unit}
            for (s, i), t in sorted(by_stage.items())
            if abs(t) > 1e-9
        ],
        "cost": {
            "total": total_cost,
            "carbon": carbon_cost,
            "per_unit": total_cost / unit,
        },
    }
