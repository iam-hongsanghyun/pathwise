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


class MeasureType(StrEnum):
    """The lever a MACC/measure pulls."""

    ENERGY_EFFICIENCY = "energy_efficiency"  # cut an input commodity's intensity
    EMISSION_REDUCTION = "emission_reduction"  # cut a (CO2) impact directly
    ENVIRONMENTAL = "environmental"  # cut a non-CO2 impact (SOx, NOx, …)


class CapexConvention(StrEnum):
    """How lump-sum capital is charged to the objective."""

    ANNUITY = "annuity"  # capital-recovery-factor annuity over lifetime
    NPV = "npv"  # full discounted lump at the event year


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
    """

    commodity_id: str
    kind: CommodityKind
    unit: str = "unit"
    price_by_year: dict[int, float] = field(default_factory=dict)
    sale_price_by_year: dict[int, float] = field(default_factory=dict)
    sellable: bool = True
    purchasable: bool | None = None

    def price(self, year: int) -> float:
        """Purchase price [currency/unit] in ``year`` (0 if unpriced)."""
        return self.price_by_year.get(year, 0.0)

    def sale_price(self, year: int) -> float:
        """Sale/disposal price [currency/unit] in ``year`` (0 if unset)."""
        return self.sale_price_by_year.get(year, 0.0)


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

    Rates are **per unit of process throughput**. Energy-efficiency measures cut
    ``input_intensity`` for their target commodity; emission/environmental
    measures cut ``direct_impact`` for their target impact.

    Attributes:
        technology_id: Unique id.
        lifespan: Economic lifetime [yr].
        introduction_year: First year the technology may be adopted [yr].
        actions: Allowed transition actions for this technology.
        capex_by_year: Replacement capital cost [currency / unit capacity] by year.
        renewal_by_year: Renewal cost [currency / unit capacity] by year.
        opex_by_year: Fixed operating cost [currency / unit throughput] by year.
        input_intensity: Input commodity use [commodity unit / throughput] by id.
        output_yield: Output commodity production [commodity unit / throughput] by id.
        direct_impact: Process (chemical) impact [impact unit / throughput] by id.
    """

    technology_id: str
    lifespan: int = 20
    introduction_year: int | None = None
    actions: frozenset[TransitionAction] = field(
        default_factory=lambda: frozenset(TransitionAction)
    )
    capex_by_year: dict[int, float] = field(default_factory=dict)
    renewal_by_year: dict[int, float] = field(default_factory=dict)
    opex_by_year: dict[int, float] = field(default_factory=dict)
    input_intensity: dict[str, float] = field(default_factory=dict)
    output_yield: dict[str, float] = field(default_factory=dict)
    direct_impact: dict[str, float] = field(default_factory=dict)

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
    """A facility/machine: one active technology per period, owned by a company.

    Attributes:
        process_id: Unique id.
        company: Owner/site group (for demand, caps, budgets).
        baseline_technology: Technology active at the horizon start.
        capacity: Nameplate throughput per year [throughput / yr].
        introduced_year: Year the baseline was installed [yr].
        capex: Overnight build cost [currency] (recorded; used for new builds).
        fixed_opex: Fixed annual cost while the facility operates [currency / yr].
        failure_rate: Unexpected-failure / forced-outage fraction [—], 0–1; the
            available throughput is ``capacity · (1 − failure_rate)``.
    """

    process_id: str
    company: str
    baseline_technology: str
    capacity: float
    introduced_year: int | None = None
    capex: float = 0.0
    fixed_opex: float = 0.0
    failure_rate: float = 0.0

    @property
    def available_capacity(self) -> float:
        """Throughput available after expected unplanned outages [throughput/yr]."""
        return self.capacity * (1.0 - self.failure_rate)


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


@dataclass(slots=True, frozen=True)
class Edge:
    """A directed commodity flow from one process's output to another's input.

    Attributes:
        from_process: Producer process id.
        to_process: Consumer process id.
        commodity_id: The commodity routed along this edge.
        max_flow: Optional per-period capacity [commodity unit / yr] (``None`` ⇒ ∞).
    """

    from_process: str
    to_process: str
    commodity_id: str
    max_flow: float | None = None


@dataclass(slots=True, frozen=True)
class MeasureBlock:
    """One piecewise step of a measure's cost curve.

    Attributes:
        reduction: Fractional reduction of the target at full adoption [—], 0–1.
        capex: Block capital cost [currency].
    """

    reduction: float
    capex: float


@dataclass(slots=True, frozen=True)
class Measure:
    """A MACC/measure adopted on a process to cut an input or an impact.

    Attributes:
        measure_id: Unique id.
        measure_type: Which lever (energy efficiency / emission / environmental).
        applies_to: Process id the measure can be installed on.
        target: Commodity id (energy efficiency) or impact id (reduction/environmental).
        lifetime: Economic lifetime [yr].
        blocks: Ordered piecewise blocks (cumulative reduction).
    """

    measure_id: str
    measure_type: MeasureType
    applies_to: str
    target: str
    lifetime: int = 15
    blocks: list[MeasureBlock] = field(default_factory=list)


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
    compatible: bool = True
