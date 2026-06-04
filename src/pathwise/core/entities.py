"""Domain-agnostic entities for the optimisation model.

These dataclasses are the vocabulary the generic core understands. A *sector
pack* (e.g. shipping) translates its own terms (ship, engine, fuel, GFI) into
these objects; the core never sees sector vocabulary.

Nothing here performs I/O or builds a solver model — these are plain data
holders. See :mod:`pathwise.core.problem` for the container that bundles them
and :mod:`pathwise.core.builder` for the translation into a ``linopy`` model.

Units (kept as plain floats here; validated/normalised at the data boundary via
:mod:`pathwise.units`):

* energy ............ MJ
* activity .......... domain-defined (e.g. nautical-mile, tonne-km)
* emission .......... gCO2e (intensities) / tCO2e (absolute abatement)
* emission intensity  gCO2e/MJ
* currency .......... USD (or the scenario currency)
* specific energy ... MJ / activity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TargetType(StrEnum):
    """How a :class:`Target` limit is interpreted."""

    INTENSITY_CAP = "intensity_cap"  # gCO2e/MJ, fleet-energy-weighted
    ABSOLUTE_CAP = "absolute_cap"  # tCO2e total over the group


class CapexConvention(StrEnum):
    """How lump-sum capital cost enters the (per-period) objective."""

    ANNUITY = "annuity"  # spread over economic life via capital recovery factor
    NPV = "npv"  # full discounted cost in the commissioning period


@dataclass(slots=True)
class Period:
    """A modelled point on the planning horizon.

    Attributes:
        year: Calendar year (the period label and ordering key).
        duration_years: Span this period represents, ``Δt`` [yr]; used to weight
            per-year flows when periods are multi-year steps.
    """

    year: int
    duration_years: float = 1.0


@dataclass(slots=True)
class Carrier:
    """A blendable consumable input with a price and an emission intensity.

    Attributes:
        carrier_id: Stable identifier.
        intensity_by_year: Well-to-wake emission intensity [gCO2e/MJ] keyed by
            year. Missing years fall back to :attr:`intensity_default`.
        price_by_year: Energy price [USD/MJ] keyed by year. Missing years fall
            back to :attr:`price_default`.
        intensity_default: Fallback intensity [gCO2e/MJ].
        price_default: Fallback price [USD/MJ].
        carrier_class: Optional grouping label for class-level limits.
    """

    carrier_id: str
    intensity_by_year: dict[int, float] = field(default_factory=dict)
    price_by_year: dict[int, float] = field(default_factory=dict)
    intensity_default: float = 0.0
    price_default: float = 0.0
    carrier_class: str | None = None

    def intensity(self, year: int) -> float:
        """Emission intensity [gCO2e/MJ] in ``year``."""
        return self.intensity_by_year.get(year, self.intensity_default)

    def price(self, year: int) -> float:
        """Energy price [USD/MJ] in ``year``."""
        return self.price_by_year.get(year, self.price_default)


@dataclass(slots=True)
class Technology:
    """A configuration an asset can run, gating carriers and setting energy use.

    Attributes:
        technology_id: Stable identifier.
        specific_energy: Energy required per unit activity, ``SEC`` [MJ/activity].
        allowed_carriers: Carrier ids this technology may consume.
        carrier_share_min: Lower bound on each carrier's energy share [-], by
            ``carrier_id`` (default 0).
        carrier_share_max: Upper bound on each carrier's energy share [-], by
            ``carrier_id`` (default 1).
        fixed_opex_by_year: Fixed O&M [USD/(size·yr)] keyed by year.
        fixed_opex_default: Fallback fixed O&M [USD/(size·yr)].
        technology_class: Optional grouping label.
    """

    technology_id: str
    specific_energy: float
    allowed_carriers: frozenset[str] = frozenset()
    carrier_share_min: dict[str, float] = field(default_factory=dict)
    carrier_share_max: dict[str, float] = field(default_factory=dict)
    fixed_opex_by_year: dict[int, float] = field(default_factory=dict)
    fixed_opex_default: float = 0.0
    technology_class: str | None = None

    def fixed_opex(self, year: int) -> float:
        """Fixed O&M [USD/(size·yr)] in ``year``."""
        return self.fixed_opex_by_year.get(year, self.fixed_opex_default)


@dataclass(slots=True)
class Asset:
    """A unit that carries one :class:`Technology` per period and serves activity.

    An asset may be *existing* (present from the horizon start) or a *candidate*
    new-build slot that the optimiser may commission (``is_candidate=True``).

    Attributes:
        asset_id: Stable identifier.
        group: Group/class id used for demand balance and targets.
        capacity: Maximum activity per year [activity/yr].
        size: Cost-scaling attribute (e.g. gross tonnage) used to scale CAPEX
            and fixed O&M.
        baseline_technology: Technology the asset runs at the baseline period
            (existing assets are locked to this in ``t0``).
        feasible_technologies: Technologies the asset may run (after
            compatibility/transition filtering). Defaults to all if empty.
        built_year: First year the asset is available (existing assets ≤ t0).
        retire_year: Last year the asset is available (``None`` ⇒ never retires).
        is_candidate: If ``True``, the asset only becomes available once the
            optimiser commissions it (see :attr:`build_capex_per_size`).
        build_capex_per_size: Overnight new-build cost [USD/size] for a candidate
            asset, charged when commissioned.
        build_lifetime_years: Economic lifetime [yr] of the new-build CAPEX.
        build_lead_years: Years between a build decision and availability.
        activity_by_year: Optional *fixed* per-year activity the asset must
            serve [activity/yr] (an exogenous workload). When set, the served
            activity is pinned to this value while the asset is alive — the
            natural representation for an existing fleet whose utilisation is
            given. When empty, the asset instead serves pooled group demand.
    """

    asset_id: str
    group: str
    capacity: float
    size: float = 1.0
    baseline_technology: str | None = None
    feasible_technologies: frozenset[str] = frozenset()
    built_year: int | None = None
    retire_year: int | None = None
    is_candidate: bool = False
    build_capex_per_size: float = 0.0
    build_lifetime_years: int | None = None
    build_lead_years: int = 0
    activity_by_year: dict[int, float] = field(default_factory=dict)

    @property
    def has_fixed_activity(self) -> bool:
        """``True`` if this asset has an exogenous fixed activity profile."""
        return bool(self.activity_by_year)

    def activity(self, year: int) -> float:
        """Fixed activity in ``year`` (0 if not specified)."""
        return self.activity_by_year.get(year, 0.0)


@dataclass(slots=True)
class Transition:
    """An allowed technology switch on an existing asset, with capital cost.

    Attributes:
        from_technology: Source technology id.
        to_technology: Destination technology id.
        capex_per_size: One-off retrofit cost [USD/size], charged on the switch.
        lifetime_years: Economic lifetime [yr] used to annualise the CAPEX.
        earliest_year: First year the switch is permitted (``None`` ⇒ any).
    """

    from_technology: str
    to_technology: str
    capex_per_size: float = 0.0
    lifetime_years: int | None = None
    earliest_year: int | None = None


@dataclass(slots=True)
class MaccBlock:
    """One step of a measure's piecewise marginal-abatement-cost curve.

    Adoption is a fraction ``z ∈ [0, 1]`` of the block; it delivers
    ``fraction · abatement`` emission reduction and ``fraction · energy_saving``
    energy reduction, at cost ``fraction · capex``. Keeping potentials as
    parameters (not products with activity) keeps the model linear.

    Attributes:
        abatement: Emission-reduction potential of the full block [tCO2e/yr].
        energy_saving: Energy-reduction potential of the full block [MJ/yr].
        capex: Capital cost to adopt the full block [USD].
    """

    abatement: float = 0.0
    energy_saving: float = 0.0
    capex: float = 0.0


@dataclass(slots=True)
class Measure:
    """A MACC efficiency/abatement retrofit applicable to a set of assets.

    Attributes:
        measure_id: Stable identifier.
        applicable_assets: Asset ids this measure may be applied to.
        blocks: Ordered piecewise blocks (cheapest first by convention).
        lifetime_years: Economic lifetime [yr] used to annualise block CAPEX.
        earliest_year: First year adoption is permitted (``None`` ⇒ any).
    """

    measure_id: str
    applicable_assets: frozenset[str] = frozenset()
    blocks: tuple[MaccBlock, ...] = ()
    lifetime_years: int | None = None
    earliest_year: int | None = None


@dataclass(slots=True)
class Target:
    """A per-period emission limit over a group.

    Attributes:
        group: Asset group the limit applies to.
        target_type: Intensity cap [gCO2e/MJ] or absolute cap [tCO2e].
        limit_by_year: The limit value keyed by year.
    """

    group: str
    target_type: TargetType
    limit_by_year: dict[int, float] = field(default_factory=dict)

    def limit(self, year: int) -> float | None:
        """Limit value in ``year`` (``None`` ⇒ no binding limit that year)."""
        return self.limit_by_year.get(year)
