"""Domain entities for the process-network model.

These are plain, immutable-ish dataclasses with **no I/O and no solver types** —
the assembler (``data/assemble.py``) builds them from a workbook and the core
(``core/build.py``) reads them to construct the ``linopy`` model.

Units: every :class:`Commodity` and :class:`Impact` declares its own unit
string. Any quantity that references a commodity (intensity, yield, price,
impact factor, flow) is expressed in that commodity's unit, so the optimisation
matrix needs no cross-unit conversion. Units are validated (parseable by pint)
at assembly and used only at I/O boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CommodityKind(StrEnum):
    """What role a commodity stream plays (informational; the math is uniform)."""

    ENERGY = "energy"
    MATERIAL = "material"
    INDIRECT = "indirect"  # cooling water, compressed air, …
    PRODUCT = "product"
    BYPRODUCT = "byproduct"


class TransitionAction(StrEnum):
    """Allowed technology actions per period (mirrors systempathway)."""

    CONTINUE = "continue"  # keep running the current technology
    RENEW = "renew"  # rebuild same technology (renewal cost, resets life)
    REPLACE = "replace"  # switch to a different technology (capex)


class LeverType(StrEnum):
    """The lever a MACC/abatement option pulls."""

    ENERGY_EFFICIENCY = "energy_efficiency"  # cut an input commodity's intensity
    EMISSION_REDUCTION = "emission_reduction"  # cut a (CO2) impact directly
    ENVIRONMENTAL = "environmental"  # cut a non-CO2 impact (SOx, NOx, …)


class CapexConvention(StrEnum):
    """How lump-sum capital is charged to the objective.

    The engine default is :attr:`NPV` (the full discounted lump at the event
    year); :attr:`ANNUITY` spreads the cost as a capital-recovery-factor annuity
    over the asset's life and so charges less when the planning horizon ends
    before the asset's life does. The two are present-value equivalent for an
    asset whose full life fits inside the horizon.
    """

    ANNUITY = "annuity"  # capital-recovery-factor annuity over lifetime
    NPV = "npv"  # full discounted lump at the event year (default)


class ObjectiveMode(StrEnum):
    """A company's optimisation goal."""

    COST = "cost"  # minimise total cost; demand is a hard, slack-softened floor
    PROFIT = "profit"  # maximise profit; demand is the max sellable (produce less is OK)


@dataclass(slots=True, frozen=True)
class Period:
    """One horizon step.

    Attributes:
        year: Calendar year [yr].
        duration_years: Years this period represents [yr].
    """

    year: int
    duration_years: float = 1.0


@dataclass(slots=True, frozen=True)
class Commodity:
    """A flow stream consumed and/or produced by processes.

    Attributes:
        commodity_id: Unique id.
        kind: Role of the stream (energy/material/indirect/product/byproduct).
        unit: Declared unit string (pint-parseable), e.g. ``"MWh"``, ``"t"``.
        price_by_year: External purchase price [currency / unit] by year.
        sale_price_by_year: Revenue when sold/exported [currency / unit] by year
            (0 ⇒ free disposal; negative ⇒ disposal cost).
        sellable: Whether surplus output may be sold/wasted rather than routed.
        purchasable: Whether the stream may be bought externally. ``None`` ⇒ use
            the default rule (raw energy/material/indirect inputs that no
            technology produces are purchasable; products/by-products/intermediates
            are not — they must be made or routed).
        available_from: First year the stream may be bought externally [yr]
            (e.g. hydrogen infrastructure arriving in 2030).
        available_to: Last year the stream may be bought externally [yr]
            (e.g. a coal-purchase ban after 2040).
        max_purchase_by_year: Upper bound on the total external purchase of this
            stream across every process in a year [commodity unit / yr]; ``None``
            for a year ⇒ unlimited. Used to cap supply availability — e.g. a
            value-chain link feeding an upstream stage's produced volume in as
            the downstream stage's available supply.
        properties: Free-form physical characteristics of the stream, keyed by
            name → value [property's own unit] — e.g. ``{"temperature_C": 600}``
            for high-pressure steam, ``{"voltage_kV": 220}`` for grid power,
            ``{"lhv_MJ_per_kg": 42.7}`` for a fuel. Carried as metadata (shown in
            the UI, preserved on round-trip); the optimisation does not constrain
            on them yet — they document what the stream physically is and leave
            room for stream-matching rules later.
    """

    commodity_id: str
    kind: CommodityKind
    unit: str = "unit"
    price_by_year: dict[int, float] = field(default_factory=dict)
    sale_price_by_year: dict[int, float] = field(default_factory=dict)
    sellable: bool = True
    purchasable: bool | None = None
    available_from: int | None = None
    available_to: int | None = None
    max_purchase_by_year: dict[int, float] = field(default_factory=dict)
    properties: dict[str, float] = field(default_factory=dict)

    def price(self, year: int) -> float:
        """Purchase price [currency/unit] in ``year`` (0 if unpriced)."""
        return self.price_by_year.get(year, 0.0)

    def max_purchase(self, year: int) -> float | None:
        """Cap on total external purchase in ``year`` (``None`` ⇒ unlimited)."""
        return self.max_purchase_by_year.get(year)

    def sale_price(self, year: int) -> float:
        """Sale/disposal price [currency/unit] in ``year`` (0 if unset)."""
        return self.sale_price_by_year.get(year, 0.0)

    def available(self, year: int) -> bool:
        """Whether external purchase is allowed in ``year``."""
        if self.available_from is not None and year < self.available_from:
            return False
        return not (self.available_to is not None and year > self.available_to)


@dataclass(slots=True, frozen=True)
class Impact:
    """An environmental impact category (CO2, SOx, NOx, …).

    Attributes:
        impact_id: Unique id.
        unit: Declared unit string, e.g. ``"tCO2e"``, ``"kg"``.
        price_by_year: Price per unit impact [currency / unit] by year
            (carbon price / ETS for CO2; any pollutant priceable).
    """

    impact_id: str
    unit: str = "unit"
    price_by_year: dict[int, float] = field(default_factory=dict)

    def price(self, year: int) -> float:
        """Impact price [currency/unit] in ``year`` (0 if unpriced)."""
        return self.price_by_year.get(year, 0.0)


@dataclass(slots=True, frozen=True)
class Technology:
    """A process configuration: what it consumes, yields, costs, and emits.

    Rates are **per unit of process throughput**. Energy-efficiency levers cut
    ``input_intensity`` for their target commodity; emission/environmental
    levers cut ``direct_impact`` for their target impact.

    Attributes:
        technology_id: Unique id.
        lifespan: Economic lifetime [yr].
        introduction_year: Available-from year [yr] — first year the technology
            may be adopted (market availability; inclusive).
        phase_out_year: Available-to year [yr], **EXCLUSIVE** — the technology is
            unusable *from* this year (usable through ``phase_out_year − 1``), so a
            facility running it must transition or switch off by then. Per-asset
            once the technology is instanced.
        actions: Allowed transition actions for this technology.
        capex_by_year: Replacement capital cost [currency / unit capacity] by year.
        renewal_by_year: Renewal cost [currency / unit capacity] by year.
        opex_by_year: Fixed operating cost [currency / unit throughput] by year.
        input_intensity: Input commodity use [commodity unit / throughput] by id.
        output_yield: Output commodity production [commodity unit / throughput] by id.
        direct_impact: Process (chemical) impact [impact unit / throughput] by id.
        min_capacity_factor: Must-run floor — when this technology is active its
            throughput must be at least ``min_capacity_factor × available
            capacity`` [dimensionless, 0–1]. Captures a minimum business level
            (e.g. a blast furnace that cannot idle below a threshold).
        share_groups: Blend (mix) groups ``{group: {commodity: (min, max)}}``.
            Members of a group are substitutable inputs (e.g. a fuel mix) whose
            consumption sums to the group requirement; each member's share of
            that sum is bounded ``[min, max]`` [dimensionless, 0–1]. The optimiser
            picks the mix per period (so a fuel blend can shift coal→H2 over time).
        output_share_groups: Output slate groups ``{group: {commodity: (min,
            max)}}`` — the mirror of ``share_groups`` for co-products. Members
            are joint outputs (e.g. a cracker's ethylene / propylene / C4 slate)
            whose production sums to the group requirement; each member's share
            is bounded ``[min, max]`` [dimensionless, 0–1]. The optimiser picks
            the slate per period (so the product mix follows prices within the
            unit's physical flexibility). Non-grouped outputs keep fixed yields.

    Algorithm:
        For each blend group ``g`` of members ``C_g`` with requirement
        ``R_g = Σ_{c∈C_g} intensity_c`` and throughput ``x``::

            $$\\sum_{c\\in C_g} f_c = R_g\\,x,\\qquad
              \\underline{s}_c R_g\\,x \\le f_c \\le \\overline{s}_c R_g\\,x$$

            sum_c f_c = R_g * x ;  s_min_c * R_g * x <= f_c <= s_max_c * R_g * x

        where ``f_c`` [input unit] is member ``c``'s consumption. Non-grouped
        inputs keep the fixed form ``f_c = intensity_c · x``. Output slate
        groups apply the same form on the production side: for slate ``G`` with
        requirement ``R_G = Σ_{c∈G} yield_c``::

            $$\\sum_{c\\in G} \\tilde f_c = R_G\\,x,\\qquad
              \\underline{s}_c R_G\\,x \\le \\tilde f_c \\le \\overline{s}_c R_G\\,x$$

            sum_c fout_c = R_G * x ;  s_min_c * R_G * x <= fout_c <= s_max_c * R_G * x

        where ``fout_c`` [output unit] is member ``c``'s production.
    """

    technology_id: str
    lifespan: int = 20
    introduction_year: int | None = None
    phase_out_year: int | None = None
    actions: frozenset[TransitionAction] = field(
        default_factory=lambda: frozenset(TransitionAction)
    )
    capex_by_year: dict[int, float] = field(default_factory=dict)
    renewal_by_year: dict[int, float] = field(default_factory=dict)
    opex_by_year: dict[int, float] = field(default_factory=dict)
    input_intensity: dict[str, float] = field(default_factory=dict)
    output_yield: dict[str, float] = field(default_factory=dict)
    direct_impact: dict[str, float] = field(default_factory=dict)
    # Optional year-varying overrides of the scalar I/O coefficients — a recipe
    # whose energy intensity, yield, or process-emission factor improves over the
    # horizon (e.g. efficiency gains). Keyed by commodity/impact id → {year:
    # value}; the scalar dict above is the fallback for any (id, year) not set.
    input_intensity_by_year: dict[str, dict[int, float]] = field(default_factory=dict)
    output_yield_by_year: dict[str, dict[int, float]] = field(default_factory=dict)
    direct_impact_by_year: dict[str, dict[int, float]] = field(default_factory=dict)
    min_capacity_factor: float = 0.0
    #: Optional year-varying must-run floor; falls back to ``min_capacity_factor``.
    min_capacity_factor_by_year: dict[int, float] = field(default_factory=dict)
    share_groups: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    output_share_groups: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    # Optional year-varying share bounds ``{group: {commodity: {year: (min, max)}}}``
    # — e.g. a max coal share that declines over the horizon. Falls back to the
    # static ``share_groups`` / ``output_share_groups`` bounds.
    share_groups_by_year: dict[str, dict[str, dict[int, tuple[float, float]]]] = field(
        default_factory=dict
    )
    output_share_groups_by_year: dict[str, dict[str, dict[int, tuple[float, float]]]] = field(
        default_factory=dict
    )

    def grouped_inputs(self) -> set[str]:
        """Input commodities that belong to a blend (share) group."""
        return {c for members in self.share_groups.values() for c in members}

    def min_cf_at(self, year: int) -> float:
        """Must-run capacity-factor floor in ``year`` (year override, else scalar)."""
        return self.min_capacity_factor_by_year.get(year, self.min_capacity_factor)

    @staticmethod
    def _share_at(
        by_year: dict[str, dict[str, dict[int, tuple[float, float]]]],
        static: dict[str, dict[str, tuple[float, float]]],
        group: str,
        commodity: str,
        year: int,
    ) -> tuple[float, float]:
        traj = by_year.get(group, {}).get(commodity)
        if traj is not None and year in traj:
            return traj[year]
        return static.get(group, {}).get(commodity, (0.0, 1.0))

    def input_share_at(self, group: str, commodity: str, year: int) -> tuple[float, float]:
        """Blend-member ``(min, max)`` share bounds in ``year`` [—]."""
        return self._share_at(self.share_groups_by_year, self.share_groups, group, commodity, year)

    def output_share_at(self, group: str, commodity: str, year: int) -> tuple[float, float]:
        """Slate-member ``(min, max)`` share bounds in ``year`` [—]."""
        return self._share_at(
            self.output_share_groups_by_year, self.output_share_groups, group, commodity, year
        )

    def input_intensity_at(self, commodity: str, year: int) -> float:
        """Input use of ``commodity`` per throughput in ``year`` [commodity unit]."""
        traj = self.input_intensity_by_year.get(commodity)
        if traj is not None and year in traj:
            return traj[year]
        return self.input_intensity.get(commodity, 0.0)

    def output_yield_at(self, commodity: str, year: int) -> float:
        """Output of ``commodity`` per throughput in ``year`` [commodity unit]."""
        traj = self.output_yield_by_year.get(commodity)
        if traj is not None and year in traj:
            return traj[year]
        return self.output_yield.get(commodity, 0.0)

    def direct_impact_at(self, impact: str, year: int) -> float:
        """Process (chemical) emission of ``impact`` per throughput in ``year``."""
        traj = self.direct_impact_by_year.get(impact)
        if traj is not None and year in traj:
            return traj[year]
        return self.direct_impact.get(impact, 0.0)

    def group_requirement_at(self, group: str, year: int) -> float:
        """Blend-group requirement in ``year`` (uses year-varying intensities)."""
        return sum(self.input_intensity_at(c, year) for c in self.share_groups.get(group, {}))

    def grouped_outputs(self) -> set[str]:
        """Output commodities that belong to a slate (output share) group."""
        return {c for members in self.output_share_groups.values() for c in members}

    def output_group_requirement_at(self, group: str, year: int) -> float:
        """Slate-group requirement in ``year`` (uses year-varying yields)."""
        return sum(self.output_yield_at(c, year) for c in self.output_share_groups.get(group, {}))

    def capex(self, year: int) -> float:
        """Replacement capex [currency/unit capacity] in ``year``."""
        return self.capex_by_year.get(year, 0.0)

    def renewal(self, year: int) -> float:
        """Renewal cost [currency/unit capacity] in ``year``."""
        return self.renewal_by_year.get(year, 0.0)

    def opex(self, year: int) -> float:
        """Fixed opex [currency/unit throughput] in ``year``."""
        return self.opex_by_year.get(year, 0.0)


@dataclass(slots=True, frozen=True)
class Process:
    """A facility/asset: one active technology per period, owned by a company.

    Attributes:
        process_id: Unique id.
        company: Demand/economic scope (the entity that must meet its demand).
        group: Higher-level grouping for constraint scoping (e.g. the owning
            company when ``company`` is used per ship-type). Defaults to
            ``company``. Constraints (caps) may be scoped to a facility id, a
            company, a group, or ``"all"`` — see :meth:`in_scope`.
        baseline_technology: Technology active at the horizon start.
        capacity: Nameplate throughput per year [throughput / yr].
        introduced_year: Build year [yr] — the asset is **off before it** (it
            does not exist yet). Also the install date used for lifecycle ageing.
        capex: Overnight build cost [currency] (recorded; used for new builds).
        fixed_opex: Fixed annual cost while the facility operates [currency / yr].
        failure_rate: Unexpected-failure / forced-outage fraction [—], 0–1; the
            available throughput is ``capacity · (1 − failure_rate)``.
        replaceable: If ``False`` the facility may not transition technologies
            (feasible set = baseline only) — the user marks it fixed.
        decommission_year: Close year [yr], **EXCLUSIVE** — the facility is off
            *from* this year (it runs through ``decommission_year − 1``). Together
            with ``introduced_year`` it defines the active window
            ``[introduced_year, decommission_year)``, which overrides the lifespan.
        max_renewals: Per-asset cap on the **total number of renewals**
            (same-technology rebuilds) over the whole horizon [count]. ``None`` ⇒
            unlimited (the asset may rebuild every lifespan indefinitely). ``0`` ⇒
            no renewal allowed at this asset, so once a vintage expires it must
            *replace* (switch technology) or switch off. ``N`` ⇒ at most ``N``
            rebuilds, after which it must replace — the "reline a BF-BOF N times,
            then build new" rule. Only binds when the asset is lifecycle-tracked
            (i.e. it declares :attr:`introduced_year`); a renewal also still
            requires the active technology to permit
            :attr:`TransitionAction.RENEW`.
    """

    process_id: str
    company: str
    baseline_technology: str
    capacity: float
    introduced_year: int | None = None
    capex: float = 0.0
    fixed_opex: float = 0.0
    failure_rate: float = 0.0
    replaceable: bool = True
    #: Per-asset total renewal-count cap over the horizon; ``None`` ⇒ unlimited,
    #: ``0`` ⇒ renewal forbidden (must replace at end of life). See class docstring.
    max_renewals: int | None = None
    capacity_by_year: dict[int, float] = field(default_factory=dict)
    #: Optional year-varying fixed O&M [currency / yr]; falls back to ``fixed_opex``.
    fixed_opex_by_year: dict[int, float] = field(default_factory=dict)
    #: Optional year-varying forced-outage fraction; falls back to ``failure_rate``.
    failure_rate_by_year: dict[int, float] = field(default_factory=dict)
    #: Per-asset utilisation ceiling [0–1]: throughput ≤ ``max_capacity_factor ×
    #: available capacity``. 1.0 ⇒ no extra ceiling (nameplate capacity is the cap).
    max_capacity_factor: float = 1.0
    #: Optional year-varying utilisation ceiling; falls back to ``max_capacity_factor``.
    max_capacity_factor_by_year: dict[int, float] = field(default_factory=dict)
    group: str = ""
    decommission_year: int | None = None
    scopes: frozenset[str] = frozenset()
    #: Per-FACILITY direct emission intensity [impact unit / throughput], by impact
    #: id — added ON TOP of the baseline technology's own ``direct_impact``. Lets
    #: two facilities running the SAME technology carry different real emission
    #: factors (e.g. plant-specific energy intensity), without a unique technology
    #: per facility. Empty ⇒ no facility-level term.
    direct_impact: dict[str, float] = field(default_factory=dict)
    #: Optional year-varying override of ``direct_impact`` (impact → {year: factor}).
    direct_impact_by_year: dict[str, dict[int, float]] = field(default_factory=dict)

    def fixed_opex_at(self, year: int) -> float:
        """Fixed annual O&M in ``year`` [currency / yr] (year override, else scalar)."""
        return self.fixed_opex_by_year.get(year, self.fixed_opex)

    def capacity_at(self, year: int) -> float:
        """Nameplate throughput in ``year`` (year override, else scalar)."""
        return self.capacity_by_year.get(year, self.capacity)

    def max_cf_at(self, year: int) -> float:
        """Utilisation-ceiling capacity factor in ``year`` (override, else scalar)."""
        return self.max_capacity_factor_by_year.get(year, self.max_capacity_factor)

    def direct_impact_at(self, impact: str, year: int) -> float:
        """Facility-level direct emission of ``impact`` per throughput in ``year``."""
        traj = self.direct_impact_by_year.get(impact)
        if traj is not None and year in traj:
            return traj[year]
        return self.direct_impact.get(impact, 0.0)

    def in_scope(self, scope: str) -> bool:
        """Whether this facility is covered by a constraint ``scope``.

        A scope matches ``"all"``, the facility id, its company, or its group.
        For a node hierarchy ``scopes`` holds the asset's full ancestor chain,
        so a cap / market / demand can be applied at ANY designed level (sector /
        company / facility / asset / all), not just the canonical three.
        """
        return (
            scope == "all"
            or scope in self.scopes
            or scope in {self.process_id, self.company, self.group or self.company}
        )

    def available(self, year: int) -> float:
        """Available throughput in ``year`` (temporal capacity × uptime)."""
        cap = self.capacity_by_year.get(year, self.capacity)
        fr = self.failure_rate_by_year.get(year, self.failure_rate)
        return cap * (1.0 - fr)


@dataclass(slots=True, frozen=True)
class Storage:
    """A per-commodity store that carries inventory across periods (years).

    Lets the system buy a commodity in cheap years and release it in expensive
    ones. Operates over the ``company`` scope (``"all"`` ⇒ every process).

    Attributes:
        storage_id: Unique id.
        commodity_id: The stored commodity.
        company: Scope this store serves (``"all"`` ⇒ all processes).
        max_capacity: Upper bound on built capacity [commodity unit].
        capex_per_capacity: Overnight build cost [currency / commodity unit].
        fixed_opex_per_capacity: Annual fixed cost [currency / (unit·yr)].
        charge_efficiency: Fraction of charged commodity that reaches the level [—].
        discharge_efficiency: Fraction of removed level that reaches the market [—].
        standing_loss: Fraction of level lost per year [—].
        initial_level: Inventory at the horizon start [commodity unit].
    """

    storage_id: str
    commodity_id: str
    company: str = "all"
    max_capacity: float = 0.0
    capex_per_capacity: float = 0.0
    fixed_opex_per_capacity: float = 0.0
    charge_efficiency: float = 1.0
    discharge_efficiency: float = 1.0
    standing_loss: float = 0.0
    initial_level: float = 0.0
    # Optional year-varying overrides; each falls back to the scalar above.
    # (``max_capacity`` and ``initial_level`` are one-time/structural and stay
    # scalar by design.)
    capex_per_capacity_by_year: dict[int, float] = field(default_factory=dict)
    fixed_opex_per_capacity_by_year: dict[int, float] = field(default_factory=dict)
    charge_efficiency_by_year: dict[int, float] = field(default_factory=dict)
    discharge_efficiency_by_year: dict[int, float] = field(default_factory=dict)
    standing_loss_by_year: dict[int, float] = field(default_factory=dict)

    def capex_per_capacity_at(self, year: int) -> float:
        """Overnight build cost in ``year`` [currency / unit] (override, else scalar)."""
        return self.capex_per_capacity_by_year.get(year, self.capex_per_capacity)

    def fixed_opex_per_capacity_at(self, year: int) -> float:
        """Annual fixed cost in ``year`` [currency / (unit·yr)] (override, else scalar)."""
        return self.fixed_opex_per_capacity_by_year.get(year, self.fixed_opex_per_capacity)

    def charge_efficiency_at(self, year: int) -> float:
        """Charge efficiency in ``year`` [—] (override, else scalar)."""
        return self.charge_efficiency_by_year.get(year, self.charge_efficiency)

    def discharge_efficiency_at(self, year: int) -> float:
        """Discharge efficiency in ``year`` [—] (override, else scalar)."""
        return self.discharge_efficiency_by_year.get(year, self.discharge_efficiency)

    def standing_loss_at(self, year: int) -> float:
        """Standing loss in ``year`` [—] (override, else scalar)."""
        return self.standing_loss_by_year.get(year, self.standing_loss)


@dataclass(slots=True, frozen=True)
class Edge:
    """A directed commodity flow from one process's output to another's input.

    Attributes:
        from_process: Producer process id.
        to_process: Consumer process id.
        commodity_id: The commodity routed along this edge.
        max_flow: Optional per-period capacity [commodity unit / yr] (``None`` ⇒ ∞).
        max_flow_by_year: Optional year-varying cap; falls back to ``max_flow``.
        min_flow: Optional per-period floor [commodity unit / yr] (``None`` ⇒ 0) —
            a take-or-pay off-take on this provider→consumer link.
        min_flow_by_year: Optional year-varying floor; falls back to ``min_flow``.
        cost: Optional freight cost [currency / commodity unit] charged on the flow —
            the physical cost of moving the stream over this link (0 ⇒ free, today's
            default). Enters the objective as ``cost · flow``.
        emissions: Optional freight emissions ``{impact_id: factor}`` [impact unit /
            commodity unit] of moving the stream — each priced at *its own* impact's
            price in the objective and reported (impact-agnostic; any/all impacts).
        energy: Optional freight energy intensity [energy unit / commodity unit] of the
            move — reported (informational; not balanced against a carrier in v1).
    """

    from_process: str
    to_process: str
    commodity_id: str
    max_flow: float | None = None
    max_flow_by_year: dict[int, float] = field(default_factory=dict)
    min_flow: float | None = None
    min_flow_by_year: dict[int, float] = field(default_factory=dict)
    #: Optional availability window [yr]: outside it this provider→consumer link
    #: carries zero flow. Different windows on competing links ⇒ alternative supply.
    available_from: int | None = None
    available_to: int | None = None
    #: Delivery lag [yr]: flow leaving the producer in year ``t`` arrives at the
    #: consumer in ``t + lag_years`` (a recycling / use-phase return). 0 ⇒ same year.
    lag_years: int = 0
    #: Optional per-unit transport physics (the spatial-transport layer). Untagged
    #: links stay free (cost = energy = 0, emissions = {}), so this is opt-in per
    #: stream. ``emissions`` maps any impact id → factor (no privileged impact).
    cost: float = 0.0
    emissions: dict[str, float] = field(default_factory=dict)
    energy: float = 0.0

    def available(self, year: int) -> bool:
        """Whether this link may carry flow in ``year`` (within its window)."""
        if self.available_from is not None and year < self.available_from:
            return False
        return not (self.available_to is not None and year > self.available_to)

    def max_flow_at(self, year: int) -> float | None:
        """Edge capacity in ``year`` [commodity unit / yr] (override, else scalar; ``None`` ⇒ ∞)."""
        return self.max_flow_by_year.get(year, self.max_flow)

    def min_flow_at(self, year: int) -> float | None:
        """Edge floor in ``year`` [commodity unit / yr] (override, else scalar; ``None`` ⇒ 0)."""
        return self.min_flow_by_year.get(year, self.min_flow)


@dataclass(slots=True, frozen=True)
class LeverBlock:
    """One piecewise step of a lever's cost curve.

    Attributes:
        reduction: Fractional reduction of the target at full adoption [—], 0–1.
        capex: Block capital cost — a one-off lump at adoption [currency].
        opex: Block fixed operating cost while adopted, per year at full
            adoption [currency / yr]. Charged every period in proportion to the
            adoption level (so a half-adopted block pays half its opex).
    """

    reduction: float
    capex: float
    opex: float = 0.0
    #: Per-year overrides of the scalar block cost (absolute currency, already
    #: scaled to the instance) and reduction. Empty → the scalar applies every year.
    capex_by_year: dict[int, float] = field(default_factory=dict)
    opex_by_year: dict[int, float] = field(default_factory=dict)
    reduction_by_year: dict[int, float] = field(default_factory=dict)

    def capex_at(self, year: int) -> float:
        """Block adoption capex in ``year`` (per-year override, else the scalar)."""
        return self.capex_by_year.get(year, self.capex)

    def opex_at(self, year: int) -> float:
        """Block fixed O&M in ``year`` (per-year override, else the scalar)."""
        return self.opex_by_year.get(year, self.opex)

    def reduction_at(self, year: int) -> float:
        """Block reduction fraction in ``year`` (per-year override, else the scalar)."""
        return self.reduction_by_year.get(year, self.reduction)


@dataclass(slots=True, frozen=True)
class Lever:
    """A MACC abatement lever adopted on a process to cut an input or an impact.

    Attributes:
        lever_id: Unique id.
        lever_type: Which lever (energy efficiency / emission / environmental).
        applies_to: Process id the lever can be installed on.
        target: Commodity id (energy efficiency) or impact id (reduction/environmental).
        lifetime: Economic lifetime [yr].
        blocks: Ordered piecewise blocks (cumulative reduction).
    """

    lever_id: str
    lever_type: LeverType
    applies_to: str
    target: str
    lifetime: int = 15
    blocks: list[LeverBlock] = field(default_factory=list)


class MarketTarget(StrEnum):
    """What a market trades."""

    COMMODITY = "commodity"  # priced supply/offtake of a stream (KEPCO/PPA/JKM)
    IMPACT = "impact"  # tradable allowances for an impact (ETS)


@dataclass(slots=True, frozen=True)
class Market:
    """A priced buy/sell node for a commodity or an impact (ETS allowances).

    Commodity markets supply (and optionally absorb) a stream at a price, up to
    volume caps — multiple markets on one stream give a least-cost mixture, and
    tags (e.g. ``"RE100"``) label green sources. Impact markets are tradable ETS:
    a free ``allocation`` per year, with deficits bought and surplus sold.

    Attributes:
        market_id: Unique id.
        target: Commodity id or impact id traded.
        target_kind: Whether ``target`` is a commodity or an impact.
        company: Scope served (``"all"`` ⇒ sector-wide).
        price_by_year: Buy price [currency / unit] by year.
        sell_price_by_year: Sell/offtake price [currency / unit] by year.
        max_buy: Max bought per year [unit] (``None`` ⇒ unlimited).
        max_sell: Max sold per year [unit] (``None`` ⇒ unlimited).
        allocation_by_year: Free ETS allowance per year [impact unit] (impact only).
        tag: Optional label (e.g. ``"RE100"``).
    """

    market_id: str
    target: str
    target_kind: MarketTarget = MarketTarget.COMMODITY
    company: str = "all"
    available_from: int | None = None
    available_to: int | None = None
    price_by_year: dict[int, float] = field(default_factory=dict)
    sell_price_by_year: dict[int, float] = field(default_factory=dict)
    max_buy: float | None = None
    max_sell: float | None = None
    #: Optional year-varying volume caps [unit / yr]; fall back to the scalars.
    max_buy_by_year: dict[int, float] = field(default_factory=dict)
    max_sell_by_year: dict[int, float] = field(default_factory=dict)
    allocation_by_year: dict[int, float] = field(default_factory=dict)
    tag: str | None = None

    def price(self, year: int) -> float:
        """Buy price [currency/unit] in ``year``."""
        return self.price_by_year.get(year, 0.0)

    def max_buy_at(self, year: int) -> float | None:
        """Max bought in ``year`` [unit] (year override, else scalar; ``None`` ⇒ ∞)."""
        return self.max_buy_by_year.get(year, self.max_buy)

    def max_sell_at(self, year: int) -> float | None:
        """Max sold in ``year`` [unit] (year override, else scalar; ``None`` ⇒ ∞)."""
        return self.max_sell_by_year.get(year, self.max_sell)

    def sell_price(self, year: int) -> float:
        """Sell price [currency/unit] in ``year`` (falls back to buy price)."""
        return self.sell_price_by_year.get(year, self.price(year))

    def allocation(self, year: int) -> float:
        """Free allowance [impact unit] in ``year`` (0 if unset)."""
        return self.allocation_by_year.get(year, 0.0)

    def available_in(self, year: int) -> bool:
        """Whether the market may trade in ``year``."""
        if self.available_from is not None and year < self.available_from:
            return False
        return not (self.available_to is not None and year > self.available_to)


@dataclass(slots=True, frozen=True)
class Transition:
    """A permitted technology change and its cost/compatibility.

    Attributes:
        from_technology: Current technology id.
        to_technology: Target technology id.
        action: ``replace`` or ``renew``.
        capex_per_capacity: Capital cost [currency / unit capacity].
        compatible: If ``True``, adjacent (connected) processes need not change
            (the existing kit is reusable); if ``False``, an incompatible swap
            forces connected processes to change too.
    """

    from_technology: str
    to_technology: str
    action: TransitionAction = TransitionAction.REPLACE
    capex_per_capacity: float = 0.0
    #: Optional year-varying capital cost [currency / unit capacity]; falls back
    #: to the scalar ``capex_per_capacity``.
    capex_per_capacity_by_year: dict[int, float] = field(default_factory=dict)
    compatible: bool = True

    def capex_at(self, year: int) -> float:
        """Transition capital cost in ``year`` [currency/unit capacity]."""
        return self.capex_per_capacity_by_year.get(year, self.capex_per_capacity)
