"""The assembled optimisation instance handed to the core builder.

A :class:`Problem` bundles the entity collections (from the workbook) with the
scenario-derived numeric settings (horizon, demand, caps, economics, toggles).
It contains no solver objects; :func:`pathwise.core.build.build` turns it into a
``linopy`` model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathwise.core.entities import (
    CapexConvention,
    Commodity,
    Edge,
    Impact,
    Market,
    Measure,
    ObjectiveMode,
    Period,
    Process,
    Storage,
    Technology,
    Transition,
)


@dataclass(slots=True, frozen=True)
class FleetRoute:
    """A fleet-managed transport process (Layer 1b).

    Attributes:
        process: The transport process (route) this row makes fleet-managed.
        archetype: Ship-class id whose shared pool serves this route — units on
            every route of an archetype sum to its ``fleet_available`` count.
        share: Annual throughput one ship of the archetype delivers on this route
            [commodity unit / ship / yr] (= voyages/yr × cargo).
        min_units: Floor on ships assigned to this route [ships].
        max_units: Ceiling on ships assigned to this route ([ships]; ``None`` ⇒ ∞).
    """

    process: str
    archetype: str
    share: float
    min_units: float = 0.0
    max_units: float | None = None


@dataclass(slots=True)
class CostToggles:
    """Which additive cost components enter the objective."""

    capex: bool = True
    renewal: bool = True
    opex: bool = True
    commodity_cost: bool = True  # purchases minus sales
    impact_price: bool = True  # carbon price / ETS, per impact
    measure_capex: bool = True


@dataclass(slots=True)
class Problem:
    """A complete process-network optimisation instance.

    Attributes:
        periods: Ordered horizon periods.
        processes: Facilities/machines.
        technologies: Technology configs keyed by id.
        commodities: Commodities keyed by id.
        impacts: Impacts keyed by id.
        measures: MACC/measures.
        edges: Inter-process commodity flows.
        transitions: Permitted technology changes (replace/renew) + compatibility.
        storages: Per-commodity inter-year stores.
        markets: Priced buy/sell nodes (commodity supply or tradable ETS).
        commodity_impacts: Impact factor of consuming a commodity, keyed by
            ``(commodity_id, impact_id)`` [impact unit / commodity unit].
        demand: Required product output, keyed by ``(company, commodity_id, year)``
            [commodity unit / yr].
        impact_caps: Upper limit on an impact, keyed by ``(company, impact_id, year)``
            [impact unit / yr]; company ``"all"`` ⇒ sector-wide.
        investment_budget: Max nominal capex spend, keyed by ``(company, year)``
            [currency / yr]; company ``"all"`` ⇒ sector-wide.
        min_production: Minimum delivered product, keyed by
            ``(company, commodity_id, year)`` [commodity unit / yr].
        max_production: Maximum delivered product (a hard ceiling), keyed by
            ``(company, commodity_id, year)`` [commodity unit / yr].
        company_objective: Per-company goal (``cost`` default, or ``profit``).
        discount_rate: Annual discount rate ``ρ`` [1/yr].
        base_year: Baseline period ``t₀``.
        capex_convention: NPV lump (default) or capital-recovery annuity — see
            :meth:`capex_charge`.
        slack_penalty: Objective penalty per unit demand/impact-cap violation.
        toggles: Which cost components are priced.
    """

    periods: list[Period]
    processes: list[Process]
    technologies: dict[str, Technology]
    commodities: dict[str, Commodity]
    impacts: dict[str, Impact]
    measures: list[Measure] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    storages: list[Storage] = field(default_factory=list)
    markets: list[Market] = field(default_factory=list)
    commodity_impacts: dict[tuple[str, str], float] = field(default_factory=dict)
    # Optional year-varying override of ``commodity_impacts`` (a commodity's
    # carbon intensity can change over the horizon — e.g. a greening grid, or an
    # upstream value-chain stage's pathway). Falls back to the static factor.
    commodity_impacts_by_year: dict[tuple[str, str], dict[int, float]] = field(default_factory=dict)
    # LCIA characterisation: ``{(flow_impact_id, category_id): factor}``. A category
    # impact's emission is the linear combination Σ_flow factor · emit[flow] — so an
    # impact category (GWP, acidification, …) is a *derived impact* and every
    # downstream mechanism (pricing, caps, ETS, the simulate inventory) treats it
    # like any other impact. A category id must also appear in ``impacts``. Empty ⇒
    # no characterisation (raw per-flow inventory only).
    characterisation: dict[tuple[str, str], float] = field(default_factory=dict)
    demand: dict[tuple[str, str, int], float] = field(default_factory=dict)
    impact_caps: dict[tuple[str, str, int], float] = field(default_factory=dict)
    # Per (company, impact): whether the cap is soft (exceedance allowed at a
    # penalty) or hard (must hold). Default soft preserves prior behaviour.
    impact_cap_soft: dict[tuple[str, str], bool] = field(default_factory=dict)
    impact_cap_penalty: dict[tuple[str, str], float] = field(default_factory=dict)
    # Per (company, impact): if True the limit is an INTENSITY (impact per unit of
    # product), so the cap is ``emit ≤ limit · production`` rather than ``emit ≤ limit``.
    impact_cap_intensity: dict[tuple[str, str], bool] = field(default_factory=dict)
    investment_budget: dict[tuple[str, int], float] = field(default_factory=dict)
    min_production: dict[tuple[str, str, int], float] = field(default_factory=dict)
    max_production: dict[tuple[str, str, int], float] = field(default_factory=dict)
    # Per-machine intake bounds on a consumed commodity (the consumer side, the
    # mirror of min/max_production), keyed by ``(company, commodity_id, year)``
    # [commodity unit / yr]. min = required offtake (a take-or-pay floor on how
    # much the machine must consume); max = maximum purchase (an intake ceiling).
    min_consumption: dict[tuple[str, str, int], float] = field(default_factory=dict)
    max_consumption: dict[tuple[str, str, int], float] = field(default_factory=dict)
    # Upper bound on how many processes may run a technology in any one year
    # (fleet-wide adoption cap), keyed by technology id — e.g. only N greenfield
    # H2-DRI plants can exist by a given year.
    technology_caps: dict[str, int] = field(default_factory=dict)
    # ── Fleet (Layer 1b): a shared pool of ships allocated across routes ──────
    # ``fleet_available[(archetype, year)]`` = ships of a class in existence that
    # year (an exogenous pool in 1b). ``fleet_routes[process_id]`` makes a
    # transport process fleet-managed: its throughput is bounded by
    # ``units·share`` rather than a fixed capacity, and its units draw on the
    # archetype's shared pool — so ships reallocate across routes (a MILP).
    fleet_available: dict[tuple[str, int], float] = field(default_factory=dict)
    fleet_routes: dict[str, FleetRoute] = field(default_factory=dict)
    company_objective: dict[str, ObjectiveMode] = field(default_factory=dict)
    # Default goal for companies without a company_config override (the run-level
    # objective set in the Optimisation tab). Falls back to COST.
    default_objective: ObjectiveMode = ObjectiveMode.COST
    # LCIA-aware objective blend: minimise ``cost_weight·cost +
    # impact_weight·Σ emit[objective_impact]`` (slack penalties always added). The
    # defaults (cost_weight 1, impact_weight 0, no objective_impact) reproduce plain
    # least-cost. A characterised category (e.g. GWP) is a valid ``objective_impact``.
    objective_impact: str | None = None
    impact_weight: float = 0.0
    cost_weight: float = 1.0
    # Vintage timing: when True, a facility may switch (replace) or rebuild (renew)
    # ONLY at end-of-life boundaries — years where ``(year - introduced_year) %
    # lifespan == 0`` — and must continue its current technology in between. Off by
    # default (facilities may re-invest in any year); opt-in for fleets that turn
    # over on a fixed vintage schedule (e.g. the steel model).
    vintage_timing: bool = False
    # Forced technology switches (the ``simulate`` backend only — the optimiser
    # never sets this). ``{process_id: (to_technology, year)}``: pin the process to
    # its baseline before ``year`` and to ``to_technology`` from ``year`` on, a
    # timed what-if intervention. The build fixes the active-technology variable
    # accordingly, exempts these cells from feasibility/lifecycle gating, and lets
    # the switch capex fire as usual. Default empty ⇒ no effect on any other run.
    forced_switches: dict[str, tuple[str, int]] = field(default_factory=dict)
    discount_rate: float = 0.08
    base_year: int = 0
    capex_convention: CapexConvention = CapexConvention.NPV
    slack_penalty: float = 1.0e9
    toggles: CostToggles = field(default_factory=CostToggles)

    @property
    def years(self) -> list[int]:
        """Ordered horizon years."""
        return [p.year for p in self.periods]

    @property
    def companies(self) -> list[str]:
        """Sorted distinct companies across all processes."""
        return sorted({p.company for p in self.processes})

    def discount_factor(self, year: int) -> float:
        r"""Discount factor ``DF_t = (1+ρ)^-(year - base_year)`` [—]."""
        return (1.0 + self.discount_rate) ** (-(year - self.base_year))

    def capex_charge(self, year: int, lifespan: int) -> float:
        r"""Objective coefficient on a lump capital cost incurred in ``year``.

        A capital outlay ``C`` [currency] on an asset of life ``L = lifespan``
        [yr] enters the objective as ``capex_charge · C`` on the event variable.
        The multiplier depends on :attr:`capex_convention`:

        Algorithm:
            $$\text{NPV: } \mathrm{DF}_{t}; \qquad
              \text{ANNUITY: } \mathrm{CRF}^{\text{due}}(\rho, L)\;
              \sum_{\substack{t'\in\text{years}\\ t \le t' < t+L}}
              \mathrm{DF}_{t'}\,\Delta_{t'}$$

            ASCII::

                NPV      -> DF[year]
                ANNUITY  -> CRF_due(rho, L) * sum(DF[t']*dur[t']
                                                  for t' in years if year<=t'<year+L)

            with the annuity-due recovery factor
            ``CRF_due(ρ, L) = CRF(ρ, L)/(1+ρ)`` and
            ``CRF(ρ, L) = ρ(1+ρ)^L / ((1+ρ)^L − 1)`` (``CRF_due → 1/L`` as ρ→0),
            ``Δ_{t'}`` the period duration [yr]. Payments start in the build year
            (so a last-year build is not free); the annuity-due factor makes the
            present value of the full stream equal the NPV lump when the asset's
            whole life lies inside the horizon. ANNUITY charges strictly less
            when the horizon truncates the life.

        Args:
            year: Event (build / renewal) year ``t`` [yr].
            lifespan: Asset economic life ``L`` [yr] (``< 1`` clamped to 1).

        Returns:
            The discount/annuitisation multiplier [—].
        """
        if self.capex_convention == CapexConvention.NPV:
            return self.discount_factor(year)
        life = max(int(lifespan), 1)
        rho = self.discount_rate
        crf = 1.0 / life if rho == 0.0 else rho * (1.0 + rho) ** life / ((1.0 + rho) ** life - 1.0)
        crf_due = crf / (1.0 + rho)
        dur = {p.year: p.duration_years for p in self.periods}
        horizon = sum(
            self.discount_factor(t) * dur.get(t, 1.0) for t in self.years if year <= t < year + life
        )
        return crf_due * horizon

    def objective_of(self, company: str) -> ObjectiveMode:
        """Objective mode for ``company`` (default :attr:`default_objective`)."""
        return self.company_objective.get(company, self.default_objective)

    def commodity_impact(self, commodity: str, impact: str, year: int) -> float:
        """Impact factor of consuming ``commodity`` in ``year`` [impact / unit].

        Returns the year-varying factor when one is defined for that year,
        otherwise the static :attr:`commodity_impacts` value (0 if unset).
        """
        traj = self.commodity_impacts_by_year.get((commodity, impact))
        if traj is not None and year in traj:
            return traj[year]
        return self.commodity_impacts.get((commodity, impact), 0.0)
