"""The :class:`OptimisationProblem` — the contract between packs and the core.

A sector pack produces one of these; :func:`pathwise.core.builder.build`
consumes it and emits a ``linopy`` model with no knowledge of the sector. It is
the single seam that makes sectors pluggable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathwise.core.entities import (
    Asset,
    CapexConvention,
    Carrier,
    Measure,
    Period,
    Target,
    Technology,
    Transition,
)


@dataclass(slots=True)
class CostToggles:
    """Which additive cost components enter the objective.

    Each flag gates one term in the discounted total-cost objective. Disabling a
    term removes it entirely (it contributes zero), which is how scenarios run
    cost-only, emissions-only, or feature-restricted cases.
    """

    fuel: bool = True
    fixed_opex: bool = True
    transition_capex: bool = True
    newbuild_capex: bool = True
    measure_capex: bool = True
    carbon_cost: bool = True


@dataclass(slots=True)
class SolveOptions:
    """Economics and feature switches that shape the model build.

    Attributes:
        discount_rate: ``ρ`` [1/yr] for discount factors and the capital
            recovery factor.
        base_year: Reference year for discounting (``DF = 1`` here).
        capex_convention: How lump-sum CAPEX enters the objective.
        carbon_price_by_year: Carbon price [USD/tCO2e] keyed by year.
        include_measures: Enable MACC measure adoption.
        include_new_build: Enable candidate new-build commissioning.
        include_transitions: Enable technology retrofits.
        max_transitions_per_asset: Cap on retrofit events per asset over the
            horizon.
        min_dwell_years: Minimum age (years since built) before an asset may be
            retrofitted.
        slack_penalty: Objective penalty [USD per unit] on demand/target slack.
        default_lifetime_years: Fallback economic lifetime [yr] for retrofits
            when a transition does not specify one.
        default_newbuild_lifetime_years: Fallback economic lifetime [yr] for new
            builds when a candidate asset does not specify one.
        default_measure_lifetime_years: Fallback economic lifetime [yr] for MACC
            measures when a measure does not specify one.
    """

    discount_rate: float = 0.08
    base_year: int | None = None
    capex_convention: CapexConvention = CapexConvention.ANNUITY
    carbon_price_by_year: dict[int, float] = field(default_factory=dict)
    include_measures: bool = True
    include_new_build: bool = True
    include_transitions: bool = True
    max_transitions_per_asset: int = 1
    min_dwell_years: int = 0
    slack_penalty: float = 1.0e9
    default_lifetime_years: int = 20
    default_newbuild_lifetime_years: int = 25
    default_measure_lifetime_years: int = 15

    def carbon_price(self, year: int) -> float:
        """Carbon price [USD/tCO2e] in ``year`` (0 if unset)."""
        return self.carbon_price_by_year.get(year, 0.0)


@dataclass(slots=True)
class OptimisationProblem:
    """A fully-specified, domain-agnostic optimisation instance.

    Attributes:
        periods: Ordered modelled periods (the first is the baseline ``t0``).
        assets: All assets, existing and candidate new-build slots.
        technologies: Technology catalogue.
        carriers: Carrier catalogue.
        demand: Required activity [activity] keyed by ``(group, year)``.
        transitions: Allowed technology switches.
        measures: MACC measures.
        targets: Per-group emission limits.
        toggles: Enabled cost components.
        options: Economics and feature switches.
    """

    periods: list[Period]
    assets: list[Asset]
    technologies: list[Technology]
    carriers: list[Carrier]
    demand: dict[tuple[str, int], float] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    toggles: CostToggles = field(default_factory=CostToggles)
    options: SolveOptions = field(default_factory=SolveOptions)

    # ── Convenience accessors ────────────────────────────────────────────────
    @property
    def years(self) -> list[int]:
        """Modelled years in order."""
        return [p.year for p in self.periods]

    @property
    def base_year(self) -> int:
        """Baseline year ``t0`` (explicit option, else the first period)."""
        return self.options.base_year if self.options.base_year is not None else self.years[0]

    @property
    def groups(self) -> list[str]:
        """Distinct asset groups, in first-seen order."""
        seen: dict[str, None] = {}
        for a in self.assets:
            seen.setdefault(a.group, None)
        return list(seen)

    def technology(self, technology_id: str) -> Technology:
        """Return the technology with ``technology_id`` (raises ``KeyError``)."""
        for tech in self.technologies:
            if tech.technology_id == technology_id:
                return tech
        raise KeyError(f"Unknown technology '{technology_id}'.")

    def feasible_technologies(self, asset: Asset) -> list[str]:
        """Technologies ``asset`` may run (its set, or all if unset)."""
        if asset.feasible_technologies:
            return [
                t.technology_id
                for t in self.technologies
                if t.technology_id in asset.feasible_technologies
            ]
        return [t.technology_id for t in self.technologies]
