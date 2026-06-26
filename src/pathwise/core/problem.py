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
    Edge,
    Flow,
    Impact,
    Lever,
    Market,
    ObjectiveMode,
    Period,
    Process,
    Storage,
    Technology,
    Transition,
)


@dataclass(slots=True, frozen=True)
class Fleet:
    """A transport fleet asset class (Layer 1b/1c).

    A fleet is a pool of interchangeable carriers (ships, trucks, …) a company
    owns, defined by what it carries and how it moves, plus its lifecycle. Its
    routes (:class:`FleetRoute`) say which transport processes it may serve; the
    optimiser assigns whole units across them, year by year.

    Attributes:
        fleet_id: Stable id.
        company: Owning company (scope); ``"all"`` ⇒ unscoped.
        mode: Transport-mode tag (sea / road / rail / air) — used by the map + 1c.
        fuel: Flow id consumed per distance (priced + emitting in Phase 3).
        cargo: Flow id carried (the stream the fleet delivers).
        efficiency: Fuel use per unit cargo per unit distance
            [fuel unit / cargo unit / distance unit] (drives fuel cost + emissions
            once routes carry distance — Phase 3).
        capacity: Throughput one unit delivers per year
            [cargo unit / unit / yr] — the default per-route share when a route
            does not override it.
        count: Units in service within the lifecycle window [units].
        build_year: First in-service year (``None`` ⇒ always in service).
        close_year: Last in-service year (``None`` ⇒ from ``lifespan``, else never).
        lifespan: Service life [yr]; with ``build_year`` and no ``close_year`` the
            fleet retires after ``build_year + lifespan − 1``.
    """

    fleet_id: str
    company: str = "all"
    mode: str = ""
    fuel: str = ""
    cargo: str = ""
    efficiency: float = 0.0
    capacity: float = 0.0
    count: float = 0.0
    build_year: int | None = None
    close_year: int | None = None
    lifespan: int | None = None
    #: Optional physical ship params for distance-derived capacity (Layer 1c). When
    #: ``ship_size`` and ``speed`` are set, a route's per-carrier throughput is the
    #: round-trip model below; otherwise the flat ``capacity`` is used.
    ship_size: float = 0.0  # cargo carried per voyage [cargo unit]
    speed: float = 0.0  # travel speed [distance unit / day]
    turnaround_days: float = 0.0  # load + unload per round trip [days]
    operating_days: float = 350.0  # in-service days per year [days / yr]
    opex: float = 0.0  # per-carrier annual operating cost [currency / unit / yr]
    capex: float = 0.0  # per-carrier overnight capital cost [currency / unit]; >0 ⇒ the
    #: optimiser may BUILD carriers (an integer decision), charged via capex_charge over
    #: the fleet's lifespan. 0 (default) ⇒ the fleet is a fixed pool (today's behaviour).
    max_build: float | None = None  # optional cap on total carriers built over the horizon
    #: Owning fleet group + its full ancestor chain (alliance → company → … in the
    #: fleet registry) — so a cap/target keyed to ANY fleet group binds on the sum over
    #: its member fleets, exactly like a node group. Empty ⇒ no group scoping.
    scopes: frozenset[str] = frozenset()

    def in_scope(self, scope: str) -> bool:
        """Whether a constraint ``scope`` covers this fleet (``all`` / id / group chain)."""
        return scope == "all" or scope == self.fleet_id or scope in self.scopes

    def active(self, year: int) -> bool:
        """Whether the fleet is in service in ``year`` (within its lifecycle)."""
        if self.build_year is not None and year < self.build_year:
            return False
        close = self.close_year
        if close is None and self.build_year is not None and self.lifespan is not None:
            close = self.build_year + self.lifespan - 1
        return not (close is not None and year > close)

    def available_at(self, year: int) -> float:
        """Units available in ``year`` — ``count`` while in service, else 0."""
        return self.count if self.active(year) else 0.0

    def capacity_on(self, distance: float) -> float | None:
        r"""Per-carrier annual throughput on a route of length ``distance`` [cargo/yr].

        A longer route means fewer round trips per year, so each carrier delivers
        less — the reason a longer route needs more carriers for the same demand::

            round_trip_days = 2·distance / speed + turnaround_days
            capacity        = ship_size · operating_days / round_trip_days

        Returns ``None`` when the physical params are unset (caller falls back to the
        flat ``capacity``).
        """
        if self.ship_size <= 0 or self.speed <= 0 or distance <= 0:
            return None
        round_trip_days = 2.0 * distance / self.speed + self.turnaround_days
        if round_trip_days <= 0:
            return None
        return self.ship_size * self.operating_days / round_trip_days


@dataclass(slots=True, frozen=True)
class FleetRoute:
    """A fleet-managed transport process (Layer 1b).

    Attributes:
        process: The transport process (route) this row makes fleet-managed.
        fleet_id: Fleet whose shared pool serves this route — units on every route
            of a fleet sum to its ``fleet_available`` count (the lifecycle pool).
        share: Annual throughput one unit delivers on this route
            [cargo unit / unit / yr] (= voyages/yr × cargo). ``None`` ⇒ fall back
            to the owning fleet's ``capacity``.
        min_units: Floor on units assigned to this route [units].
        max_units: Ceiling on units assigned to this route ([units]; ``None`` ⇒ ∞).
    """

    process: str
    fleet_id: str
    share: float | None = None
    min_units: float = 0.0
    max_units: float | None = None


def leg_key(route: str, fleet: str) -> str:
    """Stable coord id for a (connection route, candidate fleet) pair."""
    return f"{route}\x1f{fleet}"


@dataclass(slots=True, frozen=True)
class ConnectionLeg:
    """A candidate fleet for a physicalised network connection (Layer 1c+).

    A connection route lists the fleets that *may* carry its stream; the optimiser
    picks which one(s) actually run it (some fleets per route, not all).

    Attributes:
        fleet_id: Candidate fleet whose carriers may serve this route.
        min_units: Floor on this fleet's carriers on this route [units].
        max_units: Ceiling on this fleet's carriers on this route ([units]; ``None`` ⇒ ∞).
    """

    fleet_id: str
    min_units: float = 0.0
    max_units: float | None = None


@dataclass(slots=True, frozen=True)
class ConnectionRoute:
    """A network stream connection made *physical* (Layer 1c+).

    A virtual connection (an :class:`Edge`, instant + free — "teleportation") becomes
    a physical route once its endpoints carry a location and it is given a transport
    mode + candidate fleets. Its flow is then carried by an integer count of carriers
    drawn from the fleets' shared pools, and the route's ``distance`` drives both how
    many carriers are needed and the fuel burned (cost + emissions). Untouched
    connections stay virtual (no ``ConnectionRoute`` ⇒ teleport).

    Attributes:
        process: Stable route key (``r_<from>__<to>__<flow>``).
        flow: The stream this route physicalises.
        distance: Route length [distance unit, e.g. km] — drives capacity + fuel.
        edges: Indices into :attr:`Problem.edges` this route governs (the fanned
            producer→consumer flows of the connection). The carriers carry exactly
            their summed flow.
        legs: Candidate fleets (the optimiser chooses among them).
        blocked: Scenario switch — close this corridor (its flow is forced to 0, so
            the stream must reroute or go undelivered: the Hormuz/Suez what-if).
        toll: Per-voyage transit fee [currency / voyage], summed over every maritime
            chokepoint this route traverses. Priced into the objective as
            ``toll · legflow / ship_size`` (voyages ≈ cargo / cargo-per-voyage),
            independent of the chokepoint's closure probability.
    """

    process: str
    flow: str
    distance: float
    edges: tuple[int, ...]
    legs: tuple[ConnectionLeg, ...] = ()
    blocked: bool = False
    toll: float = 0.0
    #: Scope ids this route's emissions attribute to (its origin node + every ancestor),
    #: so a group/company/region impact cap that contains the origin also binds the
    #: transport leaving it. ``"all"`` always matches (sector-wide).
    scope_chain: tuple[str, ...] = ()


def green_key(label: str, impact: str, year: int) -> str:
    """Stable slack/constraint key for a green-corridor cap (lane·impact·year)."""
    return f"{label}|{impact}|{year}"


@dataclass(slots=True)
class GreenCorridor:
    r"""A per-lane transport emission-intensity cap — a "green corridor".

    All freight on a lane (every mode/fleet carrying its flow) must keep its
    cargo-weighted emission intensity below ``limit`` for the capped impact::

        Σ legflow·efficiency·distance·flow_impact(fuel, impact)  ≤  limit · cargo

    so the optimiser must shift cargo onto cleaner modes/fuels (or build them) to
    keep the corridor green. Soft by default — exceedance is allowed at a penalty;
    set ``soft=False`` to forbid it (a hard regulatory corridor).

    Attributes:
        label: Readable lane id (``<from>→<to>·<flow>``) for keys + outputs.
        edges: Indices into :attr:`Problem.edges` for the lane this binds — matched
            against :attr:`ConnectionRoute.edges` so it applies to every mode on the lane.
        impact: The capped impact id (as defined in the model); characterised
            categories expand to their flow components.
        limits: ``{year: limit}`` intensity cap [impact-unit / cargo-unit].
        soft: Soft (penalised slack) vs hard (must hold).
        penalty: Per-unit exceedance penalty; ``0`` ⇒ the global slack penalty.
    """

    label: str
    edges: tuple[int, ...]
    impact: str
    limits: dict[int, float] = field(default_factory=dict)
    soft: bool = True
    penalty: float = 0.0


@dataclass(slots=True, frozen=True)
class Station:
    r"""Refuelling infrastructure at a scope — caps + prices a fleet's fuel.

    A station dispenses a fuel flow to the fleets in its ``company`` scope: their
    fuel demand (``Σ legflow·efficiency·distance``) must be served by that scope's
    stations, capacity-limited, at a per-unit fee on top of the fuel's own price::

        Σ_{stations in scope}  dispense = Σ fleet fuel demand in scope
        dispense ≤ refuel_capacity                                   (per station)

    Inert for fleets whose scope has no matching station (they refuel at the flat
    fuel price, as before). The dispensed fuel is the SAME fuel the fleet already
    draws — ``dispense`` only adds the infrastructure cap + fee, not a second draw.

    Attributes:
        station_id: Unique id.
        company: Scope it refuels (fleets in this scope); ``"all"`` ⇒ every fleet.
        refuel_flow: The fuel flow it dispenses.
        refuel_capacity: Max units dispensed per year (``0`` ⇒ unlimited).
        refuel_fee: Currency per unit dispensed, on top of the fuel price.
        capex: One-time overnight build cost [currency].
        fixed_opex: Annual fixed cost [currency/yr].
    """

    station_id: str
    company: str = "all"
    refuel_flow: str = ""
    refuel_capacity: float = 0.0
    refuel_fee: float = 0.0
    capex: float = 0.0
    fixed_opex: float = 0.0


@dataclass(slots=True, frozen=True)
class Route:
    """The physical geography of a transport process (Layer 1c).

    A route gives a transport process its endpoints, mode and length. The optimiser
    only consumes ``distance`` (it drives per-carrier capacity and, later, fuel/
    emissions); ``from_node``/``to_node``/``mode`` are for distance computation
    (:mod:`pathwise.routing`) and the map. ``distance`` is the authored value, or one
    derived from the endpoints' coordinates when left blank.

    Attributes:
        process: The transport process this route describes.
        from_node: Origin node id (carries lon/lat).
        to_node: Destination node id (carries lon/lat).
        mode: Transport mode (``sea`` / ``road`` / ``rail`` / …).
        distance: Route length [distance unit, e.g. km].
    """

    process: str
    from_node: str = ""
    to_node: str = ""
    mode: str = ""
    distance: float = 0.0


@dataclass(slots=True)
class CostToggles:
    """Which additive cost components enter the objective."""

    capex: bool = True
    renewal: bool = True
    opex: bool = True
    flow_cost: bool = True  # purchases minus sales
    impact_price: bool = True  # carbon price / ETS, per impact
    lever_capex: bool = True


@dataclass(slots=True)
class Problem:
    """A complete process-network optimisation instance.

    Attributes:
        periods: Ordered horizon periods.
        processes: Facilities/assets.
        technologies: Technology configs keyed by id.
        flows: Flows keyed by id.
        impacts: Impacts keyed by id.
        levers: MACC abatement levers.
        edges: Inter-process flow flows.
        transitions: Permitted technology changes (replace/renew) + compatibility.
        storages: Per-flow inter-year stores.
        markets: Priced buy/sell nodes (flow supply or tradable ETS).
        flow_impacts: Impact factor of consuming a flow, keyed by
            ``(flow_id, impact_id)`` [impact unit / flow unit].
        demand: Required product output, keyed by ``(company, flow_id, year)``
            [flow unit / yr].
        impact_caps: Upper limit on an impact, keyed by ``(company, impact_id, year)``
            [impact unit / yr]; company ``"all"`` ⇒ sector-wide.
        investment_budget: Max nominal capex spend, keyed by ``(company, year)``
            [currency / yr]; company ``"all"`` ⇒ sector-wide.
        min_production: Minimum delivered product, keyed by
            ``(company, flow_id, year)`` [flow unit / yr].
        max_production: Maximum delivered product (a hard ceiling), keyed by
            ``(company, flow_id, year)`` [flow unit / yr].
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
    flows: dict[str, Flow]
    impacts: dict[str, Impact]
    levers: list[Lever] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    storages: list[Storage] = field(default_factory=list)
    markets: list[Market] = field(default_factory=list)
    flow_impacts: dict[tuple[str, str], float] = field(default_factory=dict)
    # Optional year-varying override of ``flow_impacts`` (a flow's
    # carbon intensity can change over the horizon — e.g. a greening grid, or an
    # upstream network stage's pathway). Falls back to the static factor.
    flow_impacts_by_year: dict[tuple[str, str], dict[int, float]] = field(default_factory=dict)
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
    # Per-asset intake bounds on a consumed flow (the consumer side, the
    # mirror of min/max_production), keyed by ``(company, flow_id, year)``
    # [flow unit / yr]. min = required offtake (a take-or-pay floor on how
    # much the asset must consume); max = maximum purchase (an intake ceiling).
    min_consumption: dict[tuple[str, str, int], float] = field(default_factory=dict)
    max_consumption: dict[tuple[str, str, int], float] = field(default_factory=dict)
    # Upper bound on how many processes may run a technology in any one year
    # (fleet-wide adoption cap), keyed by technology id — e.g. only N greenfield
    # H2-DRI plants can exist by a given year.
    technology_caps: dict[str, int] = field(default_factory=dict)
    # ── Fleet (Layer 1b): a shared pool of carriers allocated across routes ───
    # ``fleets[fleet_id]`` = the asset class (cargo, capacity, lifecycle, …).
    # ``fleet_available[(fleet_id, year)]`` = units in service that year (derived
    # from the fleet's count + lifecycle, or supplied per-year). ``fleet_routes``
    # makes a transport process fleet-managed: its throughput is bounded by
    # ``units·capacity`` rather than a fixed capacity, and its units draw on the
    # fleet's shared pool — so carriers reallocate across routes (a MILP).
    fleets: dict[str, Fleet] = field(default_factory=dict)
    fleet_available: dict[tuple[str, int], float] = field(default_factory=dict)
    fleet_routes: dict[str, FleetRoute] = field(default_factory=dict)
    # ``routes[process]`` = a transport process's physical geography (endpoints,
    # mode, distance). Distance drives per-carrier capacity (Layer 1c); the rest is
    # for distance computation + the map. Inert unless transport routes are present.
    routes: dict[str, Route] = field(default_factory=dict)
    # Physicalised network connections (Layer 1c+): each carries an existing
    # flow Edge's flow with a chosen fleet (from a candidate set), distance →
    # carriers + fuel. Inert unless connection routes are present (then teleport is
    # the default for every connection without one). See ``build._connection_fleet``.
    connection_routes: list[ConnectionRoute] = field(default_factory=list)
    # Green corridors (Layer 1c+): per-lane transport emission-intensity caps. Inert
    # unless authored. See ``build._connection_fleet`` + ``GreenCorridor``.
    green_corridors: list[GreenCorridor] = field(default_factory=list)
    # Stations (Layer 1c+): refuelling infrastructure that caps + prices a fleet's
    # fuel within a scope. Inert unless authored. See ``build._stations``.
    stations: list[Station] = field(default_factory=list)
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
    # Unit-conversion issues recorded while assembling (a coefficient that could not
    # be converted to its stream's canonical unit was left as authored). Surfaced as
    # result validation WARNINGS so a silently-wrong coefficient is visible, not just
    # logged. Empty ⇒ every coefficient converted cleanly (or needed no conversion).
    unit_issues: tuple[str, ...] = ()

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

    def flow_impact(self, flow: str, impact: str, year: int) -> float:
        """Impact factor of consuming ``flow`` in ``year`` [impact / unit].

        Returns the year-varying factor when one is defined for that year,
        otherwise the static :attr:`flow_impacts` value (0 if unset).
        """
        traj = self.flow_impacts_by_year.get((flow, impact))
        if traj is not None and year in traj:
            return traj[year]
        return self.flow_impacts.get((flow, impact), 0.0)
