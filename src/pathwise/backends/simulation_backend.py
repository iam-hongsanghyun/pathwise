"""Simulation backend: evaluate a FIXED configuration's lifecycle inventory.

Not an optimiser — a *what-if / LCA* lens over the **same** value-chain model
(``Workbook`` → ``Problem``), in the spirit of the ``macc`` backend: a different
SOLVE METHOD, not a new data format. Where ``linopy`` *chooses* technologies,
transitions, and measures to minimise cost, this backend **evaluates a pinned
configuration** and reports its lifecycle emission inventory and cost.

The **baseline** is the **as-is** configuration — the current plant with no
technology switching and no auto-adopted abatement (the *free-choice* sheets
``transitions`` / ``measures`` are stripped) — reported under ``outputs.lca``:

* ``by_impact``  — total emissions per impact (the engine's own totals), per
  functional unit;
* ``by_stage``   — those emissions decomposed across value-chain **stages**
  (company nodes = lifecycle stages), from ``throughput × impact factor``;
* ``cost``       — total system cost and the carbon cost (Σ emissions × price).

P2 (shipped) adds **variants** — a baseline plus a set of typed ``overrides``
(see :mod:`pathwise.backends.overrides`) — each evaluated the same way and folded
into ``outputs.variants``, with a baseline-vs-variant ``outputs.comparison``
(abatement, ex-carbon cost delta, $/impact-unit, break-even carbon price).

P3 (shipped) adds the **policy lever**: ``outputs.policy_sweep`` traces every
config's cost & emissions across a parametric carbon-price range (analytic for a
pinned config, re-solved when a measure is on the table), and
``outputs.cap_compliance`` checks each config's per-year emissions against the
``impact_caps`` (read from the full model; the caps are stripped before
evaluation so they cannot distort the inventory). The **use phase** needs no
engine change — it is authored as an ordinary process and shows up as its own
stage. See ``docs/proposals/simulation-backend.md``.
"""

from __future__ import annotations

from typing import Any

from pathwise.backends.overrides import OverrideError, apply_overrides
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

#: Emission-cap sheets are policy *targets* the simulator checks post-hoc (see
#: ``_cap_map`` / ``_compliance``), NOT constraints it should let bind during a
#: fixed-config evaluation — a binding cap would distort the very inventory we are
#: trying to measure (forcing demand slack). Read from the full model, evaluated
#: without them.
_CAP_SHEETS = ("impact_caps", "impact_caps_t__limit")

#: Everything stripped to build the evaluation view of a configuration.
_STRIP_FOR_EVAL = (*_FREE_CHOICE_SHEETS, *_CAP_SHEETS)


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
                "comparison": True,  # P2
                "policySweep": True,  # P3
                "capCompliance": True,  # P3
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

        # Baseline: the pinned configuration we diff variants against.
        plan = (sim.get("baseline") or {}).get("plan", "as-is")
        base_model = _as_is(model) if plan == "as-is" else model
        result = _evaluate(base_model, scenario, domain, report)
        if result.get("status") != "optimal":
            return result
        base_lca = _lifecycle_inventory(result, base_model, sim)
        result["outputs"]["lca"] = base_lca
        base_record = {
            "label": "baseline",
            "status": "optimal",
            "lca": base_lca,
            "model": base_model,
            "impacts": result["summary"]["impacts"],
        }

        # Variants (P2): each = baseline + a set of overrides → evaluate → diff.
        variants = sim.get("variants") or []
        try:
            evaluated = (
                _evaluate_variants(model, variants, scenario, domain, report, sim)
                if variants
                else []
            )
        except OverrideError as exc:
            rep = report.as_dict()
            rep["errors"].append(str(exc))
            logger.warning("variant override invalid: %s", exc)
            return empty_result("invalid", domain.terminology(), rep)

        configs = [base_record, *evaluated]
        if variants:
            impact = _primary_impact(base_lca)
            result["outputs"]["variants"] = [
                {"label": v["label"], "status": v["status"], "lca": v["lca"]} for v in evaluated
            ]
            result["outputs"]["comparison"] = [_compare(v, base_lca, impact) for v in evaluated]

        # Policy sweep (P3): cost & emissions of every config across a price range.
        sweep = sim.get("policy_sweep")
        if sweep:
            result["outputs"]["policy_sweep"] = _policy_sweep(
                configs, sweep, scenario, domain, report
            )

        # Cap compliance (P3): each config's per-year emissions vs the impact caps.
        caps = _cap_map(model)
        if caps:
            result["outputs"]["cap_compliance"] = [_compliance(c, caps) for c in configs]
        return result


def _as_is(model: Workbook) -> Workbook:
    """A view of ``model`` pinned for evaluation: free-choice sheets and emission
    caps removed (shallow — the kept sheets are shared, not copied, not mutated)."""
    return {k: v for k, v in model.items() if k not in _STRIP_FOR_EVAL}


def _evaluate(
    eval_model: Workbook, scenario: dict[str, Any], domain: Any, report: Any
) -> dict[str, Any]:
    """One consistent joint (system-scope) evaluation of a pinned configuration."""
    scope_scenario = {**(scenario or {}), "optimisation_scope": "system"}
    return run_model(
        eval_model,
        ScenarioConfig.from_dict(scope_scenario),
        terminology=domain.terminology(),
        report=report.as_dict(),
    )


def _evaluate_variants(
    model: Workbook,
    variants: list[dict[str, Any]],
    scenario: dict[str, Any],
    domain: Any,
    report: Any,
    sim: dict[str, Any],
) -> list[dict[str, Any]]:
    """Evaluate each variant (baseline + its overrides) and return its LCA.

    A variant inherits the baseline's *as-is* pinning (technology switching off);
    its ``overrides`` then perturb that — swap a machine's technology, change a
    price, or put a measure back on the table. The full ``model`` is the override
    *source* so ``toggle_measure on`` can re-introduce a stripped measure.
    """
    out: list[dict[str, Any]] = []
    for i, v in enumerate(variants):
        label = str(v.get("label") or f"variant {i + 1}")
        vmodel = apply_overrides(_as_is(model), v.get("overrides") or [], source=model)
        res = _evaluate(vmodel, scenario, domain, report)
        status = res.get("status")
        if status != "optimal":
            logger.warning("variant %r not optimal: %s", label, status)
            out.append(
                {"label": label, "status": status, "lca": None, "model": vmodel, "impacts": []}
            )
            continue
        out.append(
            {
                "label": label,
                "status": "optimal",
                "lca": _lifecycle_inventory(res, vmodel, sim),
                "model": vmodel,
                "impacts": res["summary"]["impacts"],
            }
        )
    return out


def _primary_impact(lca: dict[str, Any]) -> str:
    """The impact a comparison is keyed on: ``CO2`` if present, else the first."""
    impacts = [d["impact"] for d in lca.get("by_impact", [])]
    return "CO2" if "CO2" in impacts else (impacts[0] if impacts else "CO2")


def _impact_total(lca: dict[str, Any], impact: str) -> float:
    """Total of ``impact`` over the horizon from an LCA's ``by_impact``."""
    return next((float(d["total"]) for d in lca["by_impact"] if d["impact"] == impact), 0.0)


def _ex_carbon_cost(lca: dict[str, Any]) -> float:
    """System cost with the carbon cost removed — the basis for break-even."""
    return float(lca["cost"]["total"]) - float(lca["cost"]["carbon"])


def _compare(variant: dict[str, Any], base_lca: dict[str, Any], impact: str) -> dict[str, Any]:
    """Diff a variant against the baseline: abatement, cost delta, break-even price.

    Algorithm:
        With baseline/variant emissions ``E_b, E_v`` of ``impact`` and ex-carbon
        costs ``C_b, C_v``::

            abatement   = E_b - E_v                       # >0 ⇒ variant emits less
            cost_delta  = C_v - C_b                       # >0 ⇒ variant costs more
            $/unit      = cost_delta / abatement          # signed abatement cost
            break-even  = max(0, cost_delta / abatement)  # carbon price that flips
                                                          #   the choice (abatement>0)

        At carbon price ``p`` the variant's total cost is ``C_v + p·E_v``; it
        undercuts the baseline once ``p > cost_delta/abatement``. A variant that is
        both cheaper and cleaner breaks even at ``0`` (wins at any ``p ≥ 0``); one
        that emits *more* has no break-even (``None``).

        ASCII: abate = Eb-Ev; dcost = Cv-Cb; breakeven = max(0, dcost/abate).
    """
    label = variant["label"]
    var_lca = variant["lca"]
    if var_lca is None:
        return {"label": label, "status": variant["status"]}
    abatement = _impact_total(base_lca, impact) - _impact_total(var_lca, impact)
    cost_delta = _ex_carbon_cost(var_lca) - _ex_carbon_cost(base_lca)
    per_unit = cost_delta / abatement if abs(abatement) > 1e-9 else None
    breakeven = max(0.0, per_unit) if (abatement > 1e-9 and per_unit is not None) else None
    return {
        "label": label,
        "status": "optimal",
        "impact": impact,
        "abatement": abatement,
        "cost_delta": cost_delta,
        "abatement_cost_per_unit": per_unit,
        "breakeven_carbon_price": breakeven,
    }


# ── Policy sweep (P3) ─────────────────────────────────────────────────────────


def _is_pinned(eval_model: Workbook) -> bool:
    """True if the configuration has no free choices left (no measures /
    transitions). For a pinned config the physical flows — and hence emissions —
    do not move with the carbon price, so the sweep is exact arithmetic."""
    return not eval_model.get("measures") and not eval_model.get("transitions")


def _price_points(lo: float, hi: float, step: float, *, cap: int = 200) -> list[float]:
    """Inclusive ``[lo, hi]`` grid at ``step`` (single point if ``step <= 0``)."""
    if step <= 0 or hi <= lo:
        return [lo]
    n = min(cap, int((hi - lo) / step) + 1)
    pts = [lo + i * step for i in range(n)]
    if pts[-1] < hi - 1e-9:
        pts.append(hi)
    return pts


def _sweep_series(
    config: dict[str, Any],
    prices: list[float],
    impact: str,
    scenario: dict[str, Any],
    domain: Any,
    report: Any,
) -> dict[float, tuple[float | None, float | None]]:
    """``price -> (total_cost, emissions)`` for one configuration.

    A *pinned* config is evaluated analytically — ``cost(p) = ex_carbon + p·E``
    with constant emissions ``E``. A config with free choices (an available
    measure the LP may adopt under a price) is re-solved at each price.
    """
    if _is_pinned(config["model"]):
        ex = _ex_carbon_cost(config["lca"])
        emis = _impact_total(config["lca"], impact)
        return {p: (ex + p * emis, emis) for p in prices}

    series: dict[float, tuple[float | None, float | None]] = {}
    for p in prices:
        model_p = apply_overrides(
            config["model"], [{"op": "set_carbon_price", "impact": impact, "price": p}]
        )
        res = _evaluate(model_p, scenario, domain, report)
        if res.get("status") != "optimal":
            series[p] = (None, None)
            continue
        cost = sum(float(r["cost"]) for r in res["summary"]["periods"])
        emis = sum(float(r["total"]) for r in res["summary"]["impacts"] if r["impact"] == impact)
        series[p] = (cost, emis)
    return series


def _policy_sweep(
    configs: list[dict[str, Any]],
    sweep: dict[str, Any],
    scenario: dict[str, Any],
    domain: Any,
    report: Any,
) -> list[dict[str, Any]]:
    """Cost & emissions of every config across a parametric carbon-price range.

    The sweep is where simulation earns its keep: trace each config's total cost
    as the carbon price rises and read off the **break-even** price where a green
    variant overtakes the baseline. ``lever`` is fixed to ``carbon_price`` in P3.
    """
    impact = str(sweep.get("impact") or "CO2")
    prices = _price_points(
        float(sweep.get("from") or 0.0),
        float(sweep.get("to") or 0.0),
        float(sweep.get("step") or 0.0),
    )
    series = [
        (c["label"], _sweep_series(c, prices, impact, scenario, domain, report)) for c in configs
    ]
    return [
        {
            "carbon_price": p,
            "impact": impact,
            "variants": [
                {"label": label, "cost": s[p][0], "emissions": s[p][1]} for label, s in series
            ],
        }
        for p in prices
    ]


# ── Cap compliance (P3) ───────────────────────────────────────────────────────


def _cap_map(model: Workbook) -> dict[tuple[str, int], float]:
    """``(impact, year) -> total cap`` from ``impact_caps`` (summed over scopes).

    A row without a ``year`` applies its ``limit`` to every modelled year; rows
    are summed so several scoped caps roll up to one system cap per (impact, year).
    """
    years = sorted({int(r["year"]) for r in model.get("periods", []) if r.get("year") is not None})
    caps: dict[tuple[str, int], float] = {}
    for r in model.get("impact_caps", []):
        impact, limit = str(r.get("impact_id") or ""), r.get("limit")
        if not impact or limit is None:
            continue
        yr = r.get("year")
        targets = [int(yr)] if yr is not None else years
        for y in targets:
            caps[(impact, y)] = caps.get((impact, y), 0.0) + float(limit)
    return caps


def _compliance(config: dict[str, Any], caps: dict[tuple[str, int], float]) -> dict[str, Any]:
    """A configuration's per-year emissions vs the impact caps."""
    if config.get("status") != "optimal":
        return {"label": config["label"], "status": config.get("status")}
    emitted: dict[tuple[str, int], float] = {}
    for r in config.get("impacts", []):
        key = (str(r["impact"]), int(r["period"]))
        emitted[key] = emitted.get(key, 0.0) + float(r["total"])
    by_year: list[dict[str, Any]] = []
    compliant = True
    for (impact, year), cap in sorted(caps.items()):
        emis = emitted.get((impact, year), 0.0)
        over = emis - cap
        if over > 1e-6:
            compliant = False
        by_year.append(
            {
                "impact": impact,
                "year": year,
                "emissions": emis,
                "cap": cap,
                "over": max(0.0, over),
            }
        )
    return {
        "label": config["label"],
        "status": "optimal",
        "compliant": compliant,
        "by_year": by_year,
    }


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
